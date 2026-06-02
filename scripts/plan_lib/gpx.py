"""GPX 產出：route / gpx-save / gpx-waypoints。

route 透過 Google Routes API（computeRoutes）HTTPS 一次取得整天路線，
取代舊版 OpenRouteService（cycling-regular 在台灣圖資稀疏、常走產業道路小路）。
travelMode 預設 TWO_WHEELER（機車）：台灣涵蓋最好、走一般道路/省道，最貼近環島
長路線的實際騎乘動線（BICYCLE 在台灣圖資較稀、實測繞路偏多）；可由 config.json 的
travel_mode 或環境變數 ROUTES_TRAVEL_MODE 覆寫。GPX 折線由回傳的 encoded polyline 解碼產生。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

from .helpers import (ROOT, day_dir, plan_dir, read_json, die, info, haversine_km,
                      write_json, is_note_landmark, landmark_matches_name,
                      decode_polyline)


# ── Google Routes API (computeRoutes) ──
ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
ROUTES_FIELD_MASK = "routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline"
ROUTES_MAX_INTERMEDIATES = 25     # computeRoutes 預設中繼點上限（origin+dest 另計）
DEFAULT_TRAVEL_MODE = "TWO_WHEELER"
# 馬達載具（TWO_WHEELER/DRIVE）回傳的是機/汽車旅行時間，遠快於單車；環島每日距離
# 較長，估「騎乘時間」一律由距離 ÷ 平均時速推算（負重旅行車約 16 km/h），比任何
# 馬達 API duration 都更貼近真實，也與 travelMode 無關。
CYCLING_AVG_KMH = 16.0
TAIWAN_BOUNDS = {"lat_min": 21.8, "lat_max": 25.4, "lng_min": 119.2, "lng_max": 122.1}
MAX_ADJACENT_KM = 40  # 分段檢查上限


def _resolve_travel_mode(n: int) -> str:
    """travelMode 解析優先序：config.json travel_mode > 環境變數 > 預設 TWO_WHEELER。"""
    valid = {"TWO_WHEELER", "BICYCLE", "DRIVE", "WALK"}
    cfg = plan_dir(n) / "config.json"
    if cfg.exists():
        mode = (read_json(cfg).get("travel_mode") or "").strip().upper()
        if mode in valid:
            return mode
    mode = os.environ.get("ROUTES_TRAVEL_MODE", "").strip().upper()
    return mode if mode in valid else DEFAULT_TRAVEL_MODE


def _validate_coords(places: list, exempt_detour_names: set | None = None) -> None:
    """檢查座標品質：bounding box / 相鄰距離 / 繞路 / 累積距離。

    exempt_detour_names：必經景點對應的航點名集合，這些點的「繞路」是刻意安排
    （如七星潭往北越過終點再折回），不應被當成座標錯誤，故略過繞路檢查。
    """
    exempt_detour_names = exempt_detour_names or set()
    coords = [(p["location"]["lng"], p["location"]["lat"], p["name_zh"]) for p in places]
    errors = []

    for i, (lng, lat, name) in enumerate(coords):
        if not (TAIWAN_BOUNDS["lat_min"] <= lat <= TAIWAN_BOUNDS["lat_max"]):
            errors.append(f"  [{i+1}] {name}: lat={lat} 超出台灣範圍 ({TAIWAN_BOUNDS['lat_min']}–{TAIWAN_BOUNDS['lat_max']})")
        if not (TAIWAN_BOUNDS["lng_min"] <= lng <= TAIWAN_BOUNDS["lng_max"]):
            errors.append(f"  [{i+1}] {name}: lng={lng} 超出台灣範圍 ({TAIWAN_BOUNDS['lng_min']}–{TAIWAN_BOUNDS['lng_max']})")

    for i in range(len(coords) - 1):
        lng1, lat1, name1 = coords[i]
        lng2, lat2, name2 = coords[i + 1]
        dist = haversine_km(lat1, lng1, lat2, lng2)
        if dist > MAX_ADJACENT_KM:
            errors.append(f"  [{i+1}→{i+2}] {name1} → {name2}: 直線距離 {dist:.1f} km（上限 {MAX_ADJACENT_KM} km），座標可能有誤")

    for i in range(1, len(coords) - 1):
        lng_prev, lat_prev, _ = coords[i - 1]
        lng_cur, lat_cur, name_cur = coords[i]
        lng_next, lat_next, _ = coords[i + 1]
        
        # PATCH (CyclingTW): 國聖燈塔等極地/燈塔為本專案的核心目標，地理位置自然凸出，略過繞路檢查以防誤判。
        # 必經景點（index.md）的繞路是刻意安排（如七星潭往北越過終點再折回），同樣略過。
        if name_cur in exempt_detour_names or any(
                kw in name_cur for kw in ["燈塔", "極西", "極東", "極南", "極北"]):
            continue
            
        direct = haversine_km(lat_prev, lng_prev, lat_next, lng_next)
        detour = (haversine_km(lat_prev, lng_prev, lat_cur, lng_cur) +
                  haversine_km(lat_cur, lng_cur, lat_next, lng_next))
        excess = detour - direct
        if excess > 5.0 and direct > 0 and detour / direct > 1.5:
            errors.append(f"  [{i+1}] {name_cur}: 繞路 {excess:.1f} km（前後直線 {direct:.1f}，經此點 {detour:.1f}），座標疑似不在路線上")

    total_step_km = sum(
        haversine_km(coords[i][1], coords[i][0], coords[i+1][1], coords[i+1][0])
        for i in range(len(coords) - 1)
    )
    straight_km = haversine_km(coords[0][1], coords[0][0], coords[-1][1], coords[-1][0])
    if straight_km > 0 and total_step_km > straight_km * 3:
        errors.append(f"  路線累計直線距離 {total_step_km:.1f} km 是起終點直線 {straight_km:.1f} km 的 {total_step_km/straight_km:.1f} 倍，"
                      f"可能有座標跳躍異常")

    if errors:
        die("⚠️  座標品質驗證失敗，請先修正再重跑：\n" + "\n".join(errors) +
            "\n\n💡 便利商店座標務必用 Google Maps search_places 取得精確值，不要手動估算。")


def _clean_gpx(raw: str) -> str:
    """剝除 envelope 與 <extensions> 區塊（gpx-save 貼入外部 GPX 用）。"""
    start = raw.find("<?xml")
    if start == -1:
        start = raw.find("<gpx")
    if start == -1:
        die("輸入不含 GPX 內容（找不到 <?xml 或 <gpx）")
    gpx = raw[start:]
    before = len(gpx)
    gpx = re.sub(r"<extensions>.*?</extensions>", "", gpx, flags=re.DOTALL)
    saved = before - len(gpx)
    if saved > 0:
        info(f"剝除 <extensions> 區塊，省下 {saved} bytes（{saved * 100 // before}%）")
    return gpx


def _inject_waypoints(gpx: str, places: list) -> str:
    """在 <metadata> 之後插入 <wpt> 標記每個停靠點。"""
    wpt_lines = []
    for i, p in enumerate(places, 1):
        sym = "Flag, Green" if i == 1 else "Flag, Red" if i == len(places) else "Waypoint"
        wpt_lines.append(
            f'  <wpt lat="{p["location"]["lat"]}" lon="{p["location"]["lng"]}">'
            f'<name>{p["name_zh"]}</name><sym>{sym}</sym></wpt>'
        )
    wpt_block = "\n".join(wpt_lines)

    # 找到 </metadata> 或 <gpx ...> 結尾，把 wpt 插在後面
    m = re.search(r"</metadata>", gpx)
    if m:
        idx = m.end()
        return gpx[:idx] + "\n" + wpt_block + gpx[idx:]
    # 沒有 metadata：插在 <gpx ...> 開標籤之後
    m = re.search(r"<gpx[^>]*>", gpx)
    if m:
        idx = m.end()
        return gpx[:idx] + "\n" + wpt_block + gpx[idx:]
    return gpx  # 找不到位置就放棄注入，回原樣


def _routes_post(body: dict, api_key: str) -> dict:
    """對 Google Routes API computeRoutes POST，回傳解析後的 JSON（統一錯誤處理）。"""
    req = urllib.request.Request(
        ROUTES_URL,
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": ROUTES_FIELD_MASK,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        die(f"Routes API HTTP {e.code}: {e.reason}\n{body_text}\n"
            "💡 請確認該 API key 已啟用 Routes API（與 Places 同專案需個別啟用）。")
    except urllib.error.URLError as e:
        die(f"Routes API 連線失敗：{e.reason}")


def _google_route(coords: list, api_key: str, travel_mode: str) -> tuple:
    """呼叫 Google Routes API computeRoutes：回傳 (distance_km, duration_hours, points)。

    coords = [[lng, lat], …]（沿用 ORS 慣例）：首=起點、末=終點、中間=intermediates。
    points = [[lat, lng], …] 由回傳 encoded polyline 解碼（密折線，供 GPX 軌跡與
    score-pool 走廊過濾）。duration 一律由距離 ÷ CYCLING_AVG_KMH 推算成「騎乘時間」
    （見檔頭說明），不採用馬達載具回傳的旅行時間。route 與 route-skeleton 共用此函式。
    """
    n_inter = len(coords) - 2
    if n_inter > ROUTES_MAX_INTERMEDIATES:
        die(f"computeRoutes 中繼點上限 {ROUTES_MAX_INTERMEDIATES} 個，目前 {n_inter} 個"
            f"（起終點另計，共 {len(coords)} 點）")

    def _wp(lng, lat):
        return {"location": {"latLng": {"latitude": lat, "longitude": lng}}}

    body = {
        "origin": _wp(*coords[0]),
        "destination": _wp(*coords[-1]),
        "intermediates": [_wp(lng, lat) for lng, lat in coords[1:-1]],
        "travelMode": travel_mode,
        "polylineQuality": "HIGH_QUALITY",
        "polylineEncoding": "ENCODED_POLYLINE",
    }
    # routingPreference / routeModifiers 僅 DRIVE / TWO_WHEELER 支援。
    # avoidHighways：把路線推離單車不能騎的高架快速道路；avoidTolls：避收費路段。
    if travel_mode in ("DRIVE", "TWO_WHEELER"):
        body["routingPreference"] = "TRAFFIC_UNAWARE"  # 規劃用，求可重現、免 departureTime
        body["routeModifiers"] = {"avoidHighways": True, "avoidTolls": True}

    info(f"呼叫 Routes API computeRoutes（travelMode={travel_mode}）：{len(coords)} 個 waypoints …")
    resp = _routes_post(body, api_key)
    routes = resp.get("routes") or []
    if not routes:
        die("Routes API 無路線結果（檢查座標是否可達 / API key 權限）：\n"
            + json.dumps(resp, ensure_ascii=False)[:800])
    r = routes[0]
    distance_km = round(r["distanceMeters"] / 1000, 1)
    duration_hours = round(distance_km / CYCLING_AVG_KMH, 1)
    points = decode_polyline(r.get("polyline", {}).get("encodedPolyline", ""))
    if not points:
        die("Routes API 回應缺 polyline.encodedPolyline，無法產生折線")
    info(f"Routes 路線距離：{distance_km} km；估算騎乘時間 {duration_hours} 小時"
         f"（{CYCLING_AVG_KMH:.0f} km/h 推算）；折線 {len(points)} 點")
    return distance_km, duration_hours, points


def _points_to_gpx(n: int, route_name: str, points: list) -> str:
    """把路線折線點 [[lat, lng], …] 組成 GPX（metadata + trk/trkseg/trkpt）。

    wpt 停靠點由 cmd_route 之後用 _inject_waypoints 注入。
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="CyclingTW">',
        f'  <metadata><name>Day {n} {route_name}</name>',
        f'    <bounds minlat="{min(lats)}" minlon="{min(lons)}" maxlat="{max(lats)}" maxlon="{max(lons)}"/></metadata>',
        f'  <trk><name>Day {n}</name><trkseg>',
    ]
    for lat, lng in points:
        lines.append(f'    <trkpt lat="{lat}" lon="{lng}"/>')
    lines.append('  </trkseg></trk>')
    lines.append('</gpx>')
    return "\n".join(lines)


def cmd_route(args):
    """從 places.json 讀座標、呼叫 Routes API、輸出 dayN_route.gpx + 寫回距離。"""
    n = args.day
    data = read_json(plan_dir(n) / "places.json")
    places = data["places"]
    if len(places) < 2:
        die("places.json 至少需要 2 個點位")

    # 必經景點（index.md）對應的航點：其刻意繞路不應觸發座標品質硬擋
    _cfg = plan_dir(n) / "config.json"
    _landmarks = read_json(_cfg).get("must_visit_landmarks", []) if _cfg.exists() else []
    _exempt = {p["name_zh"] for p in places for lm in _landmarks
               if not is_note_landmark(lm) and landmark_matches_name(lm, p["name_zh"])}
    _validate_coords(places, _exempt)

    if len(places) - 2 > ROUTES_MAX_INTERMEDIATES:
        die(f"computeRoutes 中繼點上限 {ROUTES_MAX_INTERMEDIATES} 個，目前 {len(places) - 2} 個"
            f"（起終點另計，共 {len(places)} 點）")

    from .places_api import _get_api_key
    api_key = _get_api_key()
    travel_mode = _resolve_travel_mode(n)

    coords = [[p["location"]["lng"], p["location"]["lat"]] for p in places]
    distance_km, duration_hours, points = _google_route(coords, api_key, travel_mode)

    # 從真實路線折線（points=[lat,lng]）順手算爬升/下降，與下面距離欄位同一次寫入 places.json。
    # 放在 gpx 寫出之前 → places.json mtime 仍 < gpx，維持 render-md 自癒「gpx ≥ places.json」不變式，
    # 不會因 elevation 而觸發無窮自癒。Elevation API 失敗不影響路線本身（欄位留空，模板退回文字）。
    try:
        from .elevation import compute_from_points
        asc, desc = compute_from_points(points, api_key)
        data["elevation_ascent_m"] = asc
        data["elevation_descent_m"] = desc
    except SystemExit:
        info("    爬升/下降計算略過（Elevation API 失敗），保留 places.json 既有值")

    # 寫回 places.json（沿用 ors_* 鍵名以維持下游 render/index/template 相容）
    data["ors_distance_km"] = distance_km
    data["ors_duration_hours"] = duration_hours
    write_json(plan_dir(n) / "places.json", data)

    gpx = _inject_waypoints(_points_to_gpx(n, data.get("route_name", ""), points), places)
    out = day_dir(n) / f"day{n}_route.gpx"
    out.write_text(gpx, encoding="utf-8")
    trkpt_count = len(re.findall(r"<trkpt", gpx))
    info(f"已寫入 {out.relative_to(ROOT)}（{len(gpx)} bytes, {trkpt_count} trkpt）")

    # 把真實路線折線存成可重用檔，供 score-pool 走廊過濾用（取代航點直線近似）。
    # waypoint_signature = 本次送 Routes API 的航點座標；score-pool 比對現在 places.json
    # 航點，相符才採用真實折線（換航點後簽章不符 → 自動退回直線近似），慣例同 dinner/hotel
    # 的 source_endpoint_place_id。
    geom = {
        "waypoint_signature": [[round(p["location"]["lat"], 6), round(p["location"]["lng"], 6)]
                               for p in places],
        "points": points,
    }
    write_json(plan_dir(n) / "route_geometry.json", geom)
    info(f"已寫入 route_geometry.json（{len(geom['points'])} 個真實路線折線點）")

    # 自動把實際距離回寫 index.md
    from .index_parser import cmd_update_index
    import argparse as _ap
    try:
        cmd_update_index(_ap.Namespace(day=n))
    except SystemExit:
        pass


def cmd_route_skeleton(args):
    """Phase 1 起點：Routes API 只串「起點 + 必經景點 + 終點」算出骨架最佳路線。

    產出 _plan/skeleton.json（含 ordered_points 與 geometry 折線），供
    search-along-route 沿這條真實路線找補給點/景點。模糊地名（如「通霄海線」）
    地理編碼可能不精準，請看輸出座標，必要時手動修 skeleton.json 再重搜。
    """
    from .mirror import _search_text, _get_api_key, _sanitize_place_name

    n = args.day
    cfg = read_json(plan_dir(n) / "config.json")
    origin, dest = cfg.get("origin"), cfg.get("destination")
    if not origin or not dest:
        die("config.json 缺 origin/destination，請先 parse-index N")
    landmarks = [lm for lm in (cfg.get("must_visit_landmarks") or []) if not is_note_landmark(lm)]

    gkey = _get_api_key()
    travel_mode = _resolve_travel_mode(n)

    queries = [("起終點", origin)] + [("景點", lm) for lm in landmarks] + [("起終點", dest)]
    ordered, prev = [], None
    for csv_type, q in queries:
        bias_lat, bias_lng = (prev if prev else (None, None))
        res = _search_text(q, bias_lat, bias_lng, 30000, 1, gkey)
        if not res:
            die(f"地理編碼失敗（Places API 無結果）：{q!r}")
        p = res[0]
        loc = p.get("location", {})
        lat, lng = loc.get("latitude"), loc.get("longitude")
        ordered.append({
            "place_id": p.get("id"),
            "name_zh": _sanitize_place_name(p.get("displayName", {}).get("text", "")),
            "query": q,
            "csv_type": csv_type,
            "location": {"lat": lat, "lng": lng},
        })
        prev = (lat, lng)

    coords = [[o["location"]["lng"], o["location"]["lat"]] for o in ordered]
    distance_km, duration_hours, points = _google_route(coords, gkey, travel_mode)

    skel = {
        "day": n,
        "origin": origin,
        "destination": dest,
        "ordered_points": ordered,
        "ors_distance_km": distance_km,
        "ors_duration_hours": duration_hours,
        "geometry": points,
    }
    write_json(plan_dir(n) / "skeleton.json", skel)
    info(f"已寫入 skeleton.json（骨架 {distance_km}km / {duration_hours}h / {len(points)} 折線點）")
    print(f"\n=== route-skeleton Day {n}: 骨架 {distance_km} km ===")
    for o in ordered:
        lat, lng = o["location"]["lat"], o["location"]["lng"]
        print(f"  [{o['csv_type']}] {o['name_zh'] or '?':<18} ←{o['query']:<10} {lat:.4f},{lng:.4f}")


def cmd_gpx_save(args):
    """從 stdin 接收 GPX 文字，儲存為 dayN_route.gpx（備援用）。"""
    n = args.day
    raw = sys.stdin.read()
    if "<gpx" not in raw:
        die("stdin 不像 GPX 內容（找不到 <gpx 標籤）")
    gpx = _clean_gpx(raw)
    out = day_dir(n) / f"day{n}_route.gpx"
    out.write_text(gpx, encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}（{len(gpx)} chars）")


def cmd_gpx_waypoints(args):
    """離線備案：依 places.json 座標產出純航點 GPX。"""
    n = args.day
    data = read_json(plan_dir(n) / "places.json")
    places = data["places"]
    lats = [p["location"]["lat"] for p in places]
    lons = [p["location"]["lng"] for p in places]
    gpx = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="CyclingTW">',
        f'  <metadata><name>Day {n} {data.get("route_name", "")}</name>',
        f'    <bounds minlat="{min(lats)}" minlon="{min(lons)}" maxlat="{max(lats)}" maxlon="{max(lons)}"/></metadata>',
    ]
    for i, p in enumerate(places, 1):
        sym = "Flag, Green" if i == 1 else "Flag, Red" if i == len(places) else "Waypoint"
        gpx.append(f'  <wpt lat="{p["location"]["lat"]}" lon="{p["location"]["lng"]}">')
        gpx.append(f'    <name>{p["name_zh"]}</name><sym>{sym}</sym></wpt>')
    gpx.append(f'  <trk><name>Day {n}</name><trkseg>')
    for p in places:
        gpx.append(f'    <trkpt lat="{p["location"]["lat"]}" lon="{p["location"]["lng"]}"/>')
    gpx.append("  </trkseg></trk></gpx>")
    out = day_dir(n) / f"day{n}_route.gpx"
    out.write_text("\n".join(gpx), encoding="utf-8")
    info(f"已寫入備案 waypoint GPX：{out.relative_to(ROOT)}")

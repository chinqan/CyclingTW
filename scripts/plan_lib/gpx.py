"""GPX 產出：route / gpx-save / gpx-waypoints。

route 透過 OpenRouteService HTTPS API 一次取得整天路線，
取代舊版 split + MCP 逐段 + merge 流程。
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.request

from .helpers import ROOT, day_dir, plan_dir, read_json, die, info, haversine_km


# ── OpenRouteService API ──
ORS_URL = "https://api.openrouteservice.org/v2/directions/cycling-regular/gpx"
ORS_MAX_WAYPOINTS = 50  # cycling-regular 單次上限
TAIWAN_BOUNDS = {"lat_min": 21.8, "lat_max": 25.4, "lng_min": 119.2, "lng_max": 122.1}
MAX_ADJACENT_KM = 40  # 分段檢查上限


def _validate_coords(places: list) -> None:
    """檢查座標品質：bounding box / 相鄰距離 / 繞路 / 累積距離。"""
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
        if any(kw in name_cur for kw in ["燈塔", "極西", "極東", "極南", "極北"]):
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
    """剝除 envelope 與 <extensions> 區塊。"""
    start = raw.find("<?xml")
    if start == -1:
        start = raw.find("<gpx")
    if start == -1:
        die("ORS 回應不含 GPX 內容")
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


def _ors_request(api_key: str, coords: list, accept: str) -> bytes:
    """對 ORS Directions API 發送 POST request。"""
    body = json.dumps({
        "coordinates": coords,
        "instructions": False,
        "elevation": False,
    }).encode("utf-8")

    req = urllib.request.Request(
        ORS_URL.rsplit("/", 1)[0] + "/cycling-regular" + ("/gpx" if "gpx" in accept else ""),
        data=body,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": accept,
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        die(f"ORS API HTTP {e.code}: {e.reason}\n{body_text}")
    except urllib.error.URLError as e:
        die(f"ORS API 連線失敗：{e.reason}")


ORS_JSON_URL = "https://api.openrouteservice.org/v2/directions/cycling-regular"


def cmd_route(args):
    """從 places.json 讀座標、呼叫 ORS API、輸出 dayN_route.gpx + 寫回距離。"""
    n = args.day
    data = read_json(plan_dir(n) / "places.json")
    places = data["places"]
    if len(places) < 2:
        die("places.json 至少需要 2 個點位")

    _validate_coords(places)

    if len(places) > ORS_MAX_WAYPOINTS:
        die(f"ORS cycling-regular 單次最多 {ORS_MAX_WAYPOINTS} waypoints，目前 {len(places)} 個")

    api_key = os.environ.get("ORS_API_KEY")
    if not api_key:
        # fallback：從 .kiro/settings/mcp.json 讀取
        mcp_path = ROOT / ".kiro" / "settings" / "mcp.json"
        if mcp_path.exists():
            import re as _re
            try:
                _txt = mcp_path.read_text(encoding="utf-8")
                _txt = _re.sub(r"//.*", "", _txt)  # strip JSONC comments
                _mcp = json.loads(_txt)
                api_key = (_mcp.get("mcpServers", {})
                           .get("openroute", {})
                           .get("env", {})
                           .get("OPENROUTESERVICE_API_KEY"))
            except Exception:
                pass
    if not api_key:
        die("缺少 ORS_API_KEY 環境變數。\n"
            "請至 https://openrouteservice.org/dev/#/signup 申請後：\n"
            "  export ORS_API_KEY='your-key-here'")

    coords = [[p["location"]["lng"], p["location"]["lat"]] for p in places]

    # ── 1. 呼叫 JSON endpoint 取距離與時間 ──
    info(f"呼叫 ORS API（JSON）：取得路線距離 …")
    json_body = json.dumps({
        "coordinates": coords,
        "instructions": False,
        "elevation": False,
    }).encode("utf-8")
    json_req = urllib.request.Request(
        ORS_JSON_URL,
        data=json_body,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(json_req, timeout=60) as resp:
            json_result = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        die(f"ORS API HTTP {e.code}: {e.reason}\n{body_text}")
    except urllib.error.URLError as e:
        die(f"ORS API 連線失敗：{e.reason}")

    summary = json_result["routes"][0]["summary"]
    distance_km = round(summary["distance"] / 1000, 1)
    duration_hours = round(summary["duration"] / 3600, 1)
    info(f"ORS 路線距離：{distance_km} km，預估騎乘時間：{duration_hours} 小時")

    # 寫回 places.json
    data["ors_distance_km"] = distance_km
    data["ors_duration_hours"] = duration_hours
    from .helpers import write_json
    write_json(plan_dir(n) / "places.json", data)

    # ── 2. 呼叫 GPX endpoint 取路線軌跡 ──
    info(f"呼叫 ORS API（GPX）：{len(coords)} 個 waypoints …")
    gpx_body = json.dumps({
        "coordinates": coords,
        "instructions": False,
        "elevation": False,
    }).encode("utf-8")
    gpx_req = urllib.request.Request(
        ORS_URL,
        data=gpx_body,
        headers={
            "Authorization": api_key,
            "Content-Type": "application/json",
            "Accept": "application/gpx+xml, application/xml",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(gpx_req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace") if e.fp else ""
        die(f"ORS API HTTP {e.code}: {e.reason}\n{body_text}")
    except urllib.error.URLError as e:
        die(f"ORS API 連線失敗：{e.reason}")

    gpx = _clean_gpx(raw)
    gpx = _inject_waypoints(gpx, places)

    out = day_dir(n) / f"day{n}_route.gpx"
    out.write_text(gpx, encoding="utf-8")
    rtept_count = len(re.findall(r"<rtept", gpx))
    trkpt_count = len(re.findall(r"<trkpt", gpx))
    info(f"已寫入 {out.relative_to(ROOT)}（{len(gpx)} bytes, {rtept_count} rtept, {trkpt_count} trkpt）")

    # 自動把實際距離回寫 index.md
    from .index_parser import cmd_update_index
    import argparse as _ap
    try:
        cmd_update_index(_ap.Namespace(day=n))
    except SystemExit:
        pass


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

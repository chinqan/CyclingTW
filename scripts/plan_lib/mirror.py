"""本地鏡像 DB（mirror）管理：mirror-search / mirror-status / mirror-put / mirror-diff。

mirror-search 直接呼叫 Google Places API（zh-TW），以 keyword 找 top-N，
依 --csv-type 決定要保留哪些欄位（便利商店/加油站僅 place_id+name+location；
景點/餐廳大休/起終點額外取 rating/total_ratings），upsert 到 dayN/map/。
"""
from __future__ import annotations

import json
import os
import time

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

from .helpers import (ROOT, map_dir, plan_dir, read_json, write_json, read_stdin_json,
                      die, info, haversine_km, encode_polyline, downsample)


def _sanitize_place_name(name: str) -> str:
    """移除 Google Places 名稱中的 marketing tag（| 分隔的附加描述）。
    例：'蠔碳嘉烤鮮蚵吃到飽-東石|推薦鮮蚵|必吃' → '蠔碳嘉烤鮮蚵吃到飽-東石'
    保留第一個 | 之前的部分並 strip 空白。"""
    return name.split("|")[0].strip()

# Google Places API (New)
PLACES_API_BASE = "https://places.googleapis.com/v1/places"
MIRROR_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.formattedAddress",
    "places.primaryType",
])

# 哪些 csv_type 需要保留評分（其餘只存最小 schema）
RATED_CSV_TYPES = {"景點", "起終點", "餐廳大休"}
VALID_CSV_TYPES = RATED_CSV_TYPES | {"便利商店", "加油站", "公共設施", "綜合休息站"}
VALID_TARGETS = ("places", "candidates_not_selected")


def load_mirror_index(n: int) -> dict:
    idx = map_dir(n) / "index.json"
    if idx.exists():
        return read_json(idx)
    return {"day": n, "places": [], "candidates_not_selected": []}


def save_mirror_index(n: int, data: dict) -> None:
    write_json(map_dir(n) / "index.json", data)


def cmd_mirror_status(args):
    n = args.day
    mirror = load_mirror_index(n)
    files = sorted(map_dir(n).glob("*.json"))

    def group(items: list[dict]) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {}
        for p in items:
            out.setdefault(p.get("csv_type", "未分類"), []).append(p.get("name_zh", "?"))
        return out

    selected = mirror.get("places", [])
    candidates = mirror.get("candidates_not_selected", [])

    print(f"== Day {n} 本地鏡像現況 ==")
    print(f"map/ 檔案數：{len(files)}")
    print(f"index.json places（入選）：{len(selected)}")
    print(f"index.json candidates_not_selected（備案）：{len(candidates)}\n")

    print("【入選】")
    for t, names in group(selected).items():
        print(f"  [{t}] ({len(names)}) {'、'.join(names)}")

    if candidates:
        print("\n【備案】")
        for t, names in group(candidates).items():
            print(f"  [{t}] ({len(names)}) {'、'.join(names)}")

    rated_sel = [p for p in selected if p.get("csv_type") in ("景點", "起終點")]
    rests_sel = [p for p in selected if p.get("csv_type") == "餐廳大休"]
    rated_total = rated_sel + [p for p in candidates if p.get("csv_type") in ("景點", "起終點")]
    rests_total = rests_sel + [p for p in candidates if p.get("csv_type") == "餐廳大休"]
    print()
    if len(rated_total) < 5:
        print(f"⚠️  景點/起終點候選 {len(rated_total)} 筆（入選 {len(rated_sel)} + 備案 {len(rated_total) - len(rated_sel)}），建議再廣搜至 ≥ 5 筆")
    if len(rests_total) < 2:
        print(f"⚠️  餐廳大休候選 {len(rests_total)} 筆（入選 {len(rests_sel)} + 備案 {len(rests_total) - len(rests_sel)}），建議再廣搜至 ≥ 2 筆")


def cmd_mirror_put(args):
    """從 stdin 讀單筆 place JSON，upsert 到本地鏡像。"""
    n = args.day
    data = read_stdin_json()
    pid = data.get("place_id")
    if not pid:
        die("缺少 place_id 欄位")
    target = data.get("target", "places")
    VALID_TARGETS = ("places", "candidates_not_selected")
    if target not in VALID_TARGETS:
        die(f"target 必須是 {VALID_TARGETS} 之一，收到 '{target}'")
    place_payload = {k: v for k, v in data.items() if k != "target"}
    f = map_dir(n) / f"{pid}.json"
    write_json(f, place_payload)
    idx = load_mirror_index(n)
    for bucket_name in ("places", "candidates_not_selected"):
        b = idx.setdefault(bucket_name, [])
        b[:] = [x for x in b if x.get("place_id") != pid]
    idx[target].append({k: data[k] for k in (
        "place_id", "name_zh", "csv_type", "rating", "total_ratings", "location", "source", "note"
    ) if k in data})
    save_mirror_index(n, idx)
    info(f"upsert {f.relative_to(ROOT)} → {target}")


def cmd_mirror_diff(args):
    """從 stdin 讀 fresh 資料，與本地鏡像比對。"""
    n = args.day
    fresh = read_stdin_json()
    if isinstance(fresh, dict):
        fresh = [fresh]
    rows = []
    for f in fresh:
        pid = f["place_id"]
        cf = map_dir(n) / f"{pid}.json"
        if not cf.exists():
            rows.append((pid, f.get("name_zh", "?"), "—", "—", f.get("rating"), f.get("total_ratings"), "⭐ 新地點"))
            continue
        c = read_json(cf)
        diffs = []
        if c.get("rating") != f.get("rating"):
            diffs.append(f"rating {c.get('rating')}→{f.get('rating')}")
        if c.get("total_ratings") != f.get("total_ratings"):
            diffs.append(f"reviews {c.get('total_ratings')}→{f.get('total_ratings')}")
        rows.append((pid, f.get("name_zh") or c.get("name_zh"),
                     c.get("rating"), c.get("total_ratings"),
                     f.get("rating"), f.get("total_ratings"),
                     "、".join(diffs) or "—"))
    print(f"{'place_id':<32}{'名稱':<22}{'本地R':>6}{'本地V':>8}{'線上R':>6}{'線上V':>8}  差異")
    print("-" * 100)
    for r in rows:
        print(f"{r[0]:<32}{(r[1] or '')[:20]:<22}{str(r[2]):>6}{str(r[3]):>8}{str(r[4]):>6}{str(r[5]):>8}  {r[6]}")


# ─────────────────────────────────────────────────────────────────
# Places API 搜尋（取代 MCP google-maps）
# ─────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not key:
        die("缺少 GOOGLE_PLACES_API_KEY 環境變數")
    return key


def _search_text(keyword: str, bias_lat: float | None, bias_lng: float | None,
                 bias_radius_m: int, max_results: int, api_key: str,
                 along_polyline: str | None = None) -> list[dict]:
    body: dict = {
        "textQuery": keyword,
        "maxResultCount": max_results,
        "languageCode": "zh-TW",
        "regionCode": "TW",
    }
    if along_polyline:
        # 沿路線搜尋：結果依「偏離路線的繞路距離」排序（locationBias 此時不適用）
        body["searchAlongRouteParameters"] = {
            "polyline": {"encodedPolyline": along_polyline},
        }
    elif bias_lat is not None and bias_lng is not None:
        body["locationBias"] = {
            "circle": {
                "center": {"latitude": bias_lat, "longitude": bias_lng},
                "radius": float(bias_radius_m),
            },
        }
    req = urllib.request.Request(
        f"{PLACES_API_BASE}:searchText",
        data=json.dumps(body).encode("utf-8"),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": MIRROR_FIELD_MASK,
            "X-Goog-Api-Language": "zh-TW",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8")).get("places", []) or []
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        die(f"Places API HTTP {e.code}:\n{body_text}")
    except urllib.error.URLError as e:
        die(f"Places API 網路錯誤：{e.reason}")


def cmd_mirror_search(args):
    """以關鍵字搜 Google Places API 並 upsert 到 dayN/map/ 鏡像。

    範例：
      mirror-search 2 --keyword "7-ELEVEN 觀湖門市" --csv-type 便利商店
      mirror-search 2 --keyword "鹿港老街" --csv-type 景點 --target places
      mirror-search 2 --keyword "台灣中油大園站" --csv-type 加油站 --bias 24.687,120.881
    """
    n = args.day
    csv_type = args.csv_type
    if csv_type not in VALID_CSV_TYPES:
        die(f"--csv-type 必須是 {sorted(VALID_CSV_TYPES)} 之一，收到 {csv_type!r}")
    target = args.target
    if target not in VALID_TARGETS:
        die(f"--target 必須是 {VALID_TARGETS} 之一，收到 {target!r}")

    bias_lat = bias_lng = None
    if args.bias:
        try:
            lat_str, lng_str = args.bias.split(",")
            bias_lat, bias_lng = float(lat_str), float(lng_str)
        except ValueError:
            die(f"--bias 格式須為 LAT,LNG，收到 {args.bias!r}")

    api_key = _get_api_key()
    info(f"搜尋 '{args.keyword}' (csv_type={csv_type}, target={target})")
    results = _search_text(args.keyword, bias_lat, bias_lng,
                           args.bias_radius, args.max_results, api_key)
    if not results:
        die("Places API 沒有回傳結果")

    idx = load_mirror_index(n)
    upserted = []
    for p in results[:args.max_results]:
        pid = p.get("id")
        if not pid:
            continue
        dn = p.get("displayName", {})
        name_zh = _sanitize_place_name(dn.get("text", ""))
        loc = p.get("location", {})
        lat, lng = loc.get("latitude"), loc.get("longitude")

        # 依 csv_type 決定保留欄位
        place_payload: dict = {
            "place_id": pid,
            "name_zh": name_zh,
            "csv_type": csv_type,
            "location": {"lat": lat, "lng": lng},
            "search_keyword": args.keyword,
            "source": f"api_{time.strftime('%Y-%m-%d')}",
        }
        if csv_type in RATED_CSV_TYPES:
            place_payload["rating"] = p.get("rating")
            place_payload["total_ratings"] = p.get("userRatingCount")
            place_payload["address"] = p.get("formattedAddress", "")
            place_payload["primary_type"] = p.get("primaryType")

        write_json(map_dir(n) / f"{pid}.json", place_payload)

        # 更新 index 兩個 bucket（先全清同 pid 再 append 到目標）
        for bucket in ("places", "candidates_not_selected"):
            b = idx.setdefault(bucket, [])
            b[:] = [x for x in b if x.get("place_id") != pid]
        idx[target].append({k: place_payload[k] for k in (
            "place_id", "name_zh", "csv_type", "rating", "total_ratings",
            "location", "source"
        ) if k in place_payload})
        upserted.append((pid, name_zh, place_payload.get("rating"), place_payload.get("total_ratings")))

    save_mirror_index(n, idx)

    print(f"\n=== mirror-search Day {n}: {len(upserted)} 筆 upsert 到 {target} ===")
    for pid, name, r, v in upserted:
        rv = f"R={r} V={v}" if r is not None else ""
        print(f"  {pid:<35} {name}  {rv}")


# 各 csv_type 的預設「離線繞路」上限（km），對應規則 C（單車視角順路門檻）
_DETOUR_DEFAULT_KM = {
    "便利商店": 0.5, "加油站": 0.5, "公共設施": 0.5, "綜合休息站": 0.5,
    "餐廳大休": 1.0, "景點": 2.0, "起終點": 2.0,
}


def _route_geometry_for_search(n: int) -> list:
    """取沿線搜尋用折線：優先 skeleton.json，其次定稿 route_geometry.json。"""
    sk = plan_dir(n) / "skeleton.json"
    if sk.exists():
        pts = read_json(sk).get("geometry") or []
        if pts:
            return pts
    rg = plan_dir(n) / "route_geometry.json"
    if rg.exists():
        pts = read_json(rg).get("points") or []
        if pts:
            return pts
    die("找不到路線折線，請先跑 route-skeleton N（或 route N）")


def cmd_search_along_route(args):
    """沿 ORS 骨架/定稿路線用 Places API (New) 找指定類型停靠點並 upsert 候選。

    結果依「偏離路線的繞路距離」過濾（門檻依 --csv-type 自動帶入規則 C，可用
    --detour-km 覆寫），並印出每點的「沿路里程位置」方便挑選間距均勻的補給點。
    範例：
      search-along-route 1 --keyword "7-ELEVEN" --csv-type 便利商店 --max-results 20
      search-along-route 1 --keyword "景點 漁港" --csv-type 景點 --max-results 20
    """
    from .bayesian import _dist_to_route_km

    n = args.day
    csv_type = args.csv_type
    if csv_type not in VALID_CSV_TYPES:
        die(f"--csv-type 必須是 {sorted(VALID_CSV_TYPES)} 之一，收到 {csv_type!r}")
    detour_km = args.detour_km if args.detour_km is not None else _DETOUR_DEFAULT_KM.get(csv_type, 1.0)

    geom = _route_geometry_for_search(n)
    ds = downsample(geom, 512)
    route = [(p[0], p[1]) for p in ds]
    enc = encode_polyline(route)

    # 沿路里程：每個折線頂點的累積距離
    cum = [0.0]
    for i in range(1, len(route)):
        cum.append(cum[-1] + haversine_km(route[i - 1][0], route[i - 1][1], route[i][0], route[i][1]))

    def along_km(lat, lng):
        best_i = min(range(len(route)), key=lambda i: haversine_km(lat, lng, route[i][0], route[i][1]))
        return cum[best_i]

    api_key = _get_api_key()
    # 單次 searchAlongRoute 最多回 20 筆且依繞路排序 → 長路線會群聚頭尾。
    # 切成 --segments 段各搜一次再合併去重，達到沿線均勻覆蓋。
    segs = max(1, args.segments)
    slices = [route]
    if segs > 1:
        size = max(1, len(route) // segs)
        slices = []
        for i in range(segs):
            a = i * size
            b = len(route) if i == segs - 1 else (i + 1) * size + 1  # +1 重疊避免接縫漏點
            if a < len(route):
                slices.append(route[a:b])
    info(f"沿路線搜尋 '{args.keyword}'（csv_type={csv_type}, 繞路≤{detour_km}km, "
         f"折線 {len(route)} 點, {len(slices)} 段）…")
    merged: dict = {}
    for sl in slices:
        if len(sl) < 2:
            continue
        for p in _search_text(args.keyword, None, None, 0, args.max_results, api_key,
                              along_polyline=encode_polyline(sl)):
            pid = p.get("id")
            if pid and pid not in merged:
                merged[pid] = p
    results = list(merged.values())
    if not results:
        die("Places API 沿路線搜尋無結果")

    idx = load_mirror_index(n)
    kept, dropped = [], []
    for p in results:
        pid = p.get("id")
        loc = p.get("location", {})
        lat, lng = loc.get("latitude"), loc.get("longitude")
        if not pid or lat is None or lng is None:
            continue
        d = _dist_to_route_km(lat, lng, route)
        name_zh = _sanitize_place_name(p.get("displayName", {}).get("text", ""))
        if d > detour_km:
            dropped.append((name_zh, round(d, 2)))
            continue

        payload = {
            "place_id": pid,
            "name_zh": name_zh,
            "csv_type": csv_type,
            "location": {"lat": lat, "lng": lng},
            "search_keyword": args.keyword,
            "source": f"along_{time.strftime('%Y-%m-%d')}",
        }
        if csv_type in RATED_CSV_TYPES:
            payload["rating"] = p.get("rating")
            payload["total_ratings"] = p.get("userRatingCount")
            payload["address"] = p.get("formattedAddress", "")
            payload["primary_type"] = p.get("primaryType")
        write_json(map_dir(n) / f"{pid}.json", payload)
        for bucket in ("places", "candidates_not_selected"):
            b = idx.setdefault(bucket, [])
            b[:] = [x for x in b if x.get("place_id") != pid]
        idx["candidates_not_selected"].append({k: payload[k] for k in (
            "place_id", "name_zh", "csv_type", "rating", "total_ratings", "location", "source"
        ) if k in payload})
        kept.append((name_zh, p.get("rating"), p.get("userRatingCount"), round(d, 2), round(along_km(lat, lng), 1)))

    save_mirror_index(n, idx)

    kept.sort(key=lambda x: x[4])  # 依沿路里程排序
    print(f"\n=== search-along-route Day {n}: 收 {len(kept)} 筆（繞路≤{detour_km}km）→ candidates_not_selected ===")
    print(f"  {'沿路km':>7}  {'繞路km':>6}  {'評分':>6}  名稱")
    for name, r, v, d, akm in kept:
        rv = f"{r}/{v}" if r is not None else "—"
        print(f"  {akm:>7.1f}  {d:>6.2f}  {rv:>6}  {name}")
    if dropped:
        print(f"  （捨棄 {len(dropped)} 筆繞路 >{detour_km}km：{', '.join(f'{nm}{d}km' for nm, d in dropped[:6])}{' …' if len(dropped) > 6 else ''}）")

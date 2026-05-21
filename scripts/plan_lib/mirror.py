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

from .helpers import ROOT, map_dir, read_json, write_json, read_stdin_json, die, info


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
                 bias_radius_m: int, max_results: int, api_key: str) -> list[dict]:
    body: dict = {
        "textQuery": keyword,
        "maxResultCount": max_results,
        "languageCode": "zh-TW",
        "regionCode": "TW",
    }
    if bias_lat is not None and bias_lng is not None:
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

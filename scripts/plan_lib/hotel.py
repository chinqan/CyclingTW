"""住宿選點：hotel-search / hotel-pool / hotel-render (+ hotel-status / hotel-review / hotel-put)。

本地鏡像 DB：dayN/hotel_map/
  - index.json         索引（候選名單 + 入選標記）
  - <place_id>.json    每間飯店完整資料（write-through 更新）

工作流：
  1. hotel-search N — 從 places.json 終點呼叫 Google Places API 搜尋周邊 3km
                      住宿（含 searchNearby + searchText 多關鍵字），自動 upsert
                      到 hotel_map/。X-Goog-Api-Language=zh-TW，名稱優先中文。
  2. hotel-pool N  — 從鏡像完整候選池算 Bayesian、選 top 5，存 _plan/hotel.json
  3. hotel-render N — 產 dayN_hotel.md

備援指令：
  - hotel-put N   — [stdin] 手動 upsert 單筆 / 陣列 JSON 到鏡像
  - hotel-status N — 顯示鏡像現況
  - hotel-review N — 顯示完整排名
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

from .helpers import ROOT, plan_dir, hotel_map_dir, read_json, write_json, read_stdin_json, die, info, haversine_km

DEDUPE_RADIUS_KM = 0.05  # 50m 內同名視為同一家

# Places API (New) 設定
PLACES_API_BASE = "https://places.googleapis.com/v1/places"
HOTEL_FIELD_MASK = ",".join([
    "places.id",
    "places.displayName",
    "places.location",
    "places.rating",
    "places.userRatingCount",
    "places.formattedAddress",
    "places.primaryTypeDisplayName",
    "places.primaryType",
])

# 搜尋策略：searchNearby + 多組 searchText 補搜
# searchNearby 一次最多 20 筆且 Google 端有結果上限，多用 searchText 字串補增
DEFAULT_SEARCH_RADIUS_M = 3000
DEFAULT_MAX_RESULTS_PER_QUERY = 20
SEARCH_TEXT_QUERIES = ["飯店", "民宿", "旅館", "Hotel"]

# Google Places primary_type 住宿類白名單；searchText 即便指定 includedType=lodging
# 仍會混入餐廳/運動場/景點，必須在客戶端嚴格過濾。
LODGING_PRIMARY_TYPES = {
    "lodging",
    "hotel",
    "motel",
    "resort_hotel",
    "extended_stay_hotel",
    "inn",
    "bed_and_breakfast",
    "private_guest_room",
    "guest_house",
    "hostel",
    "campground",
    "cottage",
    "farmstay",
    "japanese_inn",
}


# ─────────────────────────────────────────────────────────────────
# Google Places API 搜尋
# ─────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not key:
        die(
            "缺少 GOOGLE_PLACES_API_KEY 環境變數。\n"
            "請至 https://console.cloud.google.com/apis/credentials 建立 API Key，\n"
            "並啟用 Places API (New)。"
        )
    return key


def _has_cjk(s: str) -> bool:
    """字串是否包含 CJK 漢字（U+4E00–U+9FFF）。"""
    if not s:
        return False
    return any('一' <= c <= '鿿' for c in s)


def _post_places_api(url: str, body: dict, api_key: str) -> dict:
    """POST 至 Places API (New)，回傳解析後 JSON。"""
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Goog-Api-Key": api_key,
            "X-Goog-FieldMask": HOTEL_FIELD_MASK,
            "X-Goog-Api-Language": "zh-TW",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        body_text = e.read().decode("utf-8", errors="replace")
        die(f"Places API HTTP {e.code}:\n{body_text}")
    except urllib.error.URLError as e:
        die(f"Places API 網路錯誤：{e.reason}")


def _search_nearby(lat: float, lng: float, radius_m: int, api_key: str) -> list[dict]:
    body = {
        "includedTypes": ["lodging"],
        "maxResultCount": DEFAULT_MAX_RESULTS_PER_QUERY,
        "languageCode": "zh-TW",
        "regionCode": "TW",
        "locationRestriction": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius_m),
            },
        },
    }
    resp = _post_places_api(f"{PLACES_API_BASE}:searchNearby", body, api_key)
    return resp.get("places", []) or []


def _search_text(query: str, lat: float, lng: float, radius_m: int, api_key: str) -> list[dict]:
    body = {
        "textQuery": query,
        "maxResultCount": DEFAULT_MAX_RESULTS_PER_QUERY,
        "languageCode": "zh-TW",
        "regionCode": "TW",
        "includedType": "lodging",
        "locationBias": {
            "circle": {
                "center": {"latitude": lat, "longitude": lng},
                "radius": float(radius_m),
            },
        },
    }
    resp = _post_places_api(f"{PLACES_API_BASE}:searchText", body, api_key)
    return resp.get("places", []) or []


def _parse_place(p: dict) -> dict | None:
    """把 Places API 回傳的 place 物件壓平成本地鏡像 schema。"""
    pid = p.get("id")
    if not pid:
        return None
    dn = p.get("displayName", {})
    name = dn.get("text", "")
    loc = p.get("location", {})
    return {
        "place_id": pid,
        "name_zh": name,
        "name_lang": dn.get("languageCode"),
        "rating": p.get("rating"),
        "total_ratings": p.get("userRatingCount"),
        "location": {"lat": loc.get("latitude"), "lng": loc.get("longitude")},
        "address": p.get("formattedAddress", ""),
        "primary_type": p.get("primaryType"),
    }


def cmd_hotel_search(args):
    """從 places.json 終點呼叫 Places API 搜尋住宿，upsert 到 hotel_map/。

    搜尋策略：
      1. searchNearby includedTypes=["lodging"] radius=3km
      2. 補搜 searchText（飯店 / 民宿 / 旅館 / Hotel）取得更多候選
      3. dedupe by place_id；過濾 rating 或 userRatingCount 為 None
      4. 過濾掉名稱純 ASCII 但同 place_id 已有中文版本（避免雙寫）

    --radius / --min-reviews 可覆寫預設。
    """
    n = args.day
    api_key = _get_api_key()
    radius_m = getattr(args, "radius", None) or DEFAULT_SEARCH_RADIUS_M
    min_reviews = getattr(args, "min_reviews", 0) or 0

    places_file = plan_dir(n) / "places.json"
    if not places_file.exists():
        die(f"day{n}/_plan/places.json 不存在，無法取得終點")
    places_data = read_json(places_file)
    pl = places_data.get("places") or []
    if not pl:
        die("places.json 內無 places")
    endpoint = pl[-1]
    loc = endpoint.get("location") or {}
    lat, lng = loc.get("lat"), loc.get("lng")
    if lat is None or lng is None:
        die(f"終點 {endpoint.get('name_zh','?')} 缺少 location")

    info(f"終點：{endpoint.get('name_zh','?')} ({lat:.5f},{lng:.5f}) radius={radius_m}m")

    all_places: dict[str, dict] = {}

    # 1. searchNearby
    info("呼叫 Places API searchNearby (type=lodging)...")
    for p in _search_nearby(lat, lng, radius_m, api_key):
        parsed = _parse_place(p)
        if parsed:
            all_places[parsed["place_id"]] = parsed

    # 2. searchText 多關鍵字補搜
    for q in SEARCH_TEXT_QUERIES:
        info(f"呼叫 Places API searchText（{q}）...")
        for p in _search_text(q, lat, lng, radius_m, api_key):
            parsed = _parse_place(p)
            if not parsed:
                continue
            pid = parsed["place_id"]
            if pid in all_places:
                # 已存在 → 用較長的中文名稱覆寫（zh-TW 結果優先）
                existing = all_places[pid]
                if _has_cjk(parsed["name_zh"]) and not _has_cjk(existing["name_zh"]):
                    existing["name_zh"] = parsed["name_zh"]
            else:
                all_places[pid] = parsed
        time.sleep(0.15)  # 簡易節流

    raw_count = len(all_places)
    info(f"原始候選：{raw_count} 筆（去重後）")

    # 過濾條件：
    #   (a) primary_type 必須屬於住宿白名單（searchText 會混入餐廳/景點）
    #   (b) 距終點 ≤ radius_km（locationBias 不是嚴格限制）
    #   (c) rating + total_ratings 不可為 None
    #   (d) total_ratings ≥ min_reviews
    radius_km = radius_m / 1000.0
    valid = []
    skipped_wrong_type = 0
    skipped_no_rating = 0
    skipped_low_reviews = 0
    skipped_too_far = 0
    for parsed in all_places.values():
        pt = parsed.get("primary_type")
        if pt and pt not in LODGING_PRIMARY_TYPES:
            skipped_wrong_type += 1
            continue
        ploc = parsed.get("location") or {}
        plat, plng = ploc.get("lat"), ploc.get("lng")
        if plat is None or plng is None:
            skipped_no_rating += 1
            continue
        dist_km = haversine_km(lat, lng, plat, plng)
        if dist_km > radius_km:
            skipped_too_far += 1
            continue
        if parsed["rating"] is None or parsed["total_ratings"] is None:
            skipped_no_rating += 1
            continue
        if parsed["total_ratings"] < min_reviews:
            skipped_low_reviews += 1
            continue
        parsed["distance_km"] = round(dist_km, 2)
        valid.append(parsed)

    if skipped_wrong_type:
        info(f"  跳過 {skipped_wrong_type} 筆（primary_type 非住宿類）")
    if skipped_too_far:
        info(f"  跳過 {skipped_too_far} 筆（距終點 > {radius_km:.1f}km）")
    if skipped_no_rating:
        info(f"  跳過 {skipped_no_rating} 筆（無評分資料）")
    if skipped_low_reviews:
        info(f"  跳過 {skipped_low_reviews} 筆（評論數 < {min_reviews}）")

    # 名稱中英文標註
    today = time.strftime("%Y-%m-%d")
    for item in valid:
        item["source"] = f"api_{today}"
        # 標記英文名（純 ASCII）以便日後人工補中文
        item["name_is_ascii"] = not _has_cjk(item["name_zh"])

    # 寫入鏡像
    idx = _load_hotel_index(n)
    candidates = idx.get("candidates", [])
    pid_map = {c["place_id"]: i for i, c in enumerate(candidates)}

    upserted = 0
    for item in valid:
        pid = item["place_id"]
        write_json(hotel_map_dir(n) / f"{pid}.json", item)
        summary_keys = ("place_id", "name_zh", "rating", "total_ratings",
                        "location", "address", "source", "name_is_ascii")
        summary = {k: item[k] for k in summary_keys if k in item}
        if pid in pid_map:
            old = candidates[pid_map[pid]]
            summary["selected"] = old.get("selected", False)
            candidates[pid_map[pid]] = summary
        else:
            summary["selected"] = False
            candidates.append(summary)
            pid_map[pid] = len(candidates) - 1
        upserted += 1
    idx["candidates"] = candidates
    _save_hotel_index(n, idx)

    info(f"完成：upsert {upserted} 筆到 hotel_map/（共 {len(candidates)} 筆候選）")

    # 中英文檢查報告
    ascii_only = [c for c in valid if c.get("name_is_ascii")]
    if ascii_only:
        print()
        print(f"⚠️  以下 {len(ascii_only)} 筆名稱為純英文（API 未提供中文化），")
        print(f"   若需中文顯示請手動 hotel-put 覆寫 name_zh：")
        for c in ascii_only:
            print(f"    - {c['place_id']}  {c['name_zh']}")
        print()


# ─────────────────────────────────────────────────────────────────
# Mirror 管理
# ─────────────────────────────────────────────────────────────────

def _load_hotel_index(n: int) -> dict:
    idx = hotel_map_dir(n) / "index.json"
    if idx.exists():
        return read_json(idx)
    return {"day": n, "candidates": []}


def _save_hotel_index(n: int, data: dict) -> None:
    write_json(hotel_map_dir(n) / "index.json", data)


def cmd_hotel_status(args):
    """顯示 dayN/hotel_map/（住宿本地鏡像）現況。"""
    n = args.day
    idx = _load_hotel_index(n)
    files = sorted(hotel_map_dir(n).glob("*.json"))
    candidates = idx.get("candidates", [])

    print(f"== Day {n} 住宿本地鏡像現況 ==")
    print(f"hotel_map/ 檔案數：{len(files)}")
    print(f"index.json 候選筆數：{len(candidates)}\n")

    if candidates:
        print("【候選】")
        for c in candidates:
            mark = "★" if c.get("selected") else " "
            r = c.get("rating", "?")
            v = c.get("total_ratings", "?")
            print(f"  {mark} {c.get('name_zh','?'):<24} R={r} V={v}")
    else:
        print("（尚無候選資料，請先搜尋並 hotel-put）")

    print()
    if len(candidates) < 10:
        print(f"⚠️  住宿候選 {len(candidates)} 筆，建議搜尋至 ≥ 15 筆再跑 hotel-pool")


def cmd_hotel_put(args):
    """從 stdin 讀單筆或多筆飯店 JSON，upsert 到本地鏡像。

    stdin schema（單筆或陣列）：
    {
      "place_id": "ChIJ...",          // 必填
      "name_zh": "竹南大飯店",         // 必填
      "rating": 4.6,                  // 必填
      "total_ratings": 320,           // 必填
      "location": {"lat": ..., "lng": ...},
      "address": "苗栗縣竹南鎮...",    // 可選
      "note": "雙人房約 2,500 元 / 含早餐",  // 可選
      "source": "search_2026-05-20"   // 可選
    }
    """
    n = args.day
    data = read_stdin_json()
    if isinstance(data, dict):
        data = [data]

    idx = _load_hotel_index(n)
    candidates = idx.get("candidates", [])
    pid_map = {c["place_id"]: i for i, c in enumerate(candidates)}

    upserted = 0
    for item in data:
        pid = item.get("place_id")
        if not pid:
            info(f"跳過缺 place_id 的項目：{item.get('name_zh', '?')}")
            continue

        f = hotel_map_dir(n) / f"{pid}.json"
        write_json(f, item)

        summary = {k: item[k] for k in (
            "place_id", "name_zh", "rating", "total_ratings", "location", "address", "note", "source"
        ) if k in item}

        if pid in pid_map:
            old = candidates[pid_map[pid]]
            summary["selected"] = old.get("selected", False)
            candidates[pid_map[pid]] = summary
        else:
            summary["selected"] = False
            candidates.append(summary)
            pid_map[pid] = len(candidates) - 1

        upserted += 1

    idx["candidates"] = candidates
    _save_hotel_index(n, idx)
    info(f"upsert {upserted} 筆到 hotel_map/（共 {len(candidates)} 筆候選）")


# ─────────────────────────────────────────────────────────────────
# Bayesian 選 Top 5
# ─────────────────────────────────────────────────────────────────

def _bayesian_score(rating: float, n: int, C: float, m: float) -> float:
    return round((C * m + rating * n) / (C + n), 4)


def _confidence_label(total_ratings: int, C: float) -> str:
    ratio = total_ratings / C if C > 0 else 0
    if ratio >= 1.0:
        return "✅ 高"
    elif ratio >= 0.5:
        return "⚠️ 中"
    else:
        return "❌ 低"


def _collect_hotel_pool(n: int) -> list[dict]:
    idx = _load_hotel_index(n)
    candidates = idx.get("candidates", [])
    pool = []
    seen: set[str] = set()
    for c in candidates:
        pid = c.get("place_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        pf = hotel_map_dir(n) / f"{pid}.json"
        if pf.exists():
            try:
                full = read_json(pf)
            except json.JSONDecodeError:
                full = c
        else:
            full = c
        merged = {**c, **full}
        if merged.get("rating") is not None and merged.get("total_ratings") is not None:
            pool.append(merged)

    deduped: list[dict] = []
    for item in pool:
        loc = item.get("location") or {}
        lat, lng = loc.get("lat"), loc.get("lng")
        matched_idx = None
        if lat is not None and lng is not None:
            for i, k in enumerate(deduped):
                if k.get("name_zh") != item.get("name_zh"):
                    continue
                kloc = k.get("location") or {}
                klat, klng = kloc.get("lat"), kloc.get("lng")
                if klat is None or klng is None:
                    continue
                if haversine_km(lat, lng, klat, klng) < DEDUPE_RADIUS_KM:
                    matched_idx = i
                    break
        if matched_idx is None:
            deduped.append(item)
        else:
            if (item.get("total_ratings") or 0) > (deduped[matched_idx].get("total_ratings") or 0):
                info(f"  dedup：{item.get('name_zh')} 同店重複，捨棄 {deduped[matched_idx].get('place_id','?')}")
                deduped[matched_idx] = item
            else:
                info(f"  dedup：{item.get('name_zh')} 同店重複，捨棄 {item.get('place_id','?')}")
    return deduped


def cmd_hotel_pool(args):
    """從 hotel_map 鏡像候選池算 Bayesian 排序，選 top 5。

    也可 stdin 帶入新資料（會先自動 upsert 到鏡像再算）。
    """
    n = args.day
    import sys

    if not sys.stdin.isatty():
        raw = sys.stdin.read()
        if raw.strip():
            new_data = json.loads(raw)
            if isinstance(new_data, dict):
                new_data = [new_data]

            idx = _load_hotel_index(n)
            candidates = idx.get("candidates", [])
            pid_map = {c["place_id"]: i for i, c in enumerate(candidates)}

            added = 0
            for item in new_data:
                pid = item.get("place_id")
                if not pid:
                    continue
                f = hotel_map_dir(n) / f"{pid}.json"
                write_json(f, item)
                summary = {k: item[k] for k in (
                    "place_id", "name_zh", "rating", "total_ratings",
                    "location", "address", "note", "source"
                ) if k in item}
                if pid in pid_map:
                    old_selected = candidates[pid_map[pid]].get("selected", False)
                    summary["selected"] = old_selected
                    candidates[pid_map[pid]] = summary
                else:
                    summary["selected"] = False
                    candidates.append(summary)
                    pid_map[pid] = len(candidates) - 1
                added += 1

            idx["candidates"] = candidates
            _save_hotel_index(n, idx)
            if added:
                info(f"從 stdin 新增/更新 {added} 筆到 hotel_map/")

    pool = _collect_hotel_pool(n)
    if len(pool) < 3:
        die(f"hotel_map 中有效候選只有 {len(pool)} 筆，至少需要 3 筆。"
            f"請先用 hotel-put 寫入資料。")

    total_ratings_list = [c["total_ratings"] for c in pool]
    C = sum(total_ratings_list) / len(total_ratings_list)
    weighted_sum = sum(c["rating"] * c["total_ratings"] for c in pool)
    total_n = sum(c["total_ratings"] for c in pool)
    m = round(weighted_sum / total_n, 4) if total_n > 0 else 4.0

    scored = []
    for c in pool:
        score = _bayesian_score(c["rating"], c["total_ratings"], C, m)
        confidence = _confidence_label(c["total_ratings"], C)
        scored.append({
            "place_id": c["place_id"],
            "name_zh": c.get("name_zh", "?"),
            "rating": c["rating"],
            "total_ratings": c["total_ratings"],
            "location": c.get("location"),
            "address": c.get("address", ""),
            "note": c.get("note", ""),
            "bayesian_score": score,
            "confidence": confidence,
        })

    scored.sort(key=lambda x: -x["bayesian_score"])

    for i, item in enumerate(scored):
        item["rank"] = i + 1
        item["selected"] = i < 5

    idx = _load_hotel_index(n)
    selected_pids = {s["place_id"] for s in scored[:5]}
    for c in idx.get("candidates", []):
        c["selected"] = c.get("place_id") in selected_pids
    _save_hotel_index(n, idx)

    source_endpoint_pid = None
    places_path = plan_dir(n) / "places.json"
    if places_path.exists():
        try:
            pl = read_json(places_path).get("places") or []
            if pl:
                source_endpoint_pid = pl[-1].get("place_id")
        except Exception:
            pass

    out_data = {
        "day": n,
        "search_radius_km": 3,
        "pool_size": len(scored),
        "bayesian_C": round(C, 1),
        "bayesian_m": m,
        "note": "C=平均留言數(先驗樣本數), m=加權平均評分(先驗期望值)",
        "source_endpoint_place_id": source_endpoint_pid,
        "top5_place_ids": [s["place_id"] for s in scored[:5]],
        "hotels": scored,
    }

    out = plan_dir(n) / "hotel.json"
    write_json(out, out_data)
    info(f"已寫入 {out.relative_to(ROOT)}（{len(scored)} 筆，C={round(C,1)}, m={m}）")

    quiet = getattr(args, "quiet", False)
    if not quiet:
        print(f"\n{'='*60}")
        print(f"  Day {n} 住宿候選排名（{len(scored)} 筆，C={round(C,1)}, m={m}）")
        print(f"  候選池來源：hotel_map/（本地鏡像）")
        print(f"{'='*60}\n")
        print(f"  {'排名':<4} {'貝葉斯分':<8} {'評分':<5} {'留言數':<7} {'信心':<6} {'店名'}")
        print(f"  {'-'*4} {'-'*8} {'-'*5} {'-'*7} {'-'*6} {'-'*20}")
        for item in scored:
            mark = "🏨" if item["selected"] else "  "
            print(f"  {mark}{item['rank']:<3} {item['bayesian_score']:<8} "
                  f"{item['rating']:<5} {item['total_ratings']:<7} "
                  f"{item['confidence']:<6} {item['name_zh']}")
        print(f"\n{'─'*60}")

    print(f"  ★ 入選 Top 5：")
    for item in scored[:5]:
        note = item.get("note", "")
        extra = f" — {note}" if note else ""
        print(f"    {item['rank']}. {item['name_zh']} "
              f"（{item['rating']}★ / {item['total_ratings']}則 → {item['bayesian_score']}）{extra}")
    print()


def cmd_hotel_review(args):
    """顯示 hotel.json 的完整排名 + 與鏡像候選池的差異。"""
    n = args.day
    f = plan_dir(n) / "hotel.json"
    if not f.exists():
        die(f"找不到 {f.relative_to(ROOT)}，請先執行 hotel-pool")

    data = read_json(f)
    scored = data["hotels"]
    C = data["bayesian_C"]
    m = data["bayesian_m"]

    print(f"\n{'='*60}")
    print(f"  Day {n} 住宿候選排名（{len(scored)} 筆）")
    print(f"  Bayesian 參數：C={C}（平均留言數）, m={m}（加權平均評分）")
    print(f"  公式：(C×m + rating×n) / (C+n)")
    print(f"{'='*60}\n")
    print(f"  {'排名':<4} {'貝葉斯分':<8} {'評分':<5} {'留言數':<7} {'信心':<6} {'店名'}")
    print(f"  {'-'*4} {'-'*8} {'-'*5} {'-'*7} {'-'*6} {'-'*20}")
    for item in scored:
        mark = "★" if item.get("selected") else " "
        print(f"  {mark}{item['rank']:<3} {item['bayesian_score']:<8} "
              f"{item['rating']:<5} {item['total_ratings']:<7} "
              f"{item.get('confidence','?'):<6} {item['name_zh']}")

    print(f"\n{'─'*60}")
    print(f"  ★ 入選 Top 5：")
    top5 = [r for r in scored if r.get("selected")]
    for item in top5:
        addr = item.get("address", "")
        note = item.get("note", "")
        extra = f" — {note}" if note else ""
        print(f"    {item['rank']}. {item['name_zh']} "
              f"（{item['rating']}★ / {item['total_ratings']}則 → {item['bayesian_score']}）{extra}")
        if addr:
            print(f"       📍 {addr}")
    print()

    mirror_pool = _collect_hotel_pool(n)
    if len(mirror_pool) > len(scored):
        print(f"  💡 hotel_map/ 目前有 {len(mirror_pool)} 筆候選（hotel.json 只有 {len(scored)} 筆），")
        print(f"     建議重跑 hotel-pool {n} 以納入新資料。\n")


# ─────────────────────────────────────────────────────────────────
# Render dayN_hotel.md
# ─────────────────────────────────────────────────────────────────

def _confidence_emoji(conf: str) -> str:
    if "高" in conf:
        return "✅"
    elif "中" in conf:
        return "⚠️"
    return "❌"


def cmd_hotel_render(args):
    """從 _plan/hotel.json 產出 dayN_hotel.md。"""
    from .helpers import day_dir
    import datetime

    n = args.day
    f = plan_dir(n) / "hotel.json"
    if not f.exists():
        die(f"找不到 {f.relative_to(ROOT)}，請先執行 hotel-pool")

    data = read_json(f)
    scored = data["hotels"]
    C = data["bayesian_C"]
    m = data["bayesian_m"]
    pool_size = data["pool_size"]

    config_f = plan_dir(n) / "config.json"
    destination = f"Day {n} 終點"
    if config_f.exists():
        cfg = read_json(config_f)
        destination = cfg.get("destination", destination)

    top5 = [r for r in scored if r.get("selected")]
    today = datetime.date.today().isoformat()

    lines = []
    lines.append(f"# Day {n} 住宿選擇 🏨\n")
    lines.append(f"**終點：{destination}**（周邊 3 公里 · {pool_size} 筆候選 · 貝葉斯排序）\n")
    lines.append(f"> 公式：`貝葉斯分 = (C × m + rating × n) / (C + n)`")
    lines.append(f"> C = {C}（平均留言數）· m = {m}（加權平均評分）\n")
    lines.append("---\n")
    lines.append("## ★ Top 5 入選\n")

    for item in top5:
        pid = item["place_id"]
        url = f"https://www.google.com/maps/place/?q=place_id:{pid}"
        conf = item.get("confidence", "?")
        addr = item.get("address", "")
        note = item.get("note", "")

        lines.append(f"### 🏨 {item['rank']}. [{item['name_zh']}]({url})\n")
        lines.append("| 貝葉斯分 | 評分 | 留言數 | 信心 |")
        lines.append("|:---:|:---:|:---:|:---:|")
        lines.append(f"| **{item['bayesian_score']}** | {item['rating']}★ | {item['total_ratings']} | {conf} |\n")
        if addr:
            lines.append(f"📍 {addr}")
        if note:
            lines.append(f"✨ {note}")
        lines.append("")
        lines.append("---\n")

    lines.append("## 候選池完整排名\n")
    lines.append("| # | 貝葉斯分 | 評分 | 留言 | 信心 | 店名 |")
    lines.append("|:---:|:---:|:---:|---:|:---:|:---|")
    for item in scored:
        mark = "★" if item.get("selected") else ""
        conf = item.get("confidence", "?")
        conf_short = _confidence_emoji(conf)
        lines.append(f"| {mark}{item['rank']} | {item['bayesian_score']} | {item['rating']} "
                     f"| {item['total_ratings']} | {conf_short} | {item['name_zh']} |")
    lines.append("")

    lines.append("---\n")
    lines.append(f"*資料來源：Google Places API (New) · 搜尋日期：{today} · 候選池 {pool_size} 筆*")
    lines.append("*排序方法：IMDB 風格貝葉斯平均（留言數越多、評分越可信）*\n")

    out = day_dir(n) / f"day{n}_hotel.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")
    print(f"產出：{out.relative_to(ROOT)}")

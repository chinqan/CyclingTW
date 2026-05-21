"""Google Places API (New) 直接呼叫 — 取代 MCP place_details。

用法：
  export GOOGLE_PLACES_API_KEY='your-key'
  python3 scripts/plan.py refresh-details 2

只請求 Essentials 層欄位（rating, userRatingCount, regularOpeningHours, location,
displayName），回傳精簡 JSON 並自動 upsert 到本地鏡像。

費用：前 10,000 次/月免費（Essentials tier @ $5/1000），環島規劃全程 < 200 次。
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Any

try:
    import urllib.request
    import urllib.error
except ImportError:
    pass

from .helpers import (
    ROOT, plan_dir, map_dir, read_json, write_json, info, die,
)
from .mirror import load_mirror_index, save_mirror_index

# Places API (New) 只取這些欄位 → 計費走 Essentials tier ($5/1000)
# 加 reviews 會升級到 Pro ($17/1000)，所以不加
FIELD_MASK_ESSENTIALS = ",".join([
    "displayName",
    "rating",
    "userRatingCount",
    "regularOpeningHours",
    "location",
    "editorialSummary",
])

# 如果需要 reviews（Pro tier），用這個 mask
FIELD_MASK_PRO = FIELD_MASK_ESSENTIALS + ",reviews"

API_BASE = "https://places.googleapis.com/v1/places"


def _get_api_key() -> str:
    key = os.environ.get("GOOGLE_PLACES_API_KEY", "")
    if not key:
        die(
            "缺少 GOOGLE_PLACES_API_KEY 環境變數。\n"
            "請至 https://console.cloud.google.com/apis/credentials 建立 API Key，\n"
            "並啟用 Places API (New)，然後：\n"
            "  export GOOGLE_PLACES_API_KEY='your-key-here'"
        )
    return key


def fetch_place_details(
    place_id: str,
    api_key: str,
    include_reviews: bool = False,
) -> dict[str, Any]:
    """呼叫 Places API (New) 的 Place Details，回傳精簡 dict。

    回傳格式：
    {
        "place_id": "ChIJ...",
        "name_zh": "...",
        "rating": 4.5,
        "total_ratings": 1234,
        "location": {"lat": ..., "lng": ...},
        "opening_hours_text": [...],   # 或 None
        "editorial_summary": "...",    # 或 None
    }
    """
    url = f"{API_BASE}/{place_id}"
    mask = FIELD_MASK_PRO if include_reviews else FIELD_MASK_ESSENTIALS
    headers = {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": mask,
        "X-Goog-Api-Language": "zh-TW",
    }

    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8", errors="replace")
        die(f"Places API HTTP {e.code} for {place_id}:\n{error_body}")
    except urllib.error.URLError as e:
        die(f"Places API 網路錯誤 for {place_id}: {e.reason}")

    # 解析回傳
    result: dict[str, Any] = {"place_id": place_id}

    dn = body.get("displayName", {})
    result["name_zh"] = dn.get("text", "")

    result["rating"] = body.get("rating")
    result["total_ratings"] = body.get("userRatingCount")

    loc = body.get("location", {})
    result["location"] = {"lat": loc.get("latitude"), "lng": loc.get("longitude")}

    hours = body.get("regularOpeningHours")
    if hours and "weekdayDescriptions" in hours:
        result["opening_hours_text"] = hours["weekdayDescriptions"]
    else:
        result["opening_hours_text"] = None

    es = body.get("editorialSummary")
    result["editorial_summary"] = es.get("text") if es else None

    return result


def cmd_refresh_details(args):
    """對 places.json 中所有可評分點位呼叫 Places API，upsert 回 mirror。"""
    n = args.day
    api_key = _get_api_key()
    include_reviews = getattr(args, "with_reviews", False)

    places_file = plan_dir(n) / "places.json"
    if not places_file.exists():
        die(f"day{n}/_plan/places.json 不存在，請先建立點位清單")

    places_data = read_json(places_file)
    places = places_data.get("places", [])

    # 只對可評分類型呼叫
    RATED_TYPES = {"景點", "起終點", "餐廳大休"}
    targets = [p for p in places if p.get("csv_type") in RATED_TYPES]

    if not targets:
        info("沒有可評分的點位需要刷新")
        return

    tier = "Pro" if include_reviews else "Essentials"
    info(f"呼叫 Places API ({tier}) 刷新 {len(targets)} 個點位...")

    mirror_idx = load_mirror_index(n)
    updated = 0
    errors = 0

    for i, p in enumerate(targets, 1):
        pid = p["place_id"]
        try:
            fresh = fetch_place_details(pid, api_key, include_reviews)
        except SystemExit:
            # die() raises SystemExit; catch it for batch continuation
            errors += 1
            print(f"  ✗ [{i}/{len(targets)}] {p.get('name_zh', pid)} — API 錯誤", file=sys.stderr)
            continue

        # 比對差異
        old_r = p.get("rating")
        old_v = p.get("total_ratings")
        new_r = fresh["rating"]
        new_v = fresh["total_ratings"]
        diff_parts = []
        if old_r != new_r:
            diff_parts.append(f"R {old_r}→{new_r}")
        if old_v != new_v:
            diff_parts.append(f"V {old_v}→{new_v}")
        diff_str = " ".join(diff_parts) if diff_parts else "—"

        print(f"  {'✓' if diff_parts else '·'} [{i}/{len(targets)}] {(fresh['name_zh'] or pid)[:20]:<20} "
              f"R={new_r} V={str(new_v):>6}  {diff_str}")

        # upsert 到 mirror 個別 JSON
        mirror_file = map_dir(n) / f"{pid}.json"
        if mirror_file.exists():
            existing = read_json(mirror_file)
        else:
            existing = {}

        existing["place_id"] = pid
        # 只在 API 回傳非空中文時才覆蓋 name_zh；避免英文蓋掉手動設定的中文
        api_name = fresh["name_zh"]
        if api_name and not all(ord(c) < 128 or c in ' ' for c in api_name):
            existing["name_zh"] = api_name
        elif not existing.get("name_zh"):
            existing["name_zh"] = api_name or ""
        existing["rating"] = new_r
        existing["total_ratings"] = new_v
        existing["location"] = fresh["location"]
        existing["source"] = f"api_{time.strftime('%Y-%m-%d')}"
        if fresh["opening_hours_text"]:
            existing["opening_hours_text"] = fresh["opening_hours_text"]
        if fresh["editorial_summary"]:
            existing["editorial_summary"] = fresh["editorial_summary"]

        write_json(mirror_file, existing)

        # upsert index.json
        for bucket_name in ("places", "candidates_not_selected"):
            b = mirror_idx.setdefault(bucket_name, [])
            for entry in b:
                if entry.get("place_id") == pid:
                    entry["rating"] = new_r
                    entry["total_ratings"] = new_v
                    # 只在 API 回傳非純 ASCII 時才覆蓋 name_zh
                    api_name = fresh["name_zh"]
                    if api_name and not all(ord(c) < 128 or c in ' ' for c in api_name):
                        entry["name_zh"] = api_name
                    if fresh["location"]["lat"]:
                        entry["location"] = fresh["location"]
                    break

        updated += 1

        # 簡易節流：每 5 筆暫停 0.2 秒（避免突發 QPS 超限）
        if i % 5 == 0 and i < len(targets):
            time.sleep(0.2)

    save_mirror_index(n, mirror_idx)
    info(f"完成：{updated} 筆已更新，{errors} 筆失敗")
    if updated > 0:
        info("建議接著執行：python3 scripts/plan.py score-pool N && compute N")

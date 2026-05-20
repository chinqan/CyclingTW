"""CSV 產出：write-csv。"""
from __future__ import annotations

import csv
import re

from .helpers import ROOT, day_dir, plan_dir, read_json, die, info

RATED_TYPES = {"景點", "起終點", "餐廳大休"}

CSV_HEADERS = [
    "景點名稱", "地點搜尋關鍵字", "順序", "類型", "評分", "評論總數",
    "bayesian_C", "bayesian_m", "bayesian_score", "備註說明",
]


def cmd_write_csv(args):
    n = args.day
    cfg = read_json(plan_dir(n) / "config.json")
    data = read_json(plan_dir(n) / "places.json")

    places = data["places"]
    missing_kw = [p.get("name_zh", "?") for p in places if not p.get("search_keyword")]
    if missing_kw:
        die(f"places.json 中以下點位缺 search_keyword：{', '.join(missing_kw)}")

    # ── 座標精度驗證：擋住未經 MCP 搜尋的粗估座標 ──
    from .helpers import map_dir
    coarse_warnings = []
    for p in places:
        loc = p.get("location", {})
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is None or lng is None:
            coarse_warnings.append(f"  {p.get('name_zh','?')}: 缺少 location.lat/lng")
            continue
        # 座標精度至少 4 位小數（約 11m 精度），粗估座標通常只有 2-3 位
        lat_decimals = len(str(lat).split(".")[-1]) if "." in str(lat) else 0
        lng_decimals = len(str(lng).split(".")[-1]) if "." in str(lng) else 0
        if lat_decimals < 4 or lng_decimals < 4:
            # 如果 mirror 有這筆的精確資料就跳過警告
            pid = p.get("place_id", "")
            mirror_file = map_dir(n) / f"{pid}.json"
            if not mirror_file.exists():
                coarse_warnings.append(
                    f"  {p.get('name_zh','?')}: 座標精度不足（lat 小數 {lat_decimals} 位, lng 小數 {lng_decimals} 位），"
                    f"且 mirror 中無 {pid}.json。請用 Google Maps search_places 取得精確座標後 mirror-put。")
    if coarse_warnings:
        info("⚠️  以下點位座標精度可疑（可能未經 MCP 搜尋）：\n" + "\n".join(coarse_warnings))

    last = places[-1]
    last_name = last["name_zh"]
    dest_raw = cfg["destination"]
    dest_options = [s.strip() for s in re.split(r"[/、,，]", dest_raw) if s.strip()]
    matched = any(opt in last_name or last_name in opt for opt in dest_options)
    if not matched:
        info(f"⚠️  最後一筆 '{last_name}' 與 index.md 目的地 '{dest_raw}' 不完全相符，請確認")

    C, m = data.get("bayesian_C"), data.get("bayesian_m")
    if C is None or m is None:
        die("places.json 缺少 bayesian_C/m，請先執行 compute")

    out = day_dir(n) / f"day{n}_mymap.csv"
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp, lineterminator="\n")
        w.writerow(CSV_HEADERS)
        for i, p in enumerate(places, 1):
            rated = p.get("csv_type") in RATED_TYPES
            w.writerow([
                p["name_zh"],
                p["search_keyword"],
                i,
                p["csv_type"],
                p.get("rating", "") if rated else "",
                p.get("total_ratings", "") if rated else "",
                C if rated else "",
                m if rated else "",
                p.get("bayesian_score", "") if rated else "",
                p.get("note", ""),
            ])
    info(f"已寫入 {out.relative_to(ROOT)}（{len(places)} 筆）")

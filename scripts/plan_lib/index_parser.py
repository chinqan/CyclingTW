"""Phase 0：parse-index — 從 index.md 解析每日設定；update-index — 回寫實際距離。"""
from __future__ import annotations

import json
import re

from .helpers import (ROOT, plan_dir, read_json, write_json, die, info,
                      normalize_landmark, is_note_landmark)

INDEX_TABLE_ROW = re.compile(
    r"^\|\s*\[?Day\s*(\d+)\]?[^|]*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|$"
)


def parse_index_md(n: int) -> dict:
    """從 index.md 抽出第 N 天的設定。"""
    md = (ROOT / "index.md").read_text(encoding="utf-8")
    for line in md.splitlines():
        m = INDEX_TABLE_ROW.match(line.strip())
        if not m:
            continue
        day = int(m.group(1))
        if day != n:
            continue
        origin = m.group(2).strip()
        dest = m.group(3).strip()
        dist_txt = m.group(4).strip()
        route = m.group(5).strip()
        spots = m.group(6).strip()

        nums = [int(x) for x in re.findall(r"\d+", dist_txt)]
        if not nums:
            dist_range = [None, None]
        elif len(nums) == 1:
            dist_range = [nums[0], nums[0]]
        else:
            dist_range = nums[:2]

        # 必經景點：拆分（含 / ；）、正規化（去 markdown / 極X：前綴）、丟棄敘述型備註
        landmarks = []
        for s in re.split(r"[、，,；;/]", spots):
            lm = normalize_landmark(s)
            if lm and not is_note_landmark(lm):
                landmarks.append(lm)

        return {
            "day": day,
            "origin": origin,
            "destination": dest,
            "distance_km_range": dist_range,
            "main_route_text": route,
            "must_visit_landmarks": landmarks,
        }
    die(f"index.md 中找不到 Day {n} 的列")


def cmd_parse_index(args):
    cfg = parse_index_md(args.day)
    out = plan_dir(args.day) / "config.json"
    if out.exists():
        try:
            existing = json.loads(out.read_text(encoding="utf-8"))
            if existing == cfg:
                info(f"{out.relative_to(ROOT)} 內容無變動，跳過寫入")
                print(json.dumps(cfg, ensure_ascii=False, indent=2))
                return
        except json.JSONDecodeError:
            pass
    write_json(out, cfg)
    info(f"已寫入 {out.relative_to(ROOT)}")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))


def cmd_update_index(args):
    """從 places.json 的 ors_distance_km 回寫 index.md 的估計距離欄位。"""
    n = args.day
    places_file = plan_dir(n) / "places.json"
    if not places_file.exists():
        die(f"day{n}/_plan/places.json 不存在")

    data = read_json(places_file)
    dist_km = data.get("ors_distance_km")
    if dist_km is None:
        die(f"places.json 中沒有 ors_distance_km，請先執行 route {n}")

    # 讀取 index.md
    index_path = ROOT / "index.md"
    lines = index_path.read_text(encoding="utf-8").splitlines()

    updated = False
    for i, line in enumerate(lines):
        m = INDEX_TABLE_ROW.match(line.strip())
        if not m:
            continue
        day = int(m.group(1))
        if day != n:
            continue

        # 產生新的距離文字：「約 XX km」
        new_dist = f"約 {dist_km:.0f} km"

        # 取得原始距離欄位位置，替換之
        # 把整行依 | 分割再重組
        parts = line.split("|")
        # parts: ['', ' [Day 2]...', ' 出發地 ', ' 目的地 ', ' 估計距離 ', ' 路線 ', ' 景點 ', '']
        # 第 4 個欄位（index 4，0-based counting empty first）是估計距離
        if len(parts) >= 7:
            old_dist = parts[4].strip()
            parts[4] = f" {new_dist} "
            new_line = "|".join(parts)
            if new_line != line:
                lines[i] = new_line
                updated = True
                info(f"Day {n} 距離：{old_dist} → {new_dist}")
            else:
                info(f"Day {n} 距離已是最新（{new_dist}）")
        break

    if not updated:
        info("index.md 無需更新")
        return

    index_path.write_text("\n".join(lines) + "\n" if lines[-1] != "" else "\n".join(lines), encoding="utf-8")
    info(f"已更新 index.md")

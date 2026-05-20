"""Phase 0：parse-index — 從 index.md 解析每日設定。"""
from __future__ import annotations

import json
import re

from .helpers import ROOT, plan_dir, write_json, die, info

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

        landmarks = [s.strip() for s in re.split(r"[、，,]", spots) if s.strip()]

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

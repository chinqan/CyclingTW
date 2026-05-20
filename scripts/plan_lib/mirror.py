"""本地鏡像 DB（mirror）管理：mirror-status / mirror-put / mirror-diff。"""
from __future__ import annotations

import json

from .helpers import ROOT, map_dir, read_json, write_json, read_stdin_json, die, info


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

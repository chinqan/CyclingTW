#!/usr/bin/env python3
"""
CyclingTW Day Planner — 半自動腳本工具
=====================================
搭配 cycling-day-route-planning skill 使用。Claude 在對話中呼叫 MCP 工具取得
資料，並透過本腳本完成所有機械步驟（快取/Bayesian/CSV/GPX/模板渲染）。

設計原則：
  - 快取優先：所有 place_id 走 dayN/map/<pid>.json
  - 先 diff 後 put：mirror-diff 顯示變動，mirror-put 一律 upsert 寫回
  - Bayesian 動態重算：C = 候選池平均，m = 中位數 (≥100)
  - 不變式驗證：CSV 終點 = index.md 目的地

子命令：
  parse-index N            解析 index.md 第 N 天設定
  mirror-status N          列出 dayN/map/（本地鏡像）內容與候選池警告
  mirror-put N             [stdin] upsert 單筆 place 到本地鏡像
  mirror-diff N            [stdin] 比對本地鏡像 vs 線上最新
  compute N                從 mirror 同步最新值並重算 Bayesian
  review N                 重評整個候選池，提示是否有更佳替換
  compute N                重算 Bayesian C/m/score，寫回 _plan/places.json
  write-csv N              產 dayN_mymap.csv（依 _plan/places.json）
  gpx-save N               [stdin] 儲存 GPX（Claude 由 openroute MCP 取得後 pipe）
  render-prompt N          產 dayN_prompt.md（依 _plan/poster_vars.json）
  render-md N              產 dayN.md（依 _plan/places.json + segments.json）

每日工作目錄結構（自動建立）：
  dayN/
  ├── _plan/
  │   ├── config.json        ← parse-index 產出（起終點/距離/必經景點）
  │   ├── places.json        ← Claude 決定的最終點位順序與 Bayesian 結果
  │   ├── segments.json      ← Claude 寫的段落敘述/魚骨圖/注意事項
  │   └── poster_vars.json   ← Claude 決定的海報主視覺與 5 變數
  ├── map/                   ← 既有 place_details 快取
  └── dayN_*.{csv,gpx,md}    ← 最終產出
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import statistics
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
except ImportError:
    print("[error] 缺少 jinja2，請安裝：pip install jinja2", file=sys.stderr)
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"

# ───────────────────────── helpers ─────────────────────────

def day_dir(n: int) -> Path:
    return ROOT / f"day{n}"

def plan_dir(n: int) -> Path:
    p = day_dir(n) / "_plan"
    p.mkdir(parents=True, exist_ok=True)
    return p

def map_dir(n: int) -> Path:
    p = day_dir(n) / "map"
    p.mkdir(parents=True, exist_ok=True)
    return p

def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))

def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def read_stdin_json() -> Any:
    raw = sys.stdin.read()
    if not raw.strip():
        die("stdin 為空，請 pipe JSON 資料進來")
    return json.loads(raw)

def die(msg: str, code: int = 1) -> None:
    print(f"[error] {msg}", file=sys.stderr)
    sys.exit(code)

def info(msg: str) -> None:
    print(f"[info] {msg}", file=sys.stderr)

# ─────────────────── Phase 0: parse index.md ───────────────────

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
        origin   = m.group(2).strip()
        dest     = m.group(3).strip()
        dist_txt = m.group(4).strip()
        route    = m.group(5).strip()
        spots    = m.group(6).strip()

        # 距離範圍解析 "約 80–100 km" → [80, 100]
        dist_range = [int(x) for x in re.findall(r"\d+", dist_txt)] or [None, None]
        if len(dist_range) == 1:
            dist_range *= 2

        # 必經景點切分（以、, 分隔）
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
    write_json(out, cfg)
    info(f"已寫入 {out.relative_to(ROOT)}")
    print(json.dumps(cfg, ensure_ascii=False, indent=2))

# ─────────────────── 本地鏡像 DB（mirror）管理 ───────────────────

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
    by_type: dict[str, list[str]] = {}
    for p in mirror.get("places", []):
        by_type.setdefault(p.get("csv_type", "未分類"), []).append(p["name_zh"])

    print(f"== Day {n} 本地鏡像現況 ==")
    print(f"map/ 檔案數：{len(files)}")
    print(f"index.json places：{len(mirror.get('places', []))}")
    print(f"index.json 未入選候選：{len(mirror.get('candidates_not_selected', []))}\n")
    for t, names in by_type.items():
        print(f"  [{t}] ({len(names)}) {'、'.join(names)}")

    # 候選池規模檢查（依 SOP：景點 ≥ 3-5、餐廳 ≥ 2-3）
    rated = [p for p in mirror.get("places", []) if p.get("csv_type") in ("景點", "起終點")]
    rests = [p for p in mirror.get("places", []) if p.get("csv_type") == "餐廳大休"]
    print()
    if len(rated) < 5:
        print(f"⚠️  景點/起終點候選 {len(rated)} 筆，建議再廣搜至 ≥ 5 筆")
    if len(rests) < 2:
        print(f"⚠️  餐廳大休候選 {len(rests)} 筆，建議再廣搜至 ≥ 2 筆")

def cmd_mirror_put(args):
    """從 stdin 讀單筆 place JSON，upsert 到本地鏡像（同 place_id 覆寫成最新值）。
    保證同 place_id 只會出現在一個 bucket（places 或 candidates_not_selected）。"""
    n = args.day
    data = read_stdin_json()
    pid = data.get("place_id") or die("缺少 place_id 欄位")
    f = map_dir(n) / f"{pid}.json"
    write_json(f, data)
    # 同步 index.json：先從所有 bucket 移除此 pid，再加到指定 target
    idx = load_mirror_index(n)
    target = data.get("target", "places")
    for bucket_name in ("places", "candidates_not_selected"):
        b = idx.setdefault(bucket_name, [])
        b[:] = [x for x in b if x.get("place_id") != pid]
    idx[target].append({k: data[k] for k in (
        "place_id", "name_zh", "csv_type", "rating", "total_ratings", "location", "source", "note"
    ) if k in data})
    save_mirror_index(n, idx)
    info(f"upsert {f.relative_to(ROOT)} → {target}")

def cmd_mirror_diff(args):
    """從 stdin 讀剛從 MCP 拿到的 fresh 資料，與本地鏡像比對 rating / total_ratings。"""
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

# ─────────────────── Bayesian ───────────────────

RATED_TYPES = {"景點", "起終點", "餐廳大休"}

def compute_bayesian(places: list[dict]) -> tuple[float, int]:
    rated = [p for p in places if p.get("csv_type") in RATED_TYPES and p.get("rating") and p.get("total_ratings")]
    if len(rated) < 2:
        die(f"Bayesian 計算需要 ≥ 2 個評分點，目前 {len(rated)}")
    C = sum(p["rating"] for p in rated) / len(rated)
    v_list = sorted(p["total_ratings"] for p in rated)
    m_raw = statistics.median(v_list)
    m = max(int(m_raw), 100)
    return round(C, 4), m

def _refresh_place_from_mirror(n: int, p: dict) -> dict:
    """以 place_id 從 mirror 拉最新 rating/total_ratings/location/name_zh。"""
    pid = p.get("place_id")
    if not pid:
        return p
    mf = map_dir(n) / f"{pid}.json"
    if not mf.exists():
        return p  # mirror 沒有此筆，沿用 places.json 內的值
    m = read_json(mf)
    for field in ("rating", "total_ratings", "location", "name_zh"):
        if m.get(field) is not None:
            p[field] = m[field]
    return p

def cmd_compute(args):
    """讀 _plan/places.json，依 place_id 從 mirror 拉最新值，重算 Bayesian 並寫回。"""
    n = args.day
    f = plan_dir(n) / "places.json"
    if not f.exists():
        die(f"找不到 {f.relative_to(ROOT)}，請先用 Claude 寫入點位選擇")
    data = read_json(f)

    # 從 mirror 同步最新數值
    refreshed = 0
    for p in data["places"]:
        before = (p.get("rating"), p.get("total_ratings"))
        _refresh_place_from_mirror(n, p)
        after = (p.get("rating"), p.get("total_ratings"))
        if before != after:
            refreshed += 1
    if refreshed:
        info(f"從 mirror 同步了 {refreshed} 個點位的最新數值")

    C, m = compute_bayesian(data["places"])
    data["bayesian_C"] = C
    data["bayesian_m"] = m
    for p in data["places"]:
        if p.get("csv_type") in RATED_TYPES and p.get("rating") and p.get("total_ratings"):
            v, R = p["total_ratings"], p["rating"]
            p["bayesian_score"] = round((v / (v + m)) * R + (m / (v + m)) * C, 2)
        else:
            p["bayesian_score"] = None
    write_json(f, data)
    print(f"C = {C}, m = {m}\n")
    for p in data["places"]:
        score = p.get("bayesian_score")
        print(f"  [{p.get('csv_type','-'):<6}] {p['name_zh']:<22} "
              f"R={p.get('rating')} V={p.get('total_ratings')} → {score}")

def cmd_review(args):
    """重評 mirror 中所有候選（含 candidates_not_selected），偵測是否有更佳替換。"""
    n = args.day
    sel_file = plan_dir(n) / "places.json"
    if not sel_file.exists():
        die(f"找不到 {sel_file.relative_to(ROOT)}")
    sel_data = read_json(sel_file)
    selected_pids = {p["place_id"] for p in sel_data["places"]}

    mirror = load_mirror_index(n)
    pool = mirror.get("places", []) + mirror.get("candidates_not_selected", [])
    # 對 mirror 中每筆從個別檔案拉最新值（更精確）；解析失敗則沿用 index.json 內值
    seen_pids = set()
    enriched = []
    for c in pool:
        if c.get("place_id") in seen_pids:
            continue
        seen_pids.add(c.get("place_id"))
        pid = c.get("place_id")
        if not pid:
            continue
        mf = map_dir(n) / f"{pid}.json"
        full = {}
        if mf.exists():
            try:
                full = read_json(mf)
            except json.JSONDecodeError as e:
                info(f"⚠️  跳過格式損壞的 {mf.name}：{e}")
        item = {**c, **{k: full[k] for k in ("rating","total_ratings","csv_type","name_zh") if k in full}}
        if item.get("csv_type") in RATED_TYPES and item.get("rating") and item.get("total_ratings"):
            enriched.append(item)

    if len(enriched) < 2:
        die(f"候選池可評分點少於 2，無法重評（目前 {len(enriched)}）")

    # 計算 Bayesian（用整個池子，不只當前選擇）
    C = round(sum(p["rating"] for p in enriched) / len(enriched), 4)
    v_sorted = sorted(p["total_ratings"] for p in enriched)
    m = max(int(statistics.median(v_sorted)), 100)
    for p in enriched:
        v, R = p["total_ratings"], p["rating"]
        p["bayesian_score"] = round((v/(v+m))*R + (m/(v+m))*C, 2)

    print(f"=== Day {n} 候選池全評（{len(enriched)} 筆，C={C}, m={m}）===\n")

    # 依 csv_type 分組排名
    by_type: dict[str, list[dict]] = {}
    for p in enriched:
        by_type.setdefault(p["csv_type"], []).append(p)
    for t in ["起終點", "景點", "餐廳大休"]:
        items = sorted(by_type.get(t, []), key=lambda x: -x["bayesian_score"])
        if not items:
            continue
        print(f"[{t}]")
        for p in items:
            mark = "★" if p["place_id"] in selected_pids else " "
            print(f"  {mark} {p['name_zh']:<28} R={p['rating']} V={p['total_ratings']:>6} → {p['bayesian_score']}")
        print()

    # 替換偵測：每個類別比較「最差入選」vs「最佳未入選」
    swaps = []
    for t, items in by_type.items():
        if t == "起終點":
            continue  # 起終點由 index.md 固定，不替換
        items.sort(key=lambda x: -x["bayesian_score"])
        inn = [c for c in items if c["place_id"] in selected_pids]
        out = [c for c in items if c["place_id"] not in selected_pids]
        if not inn or not out:
            continue
        worst_in = min(inn, key=lambda x: x["bayesian_score"])
        best_out = max(out, key=lambda x: x["bayesian_score"])
        if best_out["bayesian_score"] > worst_in["bayesian_score"]:
            swaps.append((t, worst_in, best_out, best_out["bayesian_score"] - worst_in["bayesian_score"]))

    if swaps:
        print("⚠️  偵測到可能的替換（新資料導致排名翻轉）：\n")
        for t, drop, gain, delta in swaps:
            print(f"  [{t}] 考慮把：")
            print(f"      [入選] {drop['name_zh']} (score {drop['bayesian_score']})")
            print(f"      ↓ 換成 ↓")
            print(f"      [未選] {gain['name_zh']} (score {gain['bayesian_score']})  +{delta:.2f}")
            print()
        print("→ 確認後請手動編輯 _plan/places.json 把 place_id 換掉，再跑 compute + write-csv")
    else:
        print("✓ 當前選擇仍是各類別 Bayesian 最高，無需替換")

# ─────────────────── CSV ───────────────────

CSV_HEADERS = ["景點名稱","地點搜尋關鍵字","順序","類型","評分","評論總數",
               "bayesian_C","bayesian_m","bayesian_score","備註說明"]

def cmd_write_csv(args):
    n = args.day
    cfg = read_json(plan_dir(n) / "config.json")
    data = read_json(plan_dir(n) / "places.json")

    places = data["places"]
    # 不變式驗證
    last = places[-1]
    if cfg["destination"] not in last["name_zh"] and last["name_zh"] not in cfg["destination"]:
        info(f"⚠️  最後一筆 '{last['name_zh']}' 與 index.md 目的地 '{cfg['destination']}' 不完全相符，請確認")

    C, m = data.get("bayesian_C"), data.get("bayesian_m")
    if C is None or m is None:
        die("places.json 缺少 bayesian_C/m，請先執行 compute")

    out = day_dir(n) / f"day{n}_mymap.csv"
    with out.open("w", newline="", encoding="utf-8") as fp:
        w = csv.writer(fp)
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

# ─────────────────── GPX ───────────────────

def cmd_gpx_save(args):
    """從 stdin 接收 GPX 文字（Claude 由 openroute MCP 取得後 pipe 進來），儲存。"""
    n = args.day
    raw = sys.stdin.read()
    if "<gpx" not in raw:
        die("stdin 不像 GPX 內容（找不到 <gpx 標籤）")
    # 容錯：若被包在 JSON resource 信封內，抽出 <?xml 之後
    start = raw.find("<?xml")
    if start == -1:
        start = raw.find("<gpx")
    gpx = raw[start:]
    out = day_dir(n) / f"day{n}_route.gpx"
    out.write_text(gpx, encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}（{len(gpx)} chars）")

def cmd_gpx_waypoints(args):
    """無 openroute 時的備案：依 places.json 座標產出純航點 GPX。"""
    n = args.day
    data = read_json(plan_dir(n) / "places.json")
    places = data["places"]
    lats = [p["location"]["lat"] for p in places]
    lons = [p["location"]["lng"] for p in places]
    gpx = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="CyclingTW">',
        f'  <metadata><name>Day {n} {data.get("route_name","")}</name>',
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

# ─────────────── GPX 分段（解決 openroute MCP 100KB 截斷）───────────────

def cmd_gpx_split_plan(args):
    """切割長路線為 N 段，每段 ≤ max_waypoints 中間點，避免 MCP 輸出截斷。
    輸出每段的 from/to/waypoints 給 Claude，Claude 對每段呼叫 openroute MCP。
    """
    n = args.day
    max_wp = args.max_waypoints  # 每段中間 waypoints 上限（不含 from/to）
    data = read_json(plan_dir(n) / "places.json")
    coords = [(p["location"]["lng"], p["location"]["lat"], p["name_zh"]) for p in data["places"]]
    if len(coords) < 2:
        die("places.json 至少需要 2 個點位")

    chunk = max_wp + 2  # 每段總點數上限 = from + waypoints + to
    legs = []
    i = 0
    while i < len(coords) - 1:
        end = min(i + chunk, len(coords))
        seg = coords[i:end]
        legs.append({
            "leg": len(legs) + 1,
            "from_name": seg[0][2],
            "to_name": seg[-1][2],
            "from_coordinates": [seg[0][0], seg[0][1]],
            "to_coordinates": [seg[-1][0], seg[-1][1]],
            "waypoints": [[c[0], c[1]] for c in seg[1:-1]],
        })
        i = end - 1  # 與下一段共用端點，確保軌跡連續

    plan_file = plan_dir(n) / "gpx_split.json"
    write_json(plan_file, {"legs": legs})
    print(f"切成 {len(legs)} 段（每段 ≤ {max_wp} 個中間 waypoints）：\n")
    for L in legs:
        print(f"  Leg {L['leg']}: {L['from_name']} → {L['to_name']}  ({len(L['waypoints'])} waypoints)")
    print(f"\nClaude 操作：")
    print(f"  1. 對每段呼叫 mcp__openroute-mcp__create_route_from_to")
    print(f"     (參數從 {plan_file.relative_to(ROOT)} 取出對應 leg)")
    print(f"  2. 將 MCP 結果 pipe 給 'plan.py gpx-append {n} --leg <i>'")
    print(f"  3. 最後 'plan.py gpx-merge {n}' 合併所有 leg")

def cmd_gpx_append(args):
    """[stdin] 儲存單段 openroute MCP GPX 到 _plan/gpx_leg_<i>.gpx。"""
    n = args.day
    leg_i = args.leg
    raw = sys.stdin.read()
    start = raw.find("<?xml")
    if start == -1:
        start = raw.find("<gpx")
    if start == -1:
        die("stdin 不含 GPX 內容")
    gpx = raw[start:]
    # 容錯：若被截斷沒有 </gpx>，補上閉合標籤
    if "</gpx>" not in gpx:
        # 找到最後一個完整的 </rtept>
        last_rtept = gpx.rfind("</rtept>")
        if last_rtept > 0:
            gpx = gpx[:last_rtept + len("</rtept>")] + "\n  </rte>\n</gpx>"
            info("⚠️  GPX 被截斷，已自動補上閉合標籤")
    out = plan_dir(n) / f"gpx_leg_{leg_i}.gpx"
    out.write_text(gpx, encoding="utf-8")
    rtept_count = len(re.findall(r"<rtept", gpx))
    info(f"已儲存 leg {leg_i} → {out.relative_to(ROOT)}（{rtept_count} 個 rtept）")

def cmd_gpx_merge(args):
    """合併 _plan/gpx_leg_*.gpx 為最終 dayN_route.gpx。"""
    n = args.day
    leg_files = sorted(
        plan_dir(n).glob("gpx_leg_*.gpx"),
        key=lambda p: int(re.search(r"leg_(\d+)", p.name).group(1))
    )
    if not leg_files:
        die(f"找不到 {plan_dir(n).relative_to(ROOT)}/gpx_leg_*.gpx，請先用 gpx-append 儲存各段")

    rtept_pattern = re.compile(r'<rtept\s+lat="([\d.\-]+)"\s+lon="([\d.\-]+)"', re.MULTILINE)
    all_pts = []
    for f in leg_files:
        pts = rtept_pattern.findall(f.read_text(encoding="utf-8"))
        all_pts.extend(pts)
        info(f"  leg {f.name}: {len(pts)} 個 rtept")
    if not all_pts:
        die("各 leg 檔案皆無 rtept 點位")

    lats = [float(p[0]) for p in all_pts]
    lons = [float(p[1]) for p in all_pts]

    data = read_json(plan_dir(n) / "places.json")
    places = data["places"]

    out_lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gpx xmlns="http://www.topografix.com/GPX/1/1" version="1.1" creator="CyclingTW merged">',
        '  <metadata>',
        f'    <name>Day {n} {data.get("route_name","")}</name>',
        f'    <bounds minlat="{min(lats)}" minlon="{min(lons)}" maxlat="{max(lats)}" maxlon="{max(lons)}"/>',
        '  </metadata>',
    ]
    # 加入點位標記（地圖 App 會顯示停靠點）
    for i, p in enumerate(places, 1):
        sym = "Flag, Green" if i == 1 else "Flag, Red" if i == len(places) else "Waypoint"
        out_lines.append(
            f'  <wpt lat="{p["location"]["lat"]}" lon="{p["location"]["lng"]}">'
            f'<name>{p["name_zh"]}</name><sym>{sym}</sym></wpt>'
        )
    # 合併軌跡
    out_lines.append(f'  <trk><name>Day {n} 完整軌跡</name><trkseg>')
    for lat, lon in all_pts:
        out_lines.append(f'    <trkpt lat="{lat}" lon="{lon}"/>')
    out_lines.append('  </trkseg></trk>')
    out_lines.append('</gpx>')

    out_path = day_dir(n) / f"day{n}_route.gpx"
    out_path.write_text("\n".join(out_lines), encoding="utf-8")
    info(f"合併 {len(leg_files)} 段 / {len(all_pts)} 軌跡點 → {out_path.relative_to(ROOT)}")

# ─────────────────── 模板渲染 ───────────────────

def jenv() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
    )

def cmd_render_prompt(args):
    n = args.day
    vars_path = plan_dir(n) / "poster_vars.json"
    if not vars_path.exists():
        die(f"找不到 {vars_path.relative_to(ROOT)}")
    vars = read_json(vars_path)
    tpl = jenv().get_template("prompt.md.j2")
    out = day_dir(n) / f"day{n}_prompt.md"
    out.write_text(tpl.render(**vars), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")

def cmd_render_md(args):
    n = args.day
    cfg = read_json(plan_dir(n) / "config.json")
    places = read_json(plan_dir(n) / "places.json")
    segments = read_json(plan_dir(n) / "segments.json")
    ctx = {
        "day": n,
        "cfg": cfg,
        "places_data": places,
        "places": places["places"],
        **segments,
    }
    tpl = jenv().get_template("day.md.j2")
    out = day_dir(n) / f"day{n}.md"
    out.write_text(tpl.render(**ctx), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")

# ─────────────────── CLI ───────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        sp = sub.add_parser(name, help=help)
        sp.add_argument("day", type=int)
        sp.set_defaults(func=fn)
        return sp

    add("parse-index",   cmd_parse_index,   "解析 index.md 第 N 天")
    add("mirror-status", cmd_mirror_status, "顯示 dayN/map/（本地鏡像）現況")
    add("mirror-put",    cmd_mirror_put,    "[stdin] upsert 單筆 place 到本地鏡像")
    add("mirror-diff",   cmd_mirror_diff,   "[stdin] 比對本地鏡像 vs 線上最新")
    add("compute",       cmd_compute,       "從 mirror 同步最新值並重算 Bayesian C/m/score")
    add("review",        cmd_review,        "重評整個候選池，偵測是否有更佳替換建議")
    add("write-csv",     cmd_write_csv,     "產 dayN_mymap.csv")
    add("gpx-save",      cmd_gpx_save,      "[stdin] 儲存 openroute MCP 產生的 GPX")
    add("gpx-waypoints", cmd_gpx_waypoints, "備案：純航點 GPX")

    sp = add("gpx-split-plan", cmd_gpx_split_plan, "切割長路線為多段（避免 MCP 100KB 截斷）")
    sp.add_argument("--max-waypoints", type=int, default=4, help="每段中間 waypoints 上限（預設 4）")

    sp = add("gpx-append", cmd_gpx_append, "[stdin] 儲存單段 openroute MCP GPX")
    sp.add_argument("--leg", type=int, required=True, help="段次編號（從 1 開始）")

    add("gpx-merge",     cmd_gpx_merge,     "合併所有 leg 為最終 GPX")
    add("render-prompt", cmd_render_prompt, "產 dayN_prompt.md")
    add("render-md",     cmd_render_md,     "產 dayN.md")
    return p

def main():
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
CyclingTW Day Planner — 半自動腳本工具
=====================================
Claude 在對話中呼叫 MCP 工具（Google Maps / OpenRoute）取得資料並做選點判斷，
本腳本負責所有機械步驟（鏡像維護 / Bayesian / CSV / GPX / 模板渲染）。

設計原則：
  - 本地鏡像（write-through）：dayN/map/ 是 Google Maps 的本地鏡像 DB，不是
    省 API 用的快取；線上每次搜尋仍要重打 MCP，把 fresh 資料 upsert 回本地。
  - 先 diff 後 put：mirror-diff 顯示變動，mirror-put 一律 upsert 寫回
  - Bayesian 動態重算：C = 候選池平均，m = 中位數 (≥100)
  - 不變式驗證：CSV 終點 = index.md 目的地

子命令（共 14 個）：
  parse-index N            解析 index.md 第 N 天設定
  mirror-status N          列出 dayN/map/（本地鏡像）內容與候選池警告
  mirror-put N             [stdin] upsert 單筆 place 到本地鏡像
  mirror-diff N            [stdin] 比對本地鏡像 vs 線上最新
  compute N                從 mirror 同步最新值並重算 Bayesian C/m/score
  review N                 重評整個候選池，提示是否有更佳替換
  write-csv N              產 dayN_mymap.csv（依 _plan/places.json）
  gpx-save N               [stdin] 儲存單段 openroute GPX（短路線直出時用）
  gpx-waypoints N          備案：依 places.json 座標產純航點 GPX（離線 / 無 MCP 時）
  gpx-split-plan N         切割長路線為多段（避免 MCP 100KB 截斷）
  gpx-append N --leg i     [stdin] 儲存第 i 段 openroute GPX
  gpx-merge N              合併所有 leg 為最終 dayN_route.gpx
  render-prompt N          產 dayN_prompt.md；預設先從 _plan/places.json 重推
                           poster_vars.json 結構欄位（--no-sync 跳過）
  render-md N              產 dayN.md（依 _plan/places.json + segments.json）

每日工作目錄結構（自動建立）：
  dayN/
  ├── _plan/
  │   ├── config.json        ← parse-index 產出（起終點/距離/必經景點）
  │   ├── places.json        ← Claude 決定的最終點位順序與 Bayesian 結果
  │   ├── segments.json      ← Claude 寫的段落敘述/魚骨圖/注意事項
  │   └── poster_vars.json   ← Claude 決定的海報主視覺與 5 變數
  ├── map/                   ← Google Maps 本地鏡像 DB（write-through）
  └── dayN_*.{csv,gpx,md}    ← 最終產出

================================================================================
Claude 規劃時必須遵守的規則（plan.py 無法強制，但需在對話中執行）
================================================================================
（完整規範與工作流請見 scripts/README.md，以下只列硬性約束摘要）

[A] API 節流規定
  - 僅對 csv_type ∈ {景點, 起終點, 餐廳大休} 呼叫 mcp_google-maps_maps_place_details
    以取得 total_ratings。
  - 對「便利商店 / 加油站 / 公共設施 / 綜合休息站」嚴禁呼叫 place_details，
    這些類型的 rating / total_ratings 欄位直接留空。
  - 線上規劃時，所有候選點仍要重打 maps_search_places，再透過 mirror-diff /
    mirror-put 寫回本地（本地是鏡像，不是「有就跳過」的快取）。

[B] 地點搜尋關鍵字撰寫原則（用於 places.json 的 search_keyword 與 mymap CSV）
  - 便利商店：「品牌 + 門市名稱」                     例：7-ELEVEN 觀湖門市
  - 加油站  ：「台灣中油 + 站名」                     例：台灣中油大園站
  - 景點/漁港：「縣市 + 景點名」                       例：桃園永安漁港
  - 公共設施：完整地址或附近知名地標
  - 禁用模糊關鍵字：不要只寫「加油站」或「7-11」，必須具名

[C] 單車視角選點原則
  - 需求導向：每日需涵蓋補給（便利商店/飲水）、休息、景點觀光、午餐（餐廳大休）
  - 距離與順路：
      一般補給 / 公廁：距主線 ≤ 500m
      午餐大休       ：距主線 ≤ 1 km
      景點           ：距主線 ≤ 2 km
    超過上限但屬 index.md 指定的必經景點或四極點：可納入但備註欄需註明繞行距離與原因
  - 時間節奏：出發後 20-30km 安排第一次休息；中午時段安排有冷氣的午餐點
  - 貝葉斯輔助：景點/起終點/餐廳大休 取得 rating + total_ratings 後計算 bayesian_score；
    候選多時優先 bayesian_score 高者，再依補給節奏微調

[D] 起終點不可錯置（render-prompt 已部分檢查，但選點時就要把關）
  - 起點 = dayN_mymap.csv 順序第 1 筆 = 當日出發地
  - 終點 = dayN_mymap.csv 順序最後 1 筆 = 當日目的地
  - 不可把昨天或明天的點誤植為起終點，每天獨立確認

[E] 撤退方案
  - 每日 dayN.md 的「騎乘注意事項」段落，必須列出 ≥ 2-3 個可中途撤退搭火車的車站
  - 撤退方案須附具體車站名稱與距離（例：「水尾火車站，距台61約3km」）

[F] ★主視覺視覺辨識度
  - main_visual 候選需有明確視覺符號才適合放海報：
      燈塔、廟宇、老街、漁港、濕地、山景、海岸、車站建築、橋梁、特殊地貌
  - 若 visual_score 最高點視覺辨識度不足（例如純評分高的咖啡廳、無外觀的小景點），
    改選次高且具代表性的候選點
  - 在 places.json 對應點的 note 末尾加 ` ★主視覺` 標記，render-prompt 會抓這個

[G] 海報光線氛圍（poster_vars.json 的 lighting 欄位）
  - 預設：柔和清晨明亮光線、清新藍天白雲
  - 行程包含夕陽景點（如高美濕地、漁人碼頭夕照）：金色夕陽暖光、橘紅天空漸層、黃昏氛圍
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import re
import statistics
import sys
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
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

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

        # 距離範圍解析 "約 80–100 km" → [80, 100]；只取前兩個數字
        nums = [int(x) for x in re.findall(r"\d+", dist_txt)]
        if not nums:
            dist_range = [None, None]
        elif len(nums) == 1:
            dist_range = [nums[0], nums[0]]
        else:
            dist_range = nums[:2]

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

    # 候選池規模檢查（依 SOP：景點 ≥ 3-5、餐廳 ≥ 2-3），備案也計入總候選量
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
    """從 stdin 讀單筆 place JSON，upsert 到本地鏡像（同 place_id 覆寫成最新值）。
    保證同 place_id 只會出現在一個 bucket（places 或 candidates_not_selected）。"""
    n = args.day
    data = read_stdin_json()
    pid = data.get("place_id")
    if not pid:
        die("缺少 place_id 欄位")
    target = data.get("target", "places")
    VALID_TARGETS = ("places", "candidates_not_selected")
    if target not in VALID_TARGETS:
        die(f"target 必須是 {VALID_TARGETS} 之一，收到 '{target}'")
    # target 是 meta 欄位（路由到哪個 bucket），不該寫進個別 place 檔
    place_payload = {k: v for k, v in data.items() if k != "target"}
    f = map_dir(n) / f"{pid}.json"
    write_json(f, place_payload)
    # 同步 index.json：先從所有 bucket 移除此 pid，再加到指定 target
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

def _has_rating(p: dict) -> bool:
    """是否具備計算 Bayesian 所需的 rating 與 total_ratings。
    用 is not None 而非 truthy，避免把 0（新景點無評論）誤判為缺值。"""
    return p.get("rating") is not None and p.get("total_ratings") is not None

def compute_bayesian(places: list[dict]) -> tuple[float, int]:
    rated = [p for p in places if p.get("csv_type") in RATED_TYPES and _has_rating(p)]
    # 警告：屬於應評分類型但缺 rating/total_ratings 的點會被排除，
    # 進而拉偏 C/m。直接列出讓使用者補資料。
    missing = [p for p in places
               if p.get("csv_type") in RATED_TYPES and not _has_rating(p)]
    for p in missing:
        info(f"⚠️  [{p.get('csv_type')}] {p.get('name_zh','?')} 缺 rating/total_ratings，已從 Bayesian 候選池排除")
    if len(rated) < 2:
        die(f"Bayesian 計算需要 ≥ 2 個評分點，目前 {len(rated)}")
    C = sum(p["rating"] for p in rated) / len(rated)
    v_list = sorted(p["total_ratings"] for p in rated)
    m_raw = statistics.median(v_list)
    m = max(int(m_raw), 100)
    return round(C, 4), m

def _refresh_place_from_mirror(n: int, p: dict) -> dict:
    """以 place_id 從 mirror 拉最新 rating/total_ratings/location/name_zh。
    注意：csv_type 不同步——它是「當日對該點的角色分類」（人決定），
    不是 Google Maps 的事實，mirror 不該覆寫 places.json 內的人為決定。"""
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
        if p.get("csv_type") in RATED_TYPES and _has_rating(p):
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
        if item.get("csv_type") in RATED_TYPES and _has_rating(item):
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
    # 必填欄位驗證（提早 die 比 KeyError 友善）
    missing_kw = [p.get("name_zh", "?") for p in places if not p.get("search_keyword")]
    if missing_kw:
        die(f"places.json 中以下點位缺 search_keyword：{', '.join(missing_kw)}")
    # 不變式驗證：destination 可能是「鹿港 / 彰化」這種多選，逐一拆分比對
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
        else:
            die("stdin GPX 既無 </gpx> 也無任何完整 </rtept>，無法修補；請確認 openroute MCP 回應")
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

# ─── poster_vars 自動同步：places.json 是路線真相，render-prompt 一律重推 ───

def _find_main_visual_place(places: list[dict]) -> dict | None:
    """找 places 中標記 ★主視覺 的點；若無標記則以 visual_score 自動挑選。"""
    for p in places:
        if "★主視覺" in (p.get("note") or ""):
            return p
    cands = [p for p in places
             if p.get("csv_type") in ("景點", "起終點")
             and p.get("bayesian_score") is not None
             and p.get("total_ratings")]
    if not cands:
        return None
    return max(cands, key=lambda p: p["bayesian_score"] * math.log10(p["total_ratings"]))

_CITY_RE = re.compile(r"([一-鿿]{1,3}[縣市])([一-鿿]{1,3})[區鄉鎮]")

def _normalize_city(s: str) -> str:
    """將「臺」normalize 成「台」，避免 search_keyword 與 index.md 異體字混用。"""
    return s.replace("臺", "台") if s else s

def _location_desc(place: dict) -> str:
    """格式化為「縣市區「景點名」」；無法解析行政區時退回「縣市「景點名」」或「景點名」。
    僅在 search_keyword 出現「○○縣/市 ▲▲區/鄉/鎮」結構時取行政區，避免誤匹配地名片段。"""
    name = place.get("name_zh", "")
    kw = place.get("search_keyword", "") or ""
    m = _CITY_RE.search(kw)
    if m:
        return f"{_normalize_city(m.group(1))}{m.group(2)}「{name}」" if name else _normalize_city(m.group(1))
    m2 = re.search(r"([一-鿿]{1,3}[縣市])", kw)
    if m2:
        return f"{_normalize_city(m2.group(1))}「{name}」" if name else _normalize_city(m2.group(1))
    return f"「{name}」" if name else ""

_ORIENT_AXES = {
    "vertical_portrait_2_3":  ("ns",),   # 南北走向
    "horizontal_landscape_3_2": ("ew",),  # 東西走向
}

def _axis_words(orientation: str, first_loc: dict, last_loc: dict) -> dict:
    """依 orientation 與起終點座標決定方位用語。orientation 缺值時改以 lat/lng 較大差判斷。"""
    dlat = first_loc["lat"] - last_loc["lat"]
    dlng = first_loc["lng"] - last_loc["lng"]
    axis = _ORIENT_AXES.get(orientation, (None,))[0]
    if axis is None:
        axis = "ns" if abs(dlat) >= abs(dlng) else "ew"
    if axis == "ns":
        first_pos, last_pos = ("畫面上方", "畫面下方") if dlat > 0 else ("畫面下方", "畫面上方")
        first_side, last_side = ("北側", "南側") if dlat > 0 else ("南側", "北側")
        small_corner = "右上方" if dlat > 0 else "右下方"
    else:
        first_pos, last_pos = ("畫面右側", "畫面左側") if dlng > 0 else ("畫面左側", "畫面右側")
        first_side, last_side = ("東側", "西側") if dlng > 0 else ("西側", "東側")
        small_corner = "右上方"
    return {"first_pos": first_pos, "last_pos": last_pos,
            "first_side": first_side, "last_side": last_side,
            "small_corner": small_corner}

def _derive_poster_vars(n: int) -> dict:
    """從 places.json 同步 poster_vars.json 中由路線資料驅動的欄位。
    一律覆寫：composition、geographic_notes、main_visual.place_id、small_avatar.place_id；
              main_visual / small_avatar 的 location_desc 在 place_id 變動或缺值時重新生成。
    保留：origin_label、destination_label、distance_range、subtitle、orientation、
          lighting、allowed_elements、enhancement，以及 place_id 未變動時的手寫場景文字。
    若 ★主視覺 / 起點 place_id 變動，會清空對應的 scene_elements / action / expression / scenario 並警告。"""
    places_data = read_json(plan_dir(n) / "places.json")
    places = places_data["places"]
    if len(places) < 2:
        die("places.json 至少需要 2 個點位（起點 + 終點）")
    first, last = places[0], places[-1]

    vars_path = plan_dir(n) / "poster_vars.json"
    existing = read_json(vars_path) if vars_path.exists() else {}
    out = dict(existing)
    out.setdefault("day", n)

    # 標籤類欄位：缺值才補預設，已有就尊重使用者編輯
    cfg_path = plan_dir(n) / "config.json"
    cfg = read_json(cfg_path) if cfg_path.exists() else {}
    out.setdefault("origin_label", cfg.get("origin") or first.get("name_zh", ""))
    out.setdefault("destination_label", cfg.get("destination") or last.get("name_zh", ""))
    if "distance_range" not in out:
        rng = cfg.get("distance_km_range") or [None, None]
        lo, hi = rng[0], rng[1]
        if lo is not None and hi is not None and lo != hi:
            out["distance_range"] = f"約 {lo}–{hi} 公里"
        elif lo is not None:
            out["distance_range"] = f"約 {lo} 公里"
        else:
            # 確保下游 StrictUndefined 不掛
            out["distance_range"] = "距離未定"
    out.setdefault("subtitle", places_data.get("route_name", ""))
    out.setdefault("orientation", "vertical_portrait_2_3")
    out.setdefault("lighting", "柔和清晨明亮光線、清新藍天白雲")
    out.setdefault("allowed_elements", "")
    out.setdefault("enhancement", "")

    axis = _axis_words(out["orientation"], first["location"], last["location"])

    # main_visual：偵測 ★主視覺，place_id 變動才重設手寫文字
    main_visual = _find_main_visual_place(places)
    mv_old = dict(out.get("main_visual") or {})
    if main_visual:
        new_pid = main_visual["place_id"]
        if mv_old.get("place_id") and mv_old["place_id"] != new_pid:
            info(f"⚠️  ★主視覺已從 {mv_old.get('place_id')} 換為 {new_pid}"
                 f"（{main_visual['name_zh']}），已清空 main_visual.scene_elements / action / expression")
            mv = {"place_id": new_pid, "location_desc": _location_desc(main_visual),
                  "scene_elements": "", "action": "", "expression": ""}
        else:
            mv = mv_old
            mv["place_id"] = new_pid
            if not mv.get("location_desc"):
                mv["location_desc"] = _location_desc(main_visual)
            mv.setdefault("scene_elements", "")
            mv.setdefault("action", "")
            mv.setdefault("expression", "")
        out["main_visual"] = mv
    else:
        # 沒有 ★主視覺 也沒有可評分 fallback：保留 existing 或塞空結構，避免下游 StrictUndefined
        if mv_old:
            info("⚠️  places.json 找不到 ★主視覺 標記且無可評分候選，main_visual 維持原值（可能已過時）")
            mv_old.setdefault("place_id", "")
            mv_old.setdefault("location_desc", "")
            mv_old.setdefault("scene_elements", "")
            mv_old.setdefault("action", "")
            mv_old.setdefault("expression", "")
            out["main_visual"] = mv_old
        else:
            info("⚠️  places.json 找不到 ★主視覺 標記且無可評分候選，main_visual 留白；請先跑 compute 或手動標記 ★主視覺")
            out["main_visual"] = {"place_id": "", "location_desc": "",
                                  "scene_elements": "", "action": "", "expression": ""}

    # small_avatar：第一筆 place_id 變動才重設手寫文字
    sa_old = dict(out.get("small_avatar") or {})
    first_pid = first.get("place_id")
    if sa_old.get("place_id") and sa_old["place_id"] != first_pid:
        info(f"⚠️  起點已從 {sa_old.get('place_id')} 換為 {first_pid}"
             f"（{first['name_zh']}），已清空 small_avatar.scenario / action / expression")
        sa = {"place_id": first_pid, "location_desc": _location_desc(first),
              "scenario": "", "action": "", "expression": ""}
    else:
        sa = sa_old
        sa["place_id"] = first_pid
        if not sa.get("location_desc"):
            sa["location_desc"] = _location_desc(first)
        sa.setdefault("scenario", "")
        sa.setdefault("action", "")
        sa.setdefault("expression", "")
    out["small_avatar"] = sa

    # composition / geographic_notes：每次都依 places.json 與 orientation 重生
    main_pid = (out.get("main_visual") or {}).get("place_id")
    sub_landmarks = [
        p["name_zh"] for p in places
        if p.get("csv_type") == "景點"
        and p.get("place_id") not in {first.get("place_id"), last.get("place_id"), main_pid}
    ]
    parts = [
        "主角在畫面中央偏上",
        f"{first['name_zh']}在{axis['small_corner']}小分身",
        f"{last['name_zh']}在{axis['last_pos']}遠景",
    ]
    if sub_landmarks:
        parts.append(f"沿途點綴{'、'.join(sub_landmarks)}")
    out["composition"] = "、".join(parts)
    out["geographic_notes"] = (
        f"{first['name_zh']}在{axis['first_pos']}（{axis['first_side']}）、"
        f"{last['name_zh']}在{axis['last_pos']}（{axis['last_side']}）"
    )

    write_json(vars_path, out)
    return out

def cmd_render_prompt(args):
    n = args.day
    vars_path = plan_dir(n) / "poster_vars.json"
    if args.no_sync:
        if not vars_path.exists():
            die(f"找不到 {vars_path.relative_to(ROOT)}")
        poster_vars = read_json(vars_path)
    else:
        poster_vars = _derive_poster_vars(n)
        info(f"已從 places.json 同步 {vars_path.relative_to(ROOT)}")
        empty_fields = []
        mv = poster_vars.get("main_visual") or {}
        for k in ("scene_elements", "action", "expression"):
            if not mv.get(k):
                empty_fields.append(f"main_visual.{k}")
        sa = poster_vars.get("small_avatar") or {}
        for k in ("scenario", "action", "expression"):
            if not sa.get(k):
                empty_fields.append(f"small_avatar.{k}")
        if empty_fields:
            info(f"⚠️  以下手寫欄位為空，渲染後 prompt 會留白，請手動補入：{', '.join(empty_fields)}")
    tpl = jenv().get_template("prompt.md.j2")
    out = day_dir(n) / f"day{n}_prompt.md"
    out.write_text(tpl.render(**poster_vars), encoding="utf-8")
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

    def _positive_int(s: str) -> int:
        v = int(s)
        if v < 1:
            raise argparse.ArgumentTypeError(f"必須 ≥ 1，收到 {v}")
        return v

    sp = add("gpx-split-plan", cmd_gpx_split_plan, "切割長路線為多段（避免 MCP 100KB 截斷）")
    sp.add_argument("--max-waypoints", type=_positive_int, default=4, help="每段中間 waypoints 上限 ≥1（預設 4）")

    sp = add("gpx-append", cmd_gpx_append, "[stdin] 儲存單段 openroute MCP GPX")
    sp.add_argument("--leg", type=int, required=True, help="段次編號（從 1 開始）")

    add("gpx-merge",     cmd_gpx_merge,     "合併所有 leg 為最終 GPX")
    sp = add("render-prompt", cmd_render_prompt, "產 dayN_prompt.md（預設先從 places.json 同步 poster_vars.json）")
    sp.add_argument("--no-sync", action="store_true",
                    help="跳過自動同步，僅以現有 poster_vars.json 渲染")
    add("render-md",     cmd_render_md,     "產 dayN.md")
    return p

def main():
    args = build_parser().parse_args()
    args.func(args)

if __name__ == "__main__":
    main()

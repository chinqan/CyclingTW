"""晚餐選點：dinner-put / dinner-diff / dinner-status / dinner-pool / dinner-review。

本地鏡像 DB：dayN/dinner_map/
  - index.json         索引（候選名單 + 入選標記）
  - <place_id>.json    每間餐廳完整資料（write-through 更新）

工作流（與景點 mirror 完全對稱）：
  1. Claude 用 MCP 在終點方圓 3km 搜尋 15 間餐廳/小吃
  2. Claude 對每間呼叫 place_details 取得 rating + total_ratings
  3. dinner-diff N  — 比對本地 vs 線上最新
  4. dinner-put N   — 逐筆 upsert 寫回本地鏡像（不管有無差異都寫）
  5. dinner-pool N  — 從鏡像完整候選池算 Bayesian、選 top 5，存 _plan/dinner.json
  6. dinner-review N — 顯示完整排名 + ★入選標記
"""
from __future__ import annotations

import json

from .helpers import ROOT, plan_dir, dinner_map_dir, read_json, write_json, read_stdin_json, die, info, haversine_km

DEDUPE_RADIUS_KM = 0.05  # 50m 內同名視為同一家店


# ─────────────────────────────────────────────────────────────────
# Mirror 管理
# ─────────────────────────────────────────────────────────────────

def _load_dinner_index(n: int) -> dict:
    idx = dinner_map_dir(n) / "index.json"
    if idx.exists():
        return read_json(idx)
    return {"day": n, "candidates": []}


def _save_dinner_index(n: int, data: dict) -> None:
    write_json(dinner_map_dir(n) / "index.json", data)


def cmd_dinner_status(args):
    """顯示 dayN/dinner_map/（晚餐本地鏡像）現況。"""
    n = args.day
    idx = _load_dinner_index(n)
    files = sorted(dinner_map_dir(n).glob("*.json"))
    candidates = idx.get("candidates", [])

    print(f"== Day {n} 晚餐本地鏡像現況 ==")
    print(f"dinner_map/ 檔案數：{len(files)}")
    print(f"index.json 候選筆數：{len(candidates)}\n")

    if candidates:
        print("【候選】")
        for c in candidates:
            mark = "★" if c.get("selected") else " "
            r = c.get("rating", "?")
            v = c.get("total_ratings", "?")
            print(f"  {mark} {c.get('name_zh','?'):<24} R={r} V={v}")
    else:
        print("（尚無候選資料，請先搜尋並 dinner-put）")

    print()
    if len(candidates) < 10:
        print(f"⚠️  晚餐候選 {len(candidates)} 筆，建議搜尋至 ≥ 15 筆再跑 dinner-pool")


def cmd_dinner_put(args):
    """從 stdin 讀單筆或多筆餐廳 JSON，upsert 到本地鏡像。

    stdin schema（單筆或陣列）：
    {
      "place_id": "ChIJ...",          // 必填
      "name_zh": "夏川食堂",          // 必填
      "rating": 4.8,                  // 必填
      "total_ratings": 751,           // 必填
      "location": {"lat": ..., "lng": ...},
      "address": "苗栗縣竹南鎮...",    // 可選
      "note": "日式料理",              // 可選
      "source": "search_2026-05-20"   // 可選，來源標記
    }
    """
    n = args.day
    data = read_stdin_json()
    if isinstance(data, dict):
        data = [data]

    idx = _load_dinner_index(n)
    candidates = idx.get("candidates", [])
    pid_map = {c["place_id"]: i for i, c in enumerate(candidates)}

    upserted = 0
    for item in data:
        pid = item.get("place_id")
        if not pid:
            info(f"跳過缺 place_id 的項目：{item.get('name_zh', '?')}")
            continue

        # 寫 place_id.json（完整資料）
        f = dinner_map_dir(n) / f"{pid}.json"
        write_json(f, item)

        # 更新 index.json 的候選摘要
        summary = {k: item[k] for k in (
            "place_id", "name_zh", "rating", "total_ratings", "location", "address", "note", "source"
        ) if k in item}

        if pid in pid_map:
            # upsert：保留 selected 標記
            old = candidates[pid_map[pid]]
            summary["selected"] = old.get("selected", False)
            candidates[pid_map[pid]] = summary
        else:
            summary["selected"] = False
            candidates.append(summary)
            pid_map[pid] = len(candidates) - 1

        upserted += 1

    idx["candidates"] = candidates
    _save_dinner_index(n, idx)
    info(f"upsert {upserted} 筆到 dinner_map/（共 {len(candidates)} 筆候選）")


def cmd_dinner_diff(args):
    """從 stdin 讀 fresh 資料，與本地鏡像比對。"""
    n = args.day
    fresh = read_stdin_json()
    if isinstance(fresh, dict):
        fresh = [fresh]

    rows = []
    for f in fresh:
        pid = f.get("place_id")
        if not pid:
            continue
        cf = dinner_map_dir(n) / f"{pid}.json"
        if not cf.exists():
            rows.append((pid, f.get("name_zh", "?"), "—", "—",
                         f.get("rating"), f.get("total_ratings"), "⭐ 新地點"))
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

    print(f"{'place_id':<36}{'名稱':<20}{'本地R':>6}{'本地V':>8}{'線上R':>6}{'線上V':>8}  差異")
    print("-" * 100)
    for r in rows:
        print(f"{r[0]:<36}{(r[1] or '')[:18]:<20}{str(r[2]):>6}{str(r[3]):>8}"
              f"{str(r[4]):>6}{str(r[5]):>8}  {r[6]}")


# ─────────────────────────────────────────────────────────────────
# Bayesian 選 Top 5
# ─────────────────────────────────────────────────────────────────

def _bayesian_score(rating: float, n: int, C: float, m: float) -> float:
    """IMDB 風格貝葉斯平均（與 dinner_selection_guide.md 一致）。

    公式：(C * m + rating * n) / (C + n)
      C = 全體候選的平均留言數（先驗樣本數，越大對低留言懲罰越重）
      m = 全體候選的加權平均評分（先驗期望值）
      n = 該店的留言數
      rating = 該店的評分
    """
    return round((C * m + rating * n) / (C + n), 4)


def _confidence_label(total_ratings: int, C: float) -> str:
    """信心標記：依留言數與 C（平均留言數）的比值判斷。"""
    ratio = total_ratings / C if C > 0 else 0
    if ratio >= 1.0:
        return "✅ 高"
    elif ratio >= 0.5:
        return "⚠️ 中"
    else:
        return "❌ 低"


def _collect_dinner_pool(n: int) -> list[dict]:
    """從 dinner_map 收集所有有效候選（有 rating + total_ratings 的）。"""
    idx = _load_dinner_index(n)
    candidates = idx.get("candidates", [])
    pool = []
    seen: set[str] = set()
    for c in candidates:
        pid = c.get("place_id")
        if not pid or pid in seen:
            continue
        seen.add(pid)
        # 從 pid.json 讀最新完整資料
        pf = dinner_map_dir(n) / f"{pid}.json"
        if pf.exists():
            try:
                full = read_json(pf)
            except json.JSONDecodeError:
                full = c
        else:
            full = c
        # 合併（pid.json 優先）
        merged = {**c, **full}
        if merged.get("rating") is not None and merged.get("total_ratings") is not None:
            pool.append(merged)

    # 同名 + < 50m 視為同店，保留 total_ratings 較大者
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


def cmd_dinner_pool(args):
    """從 dinner_map 鏡像候選池算 Bayesian 排序，選 top 5。

    也可 stdin 帶入新資料（會先自動 upsert 到鏡像再算）。
    若 stdin 為空，直接從現有鏡像資料計算。
    """
    n = args.day
    import sys
    import select

    # 如果 stdin 有資料，先 upsert 到鏡像
    if not sys.stdin.isatty():
        # 嘗試讀 stdin
        raw = sys.stdin.read()
        if raw.strip():
            new_data = json.loads(raw)
            if isinstance(new_data, dict):
                new_data = [new_data]

            # upsert 到鏡像
            idx = _load_dinner_index(n)
            candidates = idx.get("candidates", [])
            pid_map = {c["place_id"]: i for i, c in enumerate(candidates)}

            added = 0
            for item in new_data:
                pid = item.get("place_id")
                if not pid:
                    continue
                f = dinner_map_dir(n) / f"{pid}.json"
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
            _save_dinner_index(n, idx)
            if added:
                info(f"從 stdin 新增/更新 {added} 筆到 dinner_map/")

    # 從鏡像收集完整候選池
    pool = _collect_dinner_pool(n)
    if len(pool) < 3:
        die(f"dinner_map 中有效候選只有 {len(pool)} 筆，至少需要 3 筆。"
            f"請先用 dinner-put 寫入資料。")

    # Bayesian 參數（IMDB 風格）
    total_ratings_list = [c["total_ratings"] for c in pool]
    C = sum(total_ratings_list) / len(total_ratings_list)  # 平均留言數
    weighted_sum = sum(c["rating"] * c["total_ratings"] for c in pool)
    total_n = sum(c["total_ratings"] for c in pool)
    m = round(weighted_sum / total_n, 4) if total_n > 0 else 4.0

    # 計算每筆分數
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

    # 排序
    scored.sort(key=lambda x: -x["bayesian_score"])

    # 標記 top 5
    for i, item in enumerate(scored):
        item["rank"] = i + 1
        item["selected"] = i < 5

    # 同步 selected 標記回 index.json
    idx = _load_dinner_index(n)
    selected_pids = {s["place_id"] for s in scored[:5]}
    for c in idx.get("candidates", []):
        c["selected"] = c.get("place_id") in selected_pids
    _save_dinner_index(n, idx)

    # 紀錄 source endpoint（給 render-md 預檢比對；places.json 缺值時略過）
    source_endpoint_pid = None
    places_path = plan_dir(n) / "places.json"
    if places_path.exists():
        try:
            pl = read_json(places_path).get("places") or []
            if pl:
                source_endpoint_pid = pl[-1].get("place_id")
        except Exception:
            pass

    # 存 _plan/dinner.json
    out_data = {
        "day": n,
        "search_radius_km": 3,
        "pool_size": len(scored),
        "bayesian_C": round(C, 1),
        "bayesian_m": m,
        "note": "C=平均留言數(先驗樣本數), m=加權平均評分(先驗期望值)",
        "source_endpoint_place_id": source_endpoint_pid,
        "top5_place_ids": [s["place_id"] for s in scored[:5]],
        "restaurants": scored,
    }

    out = plan_dir(n) / "dinner.json"
    write_json(out, out_data)
    info(f"已寫入 {out.relative_to(ROOT)}（{len(scored)} 筆，C={round(C,1)}, m={m}）")

    # 印出排名
    quiet = getattr(args, "quiet", False)
    if not quiet:
        print(f"\n{'='*60}")
        print(f"  Day {n} 晚餐候選排名（{len(scored)} 筆，C={round(C,1)}, m={m}）")
        print(f"  候選池來源：dinner_map/（本地鏡像）")
        print(f"{'='*60}\n")
        print(f"  {'排名':<4} {'貝葉斯分':<8} {'評分':<5} {'留言數':<7} {'信心':<6} {'店名'}")
        print(f"  {'-'*4} {'-'*8} {'-'*5} {'-'*7} {'-'*6} {'-'*20}")
        for item in scored:
            mark = "🏆" if item["selected"] else "  "
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


def cmd_dinner_review(args):
    """顯示 dinner.json 的完整排名 + 與鏡像候選池的差異。"""
    n = args.day
    f = plan_dir(n) / "dinner.json"
    if not f.exists():
        die(f"找不到 {f.relative_to(ROOT)}，請先執行 dinner-pool")

    data = read_json(f)
    scored = data["restaurants"]
    C = data["bayesian_C"]
    m = data["bayesian_m"]

    print(f"\n{'='*60}")
    print(f"  Day {n} 晚餐候選排名（{len(scored)} 筆）")
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

    # 提示鏡像是否有更多資料（可能後來 put 了新的還沒重算）
    mirror_pool = _collect_dinner_pool(n)
    if len(mirror_pool) > len(scored):
        print(f"  💡 dinner_map/ 目前有 {len(mirror_pool)} 筆候選（dinner.json 只有 {len(scored)} 筆），")
        print(f"     建議重跑 dinner-pool {n} 以納入新資料。\n")


# ─────────────────────────────────────────────────────────────────
# Render dayN_dinner.md
# ─────────────────────────────────────────────────────────────────

def _stars(rating: float) -> str:
    full = int(rating)
    return "★" * full + ("½" if rating - full >= 0.5 else "")


def _confidence_emoji(conf: str) -> str:
    if "高" in conf:
        return "✅"
    elif "中" in conf:
        return "⚠️"
    return "❌"


def cmd_dinner_render(args):
    """從 _plan/dinner.json 產出 dayN_dinner.md。"""
    from .helpers import day_dir
    import datetime

    n = args.day
    f = plan_dir(n) / "dinner.json"
    if not f.exists():
        die(f"找不到 {f.relative_to(ROOT)}，請先執行 dinner-pool")

    data = read_json(f)
    scored = data["restaurants"]
    C = data["bayesian_C"]
    m = data["bayesian_m"]
    pool_size = data["pool_size"]

    # 讀 config 取終點名稱
    config_f = plan_dir(n) / "config.json"
    destination = f"Day {n} 終點"
    if config_f.exists():
        cfg = read_json(config_f)
        destination = cfg.get("destination", destination)

    top5 = [r for r in scored if r.get("selected")]
    today = datetime.date.today().isoformat()

    lines = []
    lines.append(f"# Day {n} 晚餐選擇 🍽️\n")
    lines.append(f"**終點：{destination}**（周邊 3 公里 · {pool_size} 筆候選 · 貝葉斯排序）\n")
    lines.append(f"> 公式：`貝葉斯分 = (C × m + rating × n) / (C + n)`")
    lines.append(f"> C = {C}（平均留言數）· m = {m}（加權平均評分）\n")
    lines.append("---\n")
    lines.append("## ★ Top 5 入選\n")

    for item in top5:
        pid = item["place_id"]
        url = f"https://www.google.com/maps/place/?q=place_id:{pid}"
        conf = item.get("confidence", "?")
        conf_emoji = _confidence_emoji(conf)
        addr = item.get("address", "")
        note = item.get("note", "")

        lines.append(f"### 🏆 {item['rank']}. [{item['name_zh']}]({url})\n")
        lines.append("| 貝葉斯分 | 評分 | 留言數 | 信心 |")
        lines.append("|:---:|:---:|:---:|:---:|")
        lines.append(f"| **{item['bayesian_score']}** | {item['rating']}★ | {item['total_ratings']} | {conf} |\n")
        if addr:
            lines.append(f"📍 {addr}")
        if note:
            lines.append(f"✨ {note}")
        lines.append("")
        lines.append("---\n")

    # 完整排名表
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

    # footer
    lines.append("---\n")
    lines.append(f"*資料來源：Google Maps MCP · 搜尋日期：{today} · 候選池 {pool_size} 筆*")
    lines.append("*排序方法：IMDB 風格貝葉斯平均（留言數越多、評分越可信）*\n")

    out = day_dir(n) / f"day{n}_dinner.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")
    print(f"產出：{out.relative_to(ROOT)}")

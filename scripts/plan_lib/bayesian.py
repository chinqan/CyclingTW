"""Bayesian 評分：score-pool / compute / review。"""
from __future__ import annotations

import argparse
import json
import statistics
import sys

from .helpers import ROOT, plan_dir, map_dir, read_json, write_json, die, info, haversine_km
from .mirror import load_mirror_index

RATED_TYPES = {"景點", "起終點", "餐廳大休"}
DEDUPE_RADIUS_KM = 0.05  # 50m 內同名視為同一家店
TYPE_MIN_POOL = {"景點": 5, "餐廳大休": 3}  # 候選池下限警告閾值


def _dedupe_same_store(items: list[dict]) -> list[dict]:
    """同 name_zh + 經緯度 < 50m 視為同店，保留 total_ratings 最大者。"""
    kept: list[dict] = []
    dropped: list[tuple[str, str]] = []  # (kept_name, dropped_pid)
    for item in items:
        name = item.get("name_zh", "")
        loc = item.get("location") or {}
        lat, lng = loc.get("lat"), loc.get("lng")
        if lat is None or lng is None:
            kept.append(item)
            continue
        matched = None
        for k in kept:
            if k.get("name_zh") != name:
                continue
            kloc = k.get("location") or {}
            klat, klng = kloc.get("lat"), kloc.get("lng")
            if klat is None or klng is None:
                continue
            if haversine_km(lat, lng, klat, klng) < DEDUPE_RADIUS_KM:
                matched = k
                break
        if matched is None:
            kept.append(item)
        else:
            if (item.get("total_ratings") or 0) > (matched.get("total_ratings") or 0):
                kept[kept.index(matched)] = item
                dropped.append((name, matched.get("place_id", "?")))
            else:
                dropped.append((name, item.get("place_id", "?")))
    if dropped:
        for name, pid in dropped:
            info(f"  dedup：{name} 同店重複，捨棄 {pid}")
    return kept


def _has_rating(p: dict) -> bool:
    return p.get("rating") is not None and p.get("total_ratings") is not None


def _collect_rated_pool(n: int) -> list[dict]:
    """從 mirror 收集所有可評分候選，依 pid.json 為 SoT 補齊欄位。"""
    mirror = load_mirror_index(n)
    pool = mirror.get("places", []) + mirror.get("candidates_not_selected", [])
    seen_pids: set[str] = set()
    rated: list[dict] = []
    for c in pool:
        pid = c.get("place_id")
        if not pid or pid in seen_pids:
            continue
        seen_pids.add(pid)
        mf = map_dir(n) / f"{pid}.json"
        full: dict = {}
        if mf.exists():
            try:
                full = read_json(mf)
            except json.JSONDecodeError as e:
                info(f"⚠️  跳過格式損壞的 {mf.name}：{e}")
                continue
        item = {**c, **full}
        if item.get("csv_type") in RATED_TYPES and _has_rating(item):
            rated.append(item)
    return _dedupe_same_store(rated)


def cmd_score_pool(args):
    """對整個 mirror 候選池算 Bayesian，產出 pool_scores.json。"""
    n = args.day
    rated = _collect_rated_pool(n)
    if len(rated) < 2:
        die(f"鏡像中可評分候選少於 2 筆（目前 {len(rated)}），無法計算 Bayesian")

    # 各類別樣本充足度檢查
    counts: dict[str, int] = {}
    for p in rated:
        counts[p["csv_type"]] = counts.get(p["csv_type"], 0) + 1
    for t, minimum in TYPE_MIN_POOL.items():
        actual = counts.get(t, 0)
        if actual < minimum:
            info(f"⚠️  [{t}] 候選只有 {actual} 筆（建議 ≥ {minimum}），Bayesian 結果代表性偏弱")
    C = round(sum(p["rating"] for p in rated) / len(rated), 4)
    m = max(int(statistics.median(sorted(p["total_ratings"] for p in rated))), 100)

    scores: dict[str, dict] = {}
    for p in rated:
        v, R = p["total_ratings"], p["rating"]
        scores[p["place_id"]] = {
            "name_zh": p.get("name_zh", ""),
            "csv_type": p.get("csv_type"),
            "rating": R,
            "total_ratings": v,
            "bayesian_score": round((v / (v + m)) * R + (m / (v + m)) * C, 2),
        }

    out = plan_dir(n) / "pool_scores.json"
    write_json(out, {"day": n, "bayesian_C": C, "bayesian_m": m,
                     "pool_size": len(rated), "scores": scores})
    info(f"已寫入 {out.relative_to(ROOT)}（{len(rated)} 筆，C={C}, m={m}）")

    if getattr(args, "quiet", False):
        return
    print(f"=== Day {n} 候選池全評（{len(rated)} 筆，C={C}, m={m}）===\n")
    by_type: dict[str, list[dict]] = {}
    for pid, s in scores.items():
        by_type.setdefault(s["csv_type"], []).append({**s, "place_id": pid})
    for t in ["起終點", "景點", "餐廳大休"]:
        items = sorted(by_type.get(t, []), key=lambda x: -x["bayesian_score"])
        if not items:
            continue
        print(f"[{t}]")
        for p in items:
            print(f"    {p['name_zh']:<28} R={p['rating']} V={p['total_ratings']:>6} → {p['bayesian_score']}")
        print()


def _ensure_pool_scores(n: int, quiet: bool = True) -> dict:
    pool_path = plan_dir(n) / "pool_scores.json"
    if not pool_path.exists():
        info(f"找不到 {pool_path.relative_to(ROOT)}，自動執行 score-pool")
        cmd_score_pool(argparse.Namespace(day=n, quiet=quiet))
    return read_json(pool_path)


def _refresh_place_from_mirror(n: int, p: dict) -> dict:
    pid = p.get("place_id")
    if not pid:
        return p
    mf = map_dir(n) / f"{pid}.json"
    if not mf.exists():
        return p
    m = read_json(mf)
    for field in ("rating", "total_ratings", "location", "name_zh"):
        if m.get(field) is not None:
            p[field] = m[field]
    return p


def cmd_compute(args):
    """套用 pool_scores 到 places.json。"""
    n = args.day
    f = plan_dir(n) / "places.json"
    if not f.exists():
        die(f"找不到 {f.relative_to(ROOT)}，請先用 Claude 寫入點位選擇")
    data = read_json(f)

    refreshed = 0
    for p in data["places"]:
        before = (p.get("rating"), p.get("total_ratings"))
        _refresh_place_from_mirror(n, p)
        after = (p.get("rating"), p.get("total_ratings"))
        if before != after:
            refreshed += 1
    if refreshed:
        info(f"從 mirror 同步了 {refreshed} 個點位的最新數值")

    pool_data = _ensure_pool_scores(n)
    C, m = pool_data["bayesian_C"], pool_data["bayesian_m"]
    pool_scores: dict[str, dict] = pool_data["scores"]

    data["bayesian_C"] = C
    data["bayesian_m"] = m
    fallback_used: list[str] = []
    for p in data["places"]:
        pid = p.get("place_id")
        if p.get("csv_type") not in RATED_TYPES:
            p["bayesian_score"] = None
            continue
        if pid and pid in pool_scores:
            p["bayesian_score"] = pool_scores[pid]["bayesian_score"]
        elif _has_rating(p):
            v, R = p["total_ratings"], p["rating"]
            p["bayesian_score"] = round((v / (v + m)) * R + (m / (v + m)) * C, 2)
            fallback_used.append(p.get("name_zh", "?"))
        else:
            p["bayesian_score"] = None

    if fallback_used:
        info(f"⚠️  以下入選點不在 mirror 候選池，用 places.json 自有資料補算：{', '.join(fallback_used)}")

    write_json(f, data)
    print(f"C = {C}, m = {m}（來自 {pool_data['pool_size']} 筆候選池）")
    if not getattr(args, "quiet", False):
        print()
        for p in data["places"]:
            score = p.get("bayesian_score")
            print(f"  [{p.get('csv_type','-'):<6}] {p['name_zh']:<22} "
                  f"R={p.get('rating')} V={p.get('total_ratings')} → {score}")

    # ── Phase 0-3 完成提醒：強制重做 Phase 3.5 / Phase 4 的依賴項 ──
    from .helpers import day_dir
    dinner_map = day_dir(n) / "dinner_map"
    dinner_json = plan_dir(n) / "dinner.json"
    segments_json = plan_dir(n) / "segments.json"

    todos: list[str] = []
    if any(dinner_map.glob("ChIJ*.json")) if dinner_map.exists() else False:
        if not dinner_json.exists() or dinner_json.stat().st_mtime < f.stat().st_mtime:
            todos.append(f"dinner-pool {n}    # places.json 已更新，重算晚餐 top 5 (Phase 3.5)")
    else:
        todos.append(f"dinner-search {n} → dinner-pool {n} → dinner-render {n}  # Phase 3.5")

    ba_ok = False
    if segments_json.exists():
        try:
            seg = read_json(segments_json)
            ba_ok = bool(seg.get("better_attractions"))
            if ba_ok and segments_json.stat().st_mtime < f.stat().st_mtime:
                todos.append(f"# 重檢 segments.json.better_attractions（places.json 已變更，建議重跑 review {n} 後更新）")
        except Exception:
            pass
    if not ba_ok:
        todos.append(f"review {n}          # 看排名後把備案表格寫進 segments.json.better_attractions (Phase 4)")

    if todos:
        print("\n" + "─" * 70, file=sys.stderr)
        print(f"[next] Phase 0-3 已完成，繼續 render-md {n} 前還需要：", file=sys.stderr)
        for t in todos:
            print(f"  · {t}", file=sys.stderr)
        print("─" * 70, file=sys.stderr)


def cmd_review(args):
    """讀 pool_scores 顯示排名 + 替換建議（排除 must_visit_landmarks）。"""
    n = args.day
    sel_file = plan_dir(n) / "places.json"
    if not sel_file.exists():
        die(f"找不到 {sel_file.relative_to(ROOT)}")
    sel_data = read_json(sel_file)
    selected_pids = {p["place_id"] for p in sel_data["places"]}

    # 必經景點：從 config.json 讀，對 places.json 用 name_zh 子字串配對
    landmarks: list[str] = []
    config_file = plan_dir(n) / "config.json"
    if config_file.exists():
        landmarks = read_json(config_file).get("must_visit_landmarks", []) or []
    locked_pids: set[str] = set()
    for p in sel_data["places"]:
        name = p.get("name_zh", "")
        if any(lm and lm in name for lm in landmarks):
            locked_pids.add(p["place_id"])

    pool_data = _ensure_pool_scores(n)
    C, m = pool_data["bayesian_C"], pool_data["bayesian_m"]
    scores: dict[str, dict] = pool_data["scores"]

    by_type: dict[str, list[dict]] = {}
    for pid, s in scores.items():
        by_type.setdefault(s["csv_type"], []).append({**s, "place_id": pid})

    print(f"=== Day {n} 候選池全評（{pool_data['pool_size']} 筆，C={C}, m={m}）===")
    if locked_pids:
        print(f"🔒 必經景點鎖定（不參與替換建議）：{', '.join(landmarks)}")
    if not getattr(args, "quiet", False):
        print()
        for t in ["起終點", "景點", "餐廳大休"]:
            items = sorted(by_type.get(t, []), key=lambda x: -x["bayesian_score"])
            if not items:
                continue
            print(f"[{t}]")
            for p in items:
                if p["place_id"] in locked_pids:
                    mark = "🔒"
                elif p["place_id"] in selected_pids:
                    mark = "★"
                else:
                    mark = " "
                print(f"  {mark} {p['name_zh']:<28} R={p['rating']} V={p['total_ratings']:>6} → {p['bayesian_score']}")
            print()

    swaps = []
    for t, items in by_type.items():
        if t == "起終點":
            continue
        items.sort(key=lambda x: -x["bayesian_score"])
        # 入選但非鎖定才可被替換
        inn = [c for c in items if c["place_id"] in selected_pids and c["place_id"] not in locked_pids]
        out = [c for c in items if c["place_id"] not in selected_pids]
        if not inn or not out:
            continue
        worst_in = min(inn, key=lambda x: x["bayesian_score"])
        best_out = max(out, key=lambda x: x["bayesian_score"])
        if best_out["bayesian_score"] > worst_in["bayesian_score"]:
            swaps.append((t, worst_in, best_out, best_out["bayesian_score"] - worst_in["bayesian_score"]))

    if swaps:
        print("⚠️  偵測到可能的替換：\n")
        for t, drop, gain, delta in swaps:
            print(f"  [{t}] 考慮把：")
            print(f"      [入選] {drop['name_zh']} (score {drop['bayesian_score']})")
            print(f"      ↓ 換成 ↓")
            print(f"      [未選] {gain['name_zh']} (score {gain['bayesian_score']})  +{delta:.2f}")
            print()
    else:
        print("✓ 當前選擇仍是各類別 Bayesian 最高（或可替換對象皆為鎖定必經點），無需替換")


def cmd_compose_better_attractions(args):
    """從 pool_scores.json 自動產出 segments.json.better_attractions markdown 表格。

    規則：
      - 景點備案：未入選、未鎖定（非必經）的 csv_type==景點，前 5 名
      - 餐廳備案：未入選的 csv_type==餐廳大休，前 3 名
      - 寫進 segments.json（若該欄位已有內容且非 --overwrite，不覆蓋；用 --dry-run 只印不寫）
    """
    n = args.day
    sel_file = plan_dir(n) / "places.json"
    seg_file = plan_dir(n) / "segments.json"
    if not sel_file.exists():
        die(f"找不到 {sel_file.relative_to(ROOT)}")
    if not seg_file.exists():
        die(f"找不到 {seg_file.relative_to(ROOT)}")

    sel_data = read_json(sel_file)
    selected_pids = {p["place_id"] for p in sel_data["places"]}

    landmarks: list[str] = []
    cfg_file = plan_dir(n) / "config.json"
    if cfg_file.exists():
        landmarks = read_json(cfg_file).get("must_visit_landmarks", []) or []
    locked_pids: set[str] = set()
    for p in sel_data["places"]:
        name = p.get("name_zh", "")
        if any(lm and lm in name for lm in landmarks):
            locked_pids.add(p["place_id"])

    pool_data = _ensure_pool_scores(n)
    scores: dict[str, dict] = pool_data["scores"]

    by_type: dict[str, list[dict]] = {}
    for pid, s in scores.items():
        by_type.setdefault(s["csv_type"], []).append({**s, "place_id": pid})

    spot_candidates = sorted(
        [c for c in by_type.get("景點", [])
         if c["place_id"] not in selected_pids and c["place_id"] not in locked_pids],
        key=lambda x: -x["bayesian_score"],
    )[:5]
    rest_candidates = sorted(
        [c for c in by_type.get("餐廳大休", []) if c["place_id"] not in selected_pids],
        key=lambda x: -x["bayesian_score"],
    )[:3]

    if not spot_candidates and not rest_candidates:
        info("候選池無未入選備案，better_attractions 設為單行說明")
        body = "> *當日候選池所有可評分點位皆已入選或為鎖定必經點，無加碼推薦。*"
    else:
        lines = [
            f"> 以下為沿途 Bayesian 排名較高但未排入路線的備選點位。"
            f"可視當天體力 / 天候 / 時間彈性加入。\n",
        ]
        if spot_candidates:
            lines.append("### 景點備案\n")
            lines.append("| 名次 | 名稱 | 評分 | 留言數 | 貝葉斯分 |")
            lines.append("|:---:|:---|:---:|---:|:---:|")
            for i, c in enumerate(spot_candidates, 1):
                lines.append(
                    f"| {i} | {c['name_zh']} | {c['rating']}★ | "
                    f"{c['total_ratings']:,} | {c['bayesian_score']} |"
                )
            lines.append("")
        if rest_candidates:
            lines.append("### 午餐 / 餐廳大休備案\n")
            lines.append("| 名次 | 店名 | 評分 | 留言數 | 貝葉斯分 |")
            lines.append("|:---:|:---|:---:|---:|:---:|")
            for i, c in enumerate(rest_candidates, 1):
                lines.append(
                    f"| {i} | {c['name_zh']} | {c['rating']}★ | "
                    f"{c['total_ratings']:,} | {c['bayesian_score']} |"
                )
            lines.append("")
        body = "\n".join(lines).rstrip()

    if args.dry_run:
        print(body)
        return

    seg = read_json(seg_file)
    if seg.get("better_attractions") and not args.overwrite:
        # 既有內容保留，但 touch mtime 表示「已驗證仍有效」，避免 render-md 預檢誤判
        import os, time
        now = time.time()
        os.utime(seg_file, (now, now))
        info(
            f"segments.json.better_attractions 已有 {len(seg['better_attractions'])} chars 內容；"
            f"加 --overwrite 才會覆蓋。預覽如下：\n"
        )
        print(body)
        return

    seg["better_attractions"] = body
    write_json(seg_file, seg)
    info(f"已寫入 segments.json.better_attractions（{len(body)} chars）")


def run_mechanical_cascade(n: int) -> None:
    """依正確順序重生 Phase 0-3 / 3.5 / 3.6 / 4 的所有「機械產出」（不含最後 render-md）。

    被 verify-and-fix 與 render-md 自癒共用。只重生不需人腦判斷的產物
    （csv / gpx / poster_vars 結構欄位 / dinner.json / hotel.json / better_attractions），
    **不碰**需人工決定的 places.json 點位選擇、segments.json 主敘述、poster_vars.json
    手寫場景文字。

    順序保證下游 mtime 一律 ≥ places.json：compute / route 都會寫 places.json，
    其餘步驟全部排在它們之後。
    """
    from .csv_out import cmd_write_csv
    from .gpx import cmd_route, cmd_gpx_waypoints
    from .render import cmd_render_prompt
    from .dinner import cmd_dinner_pool
    from .hotel import cmd_hotel_pool
    from .index_parser import cmd_update_index
    from .helpers import day_dir
    import os

    q = argparse.Namespace(day=n, quiet=True)

    info("[cascade 1/6] compute")
    cmd_compute(q)

    # route 必須在 write-csv 之前：route 會寫回 ors_distance_km 更新 places.json mtime，
    # 之後再跑 write-csv 才不會讓 csv 變舊
    if os.environ.get("ORS_API_KEY"):
        info("[cascade 2/6] route（ORS API）")
        try:
            cmd_route(q)
        except SystemExit:
            info("    route 失敗，改用 gpx-waypoints")
            cmd_gpx_waypoints(q)
    else:
        info("[cascade 2/6] route（無 ORS_API_KEY，fallback gpx-waypoints）")
        cmd_gpx_waypoints(q)

    # route 成功後把實際距離回寫 index.md
    try:
        cmd_update_index(q)
    except SystemExit:
        pass  # 沒有 ors_distance_km 時跳過（gpx-waypoints 不會產生距離）

    info("[cascade 3/6] write-csv")
    cmd_write_csv(q)

    info("[cascade 4/6] render-prompt（自動同步 poster_vars 結構欄位）")
    cmd_render_prompt(argparse.Namespace(day=n, no_sync=False, quiet=True))

    # dinner-pool / hotel-pool：各自鏡像有候選才跑；候選不足等失敗不中斷整條 cascade
    # （render-md 預檢會在 re-check 時把仍未解決的項目報出來）
    def _run_pool_guarded(label: str, fn) -> None:
        import sys
        orig_isatty = sys.stdin.isatty
        sys.stdin.isatty = lambda: True  # pool 指令在 tty 模式下不嘗試讀 stdin
        try:
            fn(q)
        except SystemExit:
            info(f"    {label} 失敗（候選不足？），略過——render-md 預檢會提示")
        finally:
            sys.stdin.isatty = orig_isatty

    info("[cascade 5/6] dinner-pool / hotel-pool（鏡像有候選才跑）")
    dinner_map = day_dir(n) / "dinner_map"
    if dinner_map.exists() and any(dinner_map.glob("ChIJ*.json")):
        _run_pool_guarded("dinner-pool", cmd_dinner_pool)
    else:
        info("    dinner_map/ 為空，略過晚餐推薦")
    hotel_map = day_dir(n) / "hotel_map"
    if hotel_map.exists() and any(hotel_map.glob("ChIJ*.json")):
        _run_pool_guarded("hotel-pool", cmd_hotel_pool)
    else:
        info("    hotel_map/ 為空，略過住宿推薦")

    info("[cascade 6/6] compose-better-attractions（若欄位為空才自動產）")
    cmd_compose_better_attractions(argparse.Namespace(day=n, dry_run=False, overwrite=False))


def cmd_verify_and_fix(args):
    """一條龍：重生 Phase 0-3 / 3.5 / 3.6 / 4 機械產出 + render-md --force。

    不能自動補的事項（places.json 點位選擇 / segments.json 主敘述 /
    poster_vars.json 手寫場景文字）需使用者補完再跑。

    註：render-md 本身已內建同樣的自癒 cascade，平常重做某天可直接跑
    `render-md N`。此指令保留為「我就是要強制重生全部並無視預檢」的入口。
    """
    n = args.day
    from .render import cmd_render_md

    info(f"=== verify-and-fix {n}：依序重生 Phase 0-3 / 3.5 / 3.6 / 4 機械產出 ===")
    run_mechanical_cascade(n)
    info("=== 機械步驟完成。最後執行 render-md --force ===")
    # 用 --force：cascade 已串完，trust 自己，跳過 render-md 內建自癒預檢。
    cmd_render_md(argparse.Namespace(day=n, force=True))
    info(f"✓ verify-and-fix {n} 完成，day{n}.md 已重生")

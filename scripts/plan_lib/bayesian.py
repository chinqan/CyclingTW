"""Bayesian 評分：score-pool / compute / review。"""
from __future__ import annotations

import argparse
import json
import statistics

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


def _ensure_pool_scores(n: int) -> dict:
    pool_path = plan_dir(n) / "pool_scores.json"
    if not pool_path.exists():
        info(f"找不到 {pool_path.relative_to(ROOT)}，自動執行 score-pool")
        cmd_score_pool(argparse.Namespace(day=n))
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
    print(f"C = {C}, m = {m}（來自 {pool_data['pool_size']} 筆候選池）\n")
    for p in data["places"]:
        score = p.get("bayesian_score")
        print(f"  [{p.get('csv_type','-'):<6}] {p['name_zh']:<22} "
              f"R={p.get('rating')} V={p.get('total_ratings')} → {score}")


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

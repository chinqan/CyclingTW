"""模板渲染：render-prompt / render-md + poster_vars 自動同步。"""
from __future__ import annotations

import argparse
import math
import os
import re
import sys

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .helpers import (ROOT, TEMPLATES_DIR, day_dir, plan_dir, read_json, write_json, die, info,
                      load_protagonist, landmark_covered, normalize_landmark, is_note_landmark)


def _jenv() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
    )


# ─── poster_vars 自動同步 ───

_DESTINATION_MIN_RATINGS = 2000  # 終點需達此評論數才視為「目的地型地標」
_ATTRACTION_CAP = 5  # 單日 csv_type=="景點" 數量上限（規則 [C]）；超過取「必經優先＋Bayesian 最高」前 N


def _find_main_visual_place(places: list[dict]) -> dict | None:
    # 1. 手動標記最優先
    for p in places:
        if "★主視覺" in (p.get("note") or ""):
            return p
    # 2. 終點為目的地型地標時優先（total_ratings 達門檻才算人們專程前往）
    last = places[-1]
    if (last.get("csv_type") == "起終點"
            and last.get("bayesian_score") is not None
            and (last.get("total_ratings") or 0) >= _DESTINATION_MIN_RATINGS):
        return last
    # 3. 景點類 Bayesian 最高者（終點為工具性節點時 fallback）
    cands = [p for p in places
             if p.get("csv_type") in ("景點", "起終點")
             and p.get("bayesian_score") is not None
             and p.get("total_ratings")]
    if not cands:
        return None
    return max(cands, key=lambda p: p["bayesian_score"] * math.log10(p["total_ratings"]))


_CITY_RE = re.compile(r"([一-鿿]{1,3}[縣市])([一-鿿]{1,3})[區鄉鎮]")


def _normalize_city(s: str) -> str:
    return s.replace("臺", "台") if s else s


def _location_desc(place: dict) -> str:
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
    "vertical_portrait_2_3": ("ns",),
    "horizontal_landscape_3_2": ("ew",),
}


def _axis_words(orientation: str, first_loc: dict, last_loc: dict) -> dict:
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


_RATED_TYPES = {"景點", "起終點", "餐廳大休"}  # 與 bayesian.RATED_TYPES 一致（可評分類型）


def _scores_not_ready(places_data: dict) -> bool:
    """places.json 是否缺 Bayesian 分數：沒跑過 compute（無 C/m），或改點後有
    「具 rating 資料卻無 bayesian_score」的可評分點。用「分數是否實際存在」而非
    mtime 判斷——compute 自己會讓 places.json 比 pool_scores 新，mtime 會誤判。"""
    if places_data.get("bayesian_C") is None or places_data.get("bayesian_m") is None:
        return True
    for p in places_data.get("places", []):
        if (p.get("csv_type") in _RATED_TYPES and p.get("rating") is not None
                and p.get("total_ratings") is not None and p.get("bayesian_score") is None):
            return True
    return False


def _derive_poster_vars(n: int) -> dict:
    places_path = plan_dir(n) / "places.json"
    places_data = read_json(places_path)
    # ★主視覺自動選點依賴 bayesian_score；分數未就緒時自動補跑 compute，
    # 拔掉「render-prompt 前必須先手動 compute」的隱性依賴。
    # （run_mechanical_cascade 內 compute 已先跑，這裡會判定就緒而不重複執行。）
    if _scores_not_ready(places_data):
        from .bayesian import cmd_compute
        info("places.json 尚無 Bayesian 分數，render-prompt 先自動補跑 compute…")
        cmd_compute(argparse.Namespace(day=n, quiet=True))
        places_data = read_json(places_path)
    places = places_data["places"]
    if len(places) < 2:
        die("places.json 至少需要 2 個點位（起點 + 終點）")
    first, last = places[0], places[-1]

    vars_path = plan_dir(n) / "poster_vars.json"
    existing = read_json(vars_path) if vars_path.exists() else {}
    out = dict(existing)
    out.setdefault("day", n)

    cfg_path = plan_dir(n) / "config.json"
    cfg = read_json(cfg_path) if cfg_path.exists() else {}
    out.setdefault("origin_label", cfg.get("origin") or first.get("name_zh", ""))
    out.setdefault("destination_label", cfg.get("destination") or last.get("name_zh", ""))
    # distance_range: 優先用 GPX 實測 (ors_distance_km)，每次同步都更新
    ors_km = places_data.get("ors_distance_km")
    if ors_km is not None:
        out["distance_range"] = f"約 {ors_km} 公里"
    elif "distance_range" not in out:
        rng = cfg.get("distance_km_range") or [None, None]
        lo, hi = rng[0], rng[1]
        if lo is not None and hi is not None and lo != hi:
            out["distance_range"] = f"約 {lo}–{hi} 公里"
        elif lo is not None:
            out["distance_range"] = f"約 {lo} 公里"
        else:
            out["distance_range"] = "距離未定"
    out.setdefault("subtitle", places_data.get("route_name", ""))
    out.setdefault("orientation", "vertical_portrait_2_3")
    out.setdefault("lighting", "柔和清晨明亮光線、清新藍天白雲")
    out.setdefault("allowed_elements", "")
    out.setdefault("enhancement", "")

    axis = _axis_words(out["orientation"], first["location"], last["location"])

    route_changed = False  # 追蹤主視覺／起點／終點是否變動

    # main_visual
    main_visual = _find_main_visual_place(places)
    mv_old = dict(out.get("main_visual") or {})
    if main_visual:
        new_pid = main_visual["place_id"]
        if mv_old.get("place_id") and mv_old["place_id"] != new_pid:
            info(f"⚠️  ★主視覺已從 {mv_old.get('place_id')} 換為 {new_pid}"
                 f"（{main_visual['name_zh']}），已清空 main_visual.scene_elements / action / expression")
            mv = {"place_id": new_pid, "location_desc": _location_desc(main_visual),
                  "scene_elements": "", "action": "", "expression": ""}
            route_changed = True
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
        if mv_old:
            info("⚠️  找不到 ★主視覺，main_visual 維持原值")
            mv_old.setdefault("place_id", "")
            mv_old.setdefault("location_desc", "")
            mv_old.setdefault("scene_elements", "")
            mv_old.setdefault("action", "")
            mv_old.setdefault("expression", "")
            out["main_visual"] = mv_old
        else:
            out["main_visual"] = {"place_id": "", "location_desc": "",
                                  "scene_elements": "", "action": "", "expression": ""}

    # small_avatar
    sa_old = dict(out.get("small_avatar") or {})
    first_pid = first.get("place_id")
    if sa_old.get("place_id") and sa_old["place_id"] != first_pid:
        info(f"⚠️  起點已換，已清空 small_avatar.scenario / action / expression")
        sa = {"place_id": first_pid, "location_desc": _location_desc(first),
              "scenario": "", "action": "", "expression": ""}
        route_changed = True
    else:
        sa = sa_old
        sa["place_id"] = first_pid
        if not sa.get("location_desc"):
            sa["location_desc"] = _location_desc(first)
        sa.setdefault("scenario", "")
        sa.setdefault("action", "")
        sa.setdefault("expression", "")
    out["small_avatar"] = sa

    # 終點變動偵測
    last_pid = last.get("place_id", "")
    if out.get("_last_place_id") and out["_last_place_id"] != last_pid:
        info(f"⚠️  終點已換（{out['_last_place_id']} → {last_pid}）")
        route_changed = True
    out["_last_place_id"] = last_pid

    # allowed_elements / enhancement：路線有任何變動就清空
    if route_changed:
        out["allowed_elements"] = ""
        out["enhancement"] = ""
        info("⚠️  路線已更動，allowed_elements / enhancement 已清空，請重新填寫")

    # composition / geographic_notes
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
            info(f"⚠️  以下手寫欄位為空：{', '.join(empty_fields)}")
    protagonist_prompt, protagonist_negative = load_protagonist()
    poster_vars["protagonist_prompt"] = protagonist_prompt
    poster_vars["protagonist_negative"] = protagonist_negative
    tpl = _jenv().get_template("prompt.md.j2")
    out = day_dir(n) / f"day{n}_prompt.md"
    out.write_text(tpl.render(**poster_vars), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")


def _collect_gate_errors(n: int, places: dict, segments: dict) -> list[str]:
    """全量新鮮度預檢：回傳所有「下游產出比 places.json 舊／缺失／簽章不符」的訊息。

    空 list 代表 Phase 0-3 / 3.5 / 3.6 / 4 產出全部新鮮。render-md 用它判斷是否需要
    啟動自癒 cascade；cascade 跑完後會再呼叫一次，殘留的就是真正需人工補的缺口。
    """
    places_path = plan_dir(n) / "places.json"
    places_mtime = places_path.stat().st_mtime
    segments_path = plan_dir(n) / "segments.json"
    dinner_path = plan_dir(n) / "dinner.json"
    dinner_map = day_dir(n) / "dinner_map"
    dinner_map_has_candidates = dinner_map.exists() and any(dinner_map.glob("ChIJ*.json"))
    hotel_path = plan_dir(n) / "hotel.json"
    hotel_map = day_dir(n) / "hotel_map"
    hotel_map_has_candidates = hotel_map.exists() and any(hotel_map.glob("ChIJ*.json"))

    gate_errors: list[str] = []

    # (A) Phase 0-3 產出 mtime ≥ places.json mtime
    csv_path = day_dir(n) / f"day{n}_mymap.csv"
    gpx_path = day_dir(n) / f"day{n}_route.gpx"
    poster_vars_path = plan_dir(n) / "poster_vars.json"
    prompt_path = day_dir(n) / f"day{n}_prompt.md"

    phase03_outputs = [
        (csv_path, "Phase 1", f"python3 scripts/plan.py write-csv {n}"),
        (gpx_path, "Phase 2", f"python3 scripts/plan.py route {n}   # 或 gpx-waypoints {n}"),
        (poster_vars_path, "Phase 3", f"python3 scripts/plan.py render-prompt {n}"),
        (prompt_path, "Phase 3", f"python3 scripts/plan.py render-prompt {n}"),
    ]
    for path, phase, cmd in phase03_outputs:
        if not path.exists():
            gate_errors.append(f"{path.relative_to(ROOT)} 不存在（{phase}）→ 請執行：{cmd}")
        elif path.stat().st_mtime < places_mtime:
            gate_errors.append(
                f"{path.relative_to(ROOT)} 比 places.json 舊（{phase} 需重做）→ 請執行：{cmd}"
            )

    # (A.2) Phase 2 爬升/下降：route 會把 elevation_ascent_m 寫進 places.json（在 gpx 之前）。
    #     gpx 已存在但欄位仍為 None → 代表是 elevation 整合前的舊產出，需重跑 route 補算。
    #     只在有 GOOGLE_PLACES_API_KEY 時當作 gate（離線 gpx-waypoints 本就算不出，留空不擋），
    #     避免離線環境永遠觸發自癒。route 重跑後欄位非 None → 此 gate 通過，無無窮迴圈。
    if os.environ.get("GOOGLE_PLACES_API_KEY") and gpx_path.exists() \
            and places.get("elevation_ascent_m") is None:
        gate_errors.append(
            "places.json 缺爬升/下降（elevation_ascent_m=None，elevation 整合前的舊產出）→ "
            f"請執行：python3 scripts/plan.py route {n}"
        )

    # (B) Phase 3.5 晚餐：dinner_map/ 有候選 → dinner.json 必須存在且新鮮
    if dinner_map_has_candidates:
        if not dinner_path.exists():
            gate_errors.append(
                f"dinner_map/ 已有候選但 dinner.json 不存在 → 請執行：python3 scripts/plan.py dinner-pool {n}"
            )
        elif dinner_path.stat().st_mtime < places_mtime:
            gate_errors.append(
                f"dinner.json 比 places.json 舊（Phase 3.5 需重做）→ 請執行：python3 scripts/plan.py dinner-pool {n}"
            )
        else:
            # (C) 內容一致性：dinner.json.source_endpoint_place_id 必須對到 places[-1]
            try:
                dj = read_json(dinner_path)
                expected_pid = places["places"][-1].get("place_id") if places.get("places") else None
                actual_pid = dj.get("source_endpoint_place_id")
                if actual_pid is None:
                    gate_errors.append(
                        f"dinner.json 缺少 source_endpoint_place_id（舊版產出）→ "
                        f"請重跑：python3 scripts/plan.py dinner-pool {n}"
                    )
                elif expected_pid and actual_pid != expected_pid:
                    gate_errors.append(
                        f"dinner.json 是為終點 {actual_pid} 算的，但 places.json 終點已換成 {expected_pid} "
                        f"→ 請重跑：python3 scripts/plan.py dinner-pool {n}"
                    )
            except Exception as e:
                gate_errors.append(f"dinner.json 讀取失敗：{e}")

    # (B.2) Phase 3.6 住宿：hotel_map/ 有候選 → hotel.json 必須存在且新鮮
    if hotel_map_has_candidates:
        if not hotel_path.exists():
            gate_errors.append(
                f"hotel_map/ 已有候選但 hotel.json 不存在 → 請執行：python3 scripts/plan.py hotel-pool {n}"
            )
        elif hotel_path.stat().st_mtime < places_mtime:
            gate_errors.append(
                f"hotel.json 比 places.json 舊（Phase 3.6 需重做）→ 請執行：python3 scripts/plan.py hotel-pool {n}"
            )
        else:
            # (C.2) 內容一致性：hotel.json.source_endpoint_place_id 必須對到 places[-1]
            try:
                hj = read_json(hotel_path)
                expected_pid = places["places"][-1].get("place_id") if places.get("places") else None
                actual_pid = hj.get("source_endpoint_place_id")
                if actual_pid is None:
                    gate_errors.append(
                        f"hotel.json 缺少 source_endpoint_place_id（舊版產出）→ "
                        f"請重跑：python3 scripts/plan.py hotel-pool {n}"
                    )
                elif expected_pid and actual_pid != expected_pid:
                    gate_errors.append(
                        f"hotel.json 是為終點 {actual_pid} 算的，但 places.json 終點已換成 {expected_pid} "
                        f"→ 請重跑：python3 scripts/plan.py hotel-search {n} && hotel-pool {n}"
                    )
            except Exception as e:
                gate_errors.append(f"hotel.json 讀取失敗：{e}")

    # (D) Phase 4 更佳景點：segments.json.better_attractions 必須非空，且不能比 places.json 舊
    ba = segments.get("better_attractions")
    if ba is None or (isinstance(ba, str) and not ba.strip()):
        gate_errors.append(
            "segments.json.better_attractions 缺失或為空 → "
            f"請參考 `python3 scripts/plan.py review {n}` 的輸出，把備案景點/餐廳表格填回 segments.json"
        )
    elif segments_path.stat().st_mtime < places_mtime:
        gate_errors.append(
            "segments.json 比 places.json 舊（Phase 4 需重做）→ "
            f"請重檢 better_attractions 是否仍符合最新點位順序，再重新存檔 segments.json"
        )

    # (E) 必經景點覆蓋：index.md 的 must_visit_landmarks 必須都對應到 places.json 航點，
    #     否則 ORS 不會繞經（如七星潭曾被指定必經卻漏選而消失）。無法自動補（需人工加點），
    #     故列為需人工處理的 gate；區域名／敘述型由 landmark_covered 視為已涵蓋不擋。
    config_path = plan_dir(n) / "config.json"
    if config_path.exists():
        cfg = read_json(config_path)
        landmarks = cfg.get("must_visit_landmarks", []) or []
        names = [p.get("name_zh", "") for p in (places.get("places") or [])]
        context = " ".join(str(cfg.get(k, "")) for k in ("origin", "destination", "main_route_text"))
        missing = [lm for lm in landmarks if not landmark_covered(lm, names, context)]
        if missing:
            gate_errors.append(
                f"必經景點未進路線（index.md 指定但不在 places.json）：{', '.join(missing)} → "
                f"請把它們加入 day{n}/_plan/places.json 當航點（ORS 才會繞經）後重跑"
            )

    # (F) 景點數上限：csv_type=="景點" 最多 _ATTRACTION_CAP 個（規則 [C]）。超過時優先保留
    #     必經景點，其餘名額給 Bayesian 評分（最受歡迎）最高者，被擠掉的降為 better_attractions
    #     備案。無法自動刪（保留哪些含必經考量需人腦判斷），與 (E) 同列為需人工處理的 gate；
    #     被降級者仍在 pool/candidates，cascade 的 compose-better-attractions 會自動納入備案表。
    attractions = [p for p in (places.get("places") or []) if p.get("csv_type") == "景點"]
    if len(attractions) > _ATTRACTION_CAP:
        lms = [lm for lm in (read_json(config_path).get("must_visit_landmarks") or [])
               if not is_note_landmark(lm)] if config_path.exists() else []

        # 每個必經 landmark 只認 1 個「最佳匹配」景點（避免 landmark_matches_name 的
        # 0.5 字元重疊把同後綴景點——如多個「○○漁港」——全誤標必經，反把高分景點擠去降級）。
        def _overlap(lm, name):
            lm = normalize_landmark(lm)
            if not lm or not name:
                return 0.0
            base = len(set(lm) & set(name)) / len(set(lm))
            return base + (1.0 if (lm in name or name in lm) else 0.0)

        must_pids = set()
        for lm in lms:
            best, sc = max(((p, _overlap(lm, p.get("name_zh", ""))) for p in attractions),
                           key=lambda t: t[1], default=(None, 0.0))
            if best is not None and sc >= 0.5:
                must_pids.add(best.get("place_id"))

        def _is_must(p):
            return p.get("place_id") in must_pids

        def _score(p):
            return p.get("bayesian_score") or 0

        must = [p for p in attractions if _is_must(p)]
        optional = sorted((p for p in attractions if not _is_must(p)), key=_score, reverse=True)
        slots = max(0, _ATTRACTION_CAP - len(must))
        keep, drop = must + optional[:slots], optional[slots:]

        def _fmt(lst):
            return "、".join(
                f"{p.get('name_zh', '?')}（{'必經' if _is_must(p) else _score(p)}）" for p in lst
            ) or "（無）"

        if len(must) > _ATTRACTION_CAP:
            gate_errors.append(
                f"景點數 {len(attractions)} 超過上限 {_ATTRACTION_CAP}，且必經景點就有 "
                f"{len(must)} 個（{_fmt(must)}）→ 全留仍超標，請檢視 index.md "
                f"must_visit_landmarks 是否過多，或把部分必經降為一般景點"
            )
        else:
            gate_errors.append(
                f"景點數 {len(attractions)} 超過上限 {_ATTRACTION_CAP}（規則 [C]）→ 請依"
                f"「必經優先＋Bayesian 最高」精簡至 {_ATTRACTION_CAP} 個。建議保留："
                f"{_fmt(keep)}；建議移出 places.json（自動降為 better_attractions 備案）：{_fmt(drop)}"
            )

    return gate_errors


def cmd_render_md(args):
    n = args.day
    cfg = read_json(plan_dir(n) / "config.json")
    places = read_json(plan_dir(n) / "places.json")
    segments = read_json(plan_dir(n) / "segments.json")

    # ── ishikawa 格式驗證 ──
    ishikawa = segments.get("ishikawa", "")
    if ishikawa:
        # 不能有 YAML front matter
        if ishikawa.startswith("---"):
            die("segments.json 的 ishikawa 欄位不能有 YAML front matter（---\\ntitle:...\\n---）。\n"
                "正確格式應直接以 'ishikawa-beta\\n' 開頭。")
        # 必須以 ishikawa-beta 開頭
        if not ishikawa.strip().startswith("ishikawa-beta"):
            die("segments.json 的 ishikawa 欄位必須以 'ishikawa-beta' 開頭。")
        # 段落順序檢查：第一個出現的「第X段」應該是最後一段（倒序）
        import re as _re
        seg_nums = _re.findall(r"第([一二三四五六七八九十]+)段", ishikawa)
        if len(seg_nums) >= 2:
            CN_NUM = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
                      "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}
            nums = [CN_NUM.get(s, 0) for s in seg_nums]
            # 去重取每段首次出現的順序
            seen = []
            for num in nums:
                if num not in seen:
                    seen.append(num)
            if len(seen) >= 2 and seen[0] < seen[-1]:
                info(f"⚠️  ishikawa 魚骨圖段落順序為正序（第{seg_nums[0]}段→第{seg_nums[-1]}段），"
                     f"Mermaid ishikawa-beta 需要倒序（最後一段在最前面）。請修正 segments.json。")

    # ── Phase 0-3 / 3.5 / 3.6 / 4 全量新鮮度預檢 + 自癒 ──
    # 「重生 = 一切重來」：places.json 一變，下游全部視為過舊。但既然這些下游都是
    # 機械產出，偵測到陳舊時不再 hard-fail 要人手動重跑，而是直接跑 cascade 自動重生，
    # 只在自癒後仍有「需人腦判斷」的缺口（如該天無備選景點可填 better_attractions）才中止。
    # --force：完全略過自癒與預檢，直接拿現有檔案渲染（verify-and-fix 收尾用）。
    if not getattr(args, "force", False):
        gate_errors = _collect_gate_errors(n, places, segments)
        if gate_errors:
            info(f"render-md {n}：偵測到 {len(gate_errors)} 項下游產出陳舊/缺失，啟動自癒 cascade 重生機械產物…")
            for e in gate_errors:
                info(f"  • {e.split('→')[0].strip()}")
            from .bayesian import run_mechanical_cascade
            run_mechanical_cascade(n)
            # cascade 會重寫 places.json / segments.json 等，必須重讀供後續渲染與 re-check
            places = read_json(plan_dir(n) / "places.json")
            segments = read_json(plan_dir(n) / "segments.json")
            residual = _collect_gate_errors(n, places, segments)
            if residual:
                for e in residual:
                    print(f"[error] {e}", file=sys.stderr)
                die(f"render-md {n}：自癒 cascade 後仍有 {len(residual)} 項需人工處理"
                    f"（最常見：該天確實無備選景點可填 better_attractions）。確認後加 --force 略過。")
            info(f"✓ render-md {n}：自癒完成，所有 Phase 0-3/3.5/3.6/4 產出已重生")

    dinner_path = plan_dir(n) / "dinner.json"
    hotel_path = plan_dir(n) / "hotel.json"

    dinner_top5 = []
    dinner_pool_size = 0
    if dinner_path.exists():
        dinner_data = read_json(dinner_path)
        dinner_pool_size = dinner_data.get("pool_size", 0)
        dinner_top5 = [r for r in dinner_data.get("restaurants", []) if r.get("selected")]

    hotel_top5 = []
    hotel_pool_size = 0
    if hotel_path.exists():
        hotel_data = read_json(hotel_path)
        hotel_pool_size = hotel_data.get("pool_size", 0)
        hotel_top5 = [h for h in hotel_data.get("hotels", []) if h.get("selected")]

    # 讀取 mymaps.json 取得該天的 My Maps mid
    mymap_mid = None
    mymaps_path = ROOT / "mymaps.json"
    if mymaps_path.exists():
        try:
            mymaps = read_json(mymaps_path)
            mymap_mid = mymaps.get("maps", {}).get(str(n))
        except Exception:
            pass

    ctx = {
        "day": n,
        "cfg": cfg,
        "places_data": places,
        "places": places["places"],
        "dinner_top5": dinner_top5,
        "dinner_pool_size": dinner_pool_size,
        "hotel_top5": hotel_top5,
        "hotel_pool_size": hotel_pool_size,
        "mymap_mid": mymap_mid,
        **segments,
    }
    tpl = _jenv().get_template("day.md.j2")
    out = day_dir(n) / f"day{n}.md"
    out.write_text(tpl.render(**ctx), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")

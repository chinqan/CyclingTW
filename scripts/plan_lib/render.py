"""模板渲染：render-prompt / render-md + poster_vars 自動同步。"""
from __future__ import annotations

import math
import re

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .helpers import ROOT, TEMPLATES_DIR, day_dir, plan_dir, read_json, write_json, die, info


def _jenv() -> Environment:
    return Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
    )


# ─── poster_vars 自動同步 ───

def _find_main_visual_place(places: list[dict]) -> dict | None:
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


def _derive_poster_vars(n: int) -> dict:
    places_data = read_json(plan_dir(n) / "places.json")
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
    if "distance_range" not in out:
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
    else:
        sa = sa_old
        sa["place_id"] = first_pid
        if not sa.get("location_desc"):
            sa["location_desc"] = _location_desc(first)
        sa.setdefault("scenario", "")
        sa.setdefault("action", "")
        sa.setdefault("expression", "")
    out["small_avatar"] = sa

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
    tpl = _jenv().get_template("prompt.md.j2")
    out = day_dir(n) / f"day{n}_prompt.md"
    out.write_text(tpl.render(**poster_vars), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")


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

    # 載入晚餐 top 5（如果有的話）
    dinner_path = plan_dir(n) / "dinner.json"
    dinner_top5 = []
    dinner_pool_size = 0
    if dinner_path.exists():
        dinner_data = read_json(dinner_path)
        dinner_pool_size = dinner_data.get("pool_size", 0)
        dinner_top5 = [r for r in dinner_data.get("restaurants", []) if r.get("selected")]
    else:
        info("⚠️  找不到 dinner.json，「晚餐推薦」區塊將略過（請先執行 dinner-pool N）")

    if not segments.get("better_attractions"):
        info("⚠️  segments.json 缺少 better_attractions，「更佳景點參考」區塊將略過")

    ctx = {
        "day": n,
        "cfg": cfg,
        "places_data": places,
        "places": places["places"],
        "dinner_top5": dinner_top5,
        "dinner_pool_size": dinner_pool_size,
        **segments,
    }
    tpl = _jenv().get_template("day.md.j2")
    out = day_dir(n) / f"day{n}.md"
    out.write_text(tpl.render(**ctx), encoding="utf-8")
    info(f"已寫入 {out.relative_to(ROOT)}")

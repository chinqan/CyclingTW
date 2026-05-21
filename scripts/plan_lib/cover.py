"""render-cover-prompt：10 天環島總覽封面海報提示詞。

設計同 render-prompt：抽 index.md 結構化資料 → cover_vars.json →
套 templates/cover_prompt.md.j2 渲染。四極點視覺防呆查表獨立放
scripts/cover_pole_visuals.json。
"""
from __future__ import annotations

import re

from jinja2 import Environment, FileSystemLoader, StrictUndefined

from .helpers import ROOT, TEMPLATES_DIR, read_json, write_json, die, info, load_protagonist
from .index_parser import INDEX_TABLE_ROW

INDEX_PATH = ROOT / "index.md"
POLE_DATA_PATH = ROOT / "scripts" / "cover_pole_visuals.json"
COVER_OUT_DIR = ROOT / "output" / "imagegen"
COVER_VARS_PATH = COVER_OUT_DIR / "cover_vars.json"
COVER_PROMPT_PATH = COVER_OUT_DIR / "cyclingtw-cover_prompt.md"


def _parse_title(md_text: str) -> str:
    for line in md_text.splitlines():
        s = line.strip()
        if s.startswith("# "):
            return s[2:].strip()
    return ""


def _parse_all_days(md_text: str) -> list[dict]:
    days = []
    for line in md_text.splitlines():
        m = INDEX_TABLE_ROW.match(line.strip())
        if not m:
            continue
        landmarks = [
            s.strip().replace("**", "")
            for s in re.split(r"[、，,]", m.group(6).strip())
            if s.strip()
        ]
        days.append({
            "day": int(m.group(1)),
            "origin": m.group(2).strip(),
            "destination": m.group(3).strip(),
            "distance": m.group(4).strip(),
            "route": m.group(5).strip(),
            "landmarks": landmarks,
        })
    days.sort(key=lambda d: d["day"])
    return days


def _total_distance_range(days: list[dict]) -> str:
    lo_sum = hi_sum = 0
    for d in days:
        nums = [int(x) for x in re.findall(r"\d+", d["distance"])]
        if not nums:
            continue
        if len(nums) == 1:
            lo_sum += nums[0]
            hi_sum += nums[0]
        else:
            lo_sum += nums[0]
            hi_sum += nums[1]
    return f"約 {lo_sum}–{hi_sum} 公里"


def _attach_poles(days: list[dict]) -> None:
    poles = read_json(POLE_DATA_PATH)
    pole_by_day: dict[int, dict] = {}
    for direction, p in poles.items():
        pole_by_day[p["day"]] = {"direction": direction, **p}
    for d in days:
        d["pole"] = pole_by_day.get(d["day"])


def _derive_cover_vars() -> dict:
    md_text = INDEX_PATH.read_text(encoding="utf-8")
    title = _parse_title(md_text)
    days = _parse_all_days(md_text)
    if len(days) != 10:
        die(f"index.md 預期 10 列 Day，實際 {len(days)} 列")
    _attach_poles(days)

    existing = read_json(COVER_VARS_PATH) if COVER_VARS_PATH.exists() else {}
    out = dict(existing)
    out["title"] = title
    out["days"] = days
    out["total_distance"] = _total_distance_range(days)
    out.setdefault("subtitle", "台灣四極點挑戰")
    out.setdefault("orientation", "vertical_portrait_2_3")
    out.setdefault("lighting", "柔和清晨明亮光線、清新藍天白雲")
    out.setdefault("allowed_elements", "台灣山脈稜線、城市縮小模型、西部海岸線、東部太平洋海岸、公路與鐵道路網")
    out.setdefault("enhancement", "畫面具有故事感與旅程感、呈現10天環島四極點全程概念、帶有完騎成就解鎖氛圍")
    out.setdefault("action", "站在台灣地圖模型中央、高舉雙手慶祝完騎、公路車靠在身旁、環島路線在腳下完整呈現")
    out.setdefault("expression", "開心、自豪、完成10天環島四極點挑戰的巔峰成就感")
    out.setdefault("scenario", "完騎返抵蘆洲柳堤公園、夕陽金光灑落、四極點全數達成")

    COVER_OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_json(COVER_VARS_PATH, out)
    return out


def cmd_render_cover_prompt(args):
    if args.no_sync:
        if not COVER_VARS_PATH.exists():
            die(f"找不到 {COVER_VARS_PATH.relative_to(ROOT)}，請先不帶 --no-sync 跑一次")
        cover_vars = read_json(COVER_VARS_PATH)
    else:
        cover_vars = _derive_cover_vars()
        info(f"已從 index.md 同步 {COVER_VARS_PATH.relative_to(ROOT)}")

    if args.aspect == "horizontal":
        cover_vars["orientation"] = "horizontal_landscape_3_2"
    elif args.aspect == "vertical":
        cover_vars["orientation"] = "vertical_portrait_2_3"

    protagonist_prompt, protagonist_negative = load_protagonist()
    cover_vars["protagonist_prompt"] = protagonist_prompt
    cover_vars["protagonist_negative"] = protagonist_negative

    env = Environment(
        loader=FileSystemLoader(TEMPLATES_DIR),
        undefined=StrictUndefined,
        keep_trailing_newline=True,
        trim_blocks=False,
    )
    tpl = env.get_template("cover_prompt.md.j2")
    COVER_OUT_DIR.mkdir(parents=True, exist_ok=True)
    COVER_PROMPT_PATH.write_text(tpl.render(**cover_vars), encoding="utf-8")
    info(f"已寫入 {COVER_PROMPT_PATH.relative_to(ROOT)}")

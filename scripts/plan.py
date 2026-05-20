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
  - Bayesian 用整池候選：C/m 由 mirror 完整候選池（含未入選備案）算，可在
    編輯 places.json **前**先用 score-pool 看分數做決策（pool_scores.json 是 SoT）
  - 不變式驗證：CSV 終點 = index.md 目的地

子命令（共 15 個）：
  parse-index N            解析 index.md 第 N 天設定
  mirror-status N          列出 dayN/map/（本地鏡像）內容與候選池警告
  mirror-put N             [stdin] upsert 單筆 place 到本地鏡像
  mirror-diff N            [stdin] 比對本地鏡像 vs 線上最新
  score-pool N             對整個 mirror 候選池算 Bayesian，產出 pool_scores.json
  compute N                套用 pool_scores 到 places.json（缺失時自動觸發 score-pool）
  review N                 讀 pool_scores 顯示排名 + ★入選 + 替換建議
  write-csv N              產 dayN_mymap.csv（依 _plan/places.json）
  gpx-save N               [stdin] 儲存單段 openroute GPX（短路線直出時用）
  gpx-waypoints N          備案：依 places.json 座標產純航點 GPX（離線 / 無 MCP 時）
  gpx-split-plan N         切割長路線為多段（避免 MCP 100KB 截斷）
  gpx-append N --leg i     [stdin] 儲存第 i 段 openroute GPX
  gpx-merge N              合併所有 leg 為最終 dayN_route.gpx
  render-prompt N          產 dayN_prompt.md；預設先從 _plan/places.json 重推
                           poster_vars.json 結構欄位（--no-sync 跳過）
  render-md N              產 dayN.md（依 _plan/places.json + segments.json）
  render-cover-prompt      產 output/imagegen/cyclingtw-cover_prompt.md（10 天總覽封面海報）

每日工作目錄結構（自動建立）：
  dayN/
  ├── _plan/
  │   ├── config.json        ← parse-index 產出（起終點/距離/必經景點）
  │   ├── pool_scores.json   ← score-pool 產出（整池 Bayesian，C/m/score by pid）
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

[D] 起終點不可錯置
  - 起點 = dayN_mymap.csv 順序第 1 筆 = 當日出發地
  - 終點 = dayN_mymap.csv 順序最後 1 筆 = 當日目的地

[E] 撤退方案
  - 每日 dayN.md 的「騎乘注意事項」段落，必須列出 ≥ 2-3 個可中途撤退搭火車的車站

[F] ★主視覺視覺辨識度
  - main_visual 候選需有明確視覺符號才適合放海報

[G] 海報光線氛圍（poster_vars.json 的 lighting 欄位）
  - 預設：柔和清晨明亮光線、清新藍天白雲
"""
from __future__ import annotations

import argparse
import sys

try:
    from jinja2 import Environment  # noqa: F401 — 驗證 jinja2 可用
except ImportError:
    print("[error] 缺少 jinja2，請安裝：pip install jinja2", file=sys.stderr)
    sys.exit(1)

from plan_lib.index_parser import cmd_parse_index
from plan_lib.mirror import cmd_mirror_status, cmd_mirror_put, cmd_mirror_diff
from plan_lib.bayesian import cmd_score_pool, cmd_compute, cmd_review
from plan_lib.csv_out import cmd_write_csv
from plan_lib.gpx import (
    cmd_gpx_save, cmd_gpx_waypoints, cmd_gpx_split_plan,
    cmd_gpx_append, cmd_gpx_fetch, cmd_gpx_merge,
)
from plan_lib.render import cmd_render_prompt, cmd_render_md
from plan_lib.cover import cmd_render_cover_prompt
from plan_lib.dinner import (
    cmd_dinner_put, cmd_dinner_diff, cmd_dinner_status,
    cmd_dinner_pool, cmd_dinner_review, cmd_dinner_render,
)


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
    add("score-pool",    cmd_score_pool,    "對整個 mirror 候選池算 Bayesian")
    add("compute",       cmd_compute,       "套用 pool_scores 到 places.json")
    add("review",        cmd_review,        "讀 pool_scores 顯示排名 + 替換建議")
    add("write-csv",     cmd_write_csv,     "產 dayN_mymap.csv")
    add("gpx-save",      cmd_gpx_save,      "[stdin] 儲存 openroute GPX")
    add("gpx-waypoints", cmd_gpx_waypoints, "備案：純航點 GPX")

    def _nonneg_int(s: str) -> int:
        v = int(s)
        if v < 0:
            raise argparse.ArgumentTypeError(f"必須 ≥ 0，收到 {v}")
        return v

    sp = add("gpx-split-plan", cmd_gpx_split_plan, "切割長路線為多段")
    sp.add_argument("--max-waypoints", type=_nonneg_int, default=4,
                    help="每段中間 waypoints 上限（預設 4；0 = 只有 from+to）")

    sp = add("gpx-append", cmd_gpx_append, "[stdin] 儲存單段 GPX")
    sp.add_argument("--leg", type=int, required=True, help="段次編號（從 1 開始）")

    sp = add("gpx-fetch", cmd_gpx_fetch, "自動從 cwd 拾取最新 cycling-regular-*.gpx")
    sp.add_argument("--leg", type=int, required=True, help="段次編號（從 1 開始）")

    add("gpx-merge",     cmd_gpx_merge,     "合併所有 leg 為最終 GPX")
    add("dinner-status", cmd_dinner_status, "顯示 dayN/dinner_map/ 鏡像現況")
    add("dinner-put",    cmd_dinner_put,    "[stdin] upsert 餐廳到 dinner_map/ 鏡像")
    add("dinner-diff",   cmd_dinner_diff,   "[stdin] 比對 dinner_map/ 本地 vs 線上最新")
    add("dinner-pool",   cmd_dinner_pool,   "從 dinner_map/ 鏡像池算 Bayesian 選 top 5")
    add("dinner-review", cmd_dinner_review, "顯示 dinner.json 排名")
    add("dinner-render", cmd_dinner_render, "產 dayN_dinner.md")
    sp = add("render-prompt", cmd_render_prompt, "產 dayN_prompt.md")
    sp.add_argument("--no-sync", action="store_true",
                    help="跳過自動同步，僅以現有 poster_vars.json 渲染")
    add("render-md",     cmd_render_md,     "產 dayN.md")

    sp = sub.add_parser("render-cover-prompt", help="產 10 天總覽封面海報提示詞")
    sp.add_argument("--no-sync", action="store_true",
                    help="跳過自動同步，僅以現有 cover_vars.json 渲染")
    sp.add_argument("--aspect", choices=["vertical", "horizontal"], default=None,
                    help="覆寫 orientation：vertical=2:3 直式（預設）、horizontal=3:2 橫式")
    sp.set_defaults(func=cmd_render_cover_prompt)
    return p


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

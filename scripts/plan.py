#!/usr/bin/env python3
"""
CyclingTW Day Planner — 半自動腳本工具
=====================================
本腳本負責所有機械步驟（HTTPS API 搜尋 / 本地鏡像 / Bayesian / CSV / GPX / 模板渲染）。
所有 Google Maps 查詢一律走 Places API (New) 直連，不走任何 MCP（mirror-search /
dinner-search / hotel-search / refresh-details 都在這一條路）。

設計原則：
  - 本地鏡像（write-through）：dayN/map/ 是 Google Maps 的本地鏡像 DB，不是
    省 API 用的快取；每次重搜把 fresh 資料 upsert 回本地。
  - 先 diff 後 put：mirror-diff 顯示變動，mirror-put 一律 upsert 寫回
  - Bayesian 用整池候選：C/m 由 mirror 完整候選池（含未入選備案）算，可在
    編輯 places.json **前**先用 score-pool 看分數做決策（pool_scores.json 是 SoT）
  - 路線/終點相關性過濾（鏡像只增不減，換路線後排除離線殘留點，不刪鏡像）：
    score-pool 剔除距目前路線折線過遠的景點。折線優先用 Routes API 真實路線幾何
    （route 會把它存進 _plan/route_geometry.json，簽章對得上現在航點時 → 走廊 15km，
    精準抓 15-30km 殘留）；尚未跑 route/離線/簽章不符時退回航點直線近似（走廊 30km，寬鬆）。
    dinner/hotel-pool 剔除距目前終點 >3km 的餐廳/飯店。compute 每次都重算 score-pool；
    render-md 自癒 cascade 在 route 成功後會再補跑一次 score-pool，使備案表一個指令內
    就套用真實路線過濾
  - 不變式驗證：CSV 終點 = index.md 目的地

子命令：
  hotel-search / hotel-pool / hotel-render
                           Phase 3.6 終點周邊 3km 飯店候選池。hotel-search 直接呼叫
                           Google Places API (zh-TW)，自動寫入 hotel_map/；
                           輸出 _plan/hotel.json 與 dayN_hotel.md。
                           （輔助：hotel-status / hotel-review）
                           ★過夜地 ≠ 騎乘終點時（如 Day8 騎到花蓮車站、火車接駁到蘇澳
                           新站過夜）：在 places.json 加頂層 "lodging_endpoint"
                           {place_id,name_zh,location}，dinner/hotel 的搜尋中心與
                           source_endpoint_place_id 簽章改用它（render-md 預檢也比對它），
                           騎乘終點 places[-1] 不受影響。
  parse-index N            解析 index.md 第 N 天設定
  route-skeleton N         Phase 1 起點：Routes API（computeRoutes）只串「起點+必經
                           景點+終點」算骨架最佳路線，產 _plan/skeleton.json（含
                           geometry 折線）。供 search-along-route 沿真實路線找點。
                           需 GOOGLE_PLACES_API_KEY（地理編碼 + 路線，需啟用 Routes API）。
  search-along-route N --keyword "…" --csv-type … [--segments K]
                           沿 skeleton/route 折線用 Places API (New)
                           searchAlongRoute 找停靠點，依「離線繞路距離」過濾
                           （便利商店≤0.5/餐廳≤1/景點≤2km，可 --detour-km 覆寫），
                           印出每點沿路里程，upsert 到 candidates_not_selected。
                           長路線用 --segments 切段各搜再合併以均勻覆蓋。
  mirror-status N          列出 dayN/map/（本地鏡像）內容與候選池警告
  mirror-search N --keyword "…" --csv-type …
                           （fallback）用 Google Places API 找單一具名停靠點並
                           upsert 到 dayN/map/（可加 --bias LAT,LNG 偏向位置）
  mirror-put N             [stdin] 手動 upsert 單筆 place（mirror-search 找不到時用）
  mirror-diff N            [stdin] 比對本地鏡像 vs 線上最新
  score-pool N             對整個 mirror 候選池算 Bayesian，產出 pool_scores.json
  compute N                套用 pool_scores 到 places.json（缺失時自動觸發 score-pool）
  review N                 讀 pool_scores 顯示排名 + ★入選 + 替換建議
  compose-better-attractions N  從 pool_scores 自動產 segments.json.better_attractions
  write-csv N              產 dayN_mymap.csv（依 _plan/places.json）。含「緯度/經度」
                           欄：匯入 Google My Maps 時請選此兩欄定位（精確、不靠地名
                           地理編碼），避免偏遠雜貨店/區域名（旭美商店、墾丁大街）被
                           My Maps 較弱的地名搜尋判為找不到。「地點搜尋關鍵字」欄保留備用。
  route N                  呼叫 Google Routes API（computeRoutes，travelMode 預設
                           TWO_WHEELER）取整天路線，輸出 dayN_route.gpx。需
                           GOOGLE_PLACES_API_KEY（須啟用 Routes API）。travelMode 可由
                           config.json travel_mode 或 ROUTES_TRAVEL_MODE 覆寫為 BICYCLE。
                           places.json 可選 top-level "route_via"：純通過點 list，每筆
                           {lat,lng,after}（after=插在 places 第幾個之後），以 Google
                           via:true 把路線釘在指定道路、避開封閉/不可行路段；不列入
                           places → 不進 CSV/地圖標記/選點計分。
                           ★折回守門（兩段式）：便利商店/餐廳大休若逼路線繞進再折回，
                           route 報錯中止逼換點。段1 免費量「路線自我重疊」篩嫌疑；段2 對
                           嫌疑點打 Routes API 算「邊際繞路」(經此點 vs 跳過此點 prev→next
                           路線長差)，>500m 才中止。marginal≈0 表繞路屬必經結構(極東岬角
                           往返/河口繞行/內灣景點)順帶經過，放行。沿線選點只看「垂直偏離」
                           會漏掉分隔島另一側的點，故由此守門在路線層攔下。
  gpx-save N               [stdin] 儲存外部來源 GPX（備援用）
  gpx-waypoints N          離線備案：依 places.json 座標產純航點 GPX
  refresh-details N        呼叫 Google Places API (New) 刷新可評分點位的
                           rating/total_ratings/opening_hours，upsert 回 mirror
                           （需設定 GOOGLE_PLACES_API_KEY 環境變數）
                           加 --with-reviews 同時取 reviews（Pro tier）
  render-prompt N          產 dayN_prompt.md；預設先從 _plan/places.json 重推
                           poster_vars.json 結構欄位（--no-sync 跳過）。主體渲染
                           Claude 手寫的 narrative 敘事段（規則 [G]）；narrative
                           為空時 fallback 舊版欄位拼接並警告
  render-md N              產 dayN.md。渲染前全量檢查 Phase 0-3 / 3.5 / 3.6 / 4
                           產出 mtime ≥ places.json 且 dinner/hotel.json 的
                           source_endpoint_place_id 對應目前終點。偵測到陳舊會
                           「自癒」：自動跑 cascade 重生所有機械產物後再渲染，只在
                           自癒後仍有需人工判斷的缺口才中止；--force 略過自癒直接渲染
  verify-and-fix N         一條龍：重生 Phase 0-3/3.5/3.6/4 機械步驟 + render-md
                           --force（render-md 已內建同樣自癒，平常重做可直接跑它）
  render-cover-prompt      產 output/imagegen/cyclingtw-cover_prompt.md（10 天總覽封面海報）

每日工作目錄結構（自動建立）：
  dayN/
  ├── _plan/
  │   ├── config.json        ← parse-index 產出（起終點/距離/必經景點）
  │   ├── skeleton.json      ← route-skeleton 產出（必經點骨架路線 + geometry 折線）
  │   ├── pool_scores.json   ← score-pool 產出（整池 Bayesian，C/m/score by pid）
  │   ├── route_geometry.json ← route 產出（Routes API 真實路線折線 + 航點簽章，供走廊過濾）
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
  - 僅對 csv_type ∈ {景點, 起終點, 餐廳大休} 需要精確 rating / total_ratings。
  - 用 `refresh-details N` 一次刷新 places.json 可評分點位的
    rating / total_ratings / opening_hours（Google Places API New，Essentials tier）。
    加 --with-reviews 取 reviews（Pro tier）。
  - 便利商店 / 加油站 / 公共設施 / 綜合休息站：用 mirror-search --csv-type 該類型
    搜尋，自動只保留 place_id / name / location；refresh-details 也會略過這些
    rating 留空。
  - 景點：mirror-search 一次搜一個候選（可用 --max-results 3 廣搜），未入選的
    自動進 candidates_not_selected 等 Bayesian pool。
  - 餐廳 / 住宿：用 dinner-search / hotel-search 對終點圓心一次抓 50–80 筆。

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
  - 景點數上限：單日 csv_type=="景點" ≤ 5 個（便利商店/餐廳大休/起終點不計）。候選超過
    時，必經景點（config must_visit_landmarks）一律保留，其餘名額給 Bayesian 評分
    （最受歡迎）最高者；被擠掉的移出 places.json，cascade 的 compose-better-attractions
    會自動降為 better_attractions 備案。render-md 預檢 gate (F) 機械擋下並列出
    「建議保留前 N／建議降級」清單；上限寫在 render.py _ATTRACTION_CAP，可依需求調整。
  - 便利商店間距：沿路約每 30 km 一個（≈ 距離 ÷ 30），於補給空窗段就近補點；午餐放中段。

[D] 起終點不可錯置
  - 起點 = dayN_mymap.csv 順序第 1 筆 = 當日出發地
  - 終點 = dayN_mymap.csv 順序最後 1 筆 = 當日目的地

[E] 撤退方案
  - 每日 dayN.md 的「騎乘注意事項」段落，必須列出 ≥ 2-3 個可中途撤退搭火車的車站

[F] ★主視覺選點原則（敘事地位優先，Bayesian 分數次之）
  - 優先順序：① note 含「★主視覺」（手動覆蓋）② 終點 total_ratings ≥ 2000（目的地型地標）③ 景點類 Bayesian 最高者
  - 終點分兩類：目的地型（人們專程前往，total_ratings 高）→ 優先；工具型（住宿/轉運節點，total_ratings 低）→ 降為 fallback
  - 閾值 2000 寫在 render.py _DESTINATION_MIN_RATINGS，可依需求調整
  - 邊界案例（終點具敘事意義但 total_ratings 不足）：在 places.json note 加「★主視覺」手動覆蓋

[G] 海報提示詞撰寫（poster_vars.json 的 narrative 欄位，dayN_prompt.md 主體）
  - 不用欄位拼接模板，Claude 必須**手寫整段敘事體提示詞**填入 narrative：
    參考專案根目錄 `prompt.md` 的敘事手法，套用當日場景情境撰寫——以「當日旅程
    故事」為敘事軸（從哪出發、跨過什麼、抵達哪個里程碑），把主視覺場景、動作、
    表情、小分身、沿途地標、地理方位（geographic_notes / composition 為機器推導
    的事實依據，必須遵守）自然織進連續散文，而非條列欄位。
  - 必含要素（敘事中自然帶到）：3D Q版公仔/diorama 風格轉換與特徵、主角為畫面
    最大主體、公路車縮小模型細節、小分身位置與情境、「台灣立體地圖模型」整體
    構圖、地理位置正確性與限制（不可虛構建築/錯置地標/非台灣風格）、前中遠景
    層次、8K/電影級光影/miniature diorama style 質感、解剖正確/臉部清晰補強。
  - 路線變動（主視覺/起點/終點換點）時 narrative 會被自動清空，需重寫。
  - narrative 為空時 render-prompt fallback 舊版欄位拼接（scene_elements/action/
    expression 等欄位保留作撰寫素材）並警告。
  - 光線氛圍（lighting 欄位，織入 narrative）預設：柔和清晨明亮光線、清新藍天白雲
"""
from __future__ import annotations

import argparse
import sys

try:
    from jinja2 import Environment  # noqa: F401 — 驗證 jinja2 可用
except ImportError:
    print("[error] 缺少 jinja2，請安裝：pip install jinja2", file=sys.stderr)
    sys.exit(1)

from plan_lib.index_parser import cmd_parse_index, cmd_update_index
from plan_lib.mirror import (cmd_mirror_status, cmd_mirror_put, cmd_mirror_diff,
                             cmd_mirror_search, cmd_search_along_route)
from plan_lib.bayesian import (
    cmd_score_pool, cmd_compute, cmd_review, cmd_compose_better_attractions,
    cmd_verify_and_fix,
)
from plan_lib.csv_out import cmd_write_csv
from plan_lib.gpx import cmd_route, cmd_route_skeleton, cmd_gpx_save, cmd_gpx_waypoints
from plan_lib.render import cmd_render_prompt, cmd_render_md
from plan_lib.cover import cmd_render_cover_prompt
from plan_lib.dinner import (
    cmd_dinner_search, cmd_dinner_status,
    cmd_dinner_pool, cmd_dinner_review, cmd_dinner_render,
)
from plan_lib.hotel import (
    cmd_hotel_search, cmd_hotel_status,
    cmd_hotel_pool, cmd_hotel_review, cmd_hotel_render,
)
from plan_lib.places_api import cmd_refresh_details
from plan_lib.elevation import cmd_elevation


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help):
        sp = sub.add_parser(name, help=help)
        sp.add_argument("day", type=int)
        sp.set_defaults(func=fn)
        return sp

    add("parse-index",   cmd_parse_index,   "解析 index.md 第 N 天")
    add("update-index",  cmd_update_index,  "把 ORS 實際距離回寫 index.md")
    add("mirror-status", cmd_mirror_status, "顯示 dayN/map/（本地鏡像）現況")
    add("mirror-put",    cmd_mirror_put,    "[stdin] upsert 單筆 place 到本地鏡像")
    add("mirror-diff",   cmd_mirror_diff,   "[stdin] 比對本地鏡像 vs 線上最新")
    sp = add("mirror-search", cmd_mirror_search,
             "用 keyword 呼叫 Google Places API 並 upsert 到 dayN/map/")
    sp.add_argument("--keyword", required=True, help="搜尋關鍵字（例：7-ELEVEN 觀湖門市）")
    sp.add_argument("--csv-type", required=True,
                    help="便利商店 / 加油站 / 景點 / 起終點 / 餐廳大休 / 公共設施 / 綜合休息站")
    sp.add_argument("--target", default="candidates_not_selected",
                    help="places 或 candidates_not_selected（預設）")
    sp.add_argument("--bias", default=None,
                    help="locationBias 圓心 LAT,LNG（例：24.687,120.881）")
    sp.add_argument("--bias-radius", type=int, default=5000,
                    help="locationBias 圓半徑（公尺，預設 5000）")
    sp.add_argument("--max-results", type=int, default=1, help="取前 N 筆（預設 1）")
    sp = add("search-along-route", cmd_search_along_route,
             "沿 ORS 骨架/定稿路線用 Places API 找停靠點並 upsert 候選")
    sp.add_argument("--keyword", required=True, help="搜尋關鍵字（例：7-ELEVEN / 漁港 / 老街）")
    sp.add_argument("--csv-type", required=True,
                    help="便利商店 / 加油站 / 景點 / 餐廳大休 / 公共設施 / 綜合休息站")
    sp.add_argument("--detour-km", type=float, default=None,
                    help="離線繞路上限（km）；預設依 csv-type 帶入規則 C（便利商店0.5/餐廳1/景點2）")
    sp.add_argument("--max-results", type=int, default=20, help="每段取前 N 筆（沿路線搜上限 20）")
    sp.add_argument("--segments", type=int, default=1,
                    help="把路線切 N 段各搜一次再合併（長路線補給均勻覆蓋用，例 6）")
    sp = add("score-pool", cmd_score_pool, "對整個 mirror 候選池算 Bayesian")
    sp.add_argument("--quiet", action="store_true", help="只印統計，不印各點排名")
    sp = add("compute",  cmd_compute,  "套用 pool_scores 到 places.json")
    sp.add_argument("--quiet", action="store_true", help="不印每點分數表，只印 C/m 摘要")
    sp = add("review",   cmd_review,   "讀 pool_scores 顯示排名 + 替換建議")
    sp.add_argument("--quiet", action="store_true", help="只印替換建議，跳過完整排名表")
    sp = add("compose-better-attractions", cmd_compose_better_attractions,
             "從 pool_scores 自動產出 segments.json.better_attractions 表格")
    sp.add_argument("--overwrite", action="store_true", help="覆蓋既有非空 better_attractions")
    sp.add_argument("--dry-run",   action="store_true", help="只印預覽，不寫入 segments.json")
    add("write-csv",     cmd_write_csv,     "產 dayN_mymap.csv")
    add("route-skeleton", cmd_route_skeleton,
        "Routes API 只串 起點+必經景點+終點 → _plan/skeleton.json（沿線搜尋基礎）")
    add("route",         cmd_route,         "呼叫 Google Routes API 取整天路線 → dayN_route.gpx")
    add("gpx-save",      cmd_gpx_save,      "[stdin] 儲存外部 GPX（備援）")
    add("gpx-waypoints", cmd_gpx_waypoints, "離線備案：純航點 GPX")

    sp = add("refresh-details", cmd_refresh_details,
             "呼叫 Google Places API 刷新 places.json 可評分點位的 rating/hours")
    sp.add_argument("--with-reviews", action="store_true",
                    help="同時取得 reviews（Pro tier，$17/1000）；預設只取 Essentials")

    add("elevation", cmd_elevation,
        "從 GPX + Google Elevation API 計算精確爬升/下降")

    sp = add("dinner-search", cmd_dinner_search,
             "呼叫 Google Places API 搜尋終點周邊餐廳並 upsert 到 dinner_map/")
    sp.add_argument("--radius", type=int, default=3000, help="搜尋半徑（公尺，預設 3000）")
    sp.add_argument("--min-reviews", type=int, default=0,
                    help="排除留言數低於此值的點（預設 0 = 不過濾）")
    add("dinner-status", cmd_dinner_status, "顯示 dayN/dinner_map/ 鏡像現況")
    sp = add("dinner-pool", cmd_dinner_pool, "從 dinner_map/ 鏡像池算 Bayesian 選 top 5")
    sp.add_argument("--quiet", action="store_true", help="不印 19 筆排名表，只印 top 5 摘要")
    add("dinner-review", cmd_dinner_review, "顯示 dinner.json 排名")
    add("dinner-render", cmd_dinner_render, "產 dayN_dinner.md")

    sp = add("hotel-search", cmd_hotel_search,
             "呼叫 Google Places API 搜尋終點周邊住宿並 upsert 到 hotel_map/")
    sp.add_argument("--radius", type=int, default=3000, help="搜尋半徑（公尺，預設 3000）")
    sp.add_argument("--min-reviews", type=int, default=0,
                    help="排除留言數低於此值的點（預設 0 = 不過濾）")
    add("hotel-status", cmd_hotel_status, "顯示 dayN/hotel_map/ 鏡像現況")
    sp = add("hotel-pool", cmd_hotel_pool, "從 hotel_map/ 鏡像池算 Bayesian 選 top 5")
    sp.add_argument("--quiet", action="store_true", help="不印完整排名表，只印 top 5 摘要")
    add("hotel-review", cmd_hotel_review, "顯示 hotel.json 排名")
    add("hotel-render", cmd_hotel_render, "產 dayN_hotel.md")
    sp = add("render-prompt", cmd_render_prompt, "產 dayN_prompt.md")
    sp.add_argument("--no-sync", action="store_true",
                    help="跳過自動同步，僅以現有 poster_vars.json 渲染")
    sp = add("render-md",     cmd_render_md,     "產 dayN.md")
    sp.add_argument("--force", action="store_true",
                    help="略過 Phase 0-3 / 3.5 / 4 全量新鮮度預檢")
    add("verify-and-fix", cmd_verify_and_fix,
        "依序重跑 Phase 0-3/3.5/4 機械步驟讓 render-md 通過預檢")

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

# 單車環島每日路線規劃
單日路線規劃改由 `scripts/plan.py` 取代舊 skill。指令流程與 Claude 需遵守的選點 / 搜尋關鍵字 / API 節流 / 撤退方案 / 主視覺等規則，全部寫在 `scripts/plan.py` 檔頭的模組 docstring，請執行前先閱讀。常用流程：
1. **Phase 0**：`python3 scripts/plan.py parse-index N`
2. **Phase 1（路線優先選點）**：
   1. `route-skeleton N`：ORS 只串「起點+必經景點+終點」算出**骨架最佳路線**（產 `_plan/skeleton.json` 含 geometry 折線）。檢查輸出的必經點座標是否合理（模糊地名如「通霄海線」可手動修 skeleton.json）。
   2. `search-along-route N --keyword "…" --csv-type … [--segments K]`：沿這條真實路線用 Places API (New) searchAlongRoute 找景點/便利商店/餐廳大休候選，依「離線繞路距離」自動過濾（便利商店≤0.5/餐廳≤1/景點≤2km），輸出每點沿路里程。長路線（>60km）用 `--segments 6` 左右切段各搜再合併，避免結果群聚頭尾。景點/便利商店/餐廳大休各搜一次。
   3. Claude 從 candidates 依**沿路里程**挑選間距均勻的停靠點 → 編寫 `dayN/_plan/places.json`（必經景點必須含；便利商店每 ~20-25km 一個；午餐放中段）。
   4. `refresh-details N`（批量刷新評分）→ `compute N` → `write-csv N`。
   > 舊作法 `mirror-search`（具名單點搜）保留為 fallback，用於 searchAlongRoute 漏掉的特定點。
3. **Phase 2**：`route N`（需 `ORS_API_KEY` 環境變數；離線時改用 `gpx-waypoints N`）
4. **Phase 3**：`render-prompt N`（Claude 先補 `_plan/poster_vars.json` 主視覺欄位）
5. **Phase 3.5（晚餐）**：`dinner-search N`（直接呼叫 Google Places API，zh-TW 語言碼，自動 upsert dinner_map/，過濾非餐廳類）→ `dinner-pool N`（產 `_plan/dinner.json` 並寫入 `source_endpoint_place_id` 簽章）。需 `GOOGLE_PLACES_API_KEY`，不走 MCP。
6. **Phase 3.6（住宿）**：`hotel-search N`（直接呼叫 Google Places API，zh-TW 語言碼，自動 upsert hotel_map/）→ `hotel-pool N`（產 `_plan/hotel.json` 帶 `source_endpoint_place_id` 簽章）→ `hotel-render N`（產 `dayN_hotel.md`）。Bayesian top 5；`render-md` 預檢會檢查 `hotel.json` 新鮮度與終點簽章。需 `GOOGLE_PLACES_API_KEY`，不走 MCP。
7. **Phase 4**：Claude 補 `dayN/_plan/segments.json`（段落、魚骨圖、注意事項、`better_attractions` 備案表格）→ `render-md N`

> ⚠️ **重規劃某天 = 直接跑 `render-md N`（自癒）**：`render-md` 渲染前會全量檢查 Phase 0-3/3.5/3.6/4 所有產出 mtime 是否 ≥ `places.json`、`dinner.json` / `hotel.json` 的 `source_endpoint_place_id` 是否對應目前終點。**偵測到陳舊不再 hard-fail，而是自動跑 cascade 重生所有機械產物**（compute → route → write-csv → render-prompt → dinner-pool → hotel-pool → compose-better-attractions）後再渲染；只在自癒後仍有需人腦判斷的缺口（如該天確實無備選景點可填 `better_attractions`）才中止並列出。所以改完 `places.json` 想重規劃整天，跑 `render-md N` 一個指令即可，不必逐階段手動重跑。`--force` 完全略過自癒與檢查直接渲染；`verify-and-fix N` ≈「強制重生全部 + render-md --force」。

## 禁用 MCP 工具
- **禁用 `mcp__openroute-mcp__*` 全部工具**。OpenRouteService 已改由 `scripts/plan.py route` 子命令直接走 HTTPS（`ORS_API_KEY` 環境變數），不再經 MCP。即便 session 列出這些 deferred tools 也不要呼叫；要產路線一律用 `python3 scripts/plan.py route N`，離線改 `gpx-waypoints N`。

## Place Details 走 API
- 一律用 `python3 scripts/plan.py refresh-details N`，直接呼叫 Google Places API (New)。
- 只取 Essentials 欄位（rating / total_ratings / opening_hours），不含 reviews，回傳精簡 JSON 並 upsert 回 mirror。
- 需設定 `GOOGLE_PLACES_API_KEY` 環境變數（前 10,000 次/月免費）。
- 加 `--with-reviews` 同時取 reviews（Pro tier，$17/1000，前 5,000 次免費）。
- 便利商店 / 加油站 **禁止**呼叫 refresh-details。

# cycling-cover-poster
- **cycling-cover-poster** (`.claude/skills/cycling-cover-poster/SKILL.md`) - 單車環島總覽封面海報提示詞產生。Trigger: `/cycling-cover-poster`
When the user types `/cycling-cover-poster`, invoke the Skill tool with `skill: "cycling-cover-poster"` before doing anything else.

# mermaid-ishikawa-fishbone
- **mermaid-ishikawa-fishbone** (`.claude/skills/mermaid-ishikawa-fishbone/SKILL.md`) - 用 Mermaid ishikawa-beta 語法製作魚骨圖。Trigger: `/mermaid-ishikawa-fishbone`
When the user types `/mermaid-ishikawa-fishbone`, invoke the Skill tool with `skill: "mermaid-ishikawa-fishbone"` before doing anything else.

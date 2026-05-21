# 單車環島每日路線規劃
單日路線規劃改由 `scripts/plan.py` 取代舊 skill。指令流程與 Claude 需遵守的選點 / 搜尋關鍵字 / API 節流 / 撤退方案 / 主視覺等規則，全部寫在 `scripts/plan.py` 檔頭的模組 docstring，請執行前先閱讀。常用流程：
1. **Phase 0**：`python3 scripts/plan.py parse-index N`
2. **Phase 1**：Claude 透過 google-maps MCP 補搜停靠點 → `mirror-put` 寫回快取 → 編寫 `dayN/_plan/places.json` → `refresh-details N`（批量刷新評分）→ `compute N` → `write-csv N`
3. **Phase 2**：`route N`（需 `ORS_API_KEY` 環境變數；離線時改用 `gpx-waypoints N`）
4. **Phase 3**：`render-prompt N`（Claude 先補 `_plan/poster_vars.json` 主視覺欄位）
5. **Phase 3.5**：Claude 用 MCP 搜尋終點周邊餐廳 → `dinner-put` → `dinner-pool N`（產 `_plan/dinner.json` 並寫入 `source_endpoint_place_id` 簽章）
6. **Phase 4**：Claude 補 `dayN/_plan/segments.json`（段落、魚骨圖、注意事項、`better_attractions` 備案表格）→ `render-md N`

> ⚠️ **重做 = 全部重來**：`render-md` 執行前會全量預檢 Phase 0-3/3.5/4 所有產出 mtime 是否 ≥ `places.json`、`dinner.json` 的 `source_endpoint_place_id` 是否對應目前終點。任一不通過就 hard-fail，要求對應指令重跑。確定該天不需要某區塊時可加 `--force` 略過。

## 禁用 MCP 工具
- **禁用 `mcp__openroute-mcp__*` 全部工具**。OpenRouteService 已改由 `scripts/plan.py route` 子命令直接走 HTTPS（`ORS_API_KEY` 環境變數），不再經 MCP。即便 session 列出這些 deferred tools 也不要呼叫；要產路線一律用 `python3 scripts/plan.py route N`，離線改 `gpx-waypoints N`。

## Place Details 改用本地 API 呼叫
- **優先使用 `python3 scripts/plan.py refresh-details N`** 取代 MCP `place_details`。
- 此命令直接呼叫 Google Places API (New)，只取 Essentials 欄位（rating / total_ratings / opening_hours），不含 reviews，回傳精簡 JSON 並 upsert 回 mirror。
- 需設定 `GOOGLE_PLACES_API_KEY` 環境變數（前 10,000 次/月免費）。
- 加 `--with-reviews` 同時取 reviews（Pro tier，$17/1000，前 5,000 次免費）。
- **MCP `place_details` 仍可作為 fallback**：無 API key 或需要即時查看單一地點評論時使用。
- 便利商店 / 加油站 仍然**禁止**呼叫 place_details 或 refresh-details。

# cycling-cover-poster
- **cycling-cover-poster** (`.claude/skills/cycling-cover-poster/SKILL.md`) - 單車環島總覽封面海報提示詞產生。Trigger: `/cycling-cover-poster`
When the user types `/cycling-cover-poster`, invoke the Skill tool with `skill: "cycling-cover-poster"` before doing anything else.

# mermaid-ishikawa-fishbone
- **mermaid-ishikawa-fishbone** (`.claude/skills/mermaid-ishikawa-fishbone/SKILL.md`) - 用 Mermaid ishikawa-beta 語法製作魚骨圖。Trigger: `/mermaid-ishikawa-fishbone`
When the user types `/mermaid-ishikawa-fishbone`, invoke the Skill tool with `skill: "mermaid-ishikawa-fishbone"` before doing anything else.

# 單車環島每日路線規劃
單日路線規劃改由 `scripts/plan.py` 取代舊 skill。指令流程與 Claude 需遵守的選點 / 搜尋關鍵字 / API 節流 / 撤退方案 / 主視覺等規則，全部寫在 `scripts/plan.py` 檔頭的模組 docstring，請執行前先閱讀。常用流程：
1. **Phase 0**：`python3 scripts/plan.py parse-index N`
2. **Phase 1**：Claude 透過 google-maps MCP 補搜停靠點 → `mirror-put` 寫回快取 → 編寫 `dayN/_plan/places.json` → `compute N` → `write-csv N`
3. **Phase 2**：`route N`（需 `ORS_API_KEY` 環境變數；離線時改用 `gpx-waypoints N`）
4. **Phase 3**：`render-prompt N`（Claude 先補 `_plan/poster_vars.json` 主視覺欄位）
5. **Phase 3.5**：Claude 用 MCP 搜尋終點周邊餐廳 → `dinner-put` → `dinner-pool N`（產 `_plan/dinner.json` 並寫入 `source_endpoint_place_id` 簽章）
6. **Phase 4**：Claude 補 `dayN/_plan/segments.json`（段落、魚骨圖、注意事項、`better_attractions` 備案表格）→ `render-md N`

> ⚠️ **重做 = 全部重來**：`render-md` 執行前會全量預檢 Phase 0-3/3.5/4 所有產出 mtime 是否 ≥ `places.json`、`dinner.json` 的 `source_endpoint_place_id` 是否對應目前終點。任一不通過就 hard-fail，要求對應指令重跑。確定該天不需要某區塊時可加 `--force` 略過。

## 禁用 MCP 工具
- **禁用 `mcp__openroute-mcp__*` 全部工具**。OpenRouteService 已改由 `scripts/plan.py route` 子命令直接走 HTTPS（`ORS_API_KEY` 環境變數），不再經 MCP。即便 session 列出這些 deferred tools 也不要呼叫；要產路線一律用 `python3 scripts/plan.py route N`，離線改 `gpx-waypoints N`。

# cycling-cover-poster
- **cycling-cover-poster** (`.claude/skills/cycling-cover-poster/SKILL.md`) - 單車環島總覽封面海報提示詞產生。Trigger: `/cycling-cover-poster`
When the user types `/cycling-cover-poster`, invoke the Skill tool with `skill: "cycling-cover-poster"` before doing anything else.

# mermaid-ishikawa-fishbone
- **mermaid-ishikawa-fishbone** (`.claude/skills/mermaid-ishikawa-fishbone/SKILL.md`) - 用 Mermaid ishikawa-beta 語法製作魚骨圖。Trigger: `/mermaid-ishikawa-fishbone`
When the user types `/mermaid-ishikawa-fishbone`, invoke the Skill tool with `skill: "mermaid-ishikawa-fishbone"` before doing anything else.

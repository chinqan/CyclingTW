# 單車環島每日路線規劃
單日路線規劃改由 `scripts/plan.py` 取代舊 skill。指令流程與 Claude 需遵守的選點 / 搜尋關鍵字 / API 節流 / 撤退方案 / 主視覺等規則，全部寫在 `scripts/plan.py` 檔頭的模組 docstring，請執行前先閱讀。常用流程：
1. `python3 scripts/plan.py parse-index N`
2. Claude 透過 google-maps MCP 補搜停靠點 → `mirror-put` 寫回快取 → 編寫 `dayN/_plan/places.json`
3. `compute N` → `write-csv N` → `gpx-split-plan N` → 對每段呼叫 openroute MCP → `gpx-append N --leg i` → `gpx-merge N`
4. Claude 補 `dayN/_plan/segments.json`（段落、魚骨圖、注意事項）
5. `render-prompt N` → `render-md N`

# cycling-cover-poster
- **cycling-cover-poster** (`.claude/skills/cycling-cover-poster/SKILL.md`) - 單車環島總覽封面海報提示詞產生。Trigger: `/cycling-cover-poster`
When the user types `/cycling-cover-poster`, invoke the Skill tool with `skill: "cycling-cover-poster"` before doing anything else.

# mermaid-ishikawa-fishbone
- **mermaid-ishikawa-fishbone** (`.claude/skills/mermaid-ishikawa-fishbone/SKILL.md`) - 用 Mermaid ishikawa-beta 語法製作魚骨圖。Trigger: `/mermaid-ishikawa-fishbone`
When the user types `/mermaid-ishikawa-fishbone`, invoke the Skill tool with `skill: "mermaid-ishikawa-fishbone"` before doing anything else.

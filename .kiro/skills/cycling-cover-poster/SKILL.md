---
name: cycling-cover-poster
description: 產生單車環島封面海報提示詞。當使用者要求「整份計劃海報」、「10天環島總海報」、「封面海報」、「整份行程總覽海報」時觸發。執行 scripts/plan.py render-cover-prompt 產出提示詞。
---

# Skill：單車環島封面海報提示詞產生

## 觸發
使用者要求「整份計劃海報」、「10 天環島總海報」、「封面海報」、「整份行程總覽海報」時觸發。
（單日海報請改用 `plan.py render-prompt N`，不在本 skill 範圍。）

## 執行
所有規則（四極點防呆、構圖、地理正確性、視覺風格、文字規範、10 個必含段落）已寫死進腳本與模板。SSOT：

- 邏輯：`scripts/plan_lib/cover.py`
- 模板：`scripts/templates/cover_prompt.md.j2`
- 四極點視覺查表：`scripts/cover_pole_visuals.json`
- 資料來源：`index.md`（10 天 table）

指令：

```bash
python3 scripts/plan.py render-cover-prompt              # 預設直式 2:3
python3 scripts/plan.py render-cover-prompt --aspect horizontal   # 橫式 3:2
python3 scripts/plan.py render-cover-prompt --no-sync    # 不重抽 index.md，沿用既有 cover_vars.json
```

產出：
- `output/imagegen/cyclingtw-cover_prompt.md`（最終提示詞）
- `output/imagegen/cover_vars.json`（中間變數，可手動編輯 `subtitle` / `lighting` / `main_character` 後再 `--no-sync` 重渲）

## 改規則時要動哪裡

| 想改的東西 | 改哪個檔 |
|---|---|
| 四極點視覺描述 | `scripts/cover_pole_visuals.json` |
| 構圖、文字規範、必含段落 | `scripts/templates/cover_prompt.md.j2` |
| 抽資料邏輯、預設值 | `scripts/plan_lib/cover.py` |
| 行程本身（天數、起終點、距離） | `index.md` |

## 跨 AI 工具
邏輯都在 Python 腳本，任何能執行 shell 的 AI 工具都能用同一條指令；複製本 shim 到該工具的 skills 目錄即可，內容無需更動。

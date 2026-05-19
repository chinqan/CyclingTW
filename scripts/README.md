# plan.py — 單車環島每日路線規劃腳本

搭配 [`cycling-day-route-planning`](../.claude/skills/cycling-day-route-planning/SKILL.md) skill 使用的半自動工具。Claude 在對話中呼叫 MCP（Google Maps / OpenRoute）取得資料並做判斷，腳本則負責所有機械步驟（**本地鏡像維護**、Bayesian 計算、CSV/GPX/Markdown 產出）。

> **重要觀念：`dayN/map/` 是「Google Maps 的本地鏡像 DB」，不是「省 API 用的快取」。**
> 線上每次搜尋仍要打 MCP，把 fresh 資料 upsert 回本地；本地的價值是在離線時仍能完整分析地圖資料、並保留歷史比對基準。

---

## 目錄

- [設計理念](#設計理念)
- [安裝與環境](#安裝與環境)
- [目錄結構](#目錄結構)
- [中間檔案 JSON Schema](#中間檔案-json-schema)
- [完整工作流（一天從零到產出）](#完整工作流一天從零到產出)
- [本地鏡像 DB 與離線使用](#本地鏡像-db-與離線使用)
- [子命令詳細參考](#子命令詳細參考)
- [GPX 截斷與分段策略](#gpx-截斷與分段策略)
- [常見錯誤與排除](#常見錯誤與排除)

---

## 設計理念

| 原則 | 說明 |
|:---|:---|
| **腳本不打 API** | 所有 Google Maps / OpenRoute 呼叫都由 Claude 透過 MCP 工具發出，腳本只接收 JSON / GPX |
| **本地鏡像 (write-through)** | 線上每次搜尋都要寫回 `dayN/map/`，**有就 upsert 成最新值**。本地會越用越完整，斷網也能分析 |
| **先 diff 後 put** | 每次寫回前先用 `mirror-diff` 看 rating / 評論數有沒有變，**有變動要顯示給人看**再 upsert |
| **Bayesian 動態重算** | C（候選池平均）與 m（評論數中位數）皆從當前點位重算，禁止硬編碼 |
| **不變式驗證** | CSV 終點要對應 `index.md` 目的地、候選池規模要達標，違反時警告 |
| **冪等** | 重跑同一命令結果一致，輸出檔可隨時覆蓋重生 |
| **分階段可獨立執行** | 13 個子命令互相獨立，可單獨除錯 |

---

## 安裝與環境

### 需求

- Python 3.8+
- `jinja2` 套件
- Claude Code 中啟用以下 MCP server：
  - `google-maps`（`mcp__google-maps__maps_search_places`、`mcp__google-maps__maps_place_details`）
  - `openroute-mcp`（`mcp__openroute-mcp__create_route_from_to`）

### 安裝

```bash
pip install jinja2
```

### 驗證

```bash
python3 scripts/plan.py --help
```

---

## 目錄結構

```
CyclingTW/
├── index.md                           # 10 天環島總覽（手寫，含每日起終點/距離/景點）
├── prompt.md                          # 海報提示詞主體骨架
├── 主角.png                            # 人物/單車參考圖
│
├── scripts/
│   ├── plan.py                        # ⭐ 主腳本
│   ├── README.md                      # 本檔
│   └── templates/
│       ├── prompt.md.j2               # 海報提示詞模板
│       └── day.md.j2                  # 每日 Markdown 模板
│
└── day1/                              # 每天一個資料夾
    ├── _plan/                         # ← 由 Claude 填寫的中間檔
    │   ├── config.json                # parse-index 產出
    │   ├── places.json                # 點位順序 + Bayesian 結果
    │   ├── poster_vars.json           # 海報 5 變數
    │   ├── segments.json              # 段落敘述/魚骨圖/注意事項
    │   ├── gpx_split.json             # gpx-split-plan 產出
    │   └── gpx_leg_*.gpx              # 每段 openroute 結果
    │
    ├── map/                           # ← Google Maps 本地鏡像 DB
    │   ├── index.json                 # 索引（含入選/未入選名單）
    │   └── ChIJxxx....json            # 每個 place_id 一個檔（write-through 更新）
    │
    └── day1_*.{csv,gpx,md,prompt.md}  # ← 最終產出（4 份）
```

---

## 中間檔案 JSON Schema

腳本在 `_plan/` 下讀寫 6 種 JSON。手動或讓 Claude 填寫時請對齊以下結構。

### `_plan/config.json`（自動產出）

由 `parse-index` 從 `index.md` 解析而來，**不需要手動編輯**。

```json
{
  "day": 1,
  "origin": "台北蘆洲柳堤公園",
  "destination": "新竹 / 竹南",
  "distance_km_range": [80, 100],
  "main_route_text": "台15線 → 台61線 (西濱公路)",
  "must_visit_landmarks": ["八里左岸", "竹圍漁港", "永安漁港", "南寮漁港"]
}
```

### `_plan/places.json`（**Claude 編輯**）

決定當日點位的順序、類型與備註。Bayesian 分數由 `compute` 自動填入。

```json
{
  "day": 1,
  "route_name": "西濱海岸線追風之旅",
  "places": [
    {
      "place_id": "ChIJ7Ws-1bOoQjQRehrUbGzlo1A",
      "name_zh": "蘆洲柳堤公園",
      "search_keyword": "新北市蘆洲區廣榮路與長樂路口柳堤公園",
      "csv_type": "起終點",
      "rating": 4.3,
      "total_ratings": 1407,
      "location": {"lat": 25.088225, "lng": 121.4626333},
      "note": "早上07:00出發 河濱起點"
    }
    // ... 依騎乘順序排列
  ]
}
```

**`csv_type` 必須為以下之一**：

| 值 | 是否需評分 | 是否參與 Bayesian |
|:---|:---:|:---:|
| `起終點` | ✓ | ✓ |
| `景點` | ✓ | ✓ |
| `餐廳大休` | ✓ | ✓ |
| `便利商店` | ✗ | ✗ |
| `加油站` | ✗ | ✗ |
| `綜合休息站` | ✗ | ✗ |
| `公共設施` | ✗ | ✗ |

### `_plan/poster_vars.json`（**Claude 編輯**）

海報提示詞模板的 5 個置換變數。

```json
{
  "day": 1,
  "origin_label": "新北蘆洲",
  "destination_label": "苗栗竹南",
  "distance_range": "約 100–110 公里",
  "subtitle": "西濱海岸線追風之旅",

  "orientation": "vertical_portrait_2_3",  // 或 horizontal_landscape_3_2

  "main_visual": {
    "location_desc": "新北市八里「八里左岸自行車道」",
    "scene_elements": "...",
    "action": "...",
    "expression": "..."
  },
  "small_avatar": {
    "location_desc": "新北市蘆洲「蘆洲柳堤公園」",
    "scenario": "...",
    "action": "...",
    "expression": "..."
  },

  "geographic_notes": "...",
  "allowed_elements": "...",
  "composition": "...",
  "lighting": "柔和清晨明亮光線、清新藍天白雲",
  "enhancement": "..."
}
```

### `_plan/segments.json`（**Claude 編輯**）

`dayN.md` 的所有自然語言內容。

```json
{
  "origin_short": "蘆洲柳堤公園",
  "destination_short": "竹南車站",
  "total_ascent_desc": "全程幾乎平坦...",
  "main_route_desc": "二重疏洪道 ➔ 八里左岸 ➔ 台15線 ➔ 台61線 ➔ 竹南",
  "gmaps_dir_url": "https://www.google.com/maps/dir/?...",

  "ishikawa": "ishikawa-beta\n    Day 1 完騎 竹南車站 約105km\n    第五段...",

  "segments": [
    {
      "cn_n": "一",
      "title": "蘆洲柳堤公園 → 水牛坑越野場地",
      "subtitle": "出發熱身段",
      "distance_km": 28,
      "condition": "蘆洲出發沿二重疏洪道...",
      "stops": [
        {
          "emoji": "🚀",
          "time_or_label": "07:00",  // 可為空字串
          "name": "蘆洲柳堤公園",
          "location_desc": "起點，km 0",  // 可為空字串
          "desc": "有公廁與停車場..."
        }
      ]
    }
  ],

  "notes": [
    "**強風防範**：...",
    "**補給空窗**：..."
  ]
}
```

### `_plan/gpx_split.json`（自動產出）

由 `gpx-split-plan` 產出，列出每段路由請求的座標。

### `_plan/gpx_leg_<i>.gpx`（自動產出）

由 `gpx-append --leg <i>` 儲存的每段 openroute MCP 回應。

---

## 完整工作流（一天從零到產出）

以下示範用腳本完整跑 Day 2。所有命令在 `CyclingTW/` 根目錄執行。

### Phase 0：起手式

```bash
# 1. 從 index.md 解析 Day 2 設定
python3 scripts/plan.py parse-index 2

# 2. 查看 day2/map/ 本地鏡像現況（如果是新天會說 0 筆）
python3 scripts/plan.py mirror-status 2
```

### Phase 1：建候選池 + 寫 CSV

#### 1-1. **每次都要先搜 MCP**（即使本地已有資料）

Claude 在對話中呼叫 MCP 搜尋，每個必經景點廣搜 3–5 個候選：

```python
# Claude 端（透過 MCP 工具）
mcp__google-maps__maps_search_places(
    query="後龍好望角 苗栗 景點",
    locationBias={"latitude": 24.642, "longitude": 120.766, "radius": 3000}
)
```

針對 `景點 / 起終點 / 餐廳大休` 還要再呼叫 `place_details` 取得精確評分與評論數。`便利商店 / 加油站` 只用搜尋結果，**不要**呼叫 details（這是 SOP 規範，省 API 額度的方式是「不查多餘資訊」，不是「跳過呼叫」）。

#### 1-2. 先 diff 看本地與線上差異

```bash
echo '[
  {"place_id":"ChIJ...","rating":4.4,"total_ratings":17800},
  {"place_id":"ChIJ...","rating":4.8,"total_ratings":21950}
]' | python3 scripts/plan.py mirror-diff 2
```

輸出會列出每筆「本地 R/V」vs「線上 R/V」與差異欄。常見三種狀況：

- `—`：完全一致
- `reviews 17664→17800`：評論數已更新，需要 upsert
- `⭐ 新地點`：本地沒有，第一次寫入

#### 1-3. 不管有無差異都 upsert 寫回本地（write-through）

```bash
echo '{
  "place_id": "ChIJ...",
  "name_zh": "後龍好望角風景區",
  "csv_type": "景點",
  "rating": 4.4,
  "total_ratings": 17800,
  "location": {"lat": 24.601974, "lng": 120.731191},
  "source": "search_2026-05-20",
  "target": "places",
  "note": "苗栗海岸最美觀景台"
}' | python3 scripts/plan.py mirror-put 2
```

`mirror-put` 是 **upsert** — 同 `place_id` 直接覆寫成最新值。`target` 欄位：
- `"places"`：入選當日 CSV
- `"candidates_not_selected"`：記錄為備案（未來可比對參考）

#### 1-4. 檢查候選池規模

```bash
python3 scripts/plan.py mirror-status 2
# 期望輸出:
#   [起終點] (2) ...
#   [景點] (≥5) ...
#   [餐廳大休] (≥2) ...
#   [便利商店] (3-4) ...
```

#### 1-5. 編寫 `_plan/places.json`（手動決定當日順序）

從 `dayN/map/index.json` 的 `places` 陣列裡，把要列入 CSV 的點按**騎乘順序**抄到 `_plan/places.json`，並補上 `search_keyword` 和 `note`（這兩個是 CSV 專用欄位，本地鏡像沒有）。參考 `day1/_plan/places.json` 當範本。

#### 1-6. 計算 Bayesian 並產 CSV

```bash
python3 scripts/plan.py compute 2       # 從 mirror 同步最新值 → 算 C/m/score → 寫回 places.json
python3 scripts/plan.py write-csv 2     # 產 dayN_mymap.csv，並警告終點不一致
```

> ⚠️ **`compute` 會自動從 `dayN/map/` 拉最新 rating / total_ratings**：因此 `mirror-put` 後直接跑 `compute` 即可，不需要手動更新 `places.json` 內的數值。

#### 1-7.（可選）偵測是否需要替換點位

當 mirror 累積新資料後，**入選與未入選的排名可能翻轉**。`review` 對整個候選池重評，提示是否該換點：

```bash
python3 scripts/plan.py review 2
```

輸出範例：

```
[餐廳大休]
  ★ 江戶壽司            R=4.8 V=  534 → 4.42
    海晏漁村料理         R=4.6 V= 1500 → 4.44      ← 因評論數成長翻轉

⚠️  偵測到可能的替換：
  [餐廳大休] 考慮把 江戶壽司 (4.42) 換成 海晏漁村料理 (4.44)  +0.02
```

`★` 標記目前入選的點位。**`review` 不會自動改 places.json**，由使用者判斷地理合理性後手動換 place_id 再重跑 `compute` + `write-csv`。

### Phase 2：GPX

短路線（< 50 km）或不需轉彎指示時直接用備案：

```bash
python3 scripts/plan.py gpx-waypoints 2
```

長路線（> 50 km）想要完整轉彎指示時用分段流程：

```bash
# 1. 規劃分段
python3 scripts/plan.py gpx-split-plan 2 --max-waypoints 4

# 2. Claude 對每段呼叫 openroute MCP（讀 _plan/gpx_split.json 取座標）
#    每段把回應 pipe 給 gpx-append
echo "$gpx_text_leg1" | python3 scripts/plan.py gpx-append 2 --leg 1
echo "$gpx_text_leg2" | python3 scripts/plan.py gpx-append 2 --leg 2
echo "$gpx_text_leg3" | python3 scripts/plan.py gpx-append 2 --leg 3

# 3. 合併
python3 scripts/plan.py gpx-merge 2
```

### Phase 3：海報提示詞

**手寫 `_plan/poster_vars.json`**：主視覺從 CSV `bayesian_score` 最高的景點選；夕陽景點（如高美濕地）要把 `lighting` 改成金色暖光。

```bash
python3 scripts/plan.py render-prompt 2
```

### Phase 4：Markdown

**手寫 `_plan/segments.json`**：依照五段配速、ishikawa 魚骨圖規範填寫（參考 `day1/_plan/segments.json`）。

```bash
python3 scripts/plan.py render-md 2
```

---

## 本地鏡像 DB 與離線使用

### 為什麼這不是「快取」

傳統「快取」的語義是「**有就跳過 API、沒有再打**」，目的是降低延遲與成本。

`dayN/map/` **不是這個用途**：

| | 傳統快取 | `dayN/map/` 本地鏡像 |
|:---|:---|:---|
| 線上時要打 API 嗎？ | 有快取就不打 | **永遠打**，拿 fresh data |
| 寫入時機 | API 回應後第一次寫入 | **每次回應都 upsert**（write-through）|
| 過期處理 | TTL 過期就失效 | 沒有過期概念，本地永遠跟上游同步 |
| 目的 | 省 API call、加速 | **離線分析能力 + 歷史比對基準** |

### 線上工作模式（標準）

```
MCP search → mirror-diff（看變動）→ mirror-put（upsert）→ 編 places.json
```

**每次規劃當日路線時，所有需要的點位都應該重搜一次**。`mirror-diff` 是讓你**看見變動**（例如某景點評論從 17,664 漲到 17,800）的機會，不是讓你跳過搜尋。

### 離線工作模式（網路斷開）

當網路不通、MCP 無法使用時：

```bash
# 1. 確認本地資料齊全
python3 scripts/plan.py mirror-status 2

# 2. 從 map/index.json 抄點位到 _plan/places.json
#    用本地最後一次的 rating / total_ratings
cat day2/map/index.json | python3 -m json.tool

# 3. 後續流程完全相同
python3 scripts/plan.py compute 2
python3 scripts/plan.py write-csv 2
python3 scripts/plan.py gpx-waypoints 2    # GPX 無 openroute，用航點 fallback
python3 scripts/plan.py render-prompt 2    # 需要先手寫 poster_vars.json
python3 scripts/plan.py render-md 2        # 需要先手寫 segments.json
```

離線時的「資料新鮮度」就停在本地最後一次 upsert 的時間點。對單車環島規劃來說（景點評論數變化緩慢），這完全可用。

### 比對歷史基準

因為 `mirror-put` 是 upsert（覆寫），本地不會保留歷史。如果想保留歷史快照，建議在重要里程碑時 `git commit` 整個 `map/` 目錄，用 git 取代版本管理。

範例：

```bash
git add day2/map/
git commit -m "snapshot: day2 map data 2026-05-20"
# 半年後比對
git log --oneline -- day2/map/
git diff <old-sha> -- day2/map/ChIJ2ffC3wEOaTQR-YuV-iIXELk.json
```

---

## 子命令詳細參考

通用語法：

```bash
python3 scripts/plan.py <subcommand> <day_number> [options]
```

### `parse-index N`

從 `index.md` 表格抽出第 N 天設定，寫入 `dayN/_plan/config.json` 並印到 stdout。

**輸入**：`index.md`
**輸出**：`dayN/_plan/config.json`
**參數**：無

### `mirror-status N`

顯示 `dayN/map/`（本地鏡像）現況：
- 個別 JSON 檔案數
- `index.json` 中已入選與未入選的點位數
- 各類型 (`csv_type`) 點位列表
- 候選池規模警告（景點 < 5 或餐廳 < 2 時警示）

**輸入**：`dayN/map/`
**輸出**：stdout 報告

> 注意：這個命令只是「看本地有什麼」，不是「決定要不要打 API」的依據。線上時不管本地有沒有都應該重搜。

### `mirror-put N`

從 stdin 讀單筆 place JSON，**upsert** 到本地鏡像並同步 `index.json`。同 `place_id` 直接覆寫成最新值。

**stdin schema**：

```json
{
  "place_id": "ChIJ...",          // 必填
  "name_zh": "中文名稱",          // 必填
  "csv_type": "景點",             // 必填
  "rating": 4.4,                  // 景點/起終點/餐廳大休 必填
  "total_ratings": 17664,         // 同上
  "location": {"lat": 24.6, "lng": 120.7},
  "source": "search_2026-05-20",  // 來源標記
  "note": "備註",
  "target": "places"              // 或 "candidates_not_selected"
}
```

**輸出**：`dayN/map/<place_id>.json` + 更新 `dayN/map/index.json`

### `mirror-diff N`

從 stdin 讀**剛從 MCP 拿到的 fresh 資料**，逐筆與本地鏡像比對 rating / total_ratings 是否有變動。

**典型流程**：MCP 搜尋 → `mirror-diff` 看變動 → `mirror-put` 寫回（不管有沒有變都寫，保持本地最新）。

**stdin**：陣列或單一物件，包含 `place_id` / `rating` / `total_ratings`

**輸出**：表格列出每筆的本地值 vs 線上值與差異

### `compute N`

讀 `dayN/_plan/places.json` 取得 place_id 與排序，然後：

1. **從 `dayN/map/<pid>.json` 拉最新 rating / total_ratings / location / name_zh**（mirror 是 SoT）
2. 重算：
   - **`bayesian_C`** = 候選池內 `rating` 平均
   - **`bayesian_m`** = 候選池內 `total_ratings` 中位數（最低採用 100，避免低樣本失真）
   - 每個點位的 **`bayesian_score`** = `(v/(v+m)) * R + (m/(v+m)) * C`
3. 只對 `csv_type ∈ {景點, 起終點, 餐廳大休}` 的點位計算
4. 寫回 `places.json`

**輸入**：`dayN/_plan/places.json` + `dayN/map/*.json`
**輸出**：寫回 `places.json` + stdout 表格

> 重要：`compute` 是 **write-back from mirror**，這保證 `mirror-put` 之後跑 `compute` 一定用到最新資料。`places.json` 內的數值會被 mirror 覆寫掉，不要手動編輯 rating / total_ratings 欄位（會被下次 compute 蓋掉）。

### `review N`

對整個候選池（`mirror.places` + `mirror.candidates_not_selected`）重評，偵測排名翻轉：

1. 用整個候選池算 C 和 m（樣本量更大、更穩定）
2. 按 `csv_type` 分組排名顯示
3. `★` 標記目前在 `places.json` 內的入選點位
4. 比較「最差入選」vs「最佳未入選」，若後者較高則提示替換

**典型使用情境**：
- 隔一段時間想看評分是否有變動 → `mirror-put` 批次更新 → `review` 看排名變化
- 規劃前期確認是否選對點 → 比較入選 vs 備案

**不變式**：
- `起終點` 由 `index.md` 固定，**不參與替換建議**
- 替換建議只看 Bayesian 分數，**不考慮地理位置順路性**，使用者要自行判斷

**輸入**：`dayN/_plan/places.json` + `dayN/map/`
**輸出**：stdout 排名表 + 替換建議

### `write-csv N`

讀 `dayN/_plan/places.json` + `config.json`，產出 `dayN_mymap.csv`。

**不變式檢查**：
- CSV 最後一筆的 `name_zh` 應與 `config.json.destination` 相符，否則 stderr 警告

**輸入**：`dayN/_plan/places.json` + `dayN/_plan/config.json`
**輸出**：`dayN/dayN_mymap.csv`

### `gpx-save N`

從 stdin 讀 openroute MCP 回應（含 envelope），自動剝離 `[Resource from ...]` 前綴，存為 `dayN_route.gpx`。

**輸入**：stdin GPX 文字
**輸出**：`dayN/dayN_route.gpx`

### `gpx-waypoints N`

無 openroute MCP 時的備案：直接從 `places.json` 座標產出純航點 GPX（含 `<wpt>` + `<trkpt>`，但只是直線連接）。

**輸入**：`dayN/_plan/places.json`
**輸出**：`dayN/dayN_route.gpx`

### `gpx-split-plan N --max-waypoints K`

切割長路線為多段，每段最多 `K` 個中間 waypoints。相鄰段共用端點以確保軌跡連續。

**參數**：
- `--max-waypoints K`（預設 4，若仍截斷可降到 2）

**輸入**：`dayN/_plan/places.json`
**輸出**：`dayN/_plan/gpx_split.json` + stdout 顯示每段範圍

### `gpx-append N --leg <i>`

從 stdin 接收第 i 段的 openroute MCP 回應，存為 `_plan/gpx_leg_<i>.gpx`。

**截斷保護**：偵測到沒有 `</gpx>` 閉合標籤時，會找到最後一個完整的 `</rtept>`，自動補上 `</rte></gpx>`，避免後續 merge 失敗。

**參數**：
- `--leg <i>`（必填，從 1 開始）

**輸入**：stdin GPX 文字
**輸出**：`dayN/_plan/gpx_leg_<i>.gpx`

### `gpx-merge N`

合併 `dayN/_plan/gpx_leg_*.gpx` 為最終的 `dayN_route.gpx`，包含：
- 從 `places.json` 取得的 `<wpt>` 停靠點標記
- 所有 leg 的 `<rtept>` 串成單一 `<trkseg>`

**輸入**：`dayN/_plan/gpx_leg_*.gpx` + `dayN/_plan/places.json`
**輸出**：`dayN/dayN_route.gpx`

### `render-prompt N`

用 `templates/prompt.md.j2` 渲染海報提示詞。

**輸入**：`dayN/_plan/poster_vars.json`
**輸出**：`dayN/dayN_prompt.md`

### `render-md N`

用 `templates/day.md.j2` 渲染完整每日文件。

**輸入**：`dayN/_plan/config.json` + `places.json` + `segments.json`
**輸出**：`dayN/dayN.md`

---

## GPX 截斷與分段策略

OpenRoute MCP 在 Claude Code 環境下會被 envelope 截斷在 **~97KB GPX / ~350 rtept** 上限。這是 harness 限制不是腳本問題。

### 選擇策略

| 場景 | 建議 |
|:---|:---|
| 路線短（< 50km）或不需轉彎指示 | `gpx-waypoints`（純航點，2KB） |
| 路線長（50–120km）想保留轉彎 | `gpx-split-plan` + `gpx-append` × N + `gpx-merge` |
| 路線超長（> 150km） | `gpx-split-plan --max-waypoints 2`（切更多段） |

### 分段後接縫

由於每段都會被截在 ~97KB，可能在 leg 末端遺失最後幾 km 的軌跡。合併後接縫處會出現 1–10 km 的直線跳躍。**這不影響 GPX 在地圖 App 中的可用性**，因為 `<wpt>` 仍標記了所有實際停靠點。

如需精確接縫，可在 `gpx-merge` 加入插值（目前未實作）。

---

## 常見錯誤與排除

### `[error] 找不到 Day N 的列`

`index.md` 表格沒有第 N 天，或表格格式被改壞。檢查表格欄位是否仍是 6 欄。

### `[error] 缺少 jinja2`

```bash
pip install jinja2
```

### `[info] ⚠️ 最後一筆 'XXX' 與 index.md 目的地 'YYY' 不完全相符`

不一定是錯誤。`index.md` 寫成「鹿港 / 彰化」這種多選項時，CSV 終點只能是其中一個（例如「鹿港老街」），警告只是提醒人工確認。

### `[info] ⚠️ 餐廳大休候選 1 筆`

`mirror-status` 提示候選池太小。技術上可以繼續，但 SOP 建議至少 2–3 個餐廳備案。請 Claude 再廣搜幾家，把結果 `mirror-put` 寫回本地。

### `[info] ⚠️ GPX 被截斷，已自動補上閉合標籤`

正常情況。Openroute 回應被 MCP envelope 截斷，腳本已自動修復。最終 GPX 仍可用，只是接縫處有跳躍。

### `[error] places.json 缺少 bayesian_C/m`

`write-csv` 前必須先跑 `compute`。

### Bayesian 分數異常

檢查 `places.json` 中每個 `csv_type ∈ {景點, 起終點, 餐廳大休}` 的點是否都有填 `rating` 和 `total_ratings`。漏填的點不會參與計算，會讓 C 和 m 偏差。

---

## 範例：Day 1 完整資料夾

可參考 `day1/_plan/` 下的 4 份 JSON 作為標準範本：

```
day1/_plan/
├── config.json       # parse-index 產出
├── places.json       # 11 筆點位（含 Bayesian）
├── poster_vars.json  # 八里左岸主視覺
└── segments.json     # 五段配速 + 魚骨圖 + 6 條注意事項
```

對應產出：

```
day1/
├── day1_mymap.csv     # 11 點
├── day1_route.gpx     # 8 航點（fallback 版）
├── day1_prompt.md     # 海報提示詞
└── day1.md            # 完整每日文件
```

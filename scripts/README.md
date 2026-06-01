# plan.py — 單車環島每日路線規劃腳本

半自動工具。Claude 在對話中呼叫 MCP（Google Maps / OpenRoute）取得資料並做判斷，腳本則負責所有機械步驟（**本地鏡像維護**、Bayesian 計算、CSV/GPX/Markdown 產出）。

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
| **腳本只打 ORS** | Google Maps 仍由 Claude 透過 MCP 取資料；OpenRouteService 改由腳本 `route` 子命令直接 HTTPS 呼叫（省 token、不分段） |
| **本地鏡像 (write-through)** | 線上每次搜尋都要寫回 `dayN/map/`，**有就 upsert 成最新值**。本地會越用越完整，斷網也能分析 |
| **先 diff 後 put** | 每次寫回前先用 `mirror-diff` 看 rating / 評論數有沒有變，**有變動要顯示給人看**再 upsert |
| **Bayesian 動態重算** | C（候選池平均）與 m（評論數中位數）皆從當前點位重算，禁止硬編碼 |
| **不變式驗證** | CSV 終點要對應 `index.md` 目的地、候選池規模要達標，違反時警告 |
| **冪等** | 重跑同一命令結果一致，輸出檔可隨時覆蓋重生 |
| **分階段可獨立執行** | 各子命令互相獨立，可單獨除錯 |

---

## 安裝與環境

### 需求

- Python 3.8+
- `jinja2` 套件
- Claude Code 中啟用 `google-maps` MCP server（`mcp__google-maps__maps_search_places`、`mcp__google-maps__maps_place_details`）
- OpenRouteService API key（[免費註冊](https://openrouteservice.org/dev/#/signup)，2000 req/day），設為 `ORS_API_KEY` 環境變數

### 安裝

```bash
pip install jinja2
export ORS_API_KEY='your-key-here'   # 建議寫進 ~/.zshrc
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
    │   ├── pool_scores.json           # score-pool 產出（整池 Bayesian SoT）
    │   ├── places.json                # 點位順序 + Bayesian 結果
    │   ├── poster_vars.json           # 海報 5 變數
    │   └── segments.json              # 段落敘述/魚骨圖/注意事項
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

### `_plan/pool_scores.json`（自動產出 by `score-pool`）

Bayesian 評分的 **SoT (Source of Truth)**。由 `score-pool N` 對整個 mirror 候選池（`places` + `candidates_not_selected`）算 C / m / 各 pid 的 `bayesian_score`，`compute N` 從這裡取分數寫回 `places.json`。**不需要手動編輯**。

```json
{
  "day": 1,
  "bayesian_C": 4.3556,
  "bayesian_m": 1588,
  "pool_size": 18,
  "scores": {
    "ChIJ7Ws-1bOoQjQRehrUbGzlo1A": {
      "name_zh": "蘆洲柳堤公園",
      "csv_type": "起終點",
      "rating": 4.3,
      "total_ratings": 1407,
      "bayesian_score": 4.33
    }
    // ... 每個可評分 pid 一筆
  }
}
```

**欄位說明**：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `bayesian_C` | float | 候選池內 `rating` 平均（先驗期望值）|
| `bayesian_m` | int | 候選池內 `total_ratings` 中位數，最低採 100 避免低樣本失真（先驗樣本數）|
| `pool_size` | int | 候選池規模（`csv_type ∈ {景點, 起終點, 餐廳大休}` 且具備 rating/total_ratings 的去重 pid 數）|
| `scores` | dict | key=`place_id`，value 含 `name_zh / csv_type / rating / total_ratings / bayesian_score` |

公式：`bayesian_score = (v/(v+m)) * R + (m/(v+m)) * C`，其中 `R = rating`、`v = total_ratings`。

> 💡 *與 `dinner.json` 的 Bayesian 不同義*：`pool_scores.json` 的 C 是「評分平均」（4.X 區間）、m 是「留言數中位數」；`dinner.json` 的 C 是「平均留言數」、m 是「加權平均評分」。兩者公式骨架相同但意義反置——別把兩邊的 C/m 搞混。

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
  ],

  "better_attractions": "> 以下為沿途搜尋結果中...（Markdown 格式，含表格）"
}
```

`better_attractions`：**必填**欄位，Markdown 格式的「未排入路線但 Bayesian 分數較高的備選景點/餐廳」表格。為空時 `render-md` 自癒會先自動 `compose-better-attractions` 從 `pool_scores` 補表格；若該天確實無備選點可填、`compose` 也產不出內容才會中止（確認後加 `--force` 略過）。可參考 `review N` 的輸出自行撰寫。

### `_plan/dinner.json`（自動產出 by `dinner-pool`）

由 `dinner-pool N` 從 `dayN/dinner_map/` 鏡像候選池算 Bayesian、選 top 5、寫入。**不需要手動編輯**——任何欄位變動都應透過 `dinner-put` 改鏡像後重跑 `dinner-pool`。

```json
{
  "day": 2,
  "search_radius_km": 3,
  "pool_size": 15,
  "bayesian_C": 1016.3,
  "bayesian_m": 4.6416,
  "note": "C=平均留言數(先驗樣本數), m=加權平均評分(先驗期望值)",
  "source_endpoint_place_id": "ChIJbZ03BtZFaTQRVSahxk_O324",
  "top5_place_ids": [
    "ChIJDyBgePpFaTQRJUsJs7vOpkc",
    "ChIJpRXSwg9HaTQRwOSJh1lAlM8"
  ],
  "restaurants": [
    {
      "place_id": "ChIJDyBgePpFaTQRJUsJs7vOpkc",
      "name_zh": "敘敘究燒肉專門店",
      "rating": 4.9,
      "total_ratings": 2739,
      "location": {"lat": 24.0643237, "lng": 120.434732},
      "address": "彰化縣鹿港鎮鹿草路一段277號",
      "note": "燒肉 需預約",
      "bayesian_score": 4.8301,
      "confidence": "✅ 高",
      "rank": 1,
      "selected": true
    }
    // ... 依 bayesian_score 由高到低排序，前 5 名 selected=true
  ]
}
```

**欄位說明**：

| 欄位 | 型別 | 說明 |
|---|---|---|
| `search_radius_km` | int | 從終點向外搜尋的半徑（目前固定 3）。**dinner/hotel-pool 也用此半徑（+0.1km 寬限）依「距目前終點」過濾**，剔除換終點後殘留在 `{kind}_map/` 的遠點，避免被算進 C/m 或選進 top 5（不刪鏡像，被剔除者列在 stderr）|
| `pool_size` | int | 鏡像候選池實際有效筆數（≥ 3 才會跑 Bayesian）|
| `bayesian_C` | float | 候選池內 `total_ratings` 平均（注意：餐廳版的 C/m 跟 places 的 Bayesian 不同義）|
| `bayesian_m` | float | 候選池內以 `total_ratings` 加權的評分平均 |
| `source_endpoint_place_id` | string \| null | **新鮮度簽章**：寫入當下 `_plan/places.json` 最後一個點位的 `place_id`。`render-md` 會比對，若與目前終點不符，自癒會自動重跑 `dinner-pool` 補上正確簽章 |
| `top5_place_ids` | string[] | top 5 的 pid 列表（順序對應 `restaurants[].rank=1..5`）|
| `restaurants` | object[] | 全部候選排名（含 top 5 以外），各筆有 `rank` 與 `selected` 標記 |

> ⚠️ 升級 / 跨機器 / 舊版 `dinner.json` 沒有 `source_endpoint_place_id` 欄位（render-md 會以「舊版產出」擋下），對該天重跑一次 `dinner-pool N` 即可遷移。

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

> 🆕 **路線優先選點（現行流程）**：先 `route-skeleton N` 讓 ORS 用「起點+必經景點+終點」算出骨架最佳路線，再 `search-along-route N --keyword … --csv-type … [--segments K]` 沿這條真實路線用 Places API (New) searchAlongRoute 找停靠點（依離線繞路距離過濾、印沿路里程），最後依沿路里程挑點寫 `places.json`。詳見 `CLAUDE.md` Phase 1 與 `plan.py` 檔頭。以下 1-1~1-8 為舊版「先憑地理知識挑點」流程，保留作為 fallback / 細節參考（mirror-search、mirror-diff、score-pool、compute、write-csv 等指令仍通用）。

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

#### 1-5. 先看整池 Bayesian 排名（**選點前**）

```bash
python3 scripts/plan.py score-pool 2
```

`score-pool` 對 mirror 中**所有可評分候選**（places + candidates_not_selected）算 Bayesian C/m/score，產出 `_plan/pool_scores.json` 並印分組排名。**在編輯 places.json 前**就能看到分數，配合順路 / 視覺辨識度做整體決策，不必先盲挑後悔再 review 翻轉。

> Bayesian 的 C/m 來自**整個候選池**（樣本大、穩定），這也是 `compute` 寫進 places.json 的最終分數來源 — score-pool 是 SoT。

#### 1-6. 編寫 `_plan/places.json`（依分數 + 順路挑選）

打開 `_plan/pool_scores.json` 看排名，從 `dayN/map/index.json` 的 `places` 陣列裡，把要列入 CSV 的點按**騎乘順序**抄到 `_plan/places.json`，並補上 `search_keyword` 和 `note`（這兩個是 CSV 專用欄位，本地鏡像沒有）。參考 `day1/_plan/places.json` 當範本。

> 選點考量順序：① 必經景點（index.md 固定）→ ② 順路（距主線距離）→ ③ 時間節奏（補給 / 午餐 / 撤退）→ ④ Bayesian 分數（破平手用）

#### 1-7. 套用分數 + 產 CSV

```bash
python3 scripts/plan.py compute 2       # 從 mirror 同步最新值 + 套用 pool_scores 到 places.json
python3 scripts/plan.py write-csv 2     # 產 dayN_mymap.csv，並警告終點不一致
```

> ⚠️ `compute` 會自動從 `dayN/map/` 拉最新 rating / total_ratings；並**每次都重算 `score-pool`**（pool 的 C/m 與路線走廊過濾都依目前路線決定，換路線後必須重算才會把離線殘留點排除；score-pool 只讀本地，成本可忽略）。

#### 1-8.（可選）替換偵測

當 mirror 累積新資料後，**入選與未入選的排名可能翻轉**。`review` 顯示完整排名（★ 標記入選）+ 替換建議：

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

直接呼叫 ORS API 取完整路線（含轉彎軌跡）：

```bash
python3 scripts/plan.py route 2
```

需事先 `export ORS_API_KEY='your-key'`。台灣單日路線（≤ 50 個 waypoints）一次 request 就能完整回傳，不再需要分段。

離線或無 API key 時的備案（純航點直線，無轉彎軌跡）：

```bash
python3 scripts/plan.py gpx-waypoints 2
```

### Phase 3：海報提示詞

> 💡 不必先手動 `compute`：`render-prompt` 的 ★主視覺自動 fallback 依賴 `bayesian_score`，偵測到 places.json 尚無分數（沒跑過 compute，或改點後未重算）時會**自動補跑 `compute`** 再同步主視覺。`--no-sync` 模式不重選主視覺，故不觸發。

**手寫 `_plan/poster_vars.json`**：主視覺從 CSV `bayesian_score` 最高的景點選；夕陽景點（如高美濕地）要把 `lighting` 改成金色暖光。

```bash
python3 scripts/plan.py render-prompt 2
```

### Phase 3.5：晚餐候選池

Claude 在對話中用 MCP 搜尋終點周邊 3km 的晚餐選項，`dinner-put` 寫入 `dinner_map/` 鏡像：

```bash
# 1. MCP 搜尋 → dinner-put 寫入鏡像（重複 N 筆）
echo '{...}' | python3 scripts/plan.py dinner-put 2

# 2. 整池 Bayesian + 自動選 top 5 → 產 _plan/dinner.json
python3 scripts/plan.py dinner-pool 2

# 3.（可選）檢查排名
python3 scripts/plan.py dinner-review 2
```

> 若 `dinner_map/` 已有候選但 `dinner.json` 不存在 / 比 `places.json` 舊 / 終點簽章不符，`render-md` 自癒會自動重跑 `dinner-pool N`（無需手動）。確定該天不需要晚餐區塊時可加 `--force` 略過。

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

### 換終點 / 換路線後，鏡像裡的舊遠點怎麼辦？

鏡像是 **write-through、只增不減**，所以換終點或重排路線後，舊路線附近的景點/餐廳/飯店**仍留在** `map/` `dinner_map/` `hotel_map/`。若直接全部算進 Bayesian，這些離線殘留點會：(a) 污染 C/m，(b) 餐廳/飯店因 top 5 是自動選的，遠點若分數高甚至會被選進新終點的推薦。

處理方式是**在 pool 階段依「目前路線」動態過濾**（不刪鏡像、保留歷史，換路線後自我修正）：

| 池 | 過濾基準 | 門檻 |
|:---|:---|:---|
| 景點（`score-pool`） | 距**目前路線折線**的最短距離 | 折線優先用 **ORS 真實路線幾何**（`route_geometry.json`，簽章對得上現在航點時）→ **> 15km 剔除**（精準）；尚未跑 route／離線／簽章不符時退回**航點直線近似** → **> 30km 剔除**（刻意寬鬆）。≤2km 選點 SOP 仍由 Claude 手選 places.json 管 |
| 晚餐 / 住宿（`dinner-pool` / `hotel-pool`） | 距**目前終點** `places.json[-1]` | > 3km（+0.1 寬限）剔除 |

- **真實路線 vs 直線近似**：`route` 會把 ORS 回傳的真實折線存進 `_plan/route_geometry.json`，並記下「產出當時的航點座標」當簽章。`score-pool` 比對現在 `places.json` 航點，相符才用真實折線（換航點後簽章不符 → 自動退回直線近似）。合法備案多為「順遊繞路型」海岸景點，距**實際騎乘路線**本來就有數 km（10 天實測：高美濕地 4.5km、七星潭 5.9km、王功漁港 11.7km，皆刻意保留），故真實折線門檻取 **15km**（需 > 最遠合法備案 11.7km，留約 3km 餘裕），不能更小。真實 vs 直線在此資料差異不大（王功 11.7 vs 12.3、七星潭 5.9 vs 5.9）；真實幾何的價值是 **(a) 距離準確**（路線彎繞時直線會嚴重低估）、**(b) 門檻能從直線的 30km 收緊到 15km**，精準抓 15–30km 區間的他區殘留點。
- 被剔除者會列在 stderr（標明用「真實路線」或「直線近似」），缺座標或無路線點時不過濾。
- `compute` 每次都重算 `score-pool`，且 `render-md` 自癒 cascade 在 **route 成功後會再補跑一次 `score-pool`**（route 才剛寫出對應現在航點的真實折線），所以換路線後跑一次 `render-md N` 即在**同一個指令內**用真實路線過濾、排除舊遠點。
- 想徹底清掉鏡像裡的舊點，仍需手動編 `index.json` + 刪 `<pid>.json`（過濾只影響「算進池子與否」，不動鏡像本身）。

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
python3 scripts/plan.py gpx-waypoints 2    # 無 ORS，用航點 fallback
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
- **入選與備案分別**依 `csv_type` 分組列出
- 候選池規模警告：景點/起終點 < 5 或餐廳大休 < 2 時警示，且計入備案數量

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

### `score-pool N`

對整個 mirror 候選池算 Bayesian，產出 `_plan/pool_scores.json`：

- **候選池** = `mirror.places + mirror.candidates_not_selected` 中所有 `csv_type ∈ {景點, 起終點, 餐廳大休}` 且具備 `rating` / `total_ratings` 的點（依 `place_id` 去重）
- **路線走廊過濾**：鏡像只增不減，換路線/終點後舊景點仍留在 `candidates_not_selected`。score-pool 會剔除「距目前路線折線過遠」的點（離線殘留），**不刪鏡像**、換路線後自我修正；被剔除者會列在 stderr，缺座標或無路線點時不過濾。折線優先用 **ORS 真實路線幾何**（`route_geometry.json` 簽章對得上現在航點時，門檻 **15km**，精準抓 15–30km 殘留）；尚未跑 route／離線／簽章不符時退回**航點直線近似**（門檻 **30km**，刻意寬鬆，只為抓不同區域殘留點，非 ≤2km 選點 SOP）
- **`bayesian_C`** = 候選池內 `rating` 平均
- **`bayesian_m`** = 候選池內 `total_ratings` 中位數（最低採用 100，避免低樣本失真）
- 每個點位的 **`bayesian_score`** = `(v/(v+m)) * R + (m/(v+m)) * C`

**輸入**：`dayN/map/index.json` + `dayN/map/<pid>.json`
**輸出**：`dayN/_plan/pool_scores.json`（**SoT**） + stdout 分組排名

**典型用法**：選點**前**先跑一次看分數，配合順路 / 視覺辨識度做整體決策。

```json
// pool_scores.json schema
{
  "day": 1,
  "bayesian_C": 4.3556,
  "bayesian_m": 1588,
  "pool_size": 18,
  "scores": {
    "ChIJ...": {"name_zh": "蘆洲柳堤公園", "csv_type": "起終點",
                "rating": 4.3, "total_ratings": 1407, "bayesian_score": 4.33},
    // ... 每個可評分 pid 一筆
  }
}
```

### `compute N [--quiet]`

> **Phase 0-3 結尾提醒**：`compute` 完成後會在 stderr 列出 Phase 3.5 (`dinner-pool`) 與 Phase 4 (`better_attractions`) 是否需要重做的清單。`places.json` 更新後若 `dinner.json` / `segments.json` 比它舊，就會列在提醒裡；不過 **`render-md` 會自動重生（自癒）這些下游**，所以直接跑 `render-md N` 即可。
>
> `--quiet`：不印每點分數表，只印 C/m 摘要與「下一步」提醒。`score-pool` / `review` / `dinner-pool` 同樣支援 `--quiet`。

套用 `pool_scores.json` 的 Bayesian 結果到 `_plan/places.json`：

1. **從 `dayN/map/<pid>.json` 拉最新 rating / total_ratings / location / name_zh**（這些屬於 Google Maps 的事實，mirror 是 SoT）。`csv_type` 不同步——它是「當日對該點的角色分類」，由人在 places.json 決定
2. 從 `pool_scores.json` 取 `bayesian_C` / `bayesian_m`，以及該 pid 的 `bayesian_score`
3. 若 pid 不在 pool_scores（例：places.json 寫了新點但忘了 mirror-put），會用 places.json 自有資料補算分數並警告
4. 只對 `csv_type ∈ {景點, 起終點, 餐廳大休}` 的點位寫 score

**輸入**：`dayN/_plan/places.json` + `dayN/_plan/pool_scores.json` + `dayN/map/*.json`
**輸出**：寫回 `places.json`（含 `bayesian_C` / `bayesian_m` / 每點的 `bayesian_score`）+ stdout 表格

> `compute` 每次都會重算 `score-pool`（不論 `pool_scores.json` 是否已存在），確保 C/m 與路線走廊過濾反映目前路線；無需手動先跑 score-pool。

> 重要：`places.json` 內的 rating / total_ratings / location / name_zh 會被 mirror 覆寫，不要手動編輯（會被下次 compute 蓋掉，應改寫到 mirror）。`csv_type` 不被 mirror 覆寫，可在 places.json 自由調整當日角色分類。
>
> 若 `csv_type ∈ {景點, 起終點, 餐廳大休}` 的點缺 rating 或 total_ratings（None），會被排除在 Bayesian 計算外。注意「值為 0」（如新景點 total_ratings=0）不算缺值，會正常參與計算。

### `review N`

讀 `pool_scores.json` 顯示候選池排名（★標記入選點），並偵測是否有更佳替換：

1. 從 `pool_scores.json` 讀取 C / m / 各 pid 的分數（pool_scores 不存在時自動觸發 `score-pool`）
2. 按 `csv_type` 分組排名顯示
3. `★` 標記目前在 `places.json` 內的入選點位
4. 比較「最差入選」vs「最佳未入選」，若後者較高則提示替換

**典型使用情境**：
- 隔一段時間想看評分是否有變動 → `mirror-put` 批次更新 → `score-pool` 重算 → `review` 看排名變化
- 規劃前期確認是否選對點 → 比較入選 vs 備案

**不變式**：
- `起終點` 由 `index.md` 固定，**不參與替換建議**
- 替換建議只看 Bayesian 分數，**不考慮地理位置順路性**，使用者要自行判斷

**輸入**：`dayN/_plan/places.json` + `dayN/_plan/pool_scores.json`
**輸出**：stdout 排名表 + 替換建議

### `write-csv N`

讀 `dayN/_plan/places.json` + `config.json`，產出 `dayN_mymap.csv`。

**不變式檢查**：
- CSV 最後一筆的 `name_zh` 應與 `config.json.destination` 相符，否則 stderr 警告

**輸入**：`dayN/_plan/places.json` + `dayN/_plan/config.json`
**輸出**：`dayN/dayN_mymap.csv`

### `route N`

從 `places.json` 讀座標，呼叫 OpenRouteService `cycling-regular` API（HTTPS POST，不經 MCP），輸出 `dayN_route.gpx`。回應為 GPX，已自動剝除 `<extensions>` 區塊並在 `<metadata>` 後注入 `<wpt>` 停靠點標記。

**需求**：
- `ORS_API_KEY` 環境變數（[免費註冊](https://openrouteservice.org/dev/#/signup)，2000 req/day）
- `places.json` 點位數 ≤ 50（ORS cycling-regular 單次上限；台灣單日不會碰到）

**座標品質檢查**：呼叫 API 前會驗證 bounding box（必在台灣範圍）/ 相鄰距離（≤ 40 km）/ 繞路（直線 ×1.5 內）/ 累積距離（≤ 直線 ×3），失敗即中止避免浪費 API 額度。

**輸入**：`dayN/_plan/places.json`
**輸出**：`dayN/dayN_route.gpx`

### `gpx-save N`

從 stdin 讀外部來源 GPX 文字（自動剝除 envelope 與 `<extensions>`），存為 `dayN_route.gpx`。`route` 失敗時手動貼路線用的備援。

**輸入**：stdin GPX 文字
**輸出**：`dayN/dayN_route.gpx`

### `gpx-waypoints N`

離線或無 `ORS_API_KEY` 時的備案：直接從 `places.json` 座標產出純航點 GPX（含 `<wpt>` + `<trkpt>`，但只是直線連接）。

**輸入**：`dayN/_plan/places.json`
**輸出**：`dayN/dayN_route.gpx`

### `render-prompt N [--no-sync]`

用 `templates/prompt.md.j2` 渲染海報提示詞。

**預設行為**：渲染前會先從 `places.json` 重推 `poster_vars.json` 的「結構欄位」：
- `composition` / `geographic_notes`：每次都依當前 places + orientation 重生
- `main_visual.place_id` / `small_avatar.place_id`：依 ★主視覺 與起點同步
- 若 `place_id` 變動，會清空對應的手寫場景文字（`scene_elements` / `action` / `expression` / `scenario`）並警告，避免舊文字配新地點
- `origin_label` / `destination_label` / `distance_range` / `subtitle` / `orientation` / `lighting` / `allowed_elements` / `enhancement`：缺值才補預設，已有就尊重使用者編輯

**參數**：
- `--no-sync`：跳過自動同步，僅以現有 `poster_vars.json` 渲染。用於已手動完成所有欄位、不想被覆寫時。

**輸入**：`dayN/_plan/poster_vars.json`（+ `places.json` / `config.json` 用於同步）
**輸出**：`dayN/dayN_prompt.md`（+ 改寫後的 `poster_vars.json`，除非 `--no-sync`）

### `compose-better-attractions N [--overwrite] [--dry-run]`

從 `pool_scores.json` 自動產出 `segments.json.better_attractions` 的 Markdown 表格：
- 景點備案：未入選、未鎖定（非必經）的 `csv_type==景點` 前 5 名（依 Bayesian 分數）
- 餐廳備案：未入選的 `csv_type==餐廳大休` 前 3 名

**參數**：
- `--overwrite`：覆蓋既有非空 `better_attractions`（預設不覆蓋，只印預覽）
- `--dry-run`：只印預覽到 stdout，不寫入 `segments.json`

未指定 `--overwrite` 時若欄位已有內容，會 `touch` `segments.json` 表示「已驗證仍有效」，避免 `render-md` 預檢誤判。

### `verify-and-fix N`

一條龍：`run_mechanical_cascade`（`compute → route/gpx-waypoints → write-csv → render-prompt → dinner-pool → hotel-pool → compose-better-attractions`）+ `render-md --force`。

> 💡 **多數情況不需要直接呼叫它**：`render-md N` 已內建同一條 `run_mechanical_cascade` 自癒，改完 `places.json` 直接跑 `render-md N` 即可。`verify-and-fix` 保留為「我就是要強制重生全部、並用 `--force` 無視檢查」的明確入口（兩者共用同一份 cascade 程式碼，不會漂移）。

- 無 `ORS_API_KEY` 自動 fallback `gpx-waypoints`
- `dinner_map/` 為空時略過 `dinner-pool`；`hotel_map/` 為空時略過 `hotel-pool`；候選不足 3 筆時該 pool 略過不中斷
- 不會覆蓋既有 `segments.json.better_attractions`（有內容才會 `touch`；空時自動產）
- 最後 `render-md --force`：cascade 已串完，bypass 自癒檢查

**不能自動補的事項**（需手動）：`places.json` 點位選擇、`segments.json` 主敘述（五段配速、ishikawa、notes）、`poster_vars.json` 手寫場景文字（`scene_elements` / `action` / `expression` / `scenario`）。

### `render-md N [--force]`

用 `templates/day.md.j2` 渲染完整每日文件。

**全量新鮮度檢查 + 自癒**：核心原則仍是「**改了 `places.json` 就要全部重做**」，但 render-md 不再 hard-fail 要你手動重跑——偵測到任一下游產出陳舊／缺失／簽章不符時，**自動跑 `run_mechanical_cascade`（= verify-and-fix 的機械步驟）重生所有機械產物後再渲染**。只有「自癒後仍存在、且需人腦判斷」的缺口才會中止並列出。所以改完 `places.json` 想重規劃整天，直接 `render-md N` 一個指令即可。

| 類別 | 檢查 | 自癒時自動執行 |
|---|---|---|
| Phase 1 | `dayN_mymap.csv` mtime ≥ `places.json` | `write-csv N` |
| Phase 2 | `dayN_route.gpx` mtime ≥ `places.json` | `route N`（無 key→`gpx-waypoints N`） |
| Phase 3 | `_plan/poster_vars.json` mtime ≥ `places.json` | `render-prompt N`（自動同步結構欄位） |
| Phase 3 | `dayN_prompt.md` mtime ≥ `places.json` | `render-prompt N` |
| Phase 3.5 | `dinner_map/` 有候選時 `dinner.json` 存在、mtime ≥ `places.json` | `dinner-pool N` |
| Phase 3.5 內容 | `dinner.json.source_endpoint_place_id` == `places.json[-1].place_id`（**signature 比 mtime 更嚴**） | `dinner-pool N`（重算會寫入新終點簽章） |
| Phase 3.6 | `hotel_map/` 有候選時 `hotel.json` 存在、mtime ≥ `places.json` | `hotel-pool N` |
| Phase 3.6 內容 | `hotel.json.source_endpoint_place_id` == `places.json[-1].place_id` | `hotel-pool N` |
| Phase 4 | `segments.json.better_attractions` 非空，且 `segments.json` mtime ≥ `places.json` | `compose-better-attractions N`（空才自動產，有內容只 `touch`） |

**自癒後仍會中止的情形**（需人工，確認後加 `--force` 略過）：最常見是該天**確實沒有備選景點/餐廳可填 `better_attractions`**（`compose` 產不出內容）；或 `dinner_map/`、`hotel_map/` 候選不足 3 筆導致 pool 算不出來。中止時會列出殘留項目。

**`--force`**：完全略過自癒與檢查，直接拿現有檔案渲染（`verify-and-fix` 收尾即用此模式）。

> 💡 舊版 `dinner.json` / `hotel.json` 沒有 `source_endpoint_place_id` 欄位，第一次升級執行時會被判定陳舊→自癒會自動重跑 `dinner-pool` / `hotel-pool` 補上（一次性遷移，不再需要手動處理）。

**輸入**：`dayN/_plan/config.json` + `places.json` + `segments.json`（+ 可選 `dinner.json`）
**輸出**：`dayN/dayN.md`

---

## GPX 來源選擇

| 場景 | 建議 | 產出 |
|:---|:---|:---|
| 標準流程（有 `ORS_API_KEY`） | `route N` | 含轉彎軌跡的完整 GPX |
| 離線、無 API key 或趕時間 | `gpx-waypoints N` | 純航點直線連接（2KB） |
| 手動取得外部 GPX 文字 | `cat foo.gpx \| plan.py gpx-save N` | 原樣存檔 |

> **舊版註記**：先前因 Claude Code MCP envelope ~97KB 截斷限制，需要 `gpx-split-plan` + `gpx-append` × N + `gpx-merge` 三步驟。改成腳本直接呼叫 ORS API 之後，台灣單日路線（≤ 50 waypoints）一次 request 就能完整回傳，全部三個子命令已移除。

---

## 常見錯誤與排除

### `[error] 找不到 Day N 的列`

`index.md` 表格沒有第 N 天，或表格格式被改壞。檢查表格欄位是否仍是 6 欄。

### `[error] 缺少 jinja2`

```bash
pip install jinja2
```

### `[info] ⚠️ 最後一筆 'XXX' 與 index.md 目的地 'YYY' 不完全相符`

`write-csv` 會把 `index.md` 目的地依 `/`、`、`、`,` 拆成多個選項，只要 CSV 終點的 `name_zh` 是任一選項的 substring（或反之）就視為相符。若仍觸發警告，代表終點確實偏離了任何一個指定選項，需要人工確認。

### `[info] ⚠️ 餐廳大休候選 1 筆`

`mirror-status` 提示候選池太小。技術上可以繼續，但 SOP 建議至少 2–3 個餐廳備案。請 Claude 再廣搜幾家，把結果 `mirror-put` 寫回本地。

### `[error] 缺少 ORS_API_KEY 環境變數`

`route` 需要 OpenRouteService API key：

```bash
export ORS_API_KEY='your-key-here'   # 建議寫進 ~/.zshrc
```

若不想申請 key，改用 `gpx-waypoints N` 產純航點 GPX。

### `[error] ORS API HTTP 4xx/5xx`

常見原因：
- `403`：API key 無效或當日 2000 次額度用罄
- `400 Could not find routable point`：某點座標落在水域 / 不可達道路上，重抓該點 Google Maps 座標
- `500`：ORS 服務端問題，稍後重試或改用 `gpx-waypoints`

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

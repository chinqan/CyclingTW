# Skill：單車環島每日海報圖形產生

## 📌 目的

為單車環島第 N 日產生一張生動精美的海報圖形。讀取 `dayN/dayN_prompt.md`，使用 `主角.png` 作為輸入圖形，調用 image2 / imagegen 繪圖，將成品儲存到該日資料夾。

---

## 📁 輸入與輸出

### 輸入檔案

| 檔案 | 用途 |
|:---|:---|
| `主角.png` | 主角人物與公路車參考圖，作為輸入圖形 |
| `dayN/dayN_prompt.md` | 第 N 日海報的完整提示詞（必須已存在） |
| `dayN/dayN.md` | 第 N 日詳細騎乘內容，用於確認地理正確性 |
| `dayN/dayN_mymap.csv` | 第 N 日景點順序與類型，用於確認地理位置 |

### 輸出檔案

海報圖輸出到：

```text
dayN/dayN_poster.png
```

若同名檔案已存在，除非使用者明確要求覆蓋，否則輸出為：

```text
dayN/dayN_poster_v2.png
dayN/dayN_poster_v3.png
...
```

---

## 📐 圖形解析度

依據當日路線走向決定圖片尺寸：

| 路線走向 | 尺寸 | 方向 | 適用天數範例 |
|:---|:---:|:---|:---|
| 南北走向 | `1024 x 1536` | 直幅（Portrait） | Day 1 蘆洲→竹南、Day 2 竹南→鹿港 |
| 東西走向 | `1536 x 1024` | 橫幅（Landscape） | 東西橫跨路段 |

> 判斷原則：看 `dayN.md` 中起點與終點的相對位置，若主要是由北往南或由南往北，用直幅；若主要是由東往西或由西往東，用橫幅。

### 強制交付規則

image2 / imagegen 的原始輸出尺寸可能不符合上表。**不可直接交付未驗證尺寸的原圖**，必須在複製到 `dayN/` 後檢查實際尺寸，若不符合指定解析度，需後製成正確尺寸再交付。

建議命名：

```text
dayN/dayN_poster.png
dayN/dayN_poster_v2.png
```

最終交付檔案本身必須符合指定尺寸，不要只另外產生一份校正版而仍回報錯誤尺寸的原圖。

### 後製方式

若原始圖比例與目標比例不同，優先採用「等比縮放填滿目標尺寸，再置中裁切」：

```bash
# 南北走向：輸出 1024 x 1536
sips --resampleWidth 1024 dayN/dayN_poster.png
sips --cropToHeightWidth 1536 1024 dayN/dayN_poster.png

# 東西走向：輸出 1536 x 1024
sips --resampleHeight 1024 dayN/dayN_poster.png
sips --cropToHeightWidth 1024 1536 dayN/dayN_poster.png
```

處理後用 `file dayN/dayN_poster.png` 驗證結果。若仍非指定尺寸，需繼續修正，不能回報完成。

---

## 🌅 光線氛圍

預設使用**早晨清新明亮**的光線風格：

| 條件 | 光線風格 | 描述 |
|:---|:---|:---|
| **預設** | 清晨明亮 | 柔和晨光、清新藍天白雲、明亮色調、空氣感 |
| 路線有經過夕陽景點 | 夕陽暖光 | 金色暖光、橘紅天空漸層、黃昏氛圍 |

> 判斷原則：檢查 `dayN.md` 或 `dayN_mymap.csv` 中是否有明確以「看夕陽」為賣點的景點（如高美濕地）。若無，一律使用清晨明亮風格。

---

## 🎨 海報產生流程 Checklist

1. [ ] 確認目標天數 N，例如 Day 1、Day 2。
2. [ ] 確認 `dayN/dayN_prompt.md` 已存在，若不存在則提示使用者先建立。
3. [ ] 讀取 `dayN/dayN_prompt.md` 作為主要提示詞，不任意改寫核心要求。
4. [ ] 載入 `主角.png` 作為輸入圖形，角色參考用途需明確標註為「人物 / 車款參考」。
5. [ ] 若提示詞需要地理正確性，參考 `dayN/dayN.md` 與 `dayN/dayN_mymap.csv` 確認路線順序。
6. [ ] 使用 image2 / imagegen 產圖，要求保留主角可辨識特徵、髮型輪廓、服裝與公路車印象。
7. [ ] 檢查輸出是否符合提示詞：主角是否最大、地標是否正確、是否有多餘肢體、是否有錯字或不合理建築。
8. [ ] 將選定圖檔複製到 `dayN/` 資料夾，保留原始產圖檔不刪除。
9. [ ] 依「圖形解析度」規則檢查實際尺寸；若不符合，後製成指定尺寸。
10. [ ] 用 `file` 驗證最終交付檔案尺寸。
11. [ ] 回報最終檔案路徑、實際尺寸、是否使用 `主角.png`、是否使用 `dayN/dayN_prompt.md`。

---

## 🖼️ image2 / imagegen 使用規範

### 輸入圖形

`主角.png` 是人物參考圖，使用時應強調：

- 保留真實臉型與五官比例
- 保留髮型輪廓與安全帽 / 車衣 / 公路車印象
- 可進行風格轉換，例如 3D Q 版公仔、微縮場景、旅遊海報
- 不應把人物改成無法辨識的完全不同角色

### 提示詞整合方式

將 `dayN/dayN_prompt.md` 內容作為主提示詞，外加必要的技術描述：

```text
Input image: Use 主角.png as the main character and road bike reference.
Preserve recognizable face shape, facial feature proportions, hairstyle silhouette,
cycling outfit impression, helmet impression, and road bike frame/color impression.

Primary prompt:
<貼上 dayN/dayN_prompt.md 的內容>

Quality constraints:
Main character must be the largest visual subject.
No extra limbs, correct anatomy, clear face, no watermark, no fake logos,
no incorrect landmark placement, no non-Taiwan architecture unless requested.
```

---

## 🧭 地理與故事要求

若提示詞要求「第 N 日路線海報」，圖像需呈現該日的旅程感：

- 起點、主要景點、終點的相對位置需合理。
- 不要把北南方向、海岸與山線位置畫反。
- 若是西濱路線，海應在西側，公路與城鎮在陸側。
- 若是山線或縱谷路線，需呈現山脈、河谷或台地等地貌。
- 可用微縮地圖、路線光帶、地標小模型、雲層與景深增加故事感。

---

## ✅ 品質檢查

完成後至少檢查：

1. **人物**：主角是否清楚、最大、表情自然，沒有多餘手腳。
2. **車輛**：公路車是否像公路車，輪框、把手、車架比例是否合理。
3. **地標**：主要景點是否符合該日地理位置，不出現虛構建築。
4. **構圖**：是否有前景、中景、遠景層次，是否像一張完整海報。
5. **文字**：若圖上有文字，需避免錯字；必要時可要求少文字或無文字。
6. **解析度**：最終交付檔案必須符合路線走向指定尺寸，例如 Day 1 / Day 2 必須是 `1024 x 1536`。
7. **儲存**：最終圖檔需在 `dayN/` 目錄下，並保留原始產圖檔。

---

## 📋 使用範例

使用者要求：

```text
幫我畫 Day 3 海報圖
```

執行方式：

1. 確認 `day3/day3_prompt.md` 存在
2. 讀取 `day3/day3_prompt.md`
3. 載入 `主角.png`
4. 可參考 `day3/day3.md` 與 `day3/day3_mymap.csv`
5. 調用 image2 / imagegen
6. 輸出到 `day3/day3_poster.png`

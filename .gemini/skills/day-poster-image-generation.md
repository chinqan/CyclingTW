# Skill：單車環島每日海報圖形產生

## 📌 目的

為單車環島第 N 日產生一張生動精美的海報圖形。產圖時必須：

1. 讀取該日提示詞：`dayN/dayN_prompt.md`
2. 使用根目錄人物參考圖：`主角.png`
3. 調用 image2 / imagegen 進行繪圖
4. 將成品儲存到該日資料夾

---

## 📁 輸入與輸出

### 輸入檔案

| 檔案 | 用途 |
|:---|:---|
| `主角.png` | 主角人物與公路車參考圖，作為輸入圖形 |
| `dayN/dayN_prompt.md` | 第 N 日海報的完整提示詞 |
| `dayN/dayN.md` | 可選參考，用於確認路線、景點、補給點與故事脈絡 |
| `dayN/dayN_mymap.csv` | 可選參考，用於確認景點順序與地理位置 |

### 輸出檔案

建議輸出到：

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

## 🔧 產生流程 Checklist

1. [ ] 確認目標天數 N，例如 Day 1、Day 2。
2. [ ] 讀取 `dayN/dayN_prompt.md` 作為主要提示詞，不任意改寫核心要求。
3. [ ] 載入 `主角.png` 作為輸入圖形，角色參考用途需明確標註為「人物 / 車款參考」。
4. [ ] 若提示詞需要地理正確性，參考 `dayN/dayN.md` 與 `dayN/dayN_mymap.csv` 確認路線順序。
5. [ ] 使用 image2 / imagegen 產圖，要求保留主角可辨識特徵、髮型輪廓、服裝與公路車印象。
6. [ ] 檢查輸出是否符合提示詞：主角是否最大、地標是否正確、是否有多餘肢體、是否有錯字或不合理建築。
7. [ ] 將選定圖檔複製到 `dayN/` 資料夾，保留原始產圖檔不刪除。
8. [ ] 回報最終檔案路徑、是否使用 `主角.png`、是否使用 `dayN/dayN_prompt.md`。

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
6. **儲存**：最終圖檔需在 `dayN/` 目錄下，並保留原始產圖檔。

---

## 📋 使用範例

使用者要求：

```text
幫我畫 Day 3 海報圖
```

執行方式：

1. 讀取 `day3/day3_prompt.md`
2. 載入 `主角.png`
3. 可參考 `day3/day3.md` 與 `day3/day3_mymap.csv`
4. 調用 image2 / imagegen
5. 輸出到 `day3/day3_poster.png`

# Skill：單車環島每日海報圖形產生

## 📌 目的
為單車環島行程產生精美的每日路線海報。以 `dayN_prompt.md` 與 `主角.png` 為核心輸入，產出符合精確尺寸的 `dayN_poster.png`。

---

## 📁 檔案規範
* **輸入**：
  * `dayN/dayN_prompt.md` (海報核心提示詞，已包含解析度、光線氛圍、地理構圖與出發地設定)
  * `主角.png` (人物與車輛特徵參考圖)
* **輸出**：
  * `dayN/dayN_poster.png` (若同名檔案已存在且未要求覆蓋，則依序命名為 `_v2.png`, `_v3.png`)

---

## 🎨 產圖提示詞 (Prompt) 組合結構
請整合以下兩部分作為最終產圖指令：

1. **參考圖宣告**（固定不變）：
   `Input image: Use 主角.png as the main character and road bike reference. Preserve recognizable face shape, facial feature proportions, hairstyle silhouette, cycling outfit, and road bike impression.`
2. **核心提示詞**：
   直接貼上 `dayN/dayN_prompt.md` 的完整內容（解析度與光線氛圍已在其中）。

---

## ✅ 尺寸驗證與後製 (嚴格要求)
產圖工具輸出尺寸常有誤差，**必須**用 `file` 指令驗證最終尺寸，若不符需後製修正：

```bash
# 南北走向 (1024x1536) 後製指令參考
sips --resampleWidth 1024 dayN/dayN_poster.png
sips --cropToHeightWidth 1536 1024 dayN/dayN_poster.png

# 東西走向 (1536x1024) 後製指令參考
sips --resampleHeight 1024 dayN/dayN_poster.png
sips --cropToHeightWidth 1024 1536 dayN/dayN_poster.png
```

---

## 🧭 品質檢查 (Checklist)
產圖後至少檢查以下標準，確認無誤才算完成：
- [ ] **精確尺寸**：已使用 `file` 指令驗證最終檔案尺寸等於 `dayN_prompt.md` 中標明的規格。
- [ ] **人物與車輛**：主角比例最大且特徵保留，表情自然、無多餘手腳；公路車結構合理。
- [ ] **地理邏輯**：起終點與景點相對位置合理，不出現虛構建築。
  - *西濱路線*：海在西側，公路/城鎮在陸側。
  - *山線/縱谷*：需呈現山脈、河谷等地貌。
- [ ] **故事感**：具備前、中、遠景層次。可用微縮地圖、路線光帶、地標小模型增加旅程感。

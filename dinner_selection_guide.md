# 🍽️ 環島晚餐挑選攻略

> 如何用 Google Maps MCP + 貝葉斯排序，找到真正值得信賴的在地餐廳

---

## 一、為什麼不能只看 Google 評分？

Google Maps 上的 ★ 評分有一個致命盲點：**樣本數不足的店，評分會嚴重失真**。

| 店名 | 評分 | 留言數 | 可信度 |
|---|---|---|---|
| 阿湯哥脆皮蚵仔煎 | ⭐ 5.0 | 14 則 | ❌ 很可能是熟人刷評 |
| 阿婆小吃 | ⭐ 5.0 | 29 則 | ❌ 樣本不足 |
| 上癮餐酒館 | ⭐ 4.6 | 830 則 | ✅ 真實可信 |
| 夏川食堂 | ⭐ 4.8 | 751 則 | ✅ 真實可信 |

**結論：一間 5.0 ★（14則）的店，不如 4.6 ★（830則）的店可信。**

---

## 二、貝葉斯平均分（Bayesian Average）方法論

這是 IMDb、Yelp、Amazon 實際使用的評分可信度演算法。

### 公式

```
貝葉斯分 = (C × m + rating × n) / (C + n)

C = 全體餐廳的平均留言數（先驗樣本數）
m = 全體餐廳的加權平均評分
n = 該店的留言數
rating = 該店的評分
```

### 白話解釋

- **留言數少**的店：強制拉向全體平均值，抑制虛高分數
- **留言數多**的店：自身評分佔主導，加權影響力大
- C 越大，對新店越保守

### 信心門檻

```
信心指數 = n / C

≥ 1.0  → 樣本充足，評分高度可信
0.5~1.0 → 可參考，留意極端評論
< 0.5  → ⚠️ 留言數偏少，僅供參考
< 0.1  → ❌ 樣本極少，不建議作為主要依據
```

---

## 三、正確的選店流程

```
步驟一：搜尋終點周邊 3km，拉取全部 20 筆結果
         ↓
步驟二：批次查詢所有 20 筆的 rating + user_ratings_total
         ↓
步驟三：計算 C（平均留言數）與 m（加權平均評分）
         ↓
步驟四：對每筆套用貝葉斯公式排序
         ↓
步驟五：取前 5，標記信心不足（n < C/2）的店
```

> ⚠️ **常見錯誤**：搜尋 20 筆後只查部分詳細資料再挑選，
> 會導致「池子太小」，遺漏真正的好店。

---

## 四、實際案例：Day 1 竹南車站（19 家完整排序）

### 資料收集

- 終點：苗栗竹南車站
- 搜尋半徑：3 公里
- 搜尋筆數：19 筆（扣除重複）

### 批次 curl 指令（取得真實資料）

```bash
PLACES=(
  "ChIJkyfmh1CzaTQRqpYlWbi62b8"  # 夏川食堂
  "ChIJ1f4lmc2zaTQRB7vfP9JBE6g"  # 阿瑋饗聚食堂
  "ChIJCxzxGT2zaTQRKNGIiiwYSX4"  # 校友飯
  "ChIJR2sOH0WzaTQRXT28QHA1CH0"  # 無名湯包
  "ChIJo5xXZSOzaTQRGM2z2TlqIRI"  # 如珍小吃
  "ChIJh-AXNQCzaTQRF_HOvvH-vp8"  # 廣進傳統宵夜
  "ChIJo0NHknhNaDQR35-ZnpnbKnk"  # 阿婆小吃
  "ChIJFVI2Ji2zaTQRw3rb-UX256E"  # 上癮餐酒館
  "ChIJSbW2QD2zaTQRY7XKyy470no"  # 江記湯包
  "ChIJ7RK9nTyzaTQRq4RC028dM9I"  # 鮮肉湯包
  "ChIJfzqAqzyzaTQR10oNAb9IAac"  # 灶咖食堂
  "ChIJ-1XMKfGzaTQR92FzpHM_bwc"  # PJ&GRACE麵店
  "ChIJlfA36TuzaTQRWeNifdEKXjI"  # 滿意麵食坊
  "ChIJgT7rXSOzaTQRRRrVBqqfL2E"  # 金典小吃
  "ChIJM8eFRgCzaTQRJCXFh00zCgk"  # 阿湯哥脆皮蚵仔煎
  "ChIJ82JjM96zaTQRAg3qQSndoO0"  # 晶富小吃店
  "ChIJG7slgDyzaTQRY1pLgo1NF7I"  # 超好吃蚵仔煎
  "ChIJm_skDD2zaTQRyeotQ2UV2NM"  # 老北方舖子
  "ChIJByV_0D6zaTQR32nL7AMvKvU"  # 古錐蒸海鮮
)
KEY="YOUR_GOOGLE_MAPS_API_KEY"
for pid in "${PLACES[@]}"; do
  curl -s "https://maps.googleapis.com/maps/api/place/details/json\
?place_id=${pid}&fields=name,rating,user_ratings_total&key=${KEY}" \
  | python3 -c "
import sys, json
d = json.load(sys.stdin)['result']
print(f\"{d.get('rating','N/A'):4} {d.get('user_ratings_total','N/A'):>6}  {d.get('name','?')}\")"
done
```

### 原始資料（19 筆）

| 評分 | 留言數 | 店名 |
|---|---|---|
| 4.8 | 751 | 夏川食堂 |
| 4.6 | 830 | 上癮餐酒館 |
| 4.5 | 269 | 古錐蒸海鮮 |
| 4.6 | 120 | 如珍小吃 |
| 4.7 | 63 | 校友飯 |
| 5.0 | 29 | 阿婆小吃 |
| 4.7 | 48 | PJ&GRACE麵店 |
| 4.9 | 27 | 阿瑋饗聚食堂 |
| 4.5 | 119 | 鮮肉湯包 |
| 5.0 | 14 | 阿湯哥脆皮蚵仔煎 |
| 4.7 | 18 | 晶富小吃店 |
| 4.7 | 3 | 無名湯包 |
| 4.2 | 11 | 廣進傳統宵夜小吃 |
| 4.3 | 106 | 金典小吃 |
| 4.3 | 767 | 滿意麵食坊 |
| 4.2 | 186 | 超好吃蚵仔煎 |
| 4.2 | 756 | 灶咖食堂 |
| 4.2 | 1408 | 老北方舖子 |
| 3.9 | 541 | 江記湯包 |

### 貝葉斯計算過程

```python
# 參數計算
C = 平均留言數 = (751+830+269+120+63+29+48+27+119+14+18+3+11+106+767+186+756+1408+541) / 19
C ≈ 319

m = 加權平均評分 = Σ(rating × n) / Σ(n)
m ≈ 4.36

# 範例計算
夏川食堂：(319 × 4.36 + 4.8 × 751) / (319 + 751) = (1390.8 + 3604.8) / 1070 = 4.670
上癮餐酒館：(319 × 4.36 + 4.6 × 830) / (319 + 830) = (1390.8 + 3818) / 1149 = 4.534
阿婆小吃（5.0星僅29則）：(319 × 4.36 + 5.0 × 29) / (319 + 29) = (1390.8 + 145) / 348 = 4.416
```

### 貝葉斯排序結果

| 排名 | 貝葉斯分 | 評分 | 留言數 | 店名 | 信心 |
|---|---|---|---|---|---|
| 🏆 1 | **4.670** | 4.8 | 751 | **夏川食堂** | ✅ 高 |
| 🏆 2 | **4.534** | 4.6 | 830 | **上癮餐酒館** | ✅ 高 |
| 🏆 3 | **4.428** | 4.6 | 120 | **如珍小吃** | ⚠️ 偏低 |
| 🏆 4 | **4.426** | 4.5 | 269 | **古錐蒸海鮮** | ✅ 高 |
| 🏆 5 | **4.419** | 4.7 | 63 | **校友飯** | ⚠️ 偏低 |
| ❌ 6 | 4.416 | 5.0 | 29 | 阿婆小吃 | ⚠️ 偏低 |
| ❌ 8 | 4.405 | 4.9 | 27 | 阿瑋饗聚食堂 | ⚠️ 偏低 |

### 關鍵發現

> **上癮餐酒館（4.6 ★, 830 則）在原本的 5 筆流程中完全被遺漏！**
> 它的貝葉斯分 4.534 排第二，遠比多數「評分高但留言少」的店更可信。
> 而阿婆小吃（5.0 ★）、阿瑋饗聚（4.9 ★）雖然看起來更亮眼，
> 但因留言數不足，貝葉斯分都低於上癮餐酒館。

---

## 五、修改 Google Maps MCP 取得 `user_ratings_total`

### 問題根源

`@modelcontextprotocol/server-google-maps` 套件的 `handlePlaceDetails()` 與
`handlePlaceSearch()` 函式**硬編碼**了回傳欄位，完全沒有包含 `user_ratings_total`：

```js
// 原始碼（只回傳這些欄位）
return {
    name: data.result.name,
    formatted_address: data.result.formatted_address,
    rating: data.result.rating,      // ← 只有平均分
    reviews: data.result.reviews,    // ← 只有 5 則樣本
    opening_hours: data.result.opening_hours
    // user_ratings_total: 完全沒有！
}
```

### 修改方法

#### 找到檔案位置

```bash
find ~/.npm/_npx -name "index.js" -path "*server-google-maps*"
# 輸出範例：
# ~/.npm/_npx/2dedcb6c0f67fe6a/node_modules/@modelcontextprotocol/server-google-maps/dist/index.js
```

#### 確認要修改的行號

```bash
grep -n "rating\|user_ratings_total" ~/.npm/_npx/2dedcb6c0f67fe6a/node_modules/@modelcontextprotocol/server-google-maps/dist/index.js
# 輸出：
# 252:  rating: place.rating,           ← handlePlaceSearch 的 map
# 284:  rating: data.result.rating,     ← handlePlaceDetails 的 return
```

#### 執行修改（兩處 sed）

```bash
FILE="$HOME/.npm/_npx/2dedcb6c0f67fe6a/node_modules/@modelcontextprotocol/server-google-maps/dist/index.js"

# 修改 1：handlePlaceSearch（搜尋結果）
sed -i '' 's/                        rating: place\.rating,/                        rating: place.rating,\n                        user_ratings_total: place.user_ratings_total,/' "$FILE"

# 修改 2：handlePlaceDetails（單店詳細資料）
sed -i '' 's/                    rating: data\.result\.rating,/                    rating: data.result.rating,\n                    user_ratings_total: data.result.user_ratings_total,/' "$FILE"
```

#### 確認修改成功

```bash
grep -n "user_ratings_total" "$FILE"
# 應輸出：
# 253:  user_ratings_total: place.user_ratings_total,
# 286:  user_ratings_total: data.result.user_ratings_total,
```

#### 重啟 MCP Server

修改完成後，須在 **Kiro Feature Panel → MCP Servers → google-maps → Reconnect** 重啟，
修改才會生效。

### 備用方案：直接 curl Google Places API

若 MCP 重啟後仍無法取得，可直接用 curl 繞過 MCP：

```bash
curl -s "https://maps.googleapis.com/maps/api/place/details/json\
?place_id=ChIJkyfmh1CzaTQRqpYlWbi62b8\
&fields=name,rating,user_ratings_total\
&key=YOUR_API_KEY"

# 回傳範例：
# {
#   "result": {
#     "name": "夏川食堂",
#     "rating": 4.8,
#     "user_ratings_total": 751   ← 成功取得！
#   },
#   "status": "OK"
# }
```

> 💡 **注意**：`user_ratings_total` 需在 `fields` 參數中明確指定，
> 否則預設不回傳（會產生額外 API 費用）。

---

## 六、注意事項

1. **客單價（price_level）不可靠** — Google 的 `price_level` 欄位在台灣餐廳覆蓋率極低，多數小吃店根本沒填，不建議使用。
2. **貝葉斯 C 值視情境調整** — 觀光區（如墾丁）平均留言數高，C 值自然大；偏鄉小鎮（如太麻里）C 值小，標準相對寬鬆。
3. **MCP 套件更新風險** — 每次 `npx` 更新套件版本，修改會被覆蓋，需重新套用 sed 指令。
4. **Google Places API 費用** — `user_ratings_total` 屬於 Basic Data，每次 Place Details 請求約 $0.017 USD。批次查 20 筆約 $0.34，可接受。

---

*文件建立日期：2026-05-19*
*適用工具：Google Maps MCP `@modelcontextprotocol/server-google-maps`*

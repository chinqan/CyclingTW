# MCP 安裝手冊

本專案路線規劃依賴兩個 MCP server：

| 名稱 | 用途 | 執行方式 | 需要的 API key |
|---|---|---|---|
| `google-maps` | 地點搜尋、地理編碼、Place 詳細資料、路線查詢 | `npx` (Node.js) | `GOOGLE_MAPS_API_KEY` |
| `openroute-mcp` | 產生自行車 GPX 路線、可達區域、POI 搜尋 | `uvx` (Python) | `OPENROUTESERVICE_API_KEY` |

兩個 server 在 `scripts/plan.py` 流程中被反覆呼叫，缺一不可。本手冊覆蓋 **Claude Code (CLI)**、**Gemini Antigravity**、以及 **Cursor / Cline 等通用 MCP 客戶端**。

---

## 0. 前置需求

| 工具 | 用途 | 安裝建議 |
|---|---|---|
| Node.js ≥ 18 | 跑 `npx` 拉 `@cablate/mcp-google-map` | 用 `nvm` 安裝（本機為 v24.x，最低 18 即可） |
| Python ≥ 3.10 + `uv` | 跑 `uvx openroute-mcp` | `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Claude Code / Gemini Antigravity / Cursor | MCP 客戶端 | 擇一安裝 |

驗證：

```bash
node --version    # 應 >= v18
npx --version
uvx --version     # uv 內附；沒有就裝 uv
```

---

## 1. 取得 API key

### 1.1 Google Maps API key
1. 進 Google Cloud Console → 建立 / 選擇專案。
2. 啟用以下 API：**Maps JavaScript API、Places API (New)、Geocoding API、Directions API、Distance Matrix API、Elevation API、Time Zone API、Air Quality API、Weather API**（依本專案實際用到的工具）。
3. 「憑證」→ 建立 API 金鑰，建議加上 HTTP referrer / IP 限制。
4. 注意每月用量配額與計費帳號設定。

### 1.2 OpenRouteService API key
1. 註冊 https://openrouteservice.org/dev/#/signup。
2. Dashboard → Tokens → 建立新 token（免費方案每日 2000 次 routing 請求）。
3. 複製 token 字串。

> ⚠️ 本手冊範例一律用 `<YOUR_GOOGLE_MAPS_API_KEY>` / `<YOUR_OPENROUTESERVICE_API_KEY>` 佔位。實際金鑰請放在各客戶端 config 的 `env` 區段，**不要 commit 進 git**。

---

## 2. Claude Code (CLI) 安裝

最簡便的方式是用 `claude mcp add`，會寫入該 project 的 local scope（不影響其他專案）。

```bash
# 切到專案根目錄
cd /path/to/CyclingTW

# 1. google-maps
claude mcp add google-maps \
  -e GOOGLE_MAPS_API_KEY=<YOUR_GOOGLE_MAPS_API_KEY> \
  -- npx -y @cablate/mcp-google-map --stdio

# 2. openroute-mcp（--data-folder 必須是「絕對路徑」且資料夾存在）
mkdir -p "$(pwd)/data/generated_routes"
claude mcp add openroute-mcp \
  -e OPENROUTESERVICE_API_KEY=<YOUR_OPENROUTESERVICE_API_KEY> \
  -- uvx openroute-mcp --data-folder "$(pwd)/data/generated_routes"
```

驗證：

```bash
claude mcp list
# 應看到：
#   google-maps:   ✓ Connected
#   openroute-mcp: ✓ Connected

claude mcp get google-maps
claude mcp get openroute-mcp
```

權限：本專案 `.claude/settings.local.json` 已允許用到的工具（`maps_search_places`、`maps_directions`、`maps_place_details`、`create_route_from_to`）。若新增工具用法，請補進 allow list 或在執行時手動授權。

---

## 3. Gemini Antigravity 安裝

Antigravity 用 `~/.gemini/antigravity/mcp_config.json` 設定 MCP（或其 symlink 來源 `~/.gemini/config/mcp_config.json`）。直接編輯，加入下方範本：

```json
{
  "mcpServers": {
    "google-maps": {
      "command": "npx",
      "args": ["-y", "@cablate/mcp-google-map", "--stdio"],
      "env": {
        "GOOGLE_MAPS_API_KEY": "<YOUR_GOOGLE_MAPS_API_KEY>"
      }
    },
    "openroute-mcp": {
      "command": "uvx",
      "args": [
        "openroute-mcp==0.0.4",
        "--data-folder",
        "/絕對路徑/CyclingTW/data/generated_routes"
      ],
      "env": {
        "OPENROUTESERVICE_API_KEY": "<YOUR_OPENROUTESERVICE_API_KEY>"
      }
    }
  }
}
```

> 💡 `command` 用 `uvx` 即可（PATH 找得到就行）。`openroute-mcp==0.0.4` 鎖版是為了避免 §6 的本地 patch 被新版覆蓋。

寫入後重啟 Antigravity 視窗讓設定生效。

---

## 4. Cursor / Cline / 其他通用 MCP 客戶端

絕大多數客戶端使用同一份 `mcp.json` 格式（key 為 `mcpServers`），可直接套用第 3 節的 JSON。常見位置：

| 客戶端 | 設定檔位置 |
|---|---|
| Cursor | `~/.cursor/mcp.json`（或 Settings → MCP） |
| Cline (VSCode) | VSCode Settings → Cline → MCP Servers |
| Continue | `~/.continue/config.json` 內 `mcpServers` |
| 自製 client | 任何接受 stdio MCP 的工具皆可 |

把第 3 節的 JSON 整段貼進對應檔案的 `mcpServers` 物件下即可。

---

## 5. 注意事項與常見坑

### 5.1 路徑與資料夾
- **`openroute-mcp --data-folder` 必須是絕對路徑**，且資料夾需先建立（`mkdir -p`）。相對路徑會導致 server 啟動或寫檔失敗。
- 本專案約定 GPX 快取放 `data/generated_routes/`，且該目錄已在 `.gitignore`；換機器時不必拷貝歷史 GPX。

### 5.2 `npx` / `uvx` 首次執行較慢
- 第一次呼叫會下載套件，可能讓 MCP 啟動超時。先在 terminal 跑一次：
  ```bash
  npx -y @cablate/mcp-google-map --help    # 預載
  uvx openroute-mcp --help                  # 預載
  ```

### 5.3 API key 配額
- Google Maps：Places API (New) 跟舊版計費不同，注意 dashboard 上的 quota。
- OpenRouteService 免費方案：routing 每日 2000 次、每分鐘 40 次。本專案 `scripts/plan.py` 已內建節流；若手動連呼可能撞限額。

### 5.4 與 `scripts/plan.py` 的對應
- `plan.py parse-index` / `compute` / `write-csv` 不需 MCP（純本地計算）。
- 補點查詢階段需要 `mcp__google-maps__maps_search_places` 等工具。
- `gpx-append` 階段需要 `mcp__openroute-mcp__create_route_from_to`。
- 詳細規則寫在 `scripts/plan.py` 檔頭 docstring。

### 5.5 macOS / Linux / Windows 差異
- macOS / Linux：上述指令直接可用。
- Windows：建議在 WSL2 內安裝；原生 PowerShell 也行，但路徑分隔、`uvx` PATH 設定需自行處理。
- ARM Mac (M1/M2/M3)：Node 與 uv 都有原生 arm64 二進位，無需額外設定。

### 5.6 排錯流程
1. `claude mcp list` 看狀態。
2. 若顯示 `Failed to connect`，先 `claude mcp get <name>` 確認 command/env。
3. 用 terminal 手動跑 `npx -y @cablate/mcp-google-map --stdio` 或 `uvx openroute-mcp --data-folder ...`，看是否能啟動（會卡在等待 stdio，Ctrl+C 中止即可）。
4. 確認 API key 沒過期、沒打錯字、有開對應 API。
5. `--data-folder` 路徑是否存在、有寫入權限。

---

## 6. 本地修補（openroute-mcp `instructions=False`）

> ⚠️ 本機目前已對 `openroute-mcp 0.0.4` 套用一行 patch，**換機器時必須重做**，否則 GPX response 會塞回 `<extensions>` 區塊、size 翻倍、極端情況下會被 MCP envelope 截斷。

### 6.1 問題背景
`openroute-mcp` 預設呼叫 ORS Directions API 時不帶 `instructions` 參數（等同 `true`），ORS 會回每個 route point 的轉彎指引，產生大量 `<extensions>` 子節點塞進 GPX。對單車環島每日 80–120 km 的長路段而言：
- response 體積 ≈ 變 2 倍
- MCP stdio envelope 容易撞上限被截斷，導致 `gpx-append` 拿到不完整 XML

修法：呼叫 ORS 時加 `"instructions": False`，response 就只剩座標點，size 直接砍半。

### 6.2 Patch 位置與內容
檔案（uv cache，**不在 git 追蹤範圍**，影響限於本機）：
```
~/.cache/uv/archive-v0/<hash>/openroute_mcp/server.py
~/.cache/uv/archive-v0/<hash>/lib/python3.12/site-packages/openroute_mcp/server.py
```
本機目前有 **兩份** 副本（uv 對同一版本可能有多個 archive），兩份都要改。

Diff（在 `create_route_from_to` 函式內，約第 125–126 行）：
```python
# Before
json={"coordinates": coordinates},

# After
# PATCH (CyclingTW): instructions=False 去掉 per-rtept <extensions>，response size 減半，避免 MCP envelope 截斷
json={"coordinates": coordinates, "instructions": False},
```

### 6.3 Idempotency 檢查（重 patch 防呆）
重新部署或升級後，用 grep 一鍵判斷是否已修補：
```bash
grep -rn "PATCH (CyclingTW)" ~/.cache/uv/archive-v0/*/openroute_mcp/server.py \
  ~/.cache/uv/archive-v0/*/lib/python3.12/site-packages/openroute_mcp/server.py 2>/dev/null
```
- 每份 `server.py` 都列出一行 → 已套用，不要重複改。
- 有檔案沒列到 → 對那份重新 patch。

### 6.4 版本鎖（避免 uvx 自動升級把 patch 還原）
`uvx openroute-mcp` 預設會跑 cache 內**最新**版本。若日後 uv 拉到新版（例如 `0.0.5`），patch 就會消失。建議在 MCP config 內鎖死版本：

Claude Code：
```bash
claude mcp remove openroute-mcp -s local 2>/dev/null || true
claude mcp add openroute-mcp \
  -e OPENROUTESERVICE_API_KEY=<YOUR_OPENROUTESERVICE_API_KEY> \
  -- uvx openroute-mcp==0.0.4 --data-folder "$(pwd)/data/generated_routes"
```

Gemini Antigravity / Cursor / Cline 等 JSON config：
```json
"openroute-mcp": {
  "command": "uvx",
  "args": [
    "openroute-mcp==0.0.4",
    "--data-folder",
    "/絕對路徑/CyclingTW/data/generated_routes"
  ],
  "env": { "OPENROUTESERVICE_API_KEY": "<YOUR_OPENROUTESERVICE_API_KEY>" }
}
```

### 6.5 跨機器重現流程
1. 先按第 2 節用 `uvx openroute-mcp==0.0.4` 安裝一次（讓 uv 把套件解壓到 cache）。
2. 找出 cache 內所有 `server.py`：
   ```bash
   find ~/.cache/uv -name server.py -path "*openroute_mcp*"
   ```
3. 對每份檔案用 sed 套用 patch（idempotent，重跑安全）：
   ```bash
   for f in $(find ~/.cache/uv -name server.py -path "*openroute_mcp*"); do
     grep -q "PATCH (CyclingTW)" "$f" && continue
     python3 - "$f" <<'PY'
   import sys, pathlib
   p = pathlib.Path(sys.argv[1])
   src = p.read_text()
   old = 'json={"coordinates": coordinates},'
   new = ('        # PATCH (CyclingTW): instructions=False 去掉 per-rtept <extensions>，'
          'response size 減半，避免 MCP envelope 截斷\n'
          '        json={"coordinates": coordinates, "instructions": False},')
   if old in src and "PATCH (CyclingTW)" not in src:
       p.write_text(src.replace(old, new.lstrip() if False else new, 1))
       print("patched", p)
   PY
   done
   ```
4. 重啟 MCP client（Claude Code / Antigravity / Cursor），讓 server 重新 spawn。
5. 對任一條 day leg 重跑 `create_route_from_to`，驗證：
   - 產出 GPX 體積 ↓ ~50%
   - `grep '<extensions>' <gpx>` 應為空
   - `gpx-append` 不再因截斷失敗

### 6.6 已知風險
- `uvx openroute-mcp@latest` 或 `uv cache prune` 會清掉現有 archive，patch 隨之消失 → 重做 6.5。
- 若 ORS API 改版要求 `instructions` 須為 string，再評估改回。
- 不要把 patch 推上游：屬本專案場景特化（不需要轉彎指引，只要 polyline）。

---

## 7. 一鍵安裝腳本範本（選用）

複製貼上即可，把兩個 `<...>` 換成自己的 key：

```bash
#!/usr/bin/env bash
set -e

GMAP_KEY="<YOUR_GOOGLE_MAPS_API_KEY>"
ORS_KEY="<YOUR_OPENROUTESERVICE_API_KEY>"
DATA_DIR="$(pwd)/data/generated_routes"

mkdir -p "$DATA_DIR"

claude mcp remove google-maps   -s local 2>/dev/null || true
claude mcp remove openroute-mcp -s local 2>/dev/null || true

claude mcp add google-maps \
  -e GOOGLE_MAPS_API_KEY="$GMAP_KEY" \
  -- npx -y @cablate/mcp-google-map --stdio

claude mcp add openroute-mcp \
  -e OPENROUTESERVICE_API_KEY="$ORS_KEY" \
  -- uvx openroute-mcp --data-folder "$DATA_DIR"

claude mcp list
```

跑完看到兩個 `✓ Connected` 就完成。

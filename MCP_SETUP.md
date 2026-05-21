# MCP 安裝手冊

本專案路線規劃只依賴一個 MCP server：

| 名稱 | 用途 | 執行方式 | 需要的 API key |
|---|---|---|---|
| `google-maps` | 地點搜尋、地理編碼、Place 詳細資料、路線查詢 | `npx` (Node.js) | `GOOGLE_MAPS_API_KEY` |

> ⚠️ **OpenRouteService 不再走 MCP**。`scripts/plan.py route` 子命令直接走 HTTPS API（需 `ORS_API_KEY` 環境變數），詳見第 §2 節。
> 即使 client 列出 `mcp__openroute-mcp__*` 工具，**禁止呼叫**——一律用 `python3 scripts/plan.py route N`。

本手冊覆蓋 **Claude Code (CLI)**、**Gemini Antigravity**、以及 **Cursor / Cline 等通用 MCP 客戶端**。

---

## 0. 前置需求

| 工具 | 用途 | 安裝建議 |
|---|---|---|
| Node.js ≥ 18 | 跑 `npx` 拉 `@cablate/mcp-google-map` | 用 `nvm` 安裝（本機為 v24.x，最低 18 即可） |
| Python ≥ 3.10 | 跑 `scripts/plan.py` | `brew install python` 或 pyenv |
| Claude Code / Gemini Antigravity / Cursor | MCP 客戶端 | 擇一安裝 |

驗證：

```bash
node --version    # 應 >= v18
npx --version
python3 --version # 應 >= 3.10
```

---

## 1. 取得 API key

### 1.1 Google Maps API key（MCP 用）
1. 進 Google Cloud Console → 建立 / 選擇專案。
2. 啟用以下 API：**Maps JavaScript API、Places API (New)、Geocoding API、Directions API、Distance Matrix API、Elevation API、Time Zone API、Air Quality API、Weather API**（依本專案實際用到的工具）。
3. 「憑證」→ 建立 API 金鑰，建議加上 HTTP referrer / IP 限制。
4. 注意每月用量配額與計費帳號設定。

### 1.2 OpenRouteService API key（給 `plan.py` 用，**非 MCP**）
1. 註冊 https://openrouteservice.org/dev/#/signup。
2. Dashboard → Tokens → 建立新 token（免費方案每日 2000 次 routing 請求）。
3. 設為環境變數：
   ```bash
   export ORS_API_KEY='your-key-here'   # 建議寫進 ~/.zshrc
   ```
4. 驗證：`echo $ORS_API_KEY` 不為空即可。

> ⚠️ 本手冊範例一律用 `<YOUR_GOOGLE_MAPS_API_KEY>` / `<YOUR_OPENROUTESERVICE_API_KEY>` 佔位。實際金鑰請放在各客戶端 config 的 `env` 區段或 shell rc，**不要 commit 進 git**。

---

## 2. Claude Code (CLI) 安裝

最簡便的方式是用 `claude mcp add`，會寫入該 project 的 local scope（不影響其他專案）。

```bash
# 切到專案根目錄
cd /path/to/CyclingTW

# 只需要 google-maps
claude mcp add google-maps \
  -e GOOGLE_MAPS_API_KEY=<YOUR_GOOGLE_MAPS_API_KEY> \
  -- npx -y @cablate/mcp-google-map --stdio
```

驗證：

```bash
claude mcp list
# 應看到：
#   google-maps: ✓ Connected

claude mcp get google-maps
```

權限：本專案 `.claude/settings.local.json` 已允許用到的工具（`maps_search_places`、`maps_directions`、`maps_place_details`）。若新增工具用法，請補進 allow list 或在執行時手動授權。

> 若舊環境已 `claude mcp add openroute-mcp`，請執行 `claude mcp remove openroute-mcp -s local` 清掉，避免誤呼叫。

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
    }
  }
}
```

寫入後重啟 Antigravity 視窗讓設定生效。如果原有 config 內有 `openroute-mcp` 區塊請整段刪除。

---

## 4. Cursor / Cline / 其他通用 MCP 客戶端

絕大多數客戶端使用同一份 `mcp.json` 格式（key 為 `mcpServers`），可直接套用第 3 節的 JSON。常見位置：

| 客戶端 | 設定檔位置 |
|---|---|
| Cursor | `~/.cursor/mcp.json`（或 Settings → MCP） |
| Cline (VSCode) | VSCode Settings → Cline → MCP Servers |
| Continue | `~/.continue/config.json` 內 `mcpServers` |
| 自製 client | 任何接受 stdio MCP 的工具皆可 |

---

## 5. 注意事項與常見坑

### 5.1 `npx` 首次執行較慢
- 第一次呼叫會下載套件，可能讓 MCP 啟動超時。先在 terminal 跑一次預載：
  ```bash
  npx -y @cablate/mcp-google-map --help
  ```

### 5.2 API key 配額
- **Google Maps**：Places API (New) 跟舊版計費不同，注意 dashboard 上的 quota。
- **OpenRouteService**（給 `plan.py` 用）：免費方案 routing 每日 2000 次、每分鐘 40 次。本專案每天最多 1 次 `route` 呼叫，正常使用不會撞限額。

### 5.3 與 `scripts/plan.py` 的對應
- `plan.py parse-index` / `compute` / `write-csv` 不需 MCP（純本地計算）。
- 補點查詢階段需要 `mcp__google-maps__maps_search_places` 等工具。
- `plan.py route` 直接走 ORS HTTPS API（讀環境變數 `ORS_API_KEY`），**不經 MCP**。
- 詳細規則寫在 `scripts/plan.py` 檔頭 docstring 與 `scripts/README.md`。

### 5.4 macOS / Linux / Windows 差異
- macOS / Linux：上述指令直接可用。
- Windows：建議在 WSL2 內安裝；原生 PowerShell 也行，但路徑分隔、PATH 設定需自行處理。
- ARM Mac (M1/M2/M3)：Node 有原生 arm64 二進位，無需額外設定。

### 5.5 排錯流程
1. `claude mcp list` 看狀態。
2. 若顯示 `Failed to connect`，先 `claude mcp get google-maps` 確認 command/env。
3. 用 terminal 手動跑 `npx -y @cablate/mcp-google-map --stdio`，看是否能啟動（會卡在等待 stdio，Ctrl+C 中止即可）。
4. 確認 API key 沒過期、沒打錯字、有開對應 API。
5. `plan.py route` 報錯：先 `echo $ORS_API_KEY` 確認環境變數存在；常見原因見 `scripts/README.md` §「常見錯誤與排除」。

---

## 6. 一鍵安裝腳本範本（選用）

複製貼上即可，把兩個 `<...>` 換成自己的 key：

```bash
#!/usr/bin/env bash
set -e

GMAP_KEY="<YOUR_GOOGLE_MAPS_API_KEY>"
ORS_KEY="<YOUR_OPENROUTESERVICE_API_KEY>"

# 1. Claude Code MCP（只需 google-maps）
claude mcp remove google-maps   -s local 2>/dev/null || true
claude mcp remove openroute-mcp -s local 2>/dev/null || true   # 清掉舊版

claude mcp add google-maps \
  -e GOOGLE_MAPS_API_KEY="$GMAP_KEY" \
  -- npx -y @cablate/mcp-google-map --stdio

claude mcp list

# 2. ORS 金鑰（plan.py 用，建議改寫到 ~/.zshrc 持久化）
export ORS_API_KEY="$ORS_KEY"
echo "ORS_API_KEY 已 export 到當前 shell；持久化請手動加到 ~/.zshrc"
```

跑完看到 `google-maps: ✓ Connected` 就完成。

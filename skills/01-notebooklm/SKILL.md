---
name: antigravity-notebooklm
description: 在 AntiGravity 連接 NotebookLM MCP。說「連接 NotebookLM」「設定 NotebookLM」時載入。
---

# 連接 NotebookLM（AntiGravity 版）

## 步驟

### 1. 安裝
```bash
uv tool install notebooklm-mcp-cli
nlm --version
```

### 2. 登入
```bash
nlm login
```
（瀏覽器 OAuth，選正確的 Google 帳號）

### 3. 驗證
```bash
nlm doctor
nlm list
```
若 Windows 有編碼錯誤：`$env:PYTHONIOENCODING = "utf-8"`

### 4. 註冊 MCP
設定以 AntiGravity 的 MCP 設定檔為準：
```json
"notebooklm": {
  "type": "local",
  "command": ["nlm", "mcp"],
  "enabled": true
}
```

⚠️ 不要複製 cookie/token，不把筆記本清單 commit 到 repo。

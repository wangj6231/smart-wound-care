# Anti-Gravity 懶人包 #09：服務連接與工作流程設定

> 版本：v1.2
> 更新日期：2026-05-24
> 語系偏好：繁體中文（Taiwan）

這份懶人包的目標，是讓 Anti-Gravity 使用者能安全連接 NotebookLM、Firebase、GitHub，並建立「開工 / 收工 / 新專案初始化」工作流程。Obsidian 保留為人工維護的專案筆記與駕駛艙，不再安裝或註冊 MCPVault。

本文件只放可公開教學的設定流程，不放任何個人 NotebookLM 清單、筆記本 ID、研究報告、生成圖片、帳號 token 或測試專案。

---

## 先備條件

- [ ] 已安裝 Anti-Gravity 或可使用 MCP 的 AI 編碼助理
- [ ] 已安裝 Git
- [ ] 已安裝 GitHub CLI（`gh`）
- [ ] 已安裝 Node.js / npm
- [ ] 已安裝 Python 或 `uv`
- [ ] 有 Google 帳號，可登入 NotebookLM / Firebase
- [ ] 有 GitHub 帳號
- [ ] 若要搭配 Obsidian，已知道 vault 或專案筆記位置（本版不使用 MCPVault）

Windows 快速檢查：

```powershell
git --version
gh --version
node --version
npm.cmd --version
python --version
```

---

## 一、連接 NotebookLM

### 重點原則

NotebookLM 登入應走瀏覽器 OAuth 授權。不要複製 cookie、token，也不要把 NotebookLM 匯出的 `notebooks.json` 或筆記本 ID 清單放進公開 repo。

### 安裝 NotebookLM MCP CLI

建議優先用 `uv` 安裝：

```powershell
uv tool install notebooklm-mcp-cli
nlm --version
```

如果沒有 `uv`，再用 pip：

```powershell
pip install notebooklm-mcp-cli
nlm --version
```

### 重新登入 Google 帳號

若曾經登入錯帳號，先登出再重新 OAuth：

```powershell
nlm logout
nlm login
```

`nlm login` 會開啟瀏覽器，請在瀏覽器選擇正確的 Google 帳號完成授權。

驗證：

```powershell
nlm doctor
nlm list
```

如果 Windows 顯示 CP950 / Unicode 編碼錯誤，可在同一個 PowerShell 視窗先設定：

```powershell
$env:PYTHONIOENCODING = "utf-8"
nlm doctor
```

### 註冊 NotebookLM MCP

Anti-Gravity 的 MCP 設定檔位置請以實際產品文件或 UI 為準。不要直接套用 OpenCode 的 `opencode.json`，除非 Anti-Gravity 明確使用同一個設定檔。

通用設定概念：

```json
{
  "mcp": {
    "notebooklm": {
      "type": "local",
      "command": ["nlm", "mcp"],
      "enabled": true
    }
  }
}
```

完成後重啟 Anti-Gravity，請它列出 NotebookLM 筆記本。只回報是否成功，不要把完整清單 commit 到 repo。

---

## 二、連接 GitHub

### 登入 GitHub CLI

```powershell
gh auth status
gh auth login --web --git-protocol https
gh auth status
```

若登入流程卡住，請在可互動的 PowerShell 視窗完成瀏覽器授權，再回來驗證。

### 設定 Git 使用者

```powershell
git config --global user.name "你的名字"
git config --global user.email "your-email@example.com"
```

若不想公開個人信箱，可使用 GitHub no-reply email。

### 安全規則

- GitHub 與 GitHub Copilot 是不同服務；本流程只需要 GitHub 帳號、Git、GitHub CLI。
- 不把 GitHub token 寫進 Markdown、AGENTS、ANTIGRAVITY、Obsidian 對外筆記或 repo。
- commit 前先檢查 diff，不要無差別提交。

---

## 三、連接 Firebase

### 安裝與登入

Windows 建議使用 `npx.cmd`，避免 PowerShell 執行原則擋到 `.ps1`：

```powershell
npx.cmd -y firebase-tools@latest --version
npx.cmd -y firebase-tools@latest login
npx.cmd -y firebase-tools@latest projects:list
```

`firebase login` 需要互動式瀏覽器登入。如果在 AI 對話裡卡住，請手動開 PowerShell 執行登入，再回來讓 AI 驗證。

### 註冊 Firebase MCP

Anti-Gravity 的 MCP 設定檔位置請以實際產品文件或 UI 為準。設定概念如下：

```json
{
  "mcp": {
    "firebase": {
      "type": "local",
      "command": ["npx.cmd", "-y", "firebase-tools@latest", "mcp"],
      "enabled": true
    }
  }
}
```

完成後重啟 Anti-Gravity，測試列出 Firebase 專案與 Firestore 集合。

### 安全規則

- Firebase 前端 config 可公開，但 Admin SDK 憑證不可公開。
- `.firebaserc` 若含私人專案 ID，公開前請確認是否適合。
- 學生個人資料、密鑰等絕對不能 commit 到 Git 庫。

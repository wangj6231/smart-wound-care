---
name: antigravity-firebase
description: 在 AntiGravity 連接 Firebase MCP。說「連接 Firebase」「設定 Firebase」時載入。
---

# 連接 Firebase（AntiGravity 版）

## 步驟

### 1. 安裝與登入
```bash
npx.cmd -y firebase-tools@latest --version
npx.cmd -y firebase-tools@latest login
npx.cmd -y firebase-tools@latest projects:list
```

### 2. 註冊 MCP
```json
"firebase": {
  "type": "local",
  "command": ["npx.cmd", "-y", "firebase-tools@latest", "mcp"],
  "enabled": true
}
```

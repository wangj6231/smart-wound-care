---
name: antigravity-github
description: 在 AntiGravity 連接 GitHub CLI。說「連接 GitHub」「設定 GitHub」時載入。
---

# 連接 GitHub（AntiGravity 版）

## 步驟

### 1. 檢查
```bash
gh auth status
```

### 2. 登入
```bash
gh auth login --web --git-protocol https
```

### 3. 設定 Git 使用者
```bash
git config --global user.name "你的名字"
git config --global user.email "your-email@example.com"
```

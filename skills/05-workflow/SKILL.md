---
name: antigravity-workflow
description: AntiGravity 開工/收工/新專案初始化流程。說「開工」「收工」「初始化專案」時載入。
---

# 開工 / 收工 / 新專案初始化

## 開工
1. 讀取 `ANTIGRAVITY.md`
2. 讀取專案筆記重點
3. `git status` + 最近 commit
4. 回報狀態與建議下一步
5. 不自動 pull/commit/push

## 收工
1. 檢查敏感資料（API key、token、學生真名等）
2. 更新專案筆記（完成事項、下一步、踩坑）
3. 只在規則改變時更新 ANTIGRAVITY.md
4. 檢查 git status + diff
5. 只 stage 本次相關檔案（不用 `git add .`）
6. 確認後 commit + push

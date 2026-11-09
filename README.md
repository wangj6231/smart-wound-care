# 智慧傷口照護系統 (Smart Wound Care System)

本專案是一套整合 **FastAPI 後端**、**YOLO AI 傷口特徵辨識**、**Fernet 臨床病歷加密**與 **三端 Web 介面（管理員 / 護理師 / 病患）** 的全方位智慧醫療照護系統。

---

## 🔗 線上展示環境 (Live Demo)

- **系統入口網址**：[https://smart-wound-care.onrender.com/](https://smart-wound-care.onrender.com/)
- **服務狀態**：24/7 常駐在線（由 UptimeRobot 與 `/api/health` 心跳機制保活）

### 🔑 預設測試帳號（密碼皆為 `123456`）

| 角色名稱 | 登入帳號 | 預設密碼 | 核心功能介紹 |
| :--- | :--- | :--- | :--- |
| **系統管理員 (Admin)** | `admin01` | `123456` | 護病每日三班指派、人員帳號與臨床病歷管理、全院傷口紀錄稽核（比對 AI 與護理師判定差異） |
| **臨床護理師 (Nurse)** | `N001` / `N002` / `N003` | `123456` | 檢視今日負責病患、上傳傷口照片進行 AI 即時邊界偵測、填寫臨床分級與處置建議 |
| **就診病患 (Patient)** | `P001` / `P002` | `123456` | 查看個人歷史傷口照片與復原進度、傷口衛教專區（影片/專文）、智慧 AI 照護助理互動諮詢 |

---

## 🌟 核心功能特色

1. **👥 三端權限分流與安全驗證**
   - 採用 JWT (JSON Web Token) 進行身份驗證與 API 存取控制。
   - 單一登入入口（`/login.html`），登入後依角色自動導向專屬儀表板。

2. **🤖 YOLO AI 邊界標註與 T.I.M.E 臨床分級**
   - 整合 `yolo11m.onnx` 輕量化模型，於雲端即時框選傷口特徵區域並繪製標註影像。
   - 自動提供國際標準 **T.I.M.E 傷口評估指導**（組織 Tissue、感染 Infection、滲出液 Moisture、邊緣 Edge）。

3. **🩺 AI 與護理師雙軌評定 (Dual-Track Assessment)**
   - 護理師結合臨床經驗與 AI 建議進行綜合判定，自動依嚴重度切換病患健康狀態燈號（綠燈 / 黃燈 / 紅燈）。
   - 管理端提供專屬稽核介面，即時掌握 AI 預測與護理師判定一致性。

4. **🔒 醫療病歷個資加密 (EMR Security)**
   - 採用 `cryptography.fernet` 對病患的病床號、過敏史、重大病史等敏感資料進行對稱加密儲存，保障醫療隱私。

5. **💬 智慧 AI 照護助理 (`/api/chat`)**
   - 自動將病患最新歷次傷口評估紀錄注入上下文，提供高度客製化的日常護理建議；若本機 LLM 離線則具備標準臨床 Fallback 提示。

---

## 🏗️ 系統架構與技術棧

- **後端 API**：Python 3.10、FastAPI、Uvicorn、SQLAlchemy、PyMySQL、PyJWT、Cryptography
- **AI 推論**：ONNX Runtime（單執行緒 CPU 記憶體優化，防範 512MB RAM OOM）
- **前端介面**：原生 HTML5 / CSS3 / JavaScript、FontAwesome、Responsive Web Design
- **雲端資料庫**：Aiven Cloud MySQL（含 SSL 安全連線與自動表格遷移）
- **雲端部署**：Docker 容器化、Render Web Service

---

## 📂 專案目錄結構

```text
├── frontend/                     # 前端網頁介面
│   ├── login.html                # 系統登入頁
│   ├── admin_dashboard.html      # 管理員主控台
│   ├── admin_assignments.html    # 護病每日指派
│   ├── admin_history.html        # 全院傷口稽核歷程
│   ├── admin_users.html          # 使用者與病歷管理
│   ├── nurse_dashboard.html      # 護理師工作台
│   ├── wound_assessment.html     # 傷口拍照與雙軌評估
│   └── patient_dashboard.html    # 病患個人照護專區
├── main.py                       # FastAPI 核心伺服器與業務邏輯
├── yolo11m.onnx                  # 傷口辨識 AI 輕量化推論模型
├── requirements.txt              # 後端相依套件清單
├── Dockerfile                    # 雲端容器化建置腳本
├── start_project.bat             # 本地端一鍵啟動腳本
└── fix_password.py               # 帳號密碼維護工具
```

---

## 💻 本地端開發與啟動

1. **安裝相依套件**：
   ```bash
   pip install -r requirements.txt
   ```

2. **啟動本機服務**：
   - 雙擊執行根目錄的 `start_project.bat`，或於終端機執行：
   ```bash
   uvicorn main:app --host 127.0.0.1 --port 8000 --reload
   ```
3. 開啟瀏覽器訪問 `http://127.0.0.1:8000/login.html` 即可開始使用。

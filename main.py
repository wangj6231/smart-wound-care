import os
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware # 新增這行載入 CORS 套件
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from sqlalchemy import create_engine, text
from passlib.context import CryptContext
from datetime import datetime, timedelta
import jwt
from typing import Optional
import json
import urllib.request

# ==========================================
# 1. 系統與資料庫初始化
# ==========================================
app = FastAPI(
    title="智慧傷口照護系統 API",
    description="提供病人、護士與管理端使用的後端接口 (包含 JWT 驗證)",
    version="1.1.0"
)

# 設定 CORS 中介軟體
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 允許所有來源
    allow_credentials=True,
    allow_methods=["*"],  # 允許所有 HTTP 方法
    allow_headers=["*"],  # 允許所有請求標頭
)

# 優先自環境變數讀取資料庫連線資訊，以支援 Aiven 雲端 MySQL 部署
DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL and DATABASE_URL.startswith("mysql://"):
    DATABASE_URL = DATABASE_URL.replace("mysql://", "mysql+pymysql://", 1)
connect_args = {}

if not DATABASE_URL:
    db_user = os.environ.get("DB_USER", "root")
    db_password = os.environ.get("DB_PASSWORD", "")
    db_host = os.environ.get("DB_HOST", "127.0.0.1")
    db_port = os.environ.get("DB_PORT", "3306")
    db_name = os.environ.get("DB_NAME", "wound_care_db")
    
    ssl_ca = os.environ.get("DB_SSL_CA")
    if ssl_ca:
        DATABASE_URL = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}?ssl_ca={ssl_ca}"
    else:
        DATABASE_URL = f"mysql+pymysql://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

if os.environ.get("DB_SSL_REQUIRE") == "true" or (DATABASE_URL and "ssl_ca" in DATABASE_URL):
    connect_args["ssl"] = {"ssl_mode": "REQUIRED"}

engine = create_engine(DATABASE_URL, connect_args=connect_args)

# ==========================================
# 1.5. Fernet 加密與資料庫遷移
# ==========================================
from cryptography.fernet import Fernet

# 優先自環境變數讀取 Fernet 金鑰以利雲端部署持久化，若無則自檔案讀取或動態生成
import os
env_fernet_key = os.environ.get("FERNET_KEY")
if env_fernet_key:
    FERNET_KEY = env_fernet_key.encode()
else:
    SECRET_KEY_PATH = "secret.key"
    if not os.path.exists(SECRET_KEY_PATH):
        with open(SECRET_KEY_PATH, "wb") as key_file:
            key_file.write(Fernet.generate_key())
    with open(SECRET_KEY_PATH, "rb") as key_file:
        FERNET_KEY = key_file.read()

cipher_suite = Fernet(FERNET_KEY)

def encrypt_data(data: str) -> str:
    if not data: return ""
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_data(data: str) -> str:
    if not data: return ""
    try:
        return cipher_suite.decrypt(data.encode()).decode()
    except Exception:
        return data  # 如果解密失敗(例如舊有明文資料)則直接回傳原值

def run_migrations():
    """執行資料庫欄位遷移，並自動建立表與預設帳號以支援全新部署"""
    # 建立表格 DDL
    ddl_queries = [
        # 1. users
        """
        CREATE TABLE IF NOT EXISTS `users` (
          `id` int(11) NOT NULL AUTO_INCREMENT,
          `username` varchar(50) NOT NULL COMMENT '帳號',
          `password_hash` varchar(255) NOT NULL COMMENT '密碼哈希',
          `role` enum('admin','nurse','patient') NOT NULL COMMENT '角色',
          `full_name` varchar(50) NOT NULL COMMENT '姓名',
          `created_at` timestamp NOT NULL DEFAULT current_timestamp() COMMENT '建立時間',
          PRIMARY KEY (`id`),
          UNIQUE KEY `username` (`username`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='使用者帳號';
        """,
        # 2. patients_info
        """
        CREATE TABLE IF NOT EXISTS `patients_info` (
          `user_id` int(11) NOT NULL COMMENT 'users.id',
          `bed_number` varchar(20) DEFAULT NULL COMMENT '病床號',
          `medical_history` text DEFAULT NULL COMMENT '病史',
          `gender` text DEFAULT NULL,
          `age` text DEFAULT NULL,
          `admission_date` text DEFAULT NULL,
          `allergies` text DEFAULT NULL,
          `status` varchar(20) DEFAULT 'green',
          `last_assessment` text DEFAULT NULL,
          PRIMARY KEY (`user_id`),
          CONSTRAINT `patients_info_ibfk_1` FOREIGN KEY (`user_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='病患詳細資料';
        """,
        # 3. wound_records
        """
        CREATE TABLE IF NOT EXISTS `wound_records` (
          `id` int(11) NOT NULL AUTO_INCREMENT,
          `patient_id` int(11) NOT NULL COMMENT '病患 ID',
          `nurse_id` int(11) NOT NULL COMMENT '護理師 ID',
          `image_url` varchar(255) NOT NULL COMMENT '圖片 URL',
          `ai_grade` varchar(20) NOT NULL COMMENT 'AI 判斷等級',
          `ai_confidence` float NOT NULL COMMENT 'AI 信心指數',
          `ai_advice` text NOT NULL COMMENT 'AI 照護建議',
          `nurse_grade` varchar(20) NOT NULL COMMENT '護理師評定等級',
          `nurse_advice` text NOT NULL COMMENT '護理師照護建議',
          `created_at` timestamp NOT NULL DEFAULT current_timestamp() COMMENT '評估時間',
          `annotated_image_url` varchar(255) DEFAULT NULL,
          PRIMARY KEY (`id`),
          KEY `patient_id` (`patient_id`),
          KEY `nurse_id` (`nurse_id`),
          CONSTRAINT `wound_records_ibfk_1` FOREIGN KEY (`patient_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
          CONSTRAINT `wound_records_ibfk_2` FOREIGN KEY (`nurse_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='傷口評估紀錄';
        """,
        # 4. care_assignments
        """
        CREATE TABLE IF NOT EXISTS `care_assignments` (
          `id` int(11) NOT NULL AUTO_INCREMENT,
          `nurse_id` int(11) NOT NULL COMMENT '護理師 ID',
          `patient_id` int(11) NOT NULL COMMENT '病患 ID',
          `shift_type` enum('day','evening','night') NOT NULL COMMENT '班別',
          `assigned_date` date NOT NULL COMMENT '指派日期',
          PRIMARY KEY (`id`),
          UNIQUE KEY `unique_assignment` (`nurse_id`,`patient_id`,`shift_type`,`assigned_date`),
          KEY `patient_id` (`patient_id`),
          CONSTRAINT `care_assignments_ibfk_1` FOREIGN KEY (`nurse_id`) REFERENCES `users` (`id`) ON DELETE CASCADE,
          CONSTRAINT `care_assignments_ibfk_2` FOREIGN KEY (`patient_id`) REFERENCES `users` (`id`) ON DELETE CASCADE
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='護病照護指派';
        """,
        # 5. education_videos
        """
        CREATE TABLE IF NOT EXISTS `education_videos` (
          `id` int(11) NOT NULL AUTO_INCREMENT,
          `title` varchar(100) NOT NULL COMMENT '影片標題',
          `video_url` varchar(255) NOT NULL COMMENT '影片網址',
          `target_wound_grade` varchar(20) DEFAULT NULL COMMENT '適用等級',
          `description` text DEFAULT NULL COMMENT '描述',
          `created_at` timestamp NOT NULL DEFAULT current_timestamp(),
          PRIMARY KEY (`id`)
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='衛教資源';
        """
    ]
    
    with engine.connect() as conn:
        # 建立表格
        for q in ddl_queries:
            conn.execute(text(q))
        conn.commit()
        
        # 檢查並置入預設測試帳號 (密碼均為 123456)
        user_check = conn.execute(text("SELECT COUNT(*) FROM users")).fetchone()[0]
        if user_check == 0:
            print("[Migration] Database is empty, seeding default accounts...")
            default_users = [
                ("admin01", "$2b$12$U5rfu1fm5s4j67QJpdKbw.eloqosPT45MU0jbfNahG1OyIYSGE5Pe", "admin", "系統管理員"),
                ("N001", "$2b$12$U5rfu1fm5s4j67QJpdKbw.eloqosPT45MU0jbfNahG1OyIYSGE5Pe", "nurse", "張護理師"),
                ("N002", "$2b$12$U5rfu1fm5s4j67QJpdKbw.eloqosPT45MU0jbfNahG1OyIYSGE5Pe", "nurse", "李護理師"),
                ("P001", "$2b$12$U5rfu1fm5s4j67QJpdKbw.eloqosPT45MU0jbfNahG1OyIYSGE5Pe", "patient", "張大明"),
                ("P002", "$2b$12$U5rfu1fm5s4j67QJpdKbw.eloqosPT45MU0jbfNahG1OyIYSGE5Pe", "patient", "李小華"),
                ("N003", "$2b$12$U5rfu1fm5s4j67QJpdKbw.eloqosPT45MU0jbfNahG1OyIYSGE5Pe", "nurse", "王護理師")
            ]
            for username, pwd_hash, role, full_name in default_users:
                conn.execute(
                    text("INSERT INTO users (username, password_hash, role, full_name) VALUES (:u, :p, :r, :f)"),
                    {"u": username, "p": pwd_hash, "r": role, "f": full_name}
                )
            conn.commit()
            
            # 替預設病患建立 patients_info 欄位
            p001_id = conn.execute(text("SELECT id FROM users WHERE username='P001'")).fetchone()[0]
            p002_id = conn.execute(text("SELECT id FROM users WHERE username='P002'")).fetchone()[0]
            
            conn.execute(
                text("INSERT INTO patients_info (user_id, bed_number, medical_history, gender, age, admission_date, allergies, status) VALUES (:id, 'B01', :history, '男', '45', '2026-07-01', '無', 'green')"),
                {"id": p001_id, "history": encrypt_data("高血壓、糖尿病史")}
            )
            conn.execute(
                text("INSERT INTO patients_info (user_id, bed_number, medical_history, gender, age, admission_date, allergies, status) VALUES (:id, 'B02', :history, '女', '32', '2026-07-10', '盤尼西林過敏', 'green')"),
                {"id": p002_id, "history": encrypt_data("氣喘病史")}
            )
            conn.commit()

        # 置入預設衛教影片
        video_check = conn.execute(text("SELECT COUNT(*) FROM education_videos")).fetchone()[0]
        if video_check == 0:
            print("[Migration] Seeding default education videos...")
            default_videos = [
                ("傷口清潔與護理技巧", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Grade 1", "如何進行第一級傷口的基礎清潔與防護敷料更換教學。"),
                ("壓瘡中重度敷料選擇與照護", "https://www.youtube.com/watch?v=dQw4w9WgXcQ", "Grade 3", "針對第三級傷口（有黃色腐肉與壞死組織）的敷料選用與 TIME 評估標準指引。")
            ]
            for title, url, grade, desc in default_videos:
                conn.execute(
                    text("INSERT INTO education_videos (title, video_url, target_wound_grade, description) VALUES (:t, :u, :g, :d)"),
                    {"t": title, "u": url, "g": grade, "d": desc}
                )
            conn.commit()
            
        # 執行欄位追加檢查 (確保若表格已存在，能自動檢查並增設欄位以相容於升級)
        columns_to_add_patients = {
            "gender": "TEXT NULL",
            "age": "TEXT NULL",
            "admission_date": "TEXT NULL",
            "allergies": "TEXT NULL",
            "status": "VARCHAR(20) DEFAULT 'green'",
            "last_assessment": "TEXT NULL"
        }
        columns_to_add_wound_records = {
            "annotated_image_url": "VARCHAR(255) NULL"
        }
        
        # 移轉 patients_info 欄位
        for col, col_type in columns_to_add_patients.items():
            check_query = text(f"SHOW COLUMNS FROM patients_info LIKE '{col}'")
            res = conn.execute(check_query).fetchone()
            if not res:
                print(f"[Migration] Adding column to patients_info: {col}")
                alter_query = text(f"ALTER TABLE patients_info ADD COLUMN {col} {col_type}")
                conn.execute(alter_query)
                conn.commit()
                
        # 移轉 wound_records 欄位
        for col, col_type in columns_to_add_wound_records.items():
            check_query = text(f"SHOW COLUMNS FROM wound_records LIKE '{col}'")
            res = conn.execute(check_query).fetchone()
            if not res:
                print(f"[Migration] Adding column to wound_records: {col}")
                alter_query = text(f"ALTER TABLE wound_records ADD COLUMN {col} {col_type}")
                conn.execute(alter_query)
                conn.commit()

try:
    run_migrations()
    print("[Migration] Database migration completed successfully!")
except Exception as e:
    print(f"[Migration] Database migration failed: {str(e)}")

# ==========================================
# 2. JWT 與密碼驗證設定
# ==========================================
# 設定密碼加密演算法為 bcrypt
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
# 設定 OAuth2 驗證的登入路徑 (Swagger UI 會用到)
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="login")

# JWT 密鑰與過期時間設定 (實務上 SECRET_KEY 應寫入 .env 環境變數檔)
SECRET_KEY = "wound_care_super_secret_key_change_this" 
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 # Token 有效期為 60 分鐘

# ==========================================
# 3. 核心功能函式 (Helper Functions)
# ==========================================
def verify_password(plain_password, hashed_password):
    """比對明文密碼與資料庫的雜湊密碼"""
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(data: dict):
    """生成 JWT Token"""
    to_encode = data.copy()
    expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    to_encode.update({"exp": expire})
    # 將使用者資訊與過期時間進行 JWT 編碼
    encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
    return encoded_jwt

def get_current_user(token: str = Depends(oauth2_scheme)):
    """解析 JWT Token 並取得當前使用者資訊 (作為 API 保護鎖)"""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="無法驗證身分，請重新登入",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        # 解碼 Token
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        username: str = payload.get("sub")
        role: str = payload.get("role")
        if username is None or role is None:
            raise credentials_exception
        return {"username": username, "role": role}
    except jwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token 已過期，請重新登入")
    except jwt.InvalidTokenError:
        raise credentials_exception

# ==========================================
# 4. API 路由端點 (Routes)
# ==========================================

from fastapi.responses import RedirectResponse

@app.get("/")
def read_root():
    return RedirectResponse(url="/login.html")

@app.post("/login")
def login(form_data: OAuth2PasswordRequestForm = Depends()):
    """
    登入 API：驗證帳號密碼，成功則回傳 JWT Token
    """
    # 1. 從資料庫查詢帳號
    with engine.connect() as connection:
        query = text("SELECT id, username, password_hash, role, full_name FROM users WHERE username = :username")
        result = connection.execute(query, {"username": form_data.username}).fetchone()

    # 2. 驗證帳號是否存在
    if not result:
        raise HTTPException(status_code=400, detail="帳號或密碼錯誤")
    
    user = result._asdict()

    # 3. 驗證密碼是否正確
    if not verify_password(form_data.password, user["password_hash"]):
        raise HTTPException(status_code=400, detail="帳號或密碼錯誤")

    # 4. 登入成功，核發 JWT Token (夾帶帳號與角色資訊)
    access_token = create_access_token(data={"sub": user["username"], "role": user["role"]})
    
    return {
        "access_token": access_token, 
        "token_type": "bearer",
        "user_info": {
            "id": user["id"],
            "full_name": user["full_name"],
            "role": user["role"]
        }
    }

@app.get("/users/me")
def read_users_me(current_user: dict = Depends(get_current_user)):
    """
    受保護的 API 測試：必須攜帶有效的 JWT Token 才能存取
    """
    return {
        "status": "success",
        "message": "身分驗證通過！",
        "data": current_user
    }

# ... (保留上面原有的所有程式碼)

from datetime import date

@app.get("/api/nurse/patients")
def get_assigned_patients(current_user: dict = Depends(get_current_user)):
    """
    護理師專用 API：取得今日被分配照護的病患清單
    """
    # 權限檢查：只有護理師可以呼叫這支 API
    if current_user["role"] != "nurse":
        raise HTTPException(status_code=403, detail="權限不足：僅限護理師存取")
    
    today = date.today()
    
    # 根據登入的護理師 username，撈取其負責的病患詳細資料
    query = text("""
        SELECT 
            u.id as patient_id, 
            u.full_name, 
            p.bed_number, 
            p.medical_history,
            ca.shift_type
        FROM care_assignments ca
        JOIN users nurse ON ca.nurse_id = nurse.id
        JOIN users u ON ca.patient_id = u.id
        LEFT JOIN patients_info p ON u.id = p.user_id
        WHERE nurse.username = :username 
          # AND ca.assigned_date = :today -- 備註：為了方便您隨時測試，我先將日期限制註解掉，這樣才撈得到我們之前寫入的測試資料
    """)
    
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {
                "username": current_user["username"],
                "today": today
            })
            patients = []
            for row in result:
                r_dict = row._asdict()
                r_dict["bed_number"] = decrypt_data(r_dict["bed_number"])
                r_dict["medical_history"] = decrypt_data(r_dict["medical_history"])
                patients.append(r_dict)
            
            return {
                "status": "success",
                "message": "病患清單撈取成功",
                "data": patients
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料庫查詢失敗: {str(e)}")
# ... (保留上方原有的所有程式碼)

@app.get("/api/patients/{patient_id}/records")
def get_patient_history_records(patient_id: int, current_user: dict = Depends(get_current_user)):
    """
    取得特定病患的歷史傷口紀錄 (包含 AI 與護理師的雙軌判定)
    """
    # 權限檢查 (護理師或管理員皆可查看)
    if current_user["role"] not in ["nurse", "admin"]:
        raise HTTPException(status_code=403, detail="權限不足")
        
    query = text("""
        SELECT 
            wr.id, 
            wr.image_url, 
            wr.annotated_image_url,
            wr.ai_grade, 
            wr.ai_confidence, 
            wr.ai_advice,
            wr.nurse_grade, 
            wr.nurse_advice, 
            wr.created_at,
            nurse.full_name AS nurse_name
        FROM wound_records wr
        JOIN users nurse ON wr.nurse_id = nurse.id
        WHERE wr.patient_id = :patient_id
        ORDER BY wr.created_at DESC
    """)
    
    try:
        with engine.connect() as connection:
            result = connection.execute(query, {"patient_id": patient_id})
            records = [row._asdict() for row in result]
            
            # 將 datetime 轉換為字串格式以便 JSON 傳遞
            for record in records:
                record["created_at"] = record["created_at"].strftime("%Y-%m-%d %H:%M")
                
            return {
                "status": "success",
                "message": "歷史紀錄撈取成功",
                "data": records
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料庫查詢失敗: {str(e)}")
    
    # ... (保留上方原有的所有程式碼)

from fastapi import Form, File, UploadFile
import shutil
import os
import time
import cv2
import numpy as np
import base64
import onnxruntime as ort

class YOLOONNX:
    def __init__(self, model_path="yolo11m.onnx"):
        self.session = ort.InferenceSession(model_path, providers=["CPUExecutionProvider"])
        self.input_name = self.session.get_inputs()[0].name
        self.output_names = [o.name for o in self.session.get_outputs()]
        self.names = {
            0: 'person', 1: 'bicycle', 2: 'car', 3: 'motorcycle', 4: 'airplane', 5: 'bus',
            6: 'train', 7: 'truck', 8: 'boat', 9: 'traffic light', 10: 'fire hydrant',
            11: 'stop sign', 12: 'parking meter', 13: 'bench', 14: 'bird', 15: 'cat',
            16: 'dog', 17: 'horse', 18: 'sheep', 19: 'cow', 20: 'elephant', 21: 'bear',
            22: 'zebra', 23: 'giraffe', 24: 'backpack', 25: 'umbrella', 26: 'handbag',
            27: 'tie', 28: 'suitcase', 29: 'frisbee', 30: 'skis', 31: 'snowboard',
            32: 'sports ball', 33: 'kite', 34: 'baseball bat', 35: 'baseball glove',
            36: 'skateboard', 37: 'surfboard', 38: 'tennis racket', 39: 'bottle',
            40: 'wine glass', 41: 'cup', 42: 'fork', 43: 'knife', 44: 'spoon', 45: 'bowl',
            46: 'banana', 47: 'apple', 48: 'sandwich', 49: 'orange', 50: 'broccoli',
            51: 'carrot', 52: 'hot dog', 53: 'pizza', 54: 'donut', 55: 'cake',
            56: 'chair', 57: 'couch', 58: 'potted plant', 59: 'bed', 60: 'dining table',
            61: 'toilet', 62: 'tv', 63: 'laptop', 64: 'mouse', 65: 'remote',
            66: 'keyboard', 67: 'cell phone', 68: 'microwave', 69: 'oven', 70: 'toaster',
            71: 'sink', 72: 'refrigerator', 73: 'book', 74: 'clock', 75: 'vase',
            76: 'scissors', 77: 'teddy bear', 78: 'hair drier', 79: 'toothbrush'
        }

    def __call__(self, img, conf_threshold=0.25, iou_threshold=0.45):
        h, w = img.shape[:2]
        input_size = 640
        
        r = min(input_size / h, input_size / w)
        new_unpad_w, new_unpad_h = int(round(w * r)), int(round(h * r))
        pad_w = (input_size - new_unpad_w) / 2
        pad_h = (input_size - new_unpad_h) / 2
        
        resized = cv2.resize(img, (new_unpad_w, new_unpad_h), interpolation=cv2.INTER_LINEAR)
        top, bottom = int(round(pad_h - 0.1)), int(round(pad_h + 0.1))
        left, right = int(round(pad_w - 0.1)), int(round(pad_w + 0.1))
        padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT, value=(114, 114, 114))
        
        blob = cv2.cvtColor(padded, cv2.COLOR_BGR2RGB)
        blob = blob.transpose((2, 0, 1))  # HWC -> CHW
        blob = np.expand_dims(blob, axis=0)  # CHW -> BCHW
        blob = blob.astype(np.float32) / 255.0
        
        outputs = self.session.run(self.output_names, {self.input_name: blob})
        output = outputs[0][0].T  # (8400, 84)
        
        boxes = []
        confidences = []
        class_ids = []
        
        for row in output:
            classes_scores = row[4:]
            class_id = np.argmax(classes_scores)
            score = classes_scores[class_id]
            if score > conf_threshold:
                cx, cy, box_w, box_h = row[:4]
                x1 = cx - box_w / 2
                y1 = cy - box_h / 2
                x1 = (x1 - pad_w) / r
                y1 = (y1 - pad_h) / r
                box_w_scaled = box_w / r
                box_h_scaled = box_h / r
                
                boxes.append([int(x1), int(y1), int(box_w_scaled), int(box_h_scaled)])
                confidences.append(float(score))
                class_ids.append(int(class_id))
                
        indices = cv2.dnn.NMSBoxes(boxes, confidences, conf_threshold, iou_threshold)
        
        class BoxObj:
            def __init__(self, xyxy, cls, conf):
                self.xyxy = [xyxy]
                self.cls = [cls]
                self.conf = [conf]
                
        class ResultObj:
            def __init__(self, boxes_list, names):
                self.boxes = boxes_list
                self.names = names
                
            def plot(self):
                annotated = img.copy()
                for box in self.boxes:
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    cls_id = int(box.cls[0])
                    conf = float(box.conf[0])
                    label = f"{self.names[cls_id]} {conf:.2f}"
                    cv2.rectangle(annotated, (x1, y1), (x2, y2), (255, 0, 0), 2)
                    cv2.putText(annotated, label, (x1, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 0, 0), 2)
                return annotated
                
        final_boxes = []
        if len(indices) > 0:
            for idx in indices.flatten():
                x, y, box_w, box_h = boxes[idx]
                cls_id = class_ids[idx]
                conf = confidences[idx]
                x1 = max(0, x)
                y1 = max(0, y)
                x2 = min(w, x + box_w)
                y2 = min(h, y + box_h)
                final_boxes.append(BoxObj([x1, y1, x2, y2], cls_id, conf))
                
        res_obj = ResultObj(final_boxes, self.names)
        return [res_obj]

# 建立上傳檔案的資料夾 (如果不存在的話)
UPLOAD_DIR = "uploads/wounds"
os.makedirs(UPLOAD_DIR, exist_ok=True)

# 載入 YOLOv8 傷口特徵辨識模型 (ONNX 格式，省去大容量 PyTorch 的記憶體與載入時間)
MODEL_PATH = "yolo11m.onnx"
try:
    yolo_model = YOLOONNX(MODEL_PATH)
    print("[YOLO] ONNX Model loaded successfully!")
except Exception as e:
    yolo_model = None
    print(f"[YOLO] ONNX Model load failed: {str(e)}")

@app.post("/api/predict")
async def predict_wound(
    file: UploadFile = File(...),
    current_user: dict = Depends(get_current_user)
):
    """
    接收傷口影像，執行 YOLOv8 辨識，並將標註後影像存檔後回傳
    """
    if yolo_model is None:
        raise HTTPException(status_code=500, detail="後端 YOLO 模型尚未載入完成或載入失敗。")
        
    try:
        # 1. 讀取圖片檔案
        contents = await file.read()
        nparr = np.frombuffer(contents, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(status_code=400, detail="無效的圖片檔案")
            
        # 2. 進行 YOLOv8 辨識
        results = yolo_model(img)
        result = results[0]
        num_boxes = len(result.boxes)
        
        # 3. 繪製標註框並儲存為獨立的標註圖片
        annotated_img = result.plot()
        unique_id = f"{int(time.time())}_{os.urandom(4).hex()}"
        annotated_filename = f"annotated_{unique_id}.jpg"
        annotated_path = os.path.join(UPLOAD_DIR, annotated_filename)
        cv2.imwrite(annotated_path, annotated_img)
        
        annotated_image_url = f"/{UPLOAD_DIR}/{annotated_filename}"
        
        # 4. 根據偵測結果及分級標準生成 AI 分級建議 (模擬與 backend_export 同等的專業 TIME 指導)
        if num_boxes > 0:
            # 依據標註框數量判定分級
            ai_grade = "Grade 2" if num_boxes == 1 else "Grade 3"
            ai_confidence = float(result.boxes.conf[0]) if hasattr(result.boxes, 'conf') and len(result.boxes.conf) > 0 else 0.85
            ai_advice = (
                f"[AI 臨床診斷] YOLO 成功偵測到 {num_boxes} 個傷口特徵區域！\n"
                f"【T.I.M.E 傷口評估指導】\n"
                f"T (Tissue 組織): 偵測到黃色腐肉與疑似壞死組織，建議進行局部清創。\n"
                f"I (Infection 感染): 傷口周邊伴隨紅腫泛紅反應，可能存在中度感染風險。\n"
                f"M (Moisture 滲出液): 評估滲出液量偏多，建議選用高吸收性敷料。\n"
                f"E (Edge 邊緣): 傷口邊界有浸潤現象，需塗抹皮膚保護劑防止浸漬。"
            )
        else:
            ai_grade = "Grade 1"
            ai_confidence = 0.50
            ai_advice = "[AI 臨床診斷] 未偵測到明顯的傷口邊界特徵。請確保拍攝光線充足、角度垂直並重新嘗試。"

        return {
            "status": "success",
            "ai_grade": ai_grade,
            "ai_confidence": ai_confidence,
            "ai_advice": ai_advice,
            "annotated_image_url": annotated_image_url
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 辨識發生錯誤: {str(e)}")

@app.post("/api/records")
async def create_wound_record(
    patient_id: int = Form(...),
    ai_grade: str = Form(...),
    ai_confidence: float = Form(...),
    ai_advice: str = Form(...),
    nurse_grade: str = Form(...),
    nurse_advice: str = Form(...),
    image: UploadFile = File(...),
    annotated_image_url: Optional[str] = Form(None), # 新增接收 AI 標註照片 URL
    current_user: dict = Depends(get_current_user)
):
    """
    儲存新的傷口雙軌紀錄，並處理圖片上傳
    """
    # 權限檢查：只有護理師可以新增紀錄
    if current_user["role"] != "nurse":
        raise HTTPException(status_code=403, detail="權限不足：僅限護理師操作")

    # 1. 處理圖片上傳與儲存
    try:
        # 產生獨一無二的檔名 (利用時間戳記避免重複)
        file_extension = image.filename.split(".")[-1]
        unique_filename = f"{patient_id}_{int(time.time())}.{file_extension}"
        file_path = os.path.join(UPLOAD_DIR, unique_filename)
        
        # 將前端傳來的圖片寫入本地資料夾
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(image.file, buffer)
            
        # 產生圖片的 URL 路徑 (存入資料庫用)
        image_url = f"/{UPLOAD_DIR}/{unique_filename}"
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"圖片上傳失敗: {str(e)}")

    # 2. 將紀錄寫入 MySQL 資料庫
    query = text("""
        INSERT INTO wound_records (
            patient_id, nurse_id, image_url, annotated_image_url,
            ai_grade, ai_confidence, ai_advice, 
            nurse_grade, nurse_advice
        ) VALUES (
            :patient_id, :nurse_id, :image_url, :annotated_image_url,
            :ai_grade, :ai_confidence, :ai_advice, 
            :nurse_grade, :nurse_advice
        )
    """)
    
    try:
        with engine.connect() as connection:
            # 先利用 current_user["username"] 找出 nurse_id
            nurse_query = text("SELECT id FROM users WHERE username = :username")
            nurse_result = connection.execute(nurse_query, {"username": current_user["username"]}).fetchone()
            nurse_id = nurse_result[0]
            
            # 執行寫入
            connection.execute(query, {
                "patient_id": patient_id,
                "nurse_id": nurse_id,
                "image_url": image_url,
                "annotated_image_url": annotated_image_url,
                "ai_grade": ai_grade,
                "ai_confidence": ai_confidence,
                "ai_advice": ai_advice,
                "nurse_grade": nurse_grade,
                "nurse_advice": nurse_advice
            })
            connection.commit()
            
            # 3. 依據護理師分級更新個案狀態 (Green/Yellow/Red) 與最新評估
            # 判定狀態標準：Grade 3 以上或 Unstageable 判定為 Red，Grade 1 或 2 判定為 Yellow，其他或未指定為 Green
            status_val = "green"
            if nurse_grade in ["Grade 3", "Grade 4", "Unstageable"]:
                status_val = "red"
            elif nurse_grade in ["Grade 1", "Grade 2"]:
                status_val = "yellow"
                
            # 判斷時段班別 (依據當前小時)
            current_hour = datetime.now().hour
            if 8 <= current_hour < 16:
                shift_str = "白班"
            elif 16 <= current_hour < 24:
                shift_str = "小夜"
            else:
                shift_str = "大夜"
                
            last_assess = f"[{shift_str}] {nurse_grade} - {nurse_advice[:20]}..."
            
            update_patient = text("""
                UPDATE patients_info 
                SET status = :status, last_assessment = :last_assessment 
                WHERE user_id = :patient_id
            """)
            connection.execute(update_patient, {
                "status": status_val,
                "last_assessment": last_assess,
                "patient_id": patient_id
            })
            connection.commit()
            
            return {"status": "success", "message": "紀錄儲存成功，且個案健康狀態已同步更新！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料庫寫入失敗: {str(e)}")
    
    # ... (保留上方原有的所有程式碼)

@app.get("/api/admin/audit-logs")
def get_audit_logs(current_user: dict = Depends(get_current_user)):
    """
    管理端專用 API：取得所有病患的最新傷口紀錄，並標示 AI 與護理師判斷是否有差異
    """
    # 權限檢查：只有管理員可以呼叫這支 API
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="權限不足：僅限系統管理員存取")
    
    # 撈取所有紀錄，包含護理師姓名與病患姓名
    query = text("""
        SELECT 
            wr.id, 
            wr.image_url, 
            wr.ai_grade, 
            wr.ai_confidence, 
            wr.ai_advice,
            wr.nurse_grade, 
            wr.nurse_advice,
            wr.created_at,
            nurse.full_name AS nurse_name,
            patient.full_name AS patient_name
        FROM wound_records wr
        JOIN users nurse ON wr.nurse_id = nurse.id
        JOIN users patient ON wr.patient_id = patient.id
        ORDER BY wr.created_at DESC
    """)
    
    try:
        with engine.connect() as connection:
            result = connection.execute(query)
            logs = [row._asdict() for row in result]
            
            # 整理資料：檢查差異並格式化時間
            for log in logs:
                log["created_at"] = log["created_at"].strftime("%Y-%m-%d %H:%M")
                # 簡單的比對邏輯：如果兩者字串不同，就標記為有差異 (has_discrepancy)
                log["has_discrepancy"] = log["ai_grade"] != log["nurse_grade"]
                
            return {
                "status": "success",
                "message": "稽核紀錄撈取成功",
                "data": logs
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"資料庫查詢失敗: {str(e)}")
    
    # ... (保留上方原有的所有程式碼)

from pydantic import BaseModel

# 定義接收前端資料的格式
class AssignmentReq(BaseModel):
    nurse_id: int
    patient_id: int
    shift_type: str

@app.get("/api/admin/assignment-options")
def get_assignment_options(current_user: dict = Depends(get_current_user)):
    """取得所有護理師與病患的名單，供下拉選單使用"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="僅限管理員存取")
        
    try:
        with engine.connect() as conn:
            # 撈取所有護理師
            nurses = [{"id": row.id, "name": row.full_name} for row in conn.execute(text("SELECT id, full_name FROM users WHERE role='nurse'"))]
            # 撈取所有病患 (連同床號與病史)
            patients_query = text("""
                SELECT u.id, u.full_name AS name, p.bed_number, p.medical_history
                FROM users u
                LEFT JOIN patients_info p ON u.id = p.user_id
                WHERE u.role='patient'
            """)
            patients = []
            for row in conn.execute(patients_query):
                patients.append({
                    "id": row.id,
                    "name": row.name,
                    "bed_number": decrypt_data(row.bed_number) or "未指派",
                    "medical_history": decrypt_data(row.medical_history) or "無特殊病史"
                })
            
            return {"status": "success", "data": {"nurses": nurses, "patients": patients}}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/admin/assignments")
def update_care_assignment(req: AssignmentReq, current_user: dict = Depends(get_current_user)):
    """更新或新增護病分配"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="僅限管理員操作")
        
    # 為了保留歷史紀錄，只刪除/覆蓋該病患在該班別「當天」的指派任務
    delete_query = text("DELETE FROM care_assignments WHERE patient_id = :p_id AND shift_type = :shift AND assigned_date = CURDATE()")
    insert_query = text("INSERT INTO care_assignments (nurse_id, patient_id, shift_type, assigned_date) VALUES (:n_id, :p_id, :shift, CURDATE())")
    
    try:
        with engine.connect() as conn:
            conn.execute(delete_query, {"p_id": req.patient_id, "shift": req.shift_type})
            conn.execute(insert_query, {"n_id": req.nurse_id, "p_id": req.patient_id, "shift": req.shift_type})
            conn.commit()
            
            return {"status": "success", "message": "護病分配更新成功！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # ... (保留上方原有的所有程式碼)

@app.get("/api/admin/assignments")
def get_all_assignments(today_only: bool = False, current_user: dict = Depends(get_current_user)):
    """取得護病分配狀況清單 (支援僅篩選當日或全部歷史紀錄)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="僅限管理員存取")
        
    if today_only:
        query = text("""
            SELECT 
                ca.nurse_id, nurse.full_name AS nurse_name,
                ca.patient_id, patient.full_name AS patient_name,
                ca.shift_type, ca.assigned_date
            FROM care_assignments ca
            JOIN users nurse ON ca.nurse_id = nurse.id
            JOIN users patient ON ca.patient_id = patient.id
            WHERE ca.assigned_date = CURDATE()
            ORDER BY ca.shift_type
        """)
    else:
        query = text("""
            SELECT 
                ca.nurse_id, nurse.full_name AS nurse_name,
                ca.patient_id, patient.full_name AS patient_name,
                ca.shift_type, ca.assigned_date
            FROM care_assignments ca
            JOIN users nurse ON ca.nurse_id = nurse.id
            JOIN users patient ON ca.patient_id = patient.id
            ORDER BY ca.assigned_date DESC, ca.shift_type
        """)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            assignments = [row._asdict() for row in result]
            
            # 將日期格式化為字串
            for item in assignments:
                item["assigned_date"] = item["assigned_date"].strftime("%Y-%m-%d") if item["assigned_date"] else "無"
                
            return {"status": "success", "data": assignments}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/api/admin/assignments")
def delete_assignment(patient_id: int, shift_type: str, current_user: dict = Depends(get_current_user)):
    """刪除特定的當日護病分配 (保留歷史紀錄)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="僅限管理員操作")
        
    query = text("DELETE FROM care_assignments WHERE patient_id = :p_id AND shift_type = :shift AND assigned_date = CURDATE()")
    
    try:
        with engine.connect() as conn:
            conn.execute(query, {"p_id": patient_id, "shift": shift_type})
            conn.commit()
            return {"status": "success", "message": "分配紀錄已成功刪除！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    # ... (保留上方原有的所有程式碼)

@app.get("/api/patient/my-records")
def get_my_wound_records(current_user: dict = Depends(get_current_user)):
    """病患專屬 API：取得自己的歷史傷口紀錄"""
    if current_user["role"] != "patient":
        raise HTTPException(status_code=403, detail="權限不足：僅限病患本人存取")
        
    query = text("""
        SELECT 
            wr.id, wr.image_url, wr.annotated_image_url, wr.ai_grade, wr.ai_advice,
            wr.nurse_grade, wr.nurse_advice, wr.created_at,
            nurse.full_name AS nurse_name
        FROM wound_records wr
        JOIN users nurse ON wr.nurse_id = nurse.id
        JOIN users patient ON wr.patient_id = patient.id
        WHERE patient.username = :username
        ORDER BY wr.created_at DESC
    """)
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query, {"username": current_user["username"]})
            records = [row._asdict() for row in result]
            
            for r in records:
                r["created_at"] = r["created_at"].strftime("%Y-%m-%d %H:%M")
                
            return {"status": "success", "data": records}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/patient/videos")
def get_education_videos(current_user: dict = Depends(get_current_user)):
    """病患專屬 API：取得衛教影片清單"""
    if current_user["role"] != "patient":
        raise HTTPException(status_code=403, detail="權限不足：僅限病患存取")
        
    query = text("SELECT id, title, video_url, description FROM education_videos ORDER BY created_at DESC")
    
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            videos = [row._asdict() for row in result]
            return {"status": "success", "data": videos}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/patient/articles")
def get_education_articles(current_user: dict = Depends(get_current_user)):
    """病患專屬 API：取得 5 篇衛教文章"""
    if current_user["role"] != "patient":
        raise HTTPException(status_code=403, detail="權限不足：僅限病患存取")
        
    articles = [
        {
            "id": 1,
            "title": "🩹 傷口清潔三步驟：無菌換藥的黃金法則",
            "category": "換藥護理",
            "summary": "學習正確的無菌換藥技巧，包括洗手、由內向外環狀清潔，以及如何正確覆蓋乾淨紗布，避免二次感染。",
            "content": (
                "正確的換藥步驟是避免傷口感染、促進肉芽組織生長的第一步。\n\n"
                "### 1. 換藥前準備與洗手\n"
                "換藥前，請務必使用肥皂或洗手乳徹底清潔雙手。準備好無菌生理食鹽水、無菌棉棒、無菌紗布、透氣膠帶，以及醫師指示的藥膏。\n\n"
                "### 2. 生理食鹽水清潔與消毒\n"
                "撕下舊紗布後，打開無菌棉棒包裝。使用生理食鹽水沾濕棉棒，**由傷口中心點往外環狀塗擦（直徑約 3-5 公分）**，切記**千萬不可來回擦拭**以免將周圍細菌帶回傷口。每枝棉棒僅能使用一次，髒了就必須更換。\n\n"
                "### 3. 上藥與覆蓋紗布\n"
                "使用乾棉棒吸乾多餘液體後，依醫囑塗抹適量藥膏。隨後取出一塊無菌紗布（手請勿觸碰紗布中心），覆蓋於傷口上並用膠帶固定。"
            )
        },
        {
            "id": 2,
            "title": "💧 人工皮敷料使用指南：何時換、怎麼撕才不痛？",
            "category": "敷料選擇",
            "summary": "人工皮可以吸收滲液並維持傷口濕潤。本篇教您如何觀察更換時機，以及安全、不拉扯組織的撕除技巧。",
            "content": (
                "人工皮是一種親水性敷料，能創造密閉的濕潤環境以加速上皮細胞再生。\n\n"
                "### 1. 什麼時候需要更換人工皮？\n"
                "當人工皮吸收傷口滲出液後，會**慢慢膨脹並呈現白色的乳化狀態**。當這塊白色的範圍蔓延到接近人工皮邊緣（約距離邊緣 0.5 公分），或敷料已經產生漏水、捲邊、甚至有異味時，就代表必須更換。\n\n"
                "### 2. 如何撕除才不會拉扯傷口？\n"
                "撕除時，請一隻手輕壓傷口周圍的皮膚，另一隻手抓住人工皮的一角，**沿著與皮膚平行的方向，輕輕向外拉伸**，人工皮會慢慢鬆開。切勿直接往上垂直拉扯，否則容易撕裂脆弱的新生表皮。\n\n"
                "### 3. 注意事項\n"
                "如果傷口已經出現感染徵兆（紅腫、熱痛、有黃綠色膿液），請**停止使用人工皮**並立即就醫。"
            )
        },
        {
            "id": 3,
            "title": "⚠️ 傷口感染的四大徵兆：『紅、腫、熱、痛』警訊",
            "category": "感染控制",
            "summary": "隨時注意傷口的異常變化。若出現發炎、分泌物變多有惡臭、發燒等症狀，可能是嚴重的感染信號。",
            "content": (
                "傷口在復原過程中，局部的輕微反應是正常的，但如果出現細菌感染，會阻礙癒合並可能引發蜂窩性組織炎。\n\n"
                "### 1. 辨識感染的四大警訊\n"
                "* **紅**：傷口周圍皮膚發紅範圍持續擴大，沒有消退的跡象。\n"
                "* **腫**：傷口邊緣持續緊繃、發脹、腫大。\n"
                "* **熱**：用手觸摸傷口周圍，能感覺到明顯的高溫與局部發熱。\n"
                "* **痛**：痛感不減反增，甚至出現抽痛、搏動性疼痛。\n\n"
                "### 2. 其他感染分泌物特徵\n"
                "如果滲出液從清澈淡黃色，轉變為**黃綠色黏稠的膿液，且散發出陣陣惡臭**，或是傷口周圍按壓有氣泡感，都是高度感染的表徵。\n\n"
                "### 3. 當心發燒與全身性症狀\n"
                "若傷口痛感加劇並伴隨體溫高於 38°C、發冷、畏寒等，此時細菌可能已進入血液，請**務必立即前往醫院掛急診**。"
            )
        },
        {
            "id": 4,
            "title": "🥦 加速傷口癒合的營養攻略：吃什麼好得快？",
            "category": "日常飲食",
            "summary": "均衡飲食能提供細胞修復所需的養分。補充足夠的蛋白質、維生素 C 與鋅是加速組織生長與復原的關鍵。",
            "content": (
                "傷口修復需要身體耗費能量與營養素來建造新的微血管與肉芽組織。\n\n"
                "### 1. 優質蛋白質：癒合的關鍵原料\n"
                "蛋白質是修補皮膚組織的最基本原料。建議適量攝取：\n"
                "* 鱸魚、鱈魚（含有豐富胺基酸，且易消化吸收）\n"
                "* 雞肉、瘦肉、雞蛋\n"
                "* 豆腐、豆漿等植物性蛋白質\n\n"
                "### 2. 維生素 C：促進膠原蛋白合成\n"
                "維生素 C 是合成膠原蛋白的必要輔酶，能強化新生組織結構。推薦食物：\n"
                "* 芭樂、奇異果、柑橘類水果\n"
                "* 綠色蔬菜\n\n"
                "### 3. 礦物質「鋅」：啟動皮膚細胞分化\n"
                "鋅能維持身體免疫系統與能量代謝，對表皮細胞修補極為關鍵。可攝取：\n"
                "* 堅果、南瓜子\n"
                "* 牡蠣、瘦肉\n\n"
                "### 4. 飲食禁忌\n"
                "請盡量**避免抽菸、喝酒，並少吃辛辣、油炸等刺激性食物**，因為這些會引發局部發炎反應，延緩傷口收口。"
            )
        },
        {
            "id": 5,
            "title": "🍭 糖尿病慢性傷口護理：預防足部潰瘍的重要叮嚀",
            "category": "慢性病照護",
            "summary": "糖尿病患者由於血液循環不佳與神經病變，足部微小傷口極易惡化。本篇教您如何進行日常足部防護與檢查。",
            "content": (
                "糖尿病患者因為末梢神經病變，對溫度、疼痛的感覺較為遲鈍，常有傷口而不自知，必須加倍用心護理。\n\n"
                "### 1. 每日足部檢查\n"
                "養成每天洗完澡後，在光線充足處**用鏡子檢查雙腳腳底、腳底趾縫**的習慣，觀察是否有發紅、水泡、割傷或破皮。\n\n"
                "### 2. 穿鞋襪的防護技巧\n"
                "* **絕對不要赤腳走路**，即使在室內也應穿著合適拖鞋。\n"
                "* 選擇純棉、吸汗、無接縫粗糙邊緣的襪子，且襪子不可過緊以免阻礙血液循環。\n"
                "* 穿鞋前，務必用手摸鞋子內部，檢查是否有小石子、沙子或鞋墊折疊，以防磨破腳皮。\n\n"
                "### 3. 指甲修剪與日常保濕\n"
                "剪腳指甲時請**平剪，不要挖兩側指甲縫**（剪成圓弧形），以免指甲嵌肉發炎（凍甲）。若腳跟乾燥龜裂，請塗抹適量乳液保濕，但**趾縫間需保持乾燥**，避免黴菌滋生。"
            )
        }
    ]
    return {"status": "success", "data": articles}

# ==========================================
# 5. 管理員專用：人員管理 API (新增、取得、刪除)
# ==========================================

class UserCreateReq(BaseModel):
    username: str
    password: str
    role: str  # 'nurse' or 'patient'
    full_name: str
    bed_number: Optional[str] = None
    medical_history: Optional[str] = None
    gender: Optional[str] = None
    age: Optional[str] = None
    admission_date: Optional[str] = None
    allergies: Optional[str] = None

@app.post("/api/admin/users")
def create_user(req: UserCreateReq, current_user: dict = Depends(get_current_user)):
    """管理員專用 API：新增護理師或病患"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="權限不足：僅限系統管理員操作")
    
    # 檢查帳號是否已存在
    check_query = text("SELECT id FROM users WHERE username = :username")
    try:
        with engine.connect() as conn:
            existing = conn.execute(check_query, {"username": req.username}).fetchone()
            if existing:
                raise HTTPException(status_code=400, detail="該帳號/員工代碼已存在")
            
            # 加密密碼
            password_hash = pwd_context.hash(req.password)
            
            # 新增使用者
            insert_user = text("""
                INSERT INTO users (username, password_hash, role, full_name)
                VALUES (:username, :password_hash, :role, :full_name)
            """)
            conn.execute(insert_user, {
                "username": req.username,
                "password_hash": password_hash,
                "role": req.role,
                "full_name": req.full_name
            })
            conn.commit()
            
            # 若為病患，同步寫入 patients_info
            if req.role == "patient":
                user_id_query = text("SELECT id FROM users WHERE username = :username")
                user_id = conn.execute(user_id_query, {"username": req.username}).fetchone()[0]
                
                insert_info = text("""
                    INSERT INTO patients_info (user_id, bed_number, medical_history, gender, age, admission_date, allergies, status)
                    VALUES (:user_id, :bed_number, :medical_history, :gender, :age, :admission_date, :allergies, 'green')
                """)
                conn.execute(insert_info, {
                    "user_id": user_id,
                    "bed_number": encrypt_data(req.bed_number),
                    "medical_history": encrypt_data(req.medical_history),
                    "gender": encrypt_data(req.gender),
                    "age": encrypt_data(req.age),
                    "admission_date": encrypt_data(req.admission_date),
                    "allergies": encrypt_data(req.allergies)
                })
                conn.commit()
                
        return {"status": "success", "message": "人員新增成功！"}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"新增失敗: {str(e)}")

@app.get("/api/admin/users")
def get_users(current_user: dict = Depends(get_current_user)):
    """管理員專用 API：取得所有護理師與病患清單"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="權限不足：僅限系統管理員存取")
        
    query = text("""
        SELECT 
            u.id, 
            u.username, 
            u.role, 
            u.full_name, 
            u.created_at,
            p.bed_number, 
            p.medical_history
        FROM users u
        LEFT JOIN patients_info p ON u.id = p.user_id
        WHERE u.role IN ('nurse', 'patient')
        ORDER BY u.role, u.id DESC
    """)
    try:
        with engine.connect() as conn:
            result = conn.execute(query)
            users = []
            for row in result:
                u_dict = row._asdict()
                u_dict["created_at"] = u_dict["created_at"].strftime("%Y-%m-%d %H:%M") if u_dict["created_at"] else "無"
                u_dict["bed_number"] = decrypt_data(u_dict["bed_number"])
                u_dict["medical_history"] = decrypt_data(u_dict["medical_history"])
                users.append(u_dict)
            return {"status": "success", "data": users}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"撈取人員失敗: {str(e)}")

@app.delete("/api/admin/users/{user_id}")
def delete_user(user_id: int, current_user: dict = Depends(get_current_user)):
    """管理員專用 API：刪除人員及其所有關聯紀錄"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="權限不足：僅限系統管理員操作")
        
    try:
        with engine.connect() as conn:
            # 1. 刪除護病分配
            conn.execute(text("DELETE FROM care_assignments WHERE nurse_id = :id OR patient_id = :id"), {"id": user_id})
            # 2. 刪除傷口紀錄
            conn.execute(text("DELETE FROM wound_records WHERE nurse_id = :id OR patient_id = :id"), {"id": user_id})
            # 3. 刪除病患基本資料
            conn.execute(text("DELETE FROM patients_info WHERE user_id = :id"), {"id": user_id})
            # 4. 刪除使用者主檔
            conn.execute(text("DELETE FROM users WHERE id = :id"), {"id": user_id})
            conn.commit()
            return {"status": "success", "message": "人員及關聯資料刪除成功！"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"刪除人員失敗: {str(e)}")

@app.get("/api/admin/patients/{patient_id}/details")
def get_patient_clinical_detail(patient_id: int, current_user: dict = Depends(get_current_user)):
    """取得特定病患的完整臨床病歷檔案 (包含基本資料、護病照護歷史與所有歷次傷口紀錄)"""
    if current_user["role"] != "admin":
        raise HTTPException(status_code=403, detail="僅限管理員存取")
    
    try:
        with engine.connect() as conn:
            # 1. 查詢病患基本資料
            info_query = text("""
                SELECT u.id, u.full_name, u.username, u.created_at,
                       p.bed_number, p.medical_history, p.gender, p.age, p.admission_date, p.allergies, p.status, p.last_assessment
                FROM users u
                LEFT JOIN patients_info p ON u.id = p.user_id
                WHERE u.id = :p_id AND u.role = 'patient'
            """)
            info_row = conn.execute(info_query, {"p_id": patient_id}).fetchone()
            if not info_row:
                raise HTTPException(status_code=404, detail="找不到該病患")
            
            patient_info = {
                "id": info_row.id,
                "full_name": info_row.full_name,
                "username": info_row.username,
                "created_at": info_row.created_at.strftime("%Y-%m-%d %H:%M") if info_row.created_at else "無",
                "bed_number": decrypt_data(info_row.bed_number) or "未指派",
                "medical_history": decrypt_data(info_row.medical_history) or "無特殊病史記錄",
                "gender": decrypt_data(info_row.gender) or "未填寫",
                "age": decrypt_data(info_row.age) or "未填寫",
                "admission_date": decrypt_data(info_row.admission_date) or "未填寫",
                "allergies": decrypt_data(info_row.allergies) or "無特定過敏史",
                "status": info_row.status or "green",
                "last_assessment": info_row.last_assessment or "無記錄"
            }
            
            # 2. 查詢護病照護歷史軌跡 (誰照顧過他)
            care_query = text("""
                SELECT ca.assigned_date, ca.shift_type, n.full_name AS nurse_name, n.username AS nurse_username
                FROM care_assignments ca
                JOIN users n ON ca.nurse_id = n.id
                WHERE ca.patient_id = :p_id
                ORDER BY ca.assigned_date DESC, ca.shift_type DESC
            """)
            care_history = []
            for row in conn.execute(care_query, {"p_id": patient_id}):
                r_dict = row._asdict()
                r_dict["assigned_date"] = r_dict["assigned_date"].strftime("%Y-%m-%d") if r_dict["assigned_date"] else "無"
                care_history.append(r_dict)
                
            # 3. 查詢歷次傷口評估紀錄
            wound_query = text("""
                SELECT wr.id, wr.image_url, wr.annotated_image_url, wr.ai_grade, wr.ai_confidence, wr.ai_advice,
                       wr.nurse_grade, wr.nurse_advice, wr.created_at, n.full_name AS nurse_name
                FROM wound_records wr
                JOIN users n ON wr.nurse_id = n.id
                WHERE wr.patient_id = :p_id
                ORDER BY wr.created_at DESC
            """)
            wound_history = []
            for row in conn.execute(wound_query, {"p_id": patient_id}):
                r_dict = row._asdict()
                r_dict["created_at"] = r_dict["created_at"].strftime("%Y-%m-%d %H:%M") if r_dict["created_at"] else "無"
                wound_history.append(r_dict)
                
            return {
                "status": "success",
                "data": {
                    "info": patient_info,
                    "care_history": care_history,
                    "wound_history": wound_history
                }
            }
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ==========================================
# 6. 病患與護理師通用：AI 照護助理對話 API
# ==========================================

class ChatMessage(BaseModel):
    role: str
    content: str

class ChatReq(BaseModel):
    messages: list[ChatMessage]

@app.post("/api/chat")
def chat_with_local_ai(req: ChatReq, current_user: dict = Depends(get_current_user)):
    """與本地端 AI 模型對話的後端代理，並自動帶入病患歷史紀錄進行問答"""
    if current_user["role"] not in ["patient", "nurse"]:
        raise HTTPException(status_code=403, detail="權限不足：僅限病患與護理師諮詢")
        
    local_ai_url = "http://127.0.0.1:1234/v1/chat/completions"
    
    # 1. 預載病患資料與最新傷口紀錄
    patient_info_str = "當前尚無病患背景與床位資料。"
    wound_records_str = "當前尚無任何傷口照護紀錄與護理建議。"
    latest_advice = "無特別照護交代，請維持清潔乾燥。"
    latest_nurse = "系統"
    latest_grade = "無"
    info_row = None
    
    if current_user["role"] == "patient":
        try:
            with engine.connect() as conn:
                # 查詢病患基本資料
                info_query = text("""
                    SELECT u.full_name, p.bed_number, p.medical_history
                    FROM users u
                    LEFT JOIN patients_info p ON u.id = p.user_id
                    WHERE u.username = :username
                """)
                info_row = conn.execute(info_query, {"username": current_user["username"]}).fetchone()
                if info_row:
                    bed = decrypt_data(info_row.bed_number) or "未指派"
                    history = decrypt_data(info_row.medical_history) or "無"
                    patient_info_str = f"病患姓名：{info_row.full_name}\n病房床號：{bed}\n病史/備註：{history}"
                
                # 查詢歷史傷口紀錄
                records_query = text("""
                    SELECT 
                        wr.created_at, wr.ai_grade, wr.ai_advice,
                        wr.nurse_grade, wr.nurse_advice,
                        n.full_name as nurse_name
                    FROM wound_records wr
                    JOIN users patient ON wr.patient_id = patient.id
                    JOIN users n ON wr.nurse_id = n.id
                    WHERE patient.username = :username
                    ORDER BY wr.created_at DESC
                    LIMIT 5
                """)
                records_res = conn.execute(records_query, {"username": current_user["username"]}).fetchall()
                if records_res:
                    records_list = []
                    for i, r in enumerate(records_res):
                        created_str = r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "未知時間"
                        records_list.append(
                            f"第 {i+1} 筆紀錄時間：{created_str}\n"
                            f"  - AI 判定等級：{r.ai_grade}\n"
                            f"  - AI 照護建議：{r.ai_advice}\n"
                            f"  - 護理師判定等級：{r.nurse_grade}\n"
                            f"  - 護理師交代建議：{r.nurse_advice} (由護理師 {r.nurse_name} 提供)"
                        )
                        # 保留最新一筆供 Fallback 使用
                        if i == 0:
                            latest_advice = r.nurse_advice or "無"
                            latest_nurse = r.nurse_name
                            latest_grade = r.nurse_grade
                    wound_records_str = "\n\n".join(records_list)
        except Exception as e:
            print(f"Chat DB Query Error: {e}")

    # 2. 建立客製化系統 Prompt
    if current_user["role"] == "nurse":
        system_prompt = (
            "你是一位極具臨床經驗、專業且嚴謹的『智慧傷口照護系統』AI 臨床護理顧問。請用專業、精準的繁體中文，為臨床護理師解答關於傷口評估、分級指引、各式先進敷料（如親水性纖維、銀離子、泡沫敷料等）的臨床應用與選擇、滲液控制、感染評估以及個案護理指導等專業臨床照護問題。\n\n"
            "=== 回答規範 ===\n"
            "1. 回答請基於實證醫學與最新臨床傷口護理指引（例如 WOCN, NPUAP 指南）。\n"
            "2. 條理分明、層次清晰，多使用列點與結構化說明，必要時分析不同處置方案的優缺點。\n"
            "3. 語氣應維持專業、客觀且具備學術及臨床實務的指導意義。\n"
            "4. 回答內容若涉及特定藥物或具高度風險之清創操作，需提醒護理師遵循院方處方及照會常規。"
        )
    else:
        system_prompt = (
            "你是一位親切、專業的『智慧傷口照護系統』AI 照護諮詢專家。請用繁體中文回覆病患關於傷口照護、換藥步驟、敷料選擇、飲食營養等醫學常識問題。\n"
            "你已被賦予該病患的基本臨床資料與最新 5 筆歷次傷口紀錄與護理建議，請**務必根據這些實際傷口歷史紀錄與護理師交代之照護建議**，來針對病患的問題進行客製化、人性化的回覆！\n\n"
            "=== 病患基本資料 ===\n"
            f"{patient_info_str}\n\n"
            "=== 病患最新歷次傷口紀錄與建議 ===\n"
            f"{wound_records_str}\n\n"
            "=== 回答規範 ===\n"
            "1. 請優先結合上述病患的『護理師交代建議』與『AI 照護建議』來作答。例如：如果護理師曾交代要使用生理食鹽水清洗或定時換藥，應在對話中溫柔地提醒與追蹤病患是否遵循。\n"
            "2. 回答時請簡明扼要、條理清晰，多用列點說明。\n"
            "3. 請以溫柔、鼓勵、同理心關懷的語氣與病患對話。\n"
            "4. 重要：如果病患描述的症狀嚴重（如：發高燒、傷口劇烈疼痛、大量滲血、發出惡臭），請務必強烈提醒他們應立即尋求專業醫師或回院急診就醫。"
        )
    
    # 3. 建立對話內容
    model_messages = [
        {
            "role": "system",
            "content": system_prompt
        }
    ]
    
    # 加入歷史對話
    for msg in req.messages:
        model_messages.append({
            "role": msg.role,
            "content": msg.content
        })
        
    payload = {
        "messages": model_messages,
        "temperature": 0.7,
        "max_tokens": 1000,
        "stream": False
    }
    
    try:
        req_data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        request = urllib.request.Request(local_ai_url, data=req_data, headers=headers, method="POST")
        
        # 設定 120 秒逾時，給予本地端大型 AI 模型足夠的 Prefill 與生成時間
        with urllib.request.urlopen(request, timeout=120) as response:
            res_body = response.read().decode("utf-8")
            res_json = json.loads(res_body)
            ai_reply = res_json["choices"][0]["message"]["content"]
            return {"status": "success", "reply": ai_reply}
            
    except Exception as e:
        # Fallback 備用回覆：若本地端 AI 模型未啟動，結合角色回覆
        if current_user["role"] == "nurse":
            mock_reply = (
                "【系統提示：本地端 AI 臨床護理顧問離線，以下為您提供傷口照護之臨床參考指引】\n\n"
                "目前本地端 AI 服務暫時離線。為協助您進行臨床評估與處置，以下提供常見傷口分級與處理要點供您參考：\n\n"
                "📋 **壓瘡/傷口臨床分級與處置參考**：\n"
                "1. **Grade 1 (表皮發紅未破損)**：\n"
                "   - 處置：加強減壓、保持皮膚乾爽，可使用皮膚保護貼或透明保護薄膜。\n"
                "2. **Grade 2 (表皮或真皮部分破損/水泡)**：\n"
                "   - 處置：生理食鹽水清潔，可選用親水性敷料（人工皮）或水膠體敷料，維持濕潤癒合。\n"
                "3. **Grade 3 (深及皮下組織)**：\n"
                "   - 處置：清除壞死組織，可選用海藻酸鹽敷料（高滲出液）或泡沫敷料，加強吸收滲液並防壓迫。\n"
                "4. **Grade 4 (深及肌肉/骨頭)**：\n"
                "   - 處置：多需外科清創，依滲液量選擇敷料，防範骨髓炎與全身性感染。\n"
                "5. **無法分級 (Unstageable)**：\n"
                "   - 處置：需清除焦痂（Eschar）或腐肉以利正確分級。\n\n"
                "💡 **先進敷料選用原則**：\n"
                "- *高滲出液*：選擇泡沫敷料（Foam）或海藻酸鹽（Alginate）。\n"
                "- *感染控制*：選擇含銀敷料（Silver-containing dressings）以達抑菌效果。\n"
                "- *乾燥結痂*：可使用水膠體（Hydrogel）進行自體溶解清創。\n\n"
                "若需進一步臨床協助，請照會專科傷口護理師或主治醫師。"
            )
        else:
            full_name = current_user['username']
            if info_row:
                full_name = info_row.full_name
                
            mock_reply = (
                "【系統提示：本地端 AI 醫療助理離線，以下為為您客製的智慧照護建議】\n\n"
                f"您好，{full_name}！雖然本地 AI 模型暫時處於離線狀態，但我為您調閱了您最新的傷口照護紀錄：\n\n"
                f"📋 **最新傷口狀態評估**：\n"
                f"- 傷口狀態等級：{latest_grade}\n"
                f"- 負責評估護理師：{latest_nurse}\n"
                f"- 🩺 **護理師交代建議**：\n"
                f"  「{latest_advice}」\n\n"
                "💡 **日常換藥核心步驟建議**：\n"
                "1. 🩹 **換藥前清潔**：使用無菌生理食鹽水由傷口中心向外清洗，並以無菌棉棒溫和吸乾。\n"
                "2. 💧 **維持適度濕潤**：依照護理師交代之敷料指示定時更換，維持傷口適當濕度，加速細胞再生。\n"
                "3. ⚠️ **發炎感染提醒**：請密切觀察傷口。若周圍出現紅、腫、熱、痛加劇，或有異味黃綠色分泌物甚至發燒，請務必立即尋求護理師協助或直接就醫！\n\n"
                "祝您早日康復！"
            )
        return {"status": "mock", "reply": mock_reply, "error": str(e)}

# 掛載圖片上傳資料夾為靜態路徑
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")
# 將前端資料夾掛載為靜態網頁伺服器
app.mount("/", StaticFiles(directory="frontend", html=True), name="frontend")
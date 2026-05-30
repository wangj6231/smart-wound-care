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

DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/wound_care_db"
engine = create_engine(DATABASE_URL)

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

# @app.get("/")
# def read_root():
#     return {"status": "success", "message": "智慧傷口照護系統 API 伺服器運行中"}

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
            patients = [row._asdict() for row in result]
            
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

# 建立上傳檔案的資料夾 (如果不存在的話)
UPLOAD_DIR = "uploads/wounds"
os.makedirs(UPLOAD_DIR, exist_ok=True)

@app.post("/api/records")
async def create_wound_record(
    patient_id: int = Form(...),
    ai_grade: str = Form(...),
    ai_confidence: float = Form(...),
    ai_advice: str = Form(...),
    nurse_grade: str = Form(...),
    nurse_advice: str = Form(...),
    image: UploadFile = File(...),
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
            patient_id, nurse_id, image_url, 
            ai_grade, ai_confidence, ai_advice, 
            nurse_grade, nurse_advice
        ) VALUES (
            :patient_id, :nurse_id, :image_url, 
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
                "ai_grade": ai_grade,
                "ai_confidence": ai_confidence,
                "ai_advice": ai_advice,
                "nurse_grade": nurse_grade,
                "nurse_advice": nurse_advice
            })
            connection.commit()
            
            return {"status": "success", "message": "紀錄儲存成功！"}
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
                    "bed_number": row.bed_number or "未指派",
                    "medical_history": row.medical_history or "無特殊病史"
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
            wr.id, wr.image_url, wr.ai_grade, wr.ai_advice,
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
                    INSERT INTO patients_info (user_id, bed_number, medical_history)
                    VALUES (:user_id, :bed_number, :medical_history)
                """)
                conn.execute(insert_info, {
                    "user_id": user_id,
                    "bed_number": req.bed_number,
                    "medical_history": req.medical_history
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
                SELECT u.id, u.full_name, u.username, p.bed_number, p.medical_history, u.created_at
                FROM users u
                LEFT JOIN patients_info p ON u.id = p.user_id
                WHERE u.id = :p_id AND u.role = 'patient'
            """)
            info_row = conn.execute(info_query, {"p_id": patient_id}).fetchone()
            if not info_row:
                raise HTTPException(status_code=404, detail="找不到該病患")
            
            patient_info = info_row._asdict()
            patient_info["created_at"] = patient_info["created_at"].strftime("%Y-%m-%d %H:%M") if patient_info["created_at"] else "無"
            
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
                SELECT wr.id, wr.image_url, wr.ai_grade, wr.ai_confidence, wr.ai_advice,
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
                    bed = info_row.bed_number or "未指派"
                    history = info_row.medical_history or "無"
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
        # Fallback 備用回覆：若本地端 AI 模型未啟動，結合病患真實傷口與建議回覆
        full_name = current_user['username']
        if current_user["role"] == "patient" and info_row:
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
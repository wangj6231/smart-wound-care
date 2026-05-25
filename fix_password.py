from passlib.context import CryptContext
from sqlalchemy import create_engine, text

# 1. 初始化密碼加密器 (與 main.py 完全相同的設定)
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# 2. 設定資料庫連線
DATABASE_URL = "mysql+pymysql://root:@127.0.0.1:3306/wound_care_db"
engine = create_engine(DATABASE_URL)

print("正在產生符合 Python 格式的加密密碼...")
# 產生 '123456' 的原生加密雜湊值
new_hash = pwd_context.hash("123456")

# 3. 更新資料庫中的所有使用者密碼
try:
    with engine.connect() as connection:
        # 將所有使用者的密碼都換成這組原生加密的 123456
        connection.execute(text("UPDATE users SET password_hash = :hash"), {"hash": new_hash})
        connection.commit()  # 儲存變更
    print("密碼修復完成！所有帳號密碼皆已重設為 '123456'")
except Exception as e:
    print(f"發生錯誤: {e}")
FROM python:3.10-slim

# 安裝 OpenCV 與 PyTorch 執行所需的作業系統依賴套件
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgthread-2.0-0 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製並安裝 Python 相依套件
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案程式碼與前端靜態檔案
COPY main.py .
COPY yolo11m.pt .
COPY yolo11m_best.pt .
COPY secret.key .
COPY frontend/ ./frontend/

# 建立 uploads/wounds 資料夾以儲存標註照片
RUN mkdir -p uploads/wounds

# 設定 Hugging Face Spaces 要求的監聽 Port 7860
EXPOSE 7860

# 啟動 FastAPI 服務，並設定 Port 為 7860
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]

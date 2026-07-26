FROM python:3.10-slim

# 安裝 OpenCV 與 ONNX Runtime 執行所需的作業系統底層解碼套件
RUN apt-get update && apt-get install -y \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgthread-2.0-0 \
    procps \
    && rm -rf /var/lib/apt/lists/*

# 設定工作目錄
WORKDIR /app

# 複製並安裝 Python 相依套件 (極簡 ONNX 依賴)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 複製專案程式碼、輕量化 ONNX 模型與靜態檔案
COPY main.py .
COPY yolo11m.onnx .
COPY secret.key .
COPY frontend/ ./frontend/

# 建立 uploads/wounds 資料夾以儲存標註照片
RUN mkdir -p uploads/wounds

# 設定通訊埠 (Render 會動態指派 $PORT)
EXPOSE 8000

# 啟動 FastAPI 服務，動態綁定 Render 給予的 Port 變數 (預設 8000)
CMD uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}

FROM python:3.12-slim

WORKDIR /app

# ติดตั้ง dependency ก่อน (layer cache)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# รันเป็น non-root user (ดีต่อ security / sensitive data)
RUN useradd --create-home appuser
USER appuser

CMD ["python", "worker.py"]

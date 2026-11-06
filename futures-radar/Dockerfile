FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

FROM python:3.11-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    TZ=Asia/Shanghai \
    DATABASE_URL=sqlite:////data/radar.db \
    PORT=8000
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt
COPY backend ./backend
COPY --from=web /web/dist ./frontend/dist

WORKDIR /app/backend
VOLUME /data
EXPOSE 8000
CMD ["sh", "-c", "if [ ! -f /data/radar.db ] && [ -f /app/backend/seed-data/radar.db ]; then cp /app/backend/seed-data/radar.db /data/radar.db; fi; python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

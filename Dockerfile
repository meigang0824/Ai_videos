FROM python:3.11-slim AS runtime
WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV HOST=0.0.0.0
ENV PORT=8010

RUN sed -i 's|http://deb.debian.org/debian|https://mirrors.tuna.tsinghua.edu.cn/debian|g; s|http://deb.debian.org/debian-security|https://mirrors.tuna.tsinghua.edu.cn/debian-security|g' /etc/apt/sources.list.d/debian.sources \
  && apt-get update \
  && apt-get install -y --no-install-recommends ffmpeg curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120 --upgrade pip setuptools wheel \
  && pip install --no-cache-dir -i https://pypi.tuna.tsinghua.edu.cn/simple --timeout 120 -r requirements.txt

COPY api_clients.py api_server.py ./
COPY pipeline/ ./pipeline/
COPY docs/ ./docs/
COPY alembic.ini ./
COPY alembic/ ./alembic/
COPY README.md ./
COPY app_ui/dist ./app_ui/dist

RUN mkdir -p backend/storage outputs voices

EXPOSE 8010
CMD ["sh", "-c", "alembic upgrade head && python -m uvicorn api_server:app --host ${HOST:-0.0.0.0} --port ${PORT:-8010}"]

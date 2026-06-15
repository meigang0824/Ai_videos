from __future__ import annotations

import os

from celery import Celery


broker_url = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND") or broker_url

celery_app = Celery("cosyvoice_api_only", broker=broker_url, backend=result_backend, include=["pipeline.celery_tasks"])
celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone=os.getenv("TZ", "Asia/Shanghai"),
    enable_utc=True,
    worker_prefetch_multiplier=max(1, int(os.getenv("CELERY_WORKER_PREFETCH_MULTIPLIER", "1"))),
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_track_started=True,
)

from __future__ import annotations

import sys
from pathlib import Path

from pipeline.celery_app import celery_app


@celery_app.task(name="pipeline.run_task", bind=True)
def run_pipeline_task(self, task_id: str):
    app_dir = Path(__file__).resolve().parents[1]
    if str(app_dir) not in sys.path:
        sys.path.insert(0, str(app_dir))
    from api_server import _run_task

    _run_task(task_id)
    return {"task_id": task_id}

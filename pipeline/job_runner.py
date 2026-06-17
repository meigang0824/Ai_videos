from __future__ import annotations

import os
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Callable


def _int_env(name: str, default: int, minimum: int = 1) -> int:
    try:
        return max(minimum, int(os.getenv(name, str(default))))
    except ValueError:
        return default


def _runner_backend() -> str:
    return os.getenv("JOB_RUNNER_BACKEND", "local").strip().lower()


def _redact_url(value: str) -> str:
    if "@" not in value:
        return value
    scheme, _, rest = value.partition("://")
    _, _, host = rest.rpartition("@")
    return f"{scheme}://***@{host}" if scheme and host else "***"


class LocalJobRunner:
    def __init__(self, max_workers: int | None = None):
        self.max_workers = max_workers or _int_env("JOB_MAX_WORKERS", 2)
        self.executor = ThreadPoolExecutor(max_workers=self.max_workers, thread_name_prefix="cosy-job")
        self.lock = threading.RLock()
        self.submitted = 0
        self.running = 0
        self.completed = 0
        self.failed = 0
        self.canceled = 0
        self.futures = {}

    def submit(self, task_id: str, fn: Callable[[], None] | None = None):
        if not fn:
            raise RuntimeError("local runner requires a callable task")
        with self.lock:
            self.submitted += 1
            future = self.executor.submit(self._run, task_id, fn)
            self.futures[task_id] = future

    def cancel(self, task_id: str) -> bool:
        with self.lock:
            future = self.futures.get(task_id)
            if not future:
                return False
            canceled = future.cancel()
            if canceled:
                self.canceled += 1
                self.futures.pop(task_id, None)
            return canceled

    def has_task(self, task_id: str) -> bool:
        with self.lock:
            future = self.futures.get(task_id)
            return bool(future and not future.done())

    def _run(self, task_id: str, fn: Callable[[], None]):
        with self.lock:
            self.running += 1
        try:
            fn()
        except Exception:
            with self.lock:
                self.failed += 1
            raise
        else:
            with self.lock:
                self.completed += 1
        finally:
            with self.lock:
                self.running = max(0, self.running - 1)
                self.futures.pop(task_id, None)

    def status(self) -> dict[str, int | str]:
        with self.lock:
            queued_estimate = max(0, self.submitted - self.completed - self.failed - self.canceled - self.running)
            return {
                "backend": "local_thread_pool",
                "max_workers": self.max_workers,
                "submitted": self.submitted,
                "running": self.running,
                "queued_estimate": queued_estimate,
                "completed": self.completed,
                "failed": self.failed,
                "canceled": self.canceled,
            }


class CeleryJobRunner:
    def __init__(self):
        from pipeline.celery_app import celery_app

        self.app = celery_app
        self.broker_url = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    def submit(self, task_id: str, fn: Callable[[], None] | None = None):
        self.app.send_task("pipeline.run_task", args=[task_id], task_id=task_id)

    def cancel(self, task_id: str) -> bool:
        self.app.control.revoke(task_id, terminate=False)
        return True

    def _queue_length(self) -> int:
        try:
            import redis

            client = redis.Redis.from_url(self.broker_url)
            return int(client.llen("celery") or 0)
        except Exception:
            return 0

    def _queued_contains(self, task_id: str) -> bool:
        import redis

        needle = task_id.encode("utf-8")
        client = redis.Redis.from_url(self.broker_url)
        for item in client.lrange("celery", 0, -1):
            if needle in item:
                return True
        return False

    def _inspect_task_ids(self) -> set[str]:
        task_ids: set[str] = set()
        inspect = self.app.control.inspect(timeout=1)
        groups = [
            inspect.active() or {},
            inspect.reserved() or {},
            inspect.scheduled() or {},
        ]
        for group in groups:
            for items in group.values():
                for item in items:
                    request = item.get("request") if isinstance(item, dict) else None
                    task_id = (request or item).get("id") if isinstance(request or item, dict) else None
                    if task_id:
                        task_ids.add(str(task_id))
        return task_ids

    def has_task(self, task_id: str) -> bool:
        return task_id in self._inspect_task_ids() or self._queued_contains(task_id)

    def status(self) -> dict[str, int | str | bool]:
        payload: dict[str, int | str | bool] = {
            "backend": "celery",
            "broker": _redact_url(self.broker_url),
            "available": False,
            "workers": 0,
            "active": 0,
            "reserved": 0,
            "scheduled": 0,
            "queue_length": self._queue_length(),
        }
        try:
            inspect = self.app.control.inspect(timeout=1)
            active = inspect.active() or {}
            reserved = inspect.reserved() or {}
            scheduled = inspect.scheduled() or {}
        except Exception as exc:
            payload["error"] = str(exc)
            return payload
        payload.update(
            {
                "available": bool(active or reserved or scheduled),
                "workers": len(set(active) | set(reserved) | set(scheduled)),
                "active": sum(len(items) for items in active.values()),
                "reserved": sum(len(items) for items in reserved.values()),
                "scheduled": sum(len(items) for items in scheduled.values()),
            }
        )
        return payload


def create_job_runner():
    if _runner_backend() == "celery":
        return CeleryJobRunner()
    return LocalJobRunner()


job_runner = create_job_runner()

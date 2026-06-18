from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from api_clients import (
    call_asr,
    call_asr_media,
    call_asr_url,
    call_lip_sync,
    call_llm,
    call_tts,
    call_video_compose,
    load_service_config,
    save_service_config,
)
from pipeline.auth_store import auth_store
from pipeline.config import BASE_DIR, DEFAULT_BACKGROUND_VIDEO, MAX_UPLOAD_BYTES, OUTPUT_DIR, TMP_DIR, UPLOAD_DIR, VOICE_DIR
from pipeline.job_runner import job_runner
from pipeline.moviepy_service import download_or_copy_media, render_video
from pipeline.object_storage import object_storage
from pipeline.task_store import task_store
from pipeline.voice_store import voice_store


APP_NAME = "CosyVoice API Only"
FRONTEND_DIST = BASE_DIR / "app_ui" / "dist"
ALLOWED_AUDIO_SUFFIXES = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".webm"}
ALLOWED_VIDEO_SUFFIXES = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
ALLOWED_TRANSCRIBE_SUFFIXES = ALLOWED_AUDIO_SUFFIXES | ALLOWED_VIDEO_SUFFIXES

def _cors_origins() -> list[str]:
    raw = os.getenv("CORS_ALLOW_ORIGINS", "").strip()
    if raw:
        return [origin.strip() for origin in raw.split(",") if origin.strip()]
    return [
        "http://127.0.0.1:8010",
        "http://localhost:8010",
        "http://127.0.0.1:5173",
        "http://localhost:5173",
    ]


def _as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


AUTH_REQUIRED = _as_bool(os.getenv("AUTH_REQUIRED"), False)
cors_origins = _cors_origins()
app = FastAPI(title=APP_NAME)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials="*" not in cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _task_status_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for task in task_store.list_tasks(limit=200):
        status = str(task.get("status") or "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def _recover_queued_tasks():
    queued = [task for task in task_store.list_tasks(limit=200) if task.get("status") == "queued"]
    if not queued:
        return
    for task in queued:
        task_id = task.get("task_id")
        if not task_id:
            continue
        try:
            job_runner.submit(task_id, lambda task_id=task_id: _run_task(task_id))
        except Exception as exc:
            _fail(task_id, exc)


@app.on_event("startup")
def recover_queued_tasks_on_startup():
    _recover_queued_tasks()


class AuthPayload(BaseModel):
    username: str
    password: str


class AdminUserPayload(AuthPayload):
    role: str = "user"


class ExtractPayload(BaseModel):
    taskId: str | None = None
    reference_url: str | None = None
    reference_text: str | None = None
    model: str | None = "base"


class RewritePayload(BaseModel):
    taskId: str | None = None
    reference_text: str
    realtor_context: dict[str, Any] | None = None
    rewrite_engine: str = "ai"
    rewrite_style: str = "viral"
    rewrite_tone: str = "natural"
    rewrite_length: str = "medium"
    rewrite_platform: str = "douyin"
    rewrite_strength: str = "balanced"
    rewrite_variants: int = 1


class TtsPayload(BaseModel):
    taskId: str | None = None
    text: str
    voice_id: str | None = None
    voice_ref_wav: str | None = None
    voice_ref_text: str | None = None
    speed: float = 1.0


class VoiceNamePayload(BaseModel):
    name: str


class VideoPayload(BaseModel):
    taskId: str | None = None
    videoUrl: str | None = None
    videoUrls: list[str] | None = None
    audioUrl: str
    subtitle: str | None = ""
    options: dict[str, Any] = Field(default_factory=dict)


class LipSyncPayload(BaseModel):
    taskId: str | None = None
    videoUrl: str
    audioUrl: str
    pads: list[int] = Field(default_factory=lambda: [0, 10, 0, 0])
    resizeFactor: int = 3
    noSmooth: bool = False
    enhanceMode: str = "none"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_id(prefix: str) -> str:
    return f"{prefix}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}"


def _task_id(raw: str | None, prefix: str) -> str:
    value = (raw or "").strip()
    value = re.sub(r"[^a-zA-Z0-9_-]", "_", value)
    return value[:80] if value else _safe_id(prefix)


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _public_url(kind: str, task_id: str) -> str:
    return f"/api/v1/{kind}/{task_id}"


def _file_size(path: Path) -> int:
    try:
        return path.stat().st_size
    except FileNotFoundError:
        return 0


def _content_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".mp4", ".m4v"}:
        return "video/mp4"
    if suffix == ".mov":
        return "video/quicktime"
    if suffix == ".wav":
        return "audio/wav"
    if suffix == ".mp3":
        return "audio/mpeg"
    if suffix in {".m4a", ".aac"}:
        return "audio/mp4"
    if suffix == ".flac":
        return "audio/flac"
    if suffix == ".ogg":
        return "audio/ogg"
    if suffix == ".webm":
        return "audio/webm"
    if suffix == ".srt":
        return "text/plain"
    if suffix == ".json":
        return "application/json"
    return "application/octet-stream"


def _upload_to_object_storage(
    local_path: Path,
    *,
    user_id: str,
    purpose: str,
    filename: str | None = None,
    task_id: str | None = None,
) -> dict[str, Any] | None:
    if not object_storage.enabled():
        return None
    key = object_storage.key(user_id, purpose, filename or local_path.name, task_id=task_id)
    try:
        return object_storage.upload_file(local_path, key, content_type=_content_type(local_path))
    except Exception as exc:
        return {"provider": "aliyun_oss", "key": key, "error": str(exc)}


async def _upload_voice_file_to_object_storage(file: UploadFile, user_id: str) -> tuple[str, int, dict[str, Any]]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_AUDIO_SUFFIXES:
        raise HTTPException(status_code=400, detail="文件格式不支持")
    filename = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{suffix}"
    key = object_storage.key(user_id, "voices/audio", filename)
    size = 0
    spool = tempfile.SpooledTemporaryFile(max_size=16 * 1024 * 1024)
    try:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                raise HTTPException(status_code=413, detail="文件太大")
            spool.write(chunk)
        if size < 1:
            raise HTTPException(status_code=400, detail="文件为空")
        upload = object_storage.upload_fileobj(spool, key, content_type=_content_type(Path(filename)))
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"音色上传 OSS 失败：{exc}") from exc
    finally:
        spool.close()
    if not upload or upload.get("error"):
        raise HTTPException(status_code=502, detail=upload.get("error") if upload else "音色上传 OSS 失败")
    return filename, size, upload


def _apply_object_result(target: dict[str, Any], field: str, upload: dict[str, Any] | None):
    if not upload:
        return
    target[f"{field}_storage_provider"] = upload.get("provider") or "aliyun_oss"
    target[f"{field}_object_key"] = upload.get("key") or ""
    if upload.get("url"):
        target[f"{field}_object_url"] = upload.get("url")
    if upload.get("error"):
        target[f"{field}_object_error"] = upload.get("error")


def _sync_voice_object_storage(voice_id: str, user_id: str, path_value: str):
    path = Path(path_value)
    if not path.exists() or not object_storage.enabled():
        return
    audio_upload = _upload_to_object_storage(path, user_id=user_id, purpose="voices/audio", filename=path.name)
    current = voice_store.get_voice(voice_id, user_id=user_id)
    if not current:
        return
    voice = dict(current)
    if audio_upload:
        voice["storage_provider"] = audio_upload.get("provider") or "aliyun_oss"
        voice["object_key"] = audio_upload.get("key") or voice.get("object_key") or ""
        if audio_upload.get("url"):
            voice["object_url"] = audio_upload.get("url")
        if audio_upload.get("error"):
            voice["object_error"] = audio_upload.get("error")
    voice_store.upsert_voice(voice)


def _redirect_to_object(key: str | None):
    if not key or not object_storage.enabled():
        return None
    try:
        return RedirectResponse(object_storage.signed_url(key))
    except Exception:
        return None


def _object_stream_response(key: str | None, fallback_name: str = "media.bin"):
    if not key or not object_storage.enabled():
        return None
    response = None
    try:
        signed = object_storage.signed_url(key)
        response = requests.get(signed, stream=True, timeout=60)
        response.raise_for_status()
    except Exception:
        if response is not None:
            response.close()
        return None

    def chunks():
        try:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    yield chunk
        finally:
            response.close()

    headers = {}
    if response.headers.get("content-length"):
        headers["Content-Length"] = response.headers["content-length"]
    content_type = response.headers.get("content-type") or _content_type(Path(fallback_name))
    return StreamingResponse(chunks(), media_type=content_type, headers=headers)


def _relative_to_base(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(BASE_DIR.resolve()))
    except (OSError, ValueError):
        return str(path)


def _resolve_voice_path(raw_path: str | None) -> Path | None:
    raw = str(raw_path or "").strip()
    if not raw:
        return None
    path = Path(raw).expanduser()
    candidates: list[Path] = []
    if path.is_absolute():
        candidates.append(path)
    else:
        candidates.append(BASE_DIR / path)
        candidates.append(VOICE_DIR / path.name)
    if path.name:
        candidates.append(VOICE_DIR / path.name)
    for candidate in candidates:
        try:
            if candidate.exists() and candidate.is_file():
                return candidate
        except OSError:
            continue
    return candidates[0] if candidates else None


def _voice_audio_local_path(item: dict[str, Any]) -> Path | None:
    path = _resolve_voice_path(item.get("ref_wav"))
    if path and path.exists():
        return path
    key = str(item.get("object_key") or "").strip()
    if not key or not object_storage.enabled():
        return None
    suffix = Path(str(item.get("ref_wav") or "")).suffix or ".wav"
    local_path = TMP_DIR / "voices" / f"{item.get('id') or uuid.uuid4().hex}{suffix}"
    try:
        local_path.parent.mkdir(parents=True, exist_ok=True)
        signed = object_storage.signed_url(key)
        download_or_copy_media(signed, local_path, os.getenv("PUBLIC_BASE_URL", ""))
    except Exception:
        return None
    return local_path if local_path.exists() else None


def _task_for_file(task_id: str, request: Request) -> dict[str, Any]:
    user_id = _request_user_id(request)
    item = task_store.get_task(task_id, user_id=user_id)
    if _auth_is_active() and not item:
        raise HTTPException(status_code=404, detail="文件不存在")
    return item or {}


def _task_object_redirect(task_id: str, request: Request, field: str):
    item = _task_for_file(task_id, request)
    result = item.get("result") or {}
    redirect = _redirect_to_object(result.get(f"{field}_object_key"))
    return redirect


def _load_voice_meta(meta_path: Path) -> dict[str, Any] | None:
    try:
        data = __import__("json").loads(meta_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    data.setdefault("id", meta_path.name.removesuffix(".json"))
    data.setdefault("user_id", "local")
    data.setdefault("kind", "local")
    return data


def _voice_owner_id(item: dict[str, Any]) -> str:
    return str(item.get("user_id") or "local")


def _voice_visible_to_user(item: dict[str, Any], user: dict[str, Any]) -> bool:
    owner_id = _voice_owner_id(item)
    return owner_id == user["id"] or (owner_id == "local" and user.get("role") == "admin")


def _iter_voice_meta() -> list[dict[str, Any]]:
    items = voice_store.list_voices()
    if not items:
        items = []
        for meta_path in VOICE_DIR.glob("*.json"):
            item = _load_voice_meta(meta_path)
            if item:
                items.append(item)
    items.sort(key=lambda item: item.get("created_at") or "", reverse=True)
    return items


def _find_user_voice(voice_id: str | None, user: dict[str, Any]) -> dict[str, Any] | None:
    if not voice_id:
        return None
    item = voice_store.get_voice(voice_id)
    if item and _voice_visible_to_user(item, user):
        return item
    for item in _iter_voice_meta():
        if item.get("id") == voice_id and _voice_visible_to_user(item, user):
            return item
    return None


def _find_user_voice_by_path(path: Path, user: dict[str, Any]) -> dict[str, Any] | None:
    resolved = path.expanduser()
    candidates = [resolved]
    if not resolved.is_absolute():
        candidates.append(BASE_DIR / resolved)
        candidates.append(VOICE_DIR / resolved.name)
    if resolved.name:
        candidates.append(VOICE_DIR / resolved.name)
    for candidate in candidates:
        item = voice_store.get_voice_by_path(candidate)
        if item and _voice_visible_to_user(item, user):
            return item
    for item in _iter_voice_meta():
        ref_path = _resolve_voice_path(item.get("ref_wav"))
        if not ref_path:
            continue
        ref_candidates = {ref_path.expanduser(), Path(item.get("ref_wav") or "").expanduser()}
        if ref_path.name:
            ref_candidates.add(VOICE_DIR / ref_path.name)
        if _voice_visible_to_user(item, user) and any(candidate in ref_candidates for candidate in candidates):
            return item
    return None


def _delete_local_voice_file(item: dict[str, Any]) -> bool:
    path = _resolve_voice_path(item.get("ref_wav"))
    if not path:
        return False
    try:
        path = path.expanduser().resolve()
        voice_root = VOICE_DIR.resolve()
    except OSError:
        return False
    if voice_root not in path.parents and path != voice_root:
        return False
    try:
        if path.exists() and path.is_file():
            path.unlink()
            return True
    except OSError:
        return False
    return False


def _local_admin() -> dict[str, Any]:
    return {
        "id": "local",
        "username": "local",
        "role": "admin",
        "status": "active",
        "created_at": None,
        "last_login_at": None,
    }


def _bearer_token(request: Request) -> str:
    header = request.headers.get("authorization") or ""
    scheme, _, token = header.partition(" ")
    if scheme.lower() == "bearer" and token.strip():
        return token.strip()
    return str(request.query_params.get("access_token") or "").strip()


def _current_user(request: Request) -> dict[str, Any] | None:
    token = _bearer_token(request)
    return auth_store.verify_token(token) if token else None


def _auth_is_active() -> bool:
    return AUTH_REQUIRED or auth_store.user_count() > 0


def _require_user(request: Request) -> dict[str, Any]:
    user = _current_user(request)
    if user:
        return user
    if not _auth_is_active():
        return _local_admin()
    raise HTTPException(status_code=401, detail="请先登录")


def _request_user_id(request: Request) -> str:
    return _require_user(request)["id"]


def _require_admin(request: Request) -> dict[str, Any]:
    user = _require_user(request)
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user


PUBLIC_API_PATHS = {
    "/api/v1/auth/login",
    "/api/v1/auth/register",
}


@app.middleware("http")
async def require_api_login(request: Request, call_next):
    if (
        request.url.path.startswith("/api/v1/")
        and request.method.upper() != "OPTIONS"
        and request.url.path not in PUBLIC_API_PATHS
        and _auth_is_active()
        and not _current_user(request)
    ):
        return JSONResponse(status_code=401, content={"detail": "请先登录"})
    return await call_next(request)


def _quota_limit(name: str) -> int | None:
    raw = os.getenv(name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return value if value >= 0 else None


def _usage_summary(user_id: str | None = None) -> dict[str, Any]:
    tasks = task_store.list_tasks(limit=200, user_id=user_id)
    uploads = task_store.list_uploads(limit=200, user_id=user_id)
    by_kind: dict[str, int] = {}
    by_status: dict[str, int] = {}
    tts_chars = 0
    video_seconds = 0.0
    output_bytes = 0
    for task in tasks:
        kind = str(task.get("kind") or "unknown")
        status = str(task.get("status") or "unknown")
        by_kind[kind] = by_kind.get(kind, 0) + 1
        by_status[status] = by_status.get(status, 0) + 1
        result = task.get("result") or {}
        if kind == "tts":
            tts_chars += len(str(result.get("text") or ""))
        if kind in {"video", "wav2lip"}:
            try:
                video_seconds += float(result.get("duration") or 0)
            except (TypeError, ValueError):
                pass
        try:
            output_bytes += int(result.get("size_bytes") or 0)
        except (TypeError, ValueError):
            pass
    upload_bytes = 0
    for item in uploads:
        try:
            upload_bytes += int(item.get("size_bytes") or 0)
        except (TypeError, ValueError):
            pass
    return {
        "task_count": len(tasks),
        "tasks_by_kind": by_kind,
        "tasks_by_status": by_status,
        "upload_count": len(uploads),
        "upload_bytes": upload_bytes,
        "output_bytes": output_bytes,
        "storage_bytes": upload_bytes + output_bytes,
        "tts_chars": tts_chars,
        "video_seconds": round(video_seconds, 2),
    }


def _quota_summary(user_id: str) -> dict[str, Any]:
    usage = _usage_summary(user_id)
    limits = {
        "tasks": _quota_limit("QUOTA_TASKS"),
        "tts_chars": _quota_limit("QUOTA_TTS_CHARS"),
        "video_seconds": _quota_limit("QUOTA_VIDEO_SECONDS"),
        "storage_bytes": _quota_limit("QUOTA_STORAGE_BYTES"),
    }
    used = {
        "tasks": usage["task_count"],
        "tts_chars": usage["tts_chars"],
        "video_seconds": usage["video_seconds"],
        "storage_bytes": usage["storage_bytes"],
    }
    remaining = {
        key: None if limit is None else max(0, limit - used.get(key, 0))
        for key, limit in limits.items()
    }
    return {"limits": limits, "used": used, "remaining": remaining}


def _update(task_id: str, progress: int, message: str):
    task_store.update_task(task_id, progress=max(0, min(99, progress)), message=message)


def _finish(task_id: str, result: dict[str, Any]):
    task_store.update_task(
        task_id,
        status="success",
        progress=100,
        message="完成",
        result=result,
        error=None,
        finished_at=_now(),
    )


def _fail(task_id: str, exc: Exception):
    task_store.update_task(
        task_id,
        status="failed",
        progress=100,
        message="失败",
        error=str(exc),
        finished_at=_now(),
    )


def _seconds_since(value: str | None) -> float:
    if not value:
        return 0
    try:
        text = value.replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return max(0, (datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds())
    except ValueError:
        return 0


def _fail_if_orphaned_task(task: dict[str, Any]) -> dict[str, Any]:
    status = task.get("status")
    if status not in {"queued", "running"}:
        return task
    if not hasattr(job_runner, "has_task"):
        return task

    age = _seconds_since(task.get("updated_at") or task.get("created_at"))
    stale_after = 45 if status == "queued" else 180
    if age < stale_after:
        return task

    try:
        still_known = bool(job_runner.has_task(str(task.get("task_id") or "")))
    except Exception:
        return task
    if still_known:
        return task

    reason = "任务队列已重启，当前任务未在执行队列中，请重新发起"
    updated = task_store.update_task(
        str(task["task_id"]),
        status="failed",
        progress=100,
        message="失败",
        error=reason,
        finished_at=_now(),
    )
    return updated or {**task, "status": "failed", "progress": 100, "message": "失败", "error": reason}


def _task_audio_available(task: dict[str, Any]) -> bool:
    result = (task or {}).get("result") or {}
    if not result.get("audio_url"):
        return False
    if result.get("audio_object_key") and object_storage.enabled():
        return True
    audio_path = result.get("audio_path")
    if audio_path and Path(audio_path).exists():
        return True
    try:
        return _resolve_output_file("audio", str(task.get("task_id") or "")).exists()
    except HTTPException:
        return False


def _payload_base_url(payload: dict[str, Any]) -> str:
    return str(payload.get("_base_url") or os.getenv("PUBLIC_BASE_URL") or "http://127.0.0.1:8010").rstrip("/")


def _source_path_from_payload(payload: dict[str, Any], task_id: str, base_url: str) -> Path:
    source_path = Path(str(payload.get("source_file") or "")).expanduser()
    if source_path.exists():
        return source_path
    key = payload.get("source_object_key")
    if key and object_storage.enabled():
        suffix = Path(str(payload.get("filename") or source_path.name or "")).suffix or ".media"
        out = TMP_DIR / "script_extract_uploads" / f"{task_id}_source{suffix}"
        signed = object_storage.signed_url(key)
        download_or_copy_media(signed, out, base_url)
        if out.exists():
            return out
    raise RuntimeError("上传源文件不存在，请重新上传")


def _execute_extract_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["task_id"]
    payload = dict(task.get("payload") or {})
    model = payload.get("model") or "base"
    if payload.get("reference_text") and str(payload.get("reference_text")).strip():
        text = str(payload.get("reference_text")).strip()
        return {"task_id": task_id, "extracted_script": text, "segments": []}
    if payload.get("reference_url") and str(payload.get("reference_url")).strip():
        reference_url = str(payload.get("reference_url")).strip()
        _update(task_id, 25, "正在调用链接转写接口")
        result = call_asr_url(reference_url, model=model)
        method = "url_transcribe"
        text = result.get("text") or ""
        if not text:
            raise RuntimeError("ASR 接口未返回文案")
        return {"task_id": task_id, "extracted_script": text, "segments": result.get("segments") or [], "transcribe_method": method}

    base_url = _payload_base_url(payload)
    path = _source_path_from_payload(payload, task_id, base_url)
    size = int(payload.get("size_bytes") or _file_size(path))
    _update(task_id, 20, "正在准备上传文件")
    suffix = path.suffix.lower()
    audio_path = path
    if suffix in ALLOWED_VIDEO_SUFFIXES:
        _update(task_id, 35, "正在调用视频转写接口")
        result = call_asr_media(path, is_video=True, model=model)
        method = "video_transcribe"
    else:
        _update(task_id, 60, "正在调用 ASR 接口")
        result = call_asr_media(audio_path, is_video=False, model=model)
        method = "audio_transcribe"
    text = result.get("text") or ""
    if not text:
        raise RuntimeError("ASR 接口未返回文案")
    result_payload = {
        "task_id": task_id,
        "extracted_script": text,
        "segments": result.get("segments") or [],
        "source_file": str(path),
        "size_bytes": size,
        "transcribe_method": method,
    }
    for key in ("source_storage_provider", "source_object_key", "source_object_url", "source_object_error"):
        if payload.get(key):
            result_payload[key] = payload[key]
    return result_payload


def _execute_rewrite_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["task_id"]
    payload = RewritePayload.model_validate(task.get("payload") or {})
    _update(task_id, 30, "正在改写文案")
    if payload.rewrite_engine == "fast":
        text = _fast_rewrite(payload.reference_text)
    else:
        system, user = _rewrite_prompt(payload)
        text = call_llm(system, user)
    text = _format_script_lines(text)
    if not text:
        raise RuntimeError("改写接口未返回有效文案")
    return {"task_id": task_id, "final_script": text, "rewrite_fallback": False}


def _execute_tts_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["task_id"]
    user_id = task.get("user_id") or "local"
    payload = TtsPayload.model_validate(task.get("payload") or {})
    _update(task_id, 35, "正在调用 TTS 接口")
    voice_item = voice_store.get_voice(payload.voice_id, user_id=user_id) if payload.voice_id else None
    ref_path = _voice_audio_local_path(voice_item) if voice_item else None
    if not ref_path:
        ref_path = _resolve_voice_path(payload.voice_ref_wav)
    output_path = OUTPUT_DIR / f"{task_id}.wav"
    call_tts(
        payload.text,
        output_path,
        voice_id=payload.voice_id,
        voice_ref_wav=ref_path if ref_path and ref_path.exists() else None,
        voice_ref_text=payload.voice_ref_text,
        speed=payload.speed,
    )
    result = {
        "task_id": task_id,
        "text": payload.text,
        "audio_path": str(output_path),
        "audio_url": _public_url("audio", task_id),
        "size_bytes": _file_size(output_path),
    }
    _apply_object_result(
        result,
        "audio",
        _upload_to_object_storage(output_path, user_id=user_id, purpose="outputs/audio", task_id=task_id),
    )
    return result


def _execute_video_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["task_id"]
    user_id = task.get("user_id") or "local"
    data = dict(task.get("payload") or {})
    data["taskId"] = task_id
    base_url = _payload_base_url(data)
    _update(task_id, 25, "正在准备剪辑素材")
    options = data.setdefault("options", {})
    if (options.get("subtitleTiming") or "").lower() == "api":
        options["subtitleTiming"] = "estimated"
    video_compose_config = load_service_config(mask_secret=False).get("videoCompose") or {}
    if video_compose_config.get("enabled") and video_compose_config.get("url"):
        external_payload = _external_video_compose_payload(data, user_id, base_url)
        _update(task_id, 35, "正在调用外部视频剪辑接口")
        result = call_video_compose(external_payload, OUTPUT_DIR / f"{task_id}_moviepy_video.mp4")
        result["compose_method"] = "external_video_compose"
        result["external_video_count"] = len(external_payload["video_urls"])
    else:
        _update(task_id, 35, "未配置外部剪辑接口，使用本地剪辑")
        result = render_video(data, base_url)
        result["compose_method"] = "local_moviepy"
    result.update(
        {
            "task_id": task_id,
            "video_url": _public_url("video", task_id),
            "outputVideoUrl": _public_url("video", task_id),
        }
    )
    video_path_value = result.get("video_path")
    video_path = Path(video_path_value) if video_path_value else None
    if video_path and video_path.exists():
        result["size_bytes"] = _file_size(video_path)
        _apply_object_result(
            result,
            "video",
            _upload_to_object_storage(video_path, user_id=user_id, purpose="outputs/video", task_id=task_id),
        )
    if result.get("subtitle_path"):
        result["subtitle_url"] = _public_url("subtitle", task_id)
        subtitle_path_value = result.get("subtitle_path")
        subtitle_path = Path(subtitle_path_value) if subtitle_path_value else None
        if subtitle_path and subtitle_path.exists():
            _apply_object_result(
                result,
                "subtitle",
                _upload_to_object_storage(
                    subtitle_path,
                    user_id=user_id,
                    purpose="outputs/subtitles",
                    task_id=task_id,
                ),
            )
    return result


def _execute_wav2lip_task(task: dict[str, Any]) -> dict[str, Any]:
    task_id = task["task_id"]
    user_id = task.get("user_id") or "local"
    payload = LipSyncPayload.model_validate(task.get("payload") or {})
    base_url = _payload_base_url(task.get("payload") or {})
    _update(task_id, 20, "正在准备口型同步素材")
    video_path = _resolve_media_to_local(payload.videoUrl, base_url, ".mp4")
    audio_path = _resolve_media_to_local(payload.audioUrl, base_url, ".wav")
    output_path = OUTPUT_DIR / f"{task_id}_wav2lip_video.mp4"
    _update(task_id, 45, "正在调用口型同步接口")
    call_lip_sync(
        video_path,
        audio_path,
        output_path,
        {
            "pads": payload.pads,
            "resizeFactor": payload.resizeFactor,
            "noSmooth": payload.noSmooth,
            "enhanceMode": payload.enhanceMode,
        },
    )
    result = {
        "task_id": task_id,
        "video_url": _public_url("wav2lip", task_id),
        "video_path": str(output_path),
        "audio_source_path": payload.audioUrl,
        "pads": payload.pads,
        "resize_factor": payload.resizeFactor,
        "no_smooth": payload.noSmooth,
        "enhance_mode": payload.enhanceMode,
        "size_bytes": _file_size(output_path),
    }
    _apply_object_result(
        result,
        "video",
        _upload_to_object_storage(output_path, user_id=user_id, purpose="outputs/wav2lip", task_id=task_id),
    )
    return result


def _execute_stored_task(task_id: str) -> dict[str, Any]:
    task = task_store.get_task(task_id, include_payload=True)
    if not task:
        raise RuntimeError("任务不存在")
    kind = task.get("kind")
    if kind == "extract":
        return _execute_extract_task(task)
    if kind == "rewrite":
        return _execute_rewrite_task(task)
    if kind == "tts":
        return _execute_tts_task(task)
    if kind == "video":
        return _execute_video_task(task)
    if kind == "wav2lip":
        return _execute_wav2lip_task(task)
    raise RuntimeError("该任务类型不支持执行")


def _run_task(task_id: str):
    existing = task_store.get_task(task_id, include_payload=True)
    if existing and existing.get("status") == "canceled":
        return
    task_store.update_task(task_id, status="running", started_at=_now(), progress=1, message="开始处理")
    try:
        _finish(task_id, _execute_stored_task(task_id))
    except Exception as exc:
        _fail(task_id, exc)
        raise


def _enqueue(
    background_tasks: BackgroundTasks,
    task_id: str,
    kind: str,
    title: str,
    payload: dict[str, Any],
    user_id: str | None = None,
):
    task_store.create_task(task_id, kind, title, payload, user_id=user_id)
    try:
        job_runner.submit(task_id, lambda: _run_task(task_id))
    except Exception as exc:
        _fail(task_id, exc)
        raise HTTPException(status_code=503, detail=f"任务队列不可用：{exc}") from exc
    return {"task_id": task_id, "status": "queued", "poll_url": f"/api/v1/jobs/{task_id}"}


def _retry_task(task: dict[str, Any], request: Request, background_tasks: BackgroundTasks):
    payload = dict(task.get("payload") or {})
    kind = task.get("kind")
    payload["taskId"] = _safe_id(f"{kind}_retry")
    if kind == "extract":
        if not payload.get("reference_url") and not payload.get("reference_text") and not payload.get("source_file") and not payload.get("source_object_key"):
            raise HTTPException(status_code=400, detail="上传文件提取任务无法自动重试，请重新上传文件")
        payload["_base_url"] = payload.get("_base_url") or _base_url(request)
        if payload.get("source_file") or payload.get("source_object_key"):
            task_id = _task_id(payload.get("taskId"), "extract")
            return _enqueue(background_tasks, task_id, "extract", "上传文件提取文案", payload, user_id=task.get("user_id"))
        return _start_script_extract(ExtractPayload.model_validate(payload), request, background_tasks)
    if kind == "rewrite":
        return rewrite_start(RewritePayload.model_validate(payload), request, background_tasks)
    if kind == "tts":
        return _start_speech(TtsPayload.model_validate(payload), request, background_tasks)
    if kind == "video":
        return _start_video_compose(VideoPayload.model_validate(payload), request, background_tasks)
    if kind == "wav2lip":
        return lip_sync_start(LipSyncPayload.model_validate(payload), request, background_tasks)
    raise HTTPException(status_code=400, detail="该任务类型不支持重试")


def _format_script_lines(text: str) -> str:
    sentences: list[str] = []
    for raw_line in re.split(r"[\r\n]+", text or ""):
        line = re.sub(r"\s+", "", raw_line).strip()
        if not line:
            continue
        clean = line.strip(" \t，、：:,.")
        if not clean:
            continue
        if not re.search(r"[。！？!?；;，,]$", clean):
            clean += "。"
        sentences.append(clean)
    return "".join(sentences)


def _split_sentences(text: str) -> list[str]:
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []
    parts = re.split(r"(?<=[。！？!?])\s*|[；;]\s*", text)
    return [part.strip(" ，。！？、；：,.!?;:") for part in parts if part.strip(" ，。！？、；：,.!?;:")]


def _fast_rewrite(text: str) -> str:
    sentences = _split_sentences(text)
    if not sentences:
        return ""
    lead = "很多人一开始都忽略了这件事"
    rewritten = [lead, *sentences[:12]]
    return _format_script_lines("。".join(rewritten))


def _realtor_rewrite_prompt(payload: RewritePayload) -> tuple[str, str]:
    context = payload.realtor_context or {}
    system = (
        "你是一名成交能力强、表达克制真实的资深房产经纪人，也懂短视频口播。"
        "你的目标不是罗列房源信息，而是让目标客户觉得这套房值得私信或约看。"
        "输出一整段中文口播正文，不要换行，不要标题，不要编号，不要解释。"
        "可以主动添加逗号、句号、问号、感叹号等中文标点，让语气像真人在镜头前说话。"
    )
    user = f"""
请根据结构化房源字段生成一条房产短视频口播文案。

内部写作方法：
1. 先判断最可能成交的目标客户，以及这套房最强的 2-3 个成交理由。
2. 第一句直接切客户真实顾虑或生活场景，不要用“今天这套房”“很多客户”“这套房源”这种泛开头。
3. 每个卖点都要翻译成客户利益，比如省钱、省事、住得舒服、老人孩子方便、换房压力更小。
4. 信息不够时少说，不要编造学校名称、地铁距离、涨幅、收益率、唯一性。
5. 结尾给一个自然动作，引导私信、看房、拿对比表或税费方案，不要喊口号。

语言要求：
- 像经纪人当面沟通，不像楼书广告，不像 AI 总结。
- 多用短句和具体场景，少用抽象形容词。
- 不要堆砌“板块价值、全面兑现、安全垫、黄金楼层、完美、闭眼入、稳赚、必涨、全城最低、唯一机会”等油腻或违规表达。
- 只输出最终正文，一整段，不换行。

内容时长：{context.get("contentDuration") or payload.rewrite_length}
文案风格：{context.get("style") or payload.rewrite_style}
行动引导：{context.get("callToAction") or "自然邀约"}

结构化房源字段：
{json.dumps(context, ensure_ascii=False, indent=2)}

前端整理的房源信息：
{payload.reference_text}
"""
    return system, user


def _rewrite_prompt(payload: RewritePayload) -> tuple[str, str]:
    if payload.realtor_context:
        return _realtor_rewrite_prompt(payload)
    system = (
        "你是短视频口播文案策划，擅长把普通文字改成有传播力、有转化力的真人口播。"
        "输出一整段中文正文，不要换行，不要标题，不要编号，不要解释。"
        "可以主动添加逗号、句号、问号、感叹号等中文标点，让节奏自然。"
    )
    user = f"""
请改写下面文案。

风格：{payload.rewrite_style}
语气：{payload.rewrite_tone}
篇幅：{payload.rewrite_length}
平台：{payload.rewrite_platform}
改写强度：{payload.rewrite_strength}

改写要求：
1. 不要只是换同义词，要重组表达，让开头更能抓住目标用户。
2. 保留原文核心事实和观点，但删掉空话、套话、重复表达。
3. 如果是转化型内容，要写出痛点、利益点和自然行动引导。
4. 语言像真人口播，少用“首先、其次、最后”和报告式总结。
5. 只输出最终正文，一整段，不换行。

原文：
{payload.reference_text}
"""
    return system, user


def _resolve_output_file(kind: str, task_id: str) -> Path:
    patterns = {
        "audio": [f"{task_id}.wav", f"{task_id}.mp3", f"{task_id}_audio.wav", f"{task_id}_audio.mp3"],
        "video": [f"{task_id}_moviepy_video.mp4", f"{task_id}.mp4"],
        "wav2lip": [f"{task_id}_wav2lip_video.mp4", f"{task_id}.mp4"],
        "subtitle": [f"{task_id}_subtitles.srt"],
    }
    for name in patterns.get(kind, []):
        path = OUTPUT_DIR / name
        if path.exists():
            return path
    raise HTTPException(status_code=404, detail="文件不存在")


def _download_task_object(kind: str, task_id: str, out: Path, base_url: str) -> Path | None:
    field = "audio" if kind == "audio" else "video"
    if kind == "subtitle":
        field = "subtitle"
    task = task_store.get_task(task_id)
    result = (task or {}).get("result") or {}
    key = result.get(f"{field}_object_key")
    if not key or not object_storage.enabled():
        return None
    signed = object_storage.signed_url(key)
    download_or_copy_media(signed, out, base_url)
    return out if out.exists() else None


def _download_upload_object(filename: str, out: Path, base_url: str) -> Path | None:
    item = task_store.get_upload(filename)
    key = (item or {}).get("video_object_key") or (item or {}).get("object_key")
    if not key or not object_storage.enabled():
        return None
    signed = object_storage.signed_url(key)
    download_or_copy_media(signed, out, base_url)
    return out if out.exists() else None


def _media_value_path(value: str) -> str:
    parsed = urlparse(value or "")
    path = parsed.path if parsed.scheme else str(value or "").split("?", 1)[0]
    return path.strip()


def _signed_upload_url(value: str, user_id: str) -> str | None:
    path = _media_value_path(value)
    marker = "/api/v1/uploads/"
    if marker not in path:
        return None
    filename = Path(path.split(marker, 1)[1]).name
    item = task_store.get_upload(filename, user_id=user_id) if _auth_is_active() else task_store.get_upload(filename)
    key = (item or {}).get("video_object_key") or (item or {}).get("object_key")
    if not key or not object_storage.enabled():
        return None
    return object_storage.url_for(key) or object_storage.signed_url(key)


def _signed_task_media_url(value: str, user_id: str, kind: str) -> str | None:
    path = _media_value_path(value)
    marker = f"/api/v1/{kind}/"
    if marker not in path:
        return None
    task_id = Path(path.split(marker, 1)[1]).name
    item = task_store.get_task(task_id, user_id=user_id) if _auth_is_active() else task_store.get_task(task_id)
    result = (item or {}).get("result") or {}
    field = "audio" if kind == "audio" else "video"
    key = result.get(f"{field}_object_key")
    if not key or not object_storage.enabled():
        return None
    return object_storage.url_for(key) or object_storage.signed_url(key)


def _external_media_url(value: str, user_id: str, base_url: str, *, kind: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise RuntimeError("外部剪辑缺少素材地址")
    signed = _signed_upload_url(raw, user_id)
    if signed:
        return signed
    signed = _signed_task_media_url(raw, user_id, kind)
    if signed:
        return signed
    parsed = urlparse(raw)
    if parsed.scheme in {"http", "https"} and "/api/v1/" not in parsed.path:
        return raw
    if not object_storage.enabled():
        raise RuntimeError("外部视频剪辑需要先启用 OSS，确保上传视频和配音音频有可访问的 OSS 链接")
    raise RuntimeError(f"素材未上传到 OSS，无法交给外部视频剪辑接口：{raw}")


def _external_video_compose_options(options: dict[str, Any]) -> dict[str, Any]:
    mapping = {
        "maxClipSeconds": "max_clip_seconds",
        "addSubtitle": "add_subtitle",
        "subtitlePosition": "subtitle_position",
        "subtitleMaxChars": "subtitle_max_chars",
        "loopVideo": "loop_video",
    }
    normalized = dict(options or {})
    for source, target in mapping.items():
        if source in normalized and target not in normalized:
            normalized[target] = normalized[source]
        normalized.pop(source, None)
    try:
        if "max_clip_seconds" in normalized and float(normalized["max_clip_seconds"]) <= 0:
            normalized.pop("max_clip_seconds", None)
    except (TypeError, ValueError):
        normalized.pop("max_clip_seconds", None)
    return normalized


def _external_video_compose_payload(data: dict[str, Any], user_id: str, base_url: str) -> dict[str, Any]:
    video_sources = data.get("videoUrls") or data.get("video_urls") or []
    if isinstance(video_sources, str):
        video_sources = [video_sources]
    single_video_source = data.get("videoUrl") or data.get("backgroundVideoUrl") or ""
    if single_video_source and single_video_source not in video_sources:
        video_sources.insert(0, single_video_source)
    signed_videos = [_external_media_url(source, user_id, base_url, kind="video") for source in video_sources if str(source or "").strip()]
    if not signed_videos:
        raise RuntimeError("外部视频剪辑缺少背景视频")
    audio_url = _external_media_url(data.get("audioUrl") or "", user_id, base_url, kind="audio")
    return {
        "video_urls": signed_videos,
        "audio_url": audio_url,
        "subtitle": data.get("subtitle") or "",
        "options": _external_video_compose_options(data.get("options") or {}),
    }


def _resolve_media_to_local(value: str, base_url: str, suffix: str = ".mp4") -> Path:
    parsed = urlparse(value or "")
    if parsed.path.startswith("/api/v1/audio/"):
        task_id = Path(parsed.path).name
        try:
            return _resolve_output_file("audio", task_id)
        except HTTPException:
            downloaded = _download_task_object("audio", task_id, TMP_DIR / f"media_{uuid.uuid4().hex[:8]}.wav", base_url)
            if downloaded:
                return downloaded
            raise
    if parsed.path.startswith("/api/v1/video/"):
        task_id = Path(parsed.path).name
        try:
            return _resolve_output_file("video", task_id)
        except HTTPException:
            downloaded = _download_task_object("video", task_id, TMP_DIR / f"media_{uuid.uuid4().hex[:8]}.mp4", base_url)
            if downloaded:
                return downloaded
            raise
    if parsed.path.startswith("/api/v1/wav2lip/"):
        task_id = Path(parsed.path).name
        try:
            return _resolve_output_file("wav2lip", task_id)
        except HTTPException:
            downloaded = _download_task_object("wav2lip", task_id, TMP_DIR / f"media_{uuid.uuid4().hex[:8]}.mp4", base_url)
            if downloaded:
                return downloaded
            raise
    if parsed.path.startswith("/api/v1/uploads/"):
        filename = Path(parsed.path).name
        path = UPLOAD_DIR / filename
        if path.exists():
            return path
        downloaded = _download_upload_object(filename, TMP_DIR / f"media_{uuid.uuid4().hex[:8]}{path.suffix or suffix}", base_url)
        if downloaded:
            return downloaded
    local = Path((value or "").split("?")[0]).expanduser()
    if local.is_absolute() and local.exists():
        return local
    out = TMP_DIR / f"media_{uuid.uuid4().hex[:8]}{suffix}"
    download_or_copy_media(value, out, base_url)
    return out


def _extract_audio_from_url(reference_url: str, output_path: Path):
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(
            [
                "yt-dlp",
                "-x",
                "--audio-format",
                "wav",
                "-o",
                str(output_path.with_suffix(".%(ext)s")),
                reference_url,
            ],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=240,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("未安装 yt-dlp，无法从视频链接提取音频；请安装或直接使用 ASR 文件接口") from exc
    except subprocess.CalledProcessError as exc:
        raise RuntimeError((exc.stderr or exc.stdout or "视频下载失败").strip()[-600:]) from exc
    wav_path = output_path.with_suffix(".wav")
    if wav_path.exists():
        return wav_path
    candidates = list(output_path.parent.glob(f"{output_path.stem}.*"))
    if candidates:
        return candidates[0]
    raise RuntimeError("视频音频提取失败")


def _extract_audio_from_media_file(source_path: Path, output_path: Path) -> Path:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-i",
            str(source_path),
            "-vn",
            "-acodec",
            "pcm_s16le",
            "-ar",
            "16000",
            "-ac",
            "1",
            str(output_path),
        ],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=240,
    )
    if not output_path.exists():
        raise RuntimeError("媒体文件音频提取失败")
    return output_path


@app.get("/api/v1/app-config")
def app_config():
    return {
        "name": APP_NAME,
        "mode": "api-only",
        "default_background_video": DEFAULT_BACKGROUND_VIDEO,
        "auth": {"required": AUTH_REQUIRED, "has_users": auth_store.user_count() > 0},
        "jobs": job_runner.status(),
        "task_status": _task_status_counts(),
        "object_storage": object_storage.status(),
    }


@app.get("/api/v1/health")
def health():
    return {
        "ok": True,
        "name": APP_NAME,
        "mode": "api-only",
        "jobs": job_runner.status(),
        "task_status": _task_status_counts(),
        "object_storage": object_storage.status(),
    }


@app.get("/api/v1/job-runner")
def job_runner_status(request: Request):
    _require_admin(request)
    return {"jobs": job_runner.status(), "task_status": _task_status_counts()}


@app.post("/api/v1/auth/register")
def auth_register(payload: AuthPayload):
    raise HTTPException(status_code=410, detail="注册功能已关闭，请联系管理员创建账号")


@app.post("/api/v1/auth/login")
def auth_login(payload: AuthPayload):
    user = auth_store.authenticate(payload.username, payload.password)
    if not user:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return {"user": user, "token": auth_store.issue_token(user)}


@app.get("/api/v1/auth/me")
def auth_me(request: Request):
    user = _current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="请先登录")
    return {"user": user}


@app.post("/api/v1/auth/logout")
def auth_logout():
    return {"ok": True}


@app.get("/api/v1/usage/me")
def usage_me(request: Request):
    user = _require_user(request)
    return {"user_id": user["id"], "usage": _usage_summary(user["id"])}


@app.get("/api/v1/quota/me")
def quota_me(request: Request):
    user = _require_user(request)
    return {"user_id": user["id"], "quota": _quota_summary(user["id"])}


@app.get("/api/v1/admin/users")
def admin_users(request: Request, limit: int = 100):
    _require_admin(request)
    users = auth_store.list_users(limit=limit)
    return {"users": users, "total": len(users)}


@app.post("/api/v1/admin/users")
def admin_create_user(payload: AdminUserPayload, request: Request):
    _require_admin(request)
    role = payload.role if payload.role in {"admin", "user", "realtor"} else "user"
    try:
        user = auth_store.create_user(payload.username, payload.password, role=role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"user": user}


@app.delete("/api/v1/admin/users/{user_id}")
def admin_delete_user(user_id: str, request: Request):
    current = _require_admin(request)
    if user_id == current["id"]:
        raise HTTPException(status_code=400, detail="不能删除当前登录的管理员")
    user = auth_store.get_user(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")
    if user.get("role") == "admin":
        admins = [item for item in auth_store.list_users(limit=500) if item.get("role") == "admin"]
        if len(admins) <= 1:
            raise HTTPException(status_code=400, detail="至少保留一个管理员")
    return {"deleted": auth_store.delete_user(user_id)}


@app.get("/api/v1/admin/tasks")
def admin_tasks(request: Request, limit: int = 100, kind: str | None = None):
    _require_admin(request)
    tasks = task_store.list_tasks(limit=limit, kind=kind)
    return {"tasks": tasks, "total": len(tasks)}


@app.get("/api/v1/admin/usage")
def admin_usage(request: Request):
    _require_admin(request)
    users = auth_store.list_users(limit=500)
    return {
        "usage": _usage_summary(),
        "users": [{"user": user, "usage": _usage_summary(user["id"])} for user in users],
    }


@app.get("/api/v1/admin/storage")
def admin_storage(request: Request):
    _require_admin(request)
    return storage()


@app.get("/api/v1/admin/service-configs")
def admin_service_configs(request: Request):
    _require_admin(request)
    return {"config": load_service_config(mask_secret=True)}


@app.put("/api/v1/admin/service-configs")
def admin_put_service_configs(payload: dict[str, Any], request: Request):
    _require_admin(request)
    return {"config": save_service_config(payload)}


@app.get("/api/v1/service-config")
def get_service_config(request: Request):
    _require_admin(request)
    return {"config": load_service_config(mask_secret=True)}


@app.put("/api/v1/service-config")
def put_service_config(payload: dict[str, Any], request: Request):
    _require_admin(request)
    return {"config": save_service_config(payload)}


@app.get("/api/v1/rewrite-options")
def rewrite_options():
    return {
        "styles": [
            {"id": "viral", "name": "爆款钩子", "desc": "强开头、强节奏"},
            {"id": "story", "name": "故事叙事", "desc": "人物、冲突、反转"},
            {"id": "knowledge", "name": "干货科普", "desc": "清晰可信、信息密度高"},
            {"id": "emotional", "name": "情绪共鸣", "desc": "代入感和情绪价值"},
            {"id": "sales", "name": "种草转化", "desc": "痛点、利益点、行动引导"},
            {"id": "plain", "name": "自然口播", "desc": "少套路，更像真人表达"},
        ],
        "tones": [
            {"id": "natural", "name": "自然"},
            {"id": "sharp", "name": "犀利"},
            {"id": "warm", "name": "温暖"},
            {"id": "professional", "name": "专业"},
            {"id": "suspense", "name": "悬念"},
        ],
        "lengths": [
            {"id": "short", "name": "短", "desc": "150-250 字"},
            {"id": "medium", "name": "中", "desc": "250-400 字"},
            {"id": "long", "name": "长", "desc": "400-600 字"},
        ],
        "platforms": [{"id": "douyin", "name": "抖音/快手"}, {"id": "xiaohongshu", "name": "小红书"}],
        "strengths": [{"id": "light", "name": "轻度"}, {"id": "balanced", "name": "平衡"}, {"id": "heavy", "name": "深度"}],
    }


@app.post("/api/v1/extract/start")
def extract_start(payload: ExtractPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_script_extract(payload, request, background_tasks)


@app.post("/api/v1/script-extract/start")
def script_extract_start(payload: ExtractPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_script_extract(payload, request, background_tasks)


def _start_script_extract(payload: ExtractPayload, request: Request, background_tasks: BackgroundTasks):
    if not (payload.reference_text and payload.reference_text.strip()) and not (payload.reference_url and payload.reference_url.strip()):
        raise HTTPException(status_code=422, detail="reference_url 或 reference_text 必填")
    task_id = _task_id(payload.taskId, "extract")
    data = payload.model_dump()
    data["_base_url"] = _base_url(request)
    return _enqueue(background_tasks, task_id, "extract", "提取文案", data, user_id=_request_user_id(request))


@app.post("/api/v1/rewrite/start")
def rewrite_start(payload: RewritePayload, request: Request, background_tasks: BackgroundTasks):
    task_id = _task_id(payload.taskId, "rewrite")
    data = payload.model_dump()
    data["_base_url"] = _base_url(request)
    return _enqueue(background_tasks, task_id, "rewrite", "AI 改写文案", data, user_id=_request_user_id(request))


@app.post("/api/v1/tts/start")
def tts_start(payload: TtsPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_speech(payload, request, background_tasks)


@app.post("/api/v1/tts/sample/start")
def tts_sample_start(payload: TtsPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_speech(payload, request, background_tasks, cache_existing=True, title="试听样音")


@app.post("/api/v1/speech/start")
def speech_start(payload: TtsPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_speech(payload, request, background_tasks)


@app.post("/api/v1/voice-tts/start")
def voice_tts_start(payload: TtsPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_speech(payload, request, background_tasks)


def _start_speech(
    payload: TtsPayload,
    request: Request,
    background_tasks: BackgroundTasks,
    *,
    cache_existing: bool = False,
    title: str = "生成配音",
):
    task_id = _task_id(payload.taskId, "tts")
    user = _require_user(request)
    user_id = user["id"]
    if payload.voice_ref_wav:
        requested_ref = Path(payload.voice_ref_wav).expanduser()
        if not requested_ref.is_absolute():
            requested_ref = BASE_DIR / requested_ref
        if _auth_is_active() and not _find_user_voice_by_path(requested_ref, user):
            raise HTTPException(status_code=403, detail="无权使用该参考音频")
    if cache_existing:
        existing = task_store.get_task(task_id, include_payload=True, user_id=user_id)
        if existing and existing.get("kind") == "tts":
            status = existing.get("status")
            if status in {"queued", "running"}:
                return {"task_id": task_id, "status": status, "poll_url": f"/api/v1/jobs/{task_id}", "cached": True}
            if status == "success" and _task_audio_available(existing):
                return {"task_id": task_id, "status": "success", "poll_url": f"/api/v1/jobs/{task_id}", "cached": True}
    data = payload.model_dump()
    data["_base_url"] = _base_url(request)
    response = _enqueue(background_tasks, task_id, "tts", title, data, user_id=user_id)
    response["cached"] = False
    return response


@app.post("/api/v1/edit-video/start")
def edit_video_start(payload: VideoPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_video_compose(payload, request, background_tasks)


@app.post("/api/v1/video-compose/start")
def video_compose_start(payload: VideoPayload, request: Request, background_tasks: BackgroundTasks):
    return _start_video_compose(payload, request, background_tasks)


def _start_video_compose(payload: VideoPayload, request: Request, background_tasks: BackgroundTasks):
    task_id = _task_id(payload.taskId, "video")
    user_id = _request_user_id(request)
    data = payload.model_dump()
    data["taskId"] = task_id
    data["_base_url"] = _base_url(request)
    return _enqueue(background_tasks, task_id, "video", "视频剪辑成片", data, user_id=user_id)


@app.post("/api/v1/wav2lip/start")
def lip_sync_start(payload: LipSyncPayload, request: Request, background_tasks: BackgroundTasks):
    task_id = _task_id(payload.taskId, "lip_sync")
    user_id = _request_user_id(request)
    data = payload.model_dump()
    data["_base_url"] = _base_url(request)
    return _enqueue(background_tasks, task_id, "wav2lip", "口型同步", data, user_id=user_id)


async def _save_upload(file: UploadFile, target_dir: Path, allowed_suffixes: set[str]) -> tuple[Path, int]:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in allowed_suffixes:
        raise HTTPException(status_code=400, detail="文件格式不支持")
    target_dir.mkdir(parents=True, exist_ok=True)
    filename = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}{suffix}"
    path = target_dir / filename
    size = 0
    with open(path, "wb") as f:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_UPLOAD_BYTES:
                path.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="文件太大")
            f.write(chunk)
    return path, size


@app.post("/api/v1/script-extract/upload")
async def script_extract_upload(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    taskId: str | None = Form(None),
    model: str | None = Form("base"),
):
    user_id = _request_user_id(request)
    path, size = await _save_upload(file, TMP_DIR / "script_extract_uploads", ALLOWED_TRANSCRIBE_SUFFIXES)
    task_id = _task_id(taskId, "extract")
    source_upload = _upload_to_object_storage(
        path,
        user_id=user_id,
        purpose="extract_uploads",
        filename=path.name,
        task_id=task_id,
    )
    payload = {
        "filename": file.filename or path.name,
        "stored_filename": path.name,
        "source_file": str(path),
        "size_bytes": size,
        "model": model,
        "_base_url": _base_url(request),
    }
    _apply_object_result(payload, "source", source_upload)
    return _enqueue(background_tasks, task_id, "extract", "上传文件提取文案", payload, user_id=user_id)


@app.post("/api/v1/upload-video")
async def upload_video(request: Request, file: UploadFile = File(...)):
    user_id = _request_user_id(request)
    path, size = await _save_upload(file, UPLOAD_DIR, ALLOWED_VIDEO_SUFFIXES)
    metadata = {
        "name": file.filename or path.name,
        "size_bytes": size,
        "video_url": f"/api/v1/uploads/{path.name}",
        "preview_url": f"/api/v1/uploads/{path.name}",
    }
    _apply_object_result(
        metadata,
        "video",
        _upload_to_object_storage(path, user_id=user_id, purpose="uploads/videos", filename=path.name),
    )
    item = task_store.record_upload(path.name, metadata, user_id=user_id)
    return item


@app.post("/api/v1/upload-voice")
async def upload_voice(request: Request, background_tasks: BackgroundTasks, file: UploadFile = File(...)):
    user_id = _request_user_id(request)
    if object_storage.enabled():
        filename, size, upload = await _upload_voice_file_to_object_storage(file, user_id)
        voice_id = Path(filename).stem
        ref_wav = f"voices/{filename}"
    else:
        path, size = await _save_upload(file, VOICE_DIR, ALLOWED_AUDIO_SUFFIXES)
        voice_id = path.stem
        ref_wav = _relative_to_base(path)
        upload = None
    voice = {
        "id": voice_id,
        "name": f"音色 {datetime.now().strftime('%m%d-%H%M')}",
        "kind": "local",
        "user_id": user_id,
        "ref_wav": ref_wav,
        "ref_text": "",
        "size_bytes": size,
        "created_at": _now(),
    }
    if upload:
        voice["storage_provider"] = upload.get("provider") or "aliyun_oss"
        voice["object_key"] = upload.get("key") or ""
        if upload.get("url"):
            voice["object_url"] = upload.get("url")
    voice_store.upsert_voice(voice)
    if object_storage.enabled() and not upload:
        background_tasks.add_task(_sync_voice_object_storage, voice_id, user_id, str(path))
    return {"voice": voice, "size_bytes": size}


@app.get("/api/v1/voices")
def voices(request: Request):
    user = _require_user(request)
    local_items = []
    for item in _iter_voice_meta():
        if not _voice_visible_to_user(item, user):
            continue
        local_items.append(
            {
                "id": item.get("id"),
                "name": item.get("name") or item.get("id"),
                "kind": "local",
                "ref_wav": item.get("ref_wav") or "",
                "ref_text": item.get("ref_text") or "",
                "size_bytes": item.get("size_bytes") or 0,
                "created_at": item.get("created_at"),
                "object_key": item.get("object_key") or "",
                "meta_object_key": item.get("meta_object_key") or "",
            }
        )
    return {"voices": local_items}


@app.patch("/api/v1/voices/{voice_id}")
def update_voice(voice_id: str, payload: VoiceNamePayload, request: Request):
    user = _require_user(request)
    item = _find_user_voice(voice_id, user)
    if not item:
        raise HTTPException(status_code=404, detail="音色不存在")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="音色名称不能为空")
    if len(name) > 50:
        raise HTTPException(status_code=400, detail="音色名称不能超过 50 个字符")
    updated = voice_store.update_voice_name(voice_id, name, user_id=_voice_owner_id(item))
    if not updated:
        raise HTTPException(status_code=404, detail="音色不存在")
    return {"voice": updated}


@app.delete("/api/v1/voices/{voice_id}")
def delete_voice(voice_id: str, request: Request):
    user = _require_user(request)
    item = _find_user_voice(voice_id, user)
    if not item:
        raise HTTPException(status_code=404, detail="音色不存在")
    deleted_file = _delete_local_voice_file(item)
    try:
        deleted_object = object_storage.delete_object(item.get("object_key"))
    except Exception:
        deleted_object = False
    deleted = voice_store.delete_voice(voice_id, user_id=_voice_owner_id(item))
    return {"deleted": deleted, "deleted_file": deleted_file, "deleted_object": deleted_object}


@app.get("/api/v1/voices/{voice_id}/audio")
def voice_audio(voice_id: str, request: Request):
    item = _find_user_voice(voice_id, _require_user(request))
    if item:
        path = _resolve_voice_path(item.get("ref_wav"))
        if path and path.exists():
            return FileResponse(path)
        stream = _object_stream_response(item.get("object_key"), Path(str(item.get("ref_wav") or "voice.wav")).name)
        if stream:
            return stream
        redirect = _redirect_to_object(item.get("object_key"))
        if redirect:
            return redirect
    raise HTTPException(status_code=404, detail="音色不存在")


@app.get("/api/v1/uploads")
def uploads(request: Request, limit: int = 80):
    return {"uploads": task_store.list_uploads(limit=limit, user_id=_request_user_id(request))}


@app.get("/api/v1/uploads/{filename}")
def uploaded_file(filename: str, request: Request):
    safe_name = Path(filename).name
    user_id = _request_user_id(request)
    item = task_store.get_upload(safe_name, user_id=user_id) if _auth_is_active() else task_store.get_upload(safe_name)
    if _auth_is_active() and not item:
        raise HTTPException(status_code=404, detail="文件不存在")
    if item:
        redirect = _redirect_to_object(item.get("video_object_key") or item.get("object_key"))
        if redirect:
            return redirect
    path = UPLOAD_DIR / safe_name
    if not path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    return FileResponse(path)


@app.delete("/api/v1/uploads/{filename}")
def delete_upload(filename: str, request: Request):
    user_id = _request_user_id(request)
    if _auth_is_active() and not task_store.get_upload(Path(filename).name, user_id=user_id):
        raise HTTPException(status_code=404, detail="文件不存在")
    path = UPLOAD_DIR / Path(filename).name
    path.unlink(missing_ok=True)
    return {"deleted": task_store.delete_upload(Path(filename).name, user_id=user_id)}


@app.get("/api/v1/audio/{task_id}")
def audio_file(task_id: str, request: Request):
    redirect = _task_object_redirect(task_id, request, "audio")
    if redirect:
        return redirect
    return FileResponse(_resolve_output_file("audio", task_id))


@app.get("/api/v1/video/{task_id}")
def video_file(task_id: str, request: Request):
    redirect = _task_object_redirect(task_id, request, "video")
    if redirect:
        return redirect
    return FileResponse(_resolve_output_file("video", task_id))


@app.get("/api/v1/wav2lip/{task_id}")
def wav2lip_file(task_id: str, request: Request):
    redirect = _task_object_redirect(task_id, request, "video")
    if redirect:
        return redirect
    return FileResponse(_resolve_output_file("wav2lip", task_id))


@app.get("/api/v1/subtitle/{task_id}")
def subtitle_file(task_id: str, request: Request):
    redirect = _task_object_redirect(task_id, request, "subtitle")
    if redirect:
        return redirect
    return FileResponse(_resolve_output_file("subtitle", task_id), media_type="text/plain")


@app.get("/api/v1/jobs/{task_id}")
def job(task_id: str, request: Request):
    item = task_store.get_task(task_id, user_id=_request_user_id(request))
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    return _fail_if_orphaned_task(item)


@app.post("/api/v1/tasks/{task_id}/cancel")
def cancel_task(task_id: str, request: Request):
    user_id = _request_user_id(request)
    item = task_store.get_task(task_id, include_payload=True, user_id=user_id)
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    status = item.get("status")
    if status in {"success", "failed", "canceled"}:
        return {"task_id": task_id, "status": status, "canceled": False}
    if status == "running":
        raise HTTPException(status_code=409, detail="任务已开始运行，当前执行器暂不支持强制中断")
    canceled = job_runner.cancel(task_id)
    if not canceled and status != "queued":
        raise HTTPException(status_code=409, detail="任务当前状态无法取消")
    task_store.update_task(
        task_id,
        status="canceled",
        progress=100,
        message="已取消",
        error=None,
        finished_at=_now(),
    )
    return {"task_id": task_id, "status": "canceled", "canceled": True}


@app.post("/api/v1/tasks/{task_id}/retry")
def retry_task(task_id: str, request: Request, background_tasks: BackgroundTasks):
    item = task_store.get_task(task_id, include_payload=True, user_id=_request_user_id(request))
    if not item:
        raise HTTPException(status_code=404, detail="任务不存在")
    if item.get("status") in {"queued", "running"}:
        raise HTTPException(status_code=409, detail="任务仍在执行，不能重试")
    return _retry_task(item, request, background_tasks)


@app.get("/api/v1/history")
def history(request: Request, limit: int = 12, kind: str | None = None):
    return {"tasks": task_store.list_tasks(limit=limit, kind=kind, user_id=_request_user_id(request))}


@app.delete("/api/v1/history/{task_id}")
def delete_history(task_id: str, request: Request):
    return {"deleted": task_store.delete_task(task_id, user_id=_request_user_id(request))}


def _dir_stats(path: Path) -> dict[str, int]:
    files = [p for p in path.rglob("*") if p.is_file()] if path.exists() else []
    return {"bytes": sum(p.stat().st_size for p in files), "files": len(files)}


@app.get("/api/v1/storage")
def storage():
    sections = {
        "tmp": _dir_stats(TMP_DIR),
        "uploads": _dir_stats(UPLOAD_DIR),
        "outputs": _dir_stats(OUTPUT_DIR),
        "voices": _dir_stats(VOICE_DIR),
    }
    return {
        **sections,
        "jobs": job_runner.status(),
        "task_status": _task_status_counts(),
        "object_storage": object_storage.status(),
        "total_bytes": sum(item["bytes"] for item in sections.values()),
        "total_files": sum(item["files"] for item in sections.values()),
    }


@app.post("/api/v1/storage/cleanup")
def cleanup(payload: dict[str, Any], request: Request):
    _require_admin(request)
    include_tmp = _as_bool(payload.get("include_tmp"), True)
    include_outputs = _as_bool(payload.get("include_outputs"), False)
    include_uploads = _as_bool(payload.get("include_uploads"), False)
    dangerous_sections = []
    if include_outputs:
        dangerous_sections.append("outputs")
    if include_uploads:
        dangerous_sections.append("uploads")
    if dangerous_sections:
        expected_confirm = f"delete:{','.join(dangerous_sections)}"
        if str(payload.get("confirm") or "") != expected_confirm:
            raise HTTPException(
                status_code=400,
                detail=f"清理 {', '.join(dangerous_sections)} 需要 confirm={expected_confirm}",
            )
    try:
        older_than_hours = max(0.0, float(payload.get("older_than_hours", 0) or 0))
    except (TypeError, ValueError):
        older_than_hours = 0.0
    cutoff = time.time() - older_than_hours * 3600 if older_than_hours else None
    dirs = []
    if include_tmp:
        dirs.append(TMP_DIR)
    if include_outputs:
        dirs.append(OUTPUT_DIR)
    if include_uploads:
        dirs.append(UPLOAD_DIR)
    deleted_files = deleted_dirs = bytes_deleted = 0
    for folder in dirs:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob("*"), key=lambda p: len(p.parts), reverse=True):
            try:
                if path.is_file():
                    if cutoff and path.stat().st_mtime > cutoff:
                        continue
                    bytes_deleted += path.stat().st_size
                    path.unlink()
                    deleted_files += 1
                elif path.is_dir():
                    path.rmdir()
                    deleted_dirs += 1
            except OSError:
                pass
        folder.mkdir(parents=True, exist_ok=True)
    return {"cleanup": {"deleted_files": deleted_files, "deleted_dirs": deleted_dirs, "bytes_deleted": bytes_deleted}}


if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


@app.get("/{path:path}")
def spa(path: str = ""):
    index = FRONTEND_DIST / "index.html"
    if index.exists():
        candidate = FRONTEND_DIST / path
        if path and candidate.exists() and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(index)
    return {"name": APP_NAME, "message": "前端尚未构建，请先执行 npm run build", "project": str(BASE_DIR)}

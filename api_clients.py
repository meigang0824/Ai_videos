from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
import re
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests

from pipeline.config import STORAGE_DIR
from pipeline.service_config_store import service_config_store


CONFIG_PATH = STORAGE_DIR / "service_config.json"
logger = logging.getLogger("cosyvoice.api_clients")

DEFAULT_SERVICE_CONFIG: dict[str, Any] = {
    "llm": {
        "enabled": False,
        "url": "",
        "apiKey": "",
        "model": "",
        "timeout": 90,
    },
    "asr": {
        "enabled": False,
        "url": "",
        "videoUrl": "",
        "apiKey": "",
        "model": "base",
        "timeout": 180,
    },
    "tts": {
        "enabled": False,
        "url": "",
        "cloneUrl": "",
        "apiKey": "",
        "timeout": 240,
    },
    "lipSync": {
        "enabled": False,
        "url": "",
        "apiKey": "",
        "outputMode": "binary",
        "videoPath": "video_url",
        "base64Path": "video",
        "timeout": 900,
    },
    "videoCompose": {
        "enabled": False,
        "url": "",
        "apiKey": "",
        "timeout": 900,
    },
}


def _merge_defaults(data: dict[str, Any] | None) -> dict[str, Any]:
    merged = deepcopy(DEFAULT_SERVICE_CONFIG)
    for section, values in (data or {}).items():
        if isinstance(values, dict) and section in merged:
            if section == "asr":
                values = _normalize_asr_config(values)
            allowed = set(DEFAULT_SERVICE_CONFIG[section])
            merged[section].update({key: value for key, value in values.items() if key in allowed})
    return merged


def load_service_config(mask_secret: bool = False) -> dict[str, Any]:
    data = service_config_store.load()
    if data is None:
        data = service_config_store.migrate_from_file(CONFIG_PATH) or {}
    merged = _merge_defaults(data)
    if mask_secret:
        masked = deepcopy(merged)
        for section in masked.values():
            if section.get("apiKey"):
                section["apiKey"] = "********"
        return masked
    return merged


def save_service_config(payload: dict[str, Any]) -> dict[str, Any]:
    current = load_service_config(mask_secret=False)
    next_config = _merge_defaults(payload)
    for section, values in next_config.items():
        key = str(values.get("apiKey") or "")
        if not key or "*" in key:
            values["apiKey"] = current.get(section, {}).get("apiKey", "")
    service_config_store.save(next_config)
    return load_service_config(mask_secret=True)


def _section(name: str) -> dict[str, Any]:
    config = load_service_config(mask_secret=False).get(name) or {}
    has_url = bool(config.get("url") or (name == "asr" and config.get("videoUrl")))
    if not config.get("enabled") or not has_url:
        raise RuntimeError(f"请先在接口配置里启用并填写 {name} 接口")
    return config


def _timeout(config: dict[str, Any], default: int) -> int:
    try:
        return max(5, int(config.get("timeout") or default))
    except (TypeError, ValueError):
        return default


def _headers(config: dict[str, Any], json_mode: bool = False, default_prefix: str = "") -> dict[str, str]:
    headers: dict[str, str] = {}
    key = str(config.get("apiKey") or "").strip()
    if key:
        header_name = str(config.get("headerName") or "Authorization").strip()
        prefix = str(config.get("headerPrefix") or default_prefix or "")
        if prefix and key.lower().startswith(prefix.strip().lower() + " "):
            headers[header_name] = key
        else:
            headers[header_name] = f"{prefix}{key}" if prefix else key
    if json_mode:
        headers["Content-Type"] = "application/json"
    return headers


def _asr_headers(config: dict[str, Any], json_mode: bool = False) -> dict[str, str]:
    return _headers(config, json_mode=json_mode, default_prefix="Bearer ")


def _tts_headers(config: dict[str, Any], json_mode: bool = False) -> dict[str, str]:
    return _headers(config, json_mode=json_mode, default_prefix="Bearer ")


def _lip_sync_headers(config: dict[str, Any], json_mode: bool = False) -> dict[str, str]:
    return _headers(config, json_mode=json_mode, default_prefix="Bearer ")


def _video_compose_headers(config: dict[str, Any], json_mode: bool = False) -> dict[str, str]:
    return _headers(config, json_mode=json_mode, default_prefix="Bearer ")


def _raise_for_status(response: requests.Response):
    try:
        response.raise_for_status()
    except requests.HTTPError as exc:
        message = response.text
        try:
            data = response.json()
            if isinstance(data, dict) and data.get("detail"):
                message = str(data["detail"])
        except ValueError:
            pass
        raise RuntimeError(message.strip() or str(exc)) from exc


def _get_path(data: Any, path: str | None) -> Any:
    if not path:
        return None
    current = data
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        elif isinstance(current, dict):
            current = current.get(part)
        else:
            return None
    return current


def _download_file(url: str, output_path: Path, timeout: int, base_url: str | None = None):
    resolved_url = urljoin(base_url, url) if base_url else url
    with requests.get(resolved_url, stream=True, timeout=timeout) as response:
        _raise_for_status(response)
        with open(output_path, "wb") as f:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)


def _replace_path_suffix(url: str, old_suffix: str, new_suffix: str) -> str | None:
    base = url.split("?", 1)[0].rstrip("/")
    if not base.endswith(old_suffix):
        return None
    return f"{base[: -len(old_suffix)]}{new_suffix}"


def _derive_asr_endpoint(value: str, target: str) -> str:
    value = str(value or "").strip()
    if not value:
        return ""
    replacements = {
        "audio": [
            ("/v1/audio/transcribe-url", "/v1/audio/transcribe"),
            ("/v1/video/transcribe", "/v1/audio/transcribe"),
        ],
        "url": [
            ("/v1/audio/transcribe", "/v1/audio/transcribe-url"),
            ("/v1/video/transcribe", "/v1/audio/transcribe-url"),
        ],
        "video": [
            ("/v1/audio/transcribe", "/v1/video/transcribe"),
            ("/v1/audio/transcribe-url", "/v1/video/transcribe"),
        ],
    }
    for old_suffix, new_suffix in replacements.get(target, []):
        derived = _replace_path_suffix(value, old_suffix, new_suffix)
        if derived:
            return derived
    return value


def _normalize_asr_config(values: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(values)
    legacy_audio_url = str(normalized.get("url") or "").strip()
    legacy_link_url = str(normalized.get("urlTranscribeUrl") or "").strip()
    legacy_video_url = str(
        normalized.get("videoUrl") or normalized.get("video_url") or normalized.get("videoTranscribeUrl") or ""
    ).strip()
    if legacy_link_url:
        normalized["url"] = legacy_link_url
    elif legacy_audio_url and legacy_audio_url.rstrip("/").endswith("/v1/audio/transcribe"):
        normalized["url"] = _derive_asr_endpoint(legacy_audio_url, "url")
    if legacy_video_url:
        normalized["videoUrl"] = legacy_video_url
    elif legacy_audio_url:
        normalized["videoUrl"] = _derive_asr_endpoint(legacy_audio_url, "video")
    return normalized


def _asr_endpoint(config: dict[str, Any], kind: str) -> str:
    link_url = str(config.get("url") or "").strip()
    video_url = str(config.get("videoUrl") or "").strip()
    if kind == "audio":
        return _derive_asr_endpoint(video_url or link_url, "audio")
    if kind == "url":
        return link_url or _derive_asr_endpoint(video_url, "url")
    if kind == "video":
        return video_url or _derive_asr_endpoint(link_url, "video")
    return link_url or video_url


def _parse_asr_result(result: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    text = (
        _get_path(result, config.get("textPath"))
        or result.get("text")
        or result.get("script")
        or result.get("transcript")
        or result.get("content")
        or result.get("result")
        or _get_path(result, "data.text")
        or _get_path(result, "data.script")
        or ""
    )
    segments = (
        _get_path(result, config.get("segmentsPath"))
        or result.get("segments")
        or _get_path(result, "data.segments")
        or []
    )
    return {"text": str(text).strip(), "segments": segments if isinstance(segments, list) else []}


def _extract_rewrite_script(user_prompt: str) -> str:
    marker = "原文："
    if marker in user_prompt:
        return user_prompt.split(marker, 1)[1].strip()
    return user_prompt.strip()


def _extract_rewrite_style(user_prompt: str) -> str:
    match = re.search(r"^风格：(.+)$", user_prompt, re.MULTILINE)
    return match.group(1).strip() if match else ""


def _clean_url(value: str) -> str:
    value = str(value or "").strip()
    markdown_match = re.search(r"\((https?://[^)]+)\)", value)
    if markdown_match:
        return markdown_match.group(1).strip()
    bracket_match = re.search(r"https?://[^\]\s)]+", value)
    if bracket_match:
        return bracket_match.group(0).strip()
    return value


def _openai_chat_endpoint(value: str) -> str:
    endpoint = _clean_url(value).rstrip("/")
    if endpoint.endswith("/v1"):
        return f"{endpoint}/chat/completions"
    return endpoint


def call_llm(system_prompt: str, user_prompt: str, temperature: float = 0.7) -> str:
    config = _section("llm")
    provider = str(config.get("provider") or "openai_chat")
    model = str(config.get("model") or "")
    timeout = _timeout(config, 90)

    if provider == "short_video_rewrite":
        payload = {
            "script": _extract_rewrite_script(user_prompt),
            "style": _extract_rewrite_style(user_prompt),
            "targetLength": int(config.get("targetLength") or 0),
        }
        response = requests.post(config["url"], headers=_headers(config, json_mode=True), json=payload, timeout=timeout)
    elif provider == "anthropic_messages":
        payload = {
            "model": model,
            "max_tokens": 1800,
            "temperature": temperature,
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_prompt}],
        }
        headers = _headers(config, json_mode=True)
        if config.get("apiKey"):
            headers.setdefault("x-api-key", config["apiKey"])
            headers.setdefault("anthropic-version", "2023-06-01")
        response = requests.post(config["url"], headers=headers, json=payload, timeout=timeout)
    else:
        payload = {
            "model": model,
            "temperature": temperature,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        response = requests.post(
            _openai_chat_endpoint(config["url"]),
            headers=_headers(config, json_mode=True, default_prefix="Bearer "),
            json=payload,
            timeout=timeout,
        )

    _raise_for_status(response)
    data = response.json()
    text = _get_path(data, config.get("textPath")) or _get_path(data, "choices.0.message.content")
    if not text and isinstance(data.get("content"), list):
        text = "\n".join(item.get("text", "") for item in data["content"] if isinstance(item, dict))
    if not text:
        text = data.get("output_text") or data.get("text")
    if not text:
        raise RuntimeError("LLM 接口未返回文本")
    return str(text).strip()


def call_asr(audio_path: Path, model: str | None = None, language: str | None = None) -> dict[str, Any]:
    config = _section("asr")
    timeout = _timeout(config, 180)
    file_field = str(config.get("fileField") or "file")
    data = {
        "model": model or config.get("model") or "base",
        "language": language or config.get("language") or "zh",
    }
    with open(audio_path, "rb") as f:
        files = {file_field: (audio_path.name, f, "application/octet-stream")}
        response = requests.post(
            _asr_endpoint(config, "audio"),
            headers=_asr_headers(config),
            data=data,
            files=files,
            timeout=timeout,
        )
    _raise_for_status(response)
    result = response.json()
    return _parse_asr_result(result, config)


def call_asr_url(reference_url: str, model: str | None = None, language: str | None = None) -> dict[str, Any]:
    config = _section("asr")
    timeout = _timeout(config, 180)
    payload: dict[str, Any] = {str(config.get("urlField") or "url"): reference_url}
    if model or config.get("model"):
        payload["model"] = model or config.get("model")
    if language or config.get("language"):
        payload["language"] = language or config.get("language")
    response = requests.post(
        _asr_endpoint(config, "url"),
        headers=_asr_headers(config, json_mode=True),
        json=payload,
        timeout=timeout,
    )
    _raise_for_status(response)
    return _parse_asr_result(response.json(), config)


def call_asr_media(media_path: Path, *, is_video: bool = False, model: str | None = None, language: str | None = None) -> dict[str, Any]:
    if not is_video:
        return call_asr(media_path, model=model, language=language)
    config = _section("asr")
    timeout = _timeout(config, 180)
    file_field = str(config.get("videoField") or "video")
    data = {
        "model": model or config.get("model") or "base",
        "language": language or config.get("language") or "zh",
    }
    content_type = mimetypes.guess_type(media_path.name)[0] or "application/octet-stream"
    with open(media_path, "rb") as f:
        files = {file_field: (media_path.name, f, content_type)}
        response = requests.post(
            _asr_endpoint(config, "video"),
            headers=_asr_headers(config),
            data=data,
            files=files,
            timeout=timeout,
        )
    _raise_for_status(response)
    return _parse_asr_result(response.json(), config)


def call_tts(
    text: str,
    output_path: Path,
    *,
    voice_id: str | None = None,
    voice_ref_wav: Path | None = None,
    voice_ref_text: str | None = None,
    speed: float = 1.0,
) -> Path:
    config = _section("tts")
    timeout = _timeout(config, 240)
    model = str(config.get("model") or "")
    output_mode = str(config.get("outputMode") or "binary")
    clone_url = str(config.get("cloneUrl") or "").strip()

    if clone_url and voice_ref_wav and voice_ref_wav.exists():
        logger.info("Calling TTS clone endpoint: %s", clone_url)
        data = {
            str(config.get("textField") or "text"): text,
            str(config.get("speedField") or "speed"): str(speed),
        }
        with open(voice_ref_wav, "rb") as file_handle:
            files = {
                str(config.get("promptAudioField") or "prompt_audio"): (
                    voice_ref_wav.name,
                    file_handle,
                    "application/octet-stream",
                )
            }
            response = requests.post(clone_url, headers=_tts_headers(config), data=data, files=files, timeout=timeout)
    elif config.get("useMultipart"):
        logger.info("Calling TTS multipart endpoint: %s", config["url"])
        data = {
            str(config.get("textField") or "text"): text,
            str(config.get("speedField") or "speed"): str(speed),
        }
        if model:
            data["model"] = model
        if voice_id:
            data[str(config.get("voiceField") or "voice_id")] = voice_id
        if voice_ref_text:
            data[str(config.get("promptTextField") or "voice_ref_text")] = voice_ref_text
        files = {}
        file_handle = None
        try:
            if voice_ref_wav and voice_ref_wav.exists():
                file_handle = open(voice_ref_wav, "rb")
                files[str(config.get("promptAudioField") or "voice_ref_wav")] = (
                    voice_ref_wav.name,
                    file_handle,
                    "application/octet-stream",
                )
            response = requests.post(config["url"], headers=_tts_headers(config), data=data, files=files, timeout=timeout)
        finally:
            if file_handle:
                file_handle.close()
    else:
        logger.info("Calling TTS json endpoint: %s", config["url"])
        payload = {
            str(config.get("textField") or "text"): text,
            str(config.get("speedField") or "speed"): speed,
        }
        if model:
            payload["model"] = model
        if voice_id:
            payload[str(config.get("voiceField") or "voice_id")] = voice_id
        if voice_ref_text:
            payload["voice_ref_text"] = voice_ref_text
        if voice_ref_wav:
            payload["voice_ref_wav"] = str(voice_ref_wav)
        response = requests.post(config["url"], headers=_tts_headers(config, json_mode=True), json=payload, timeout=timeout)

    _raise_for_status(response)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_mode == "binary":
        output_path.write_bytes(response.content)
        return output_path

    result = response.json()
    if output_mode == "json_base64":
        raw = _get_path(result, config.get("base64Path")) or result.get("audio")
        if not raw:
            raise RuntimeError("TTS 接口未返回 base64 音频")
        output_path.write_bytes(base64.b64decode(str(raw).split(",")[-1]))
        return output_path

    audio_url = _get_path(result, config.get("audioPath")) or result.get("audio_url")
    if not audio_url:
        raise RuntimeError("TTS 接口未返回音频地址")
    _download_file(str(audio_url), output_path, timeout, config["url"])
    return output_path


def call_lip_sync(video_path: Path, audio_path: Path, output_path: Path, options: dict[str, Any] | None = None) -> dict[str, Any]:
    config = _section("lipSync")
    timeout = _timeout(config, 900)
    output_mode = str(config.get("outputMode") or "binary")
    options = options or {}
    data = {"model": config.get("model") or "", "options": json.dumps(options, ensure_ascii=False)}
    with open(video_path, "rb") as vf, open(audio_path, "rb") as af:
        files = {
            str(config.get("videoField") or "video"): (video_path.name, vf, "application/octet-stream"),
            str(config.get("audioField") or "audio"): (audio_path.name, af, "application/octet-stream"),
        }
        response = requests.post(config["url"], headers=_lip_sync_headers(config), data=data, files=files, timeout=timeout)
    _raise_for_status(response)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_mode == "binary":
        output_path.write_bytes(response.content)
        return {"video_path": str(output_path)}
    result = response.json()
    if output_mode == "json_base64":
        raw = _get_path(result, config.get("base64Path")) or result.get("video")
        if not raw:
            raise RuntimeError("口型同步接口未返回 base64 视频")
        output_path.write_bytes(base64.b64decode(str(raw).split(",")[-1]))
        return {**result, "video_path": str(output_path)}
    video_url = _get_path(result, config.get("videoPath")) or result.get("video_url")
    if not video_url:
        raise RuntimeError("口型同步接口未返回视频地址")
    return {**result, "video_url": str(video_url), "external_video_url": str(video_url)}


def call_video_compose(payload: dict[str, Any], output_path: Path) -> dict[str, Any]:
    config = _section("videoCompose")
    timeout = _timeout(config, 900)
    output_mode = str(config.get("outputMode") or "json_url")
    request_payload = {
        "video_urls": payload.get("video_urls") or payload.get("videoUrls") or [],
        "audio_url": payload.get("audio_url") or payload.get("audioUrl") or "",
        "subtitle": payload.get("subtitle") or "",
        "options": payload.get("options") or {},
    }
    logger.info("Calling video compose endpoint: %s", config["url"])
    response = requests.post(
        config["url"],
        headers=_video_compose_headers(config, json_mode=True),
        json=request_payload,
        timeout=timeout,
    )
    _raise_for_status(response)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if output_mode == "binary":
        output_path.write_bytes(response.content)
        return {"video_path": str(output_path)}

    result = response.json()
    if output_mode == "json_base64":
        raw = _get_path(result, config.get("base64Path")) or result.get("video")
        if not raw:
            raise RuntimeError("视频合成接口未返回 base64 视频")
        output_path.write_bytes(base64.b64decode(str(raw).split(",")[-1]))
        result["video_path"] = str(output_path)
        return result

    video_url = (
        _get_path(result, config.get("videoPath"))
        or result.get("video_url")
        or result.get("outputVideoUrl")
        or result.get("output_video_url")
        or _get_path(result, "data.video_url")
    )
    if not video_url:
        raise RuntimeError("视频合成接口未返回视频地址")
    _download_file(str(video_url), output_path, timeout, config["url"])
    result["video_path"] = str(output_path)
    return result


def env_summary() -> dict[str, str]:
    config = load_service_config(mask_secret=True)
    return {
        section: "enabled" if values.get("enabled") and values.get("url") else "not_configured"
        for section, values in config.items()
    }

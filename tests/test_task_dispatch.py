from __future__ import annotations

import api_server
from pipeline.database import uploads_table
from pipeline.task_store import TaskStore


def test_run_task_executes_rewrite_payload_from_store(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)

    task_id = "rewrite_dispatch_test"
    task_store.create_task(
        task_id,
        "rewrite",
        "dispatch smoke",
        {
            "reference_text": "你好世界。今天继续优化项目。",
            "rewrite_engine": "fast",
            "rewrite_style": "plain",
            "rewrite_tone": "natural",
            "rewrite_length": "short",
            "rewrite_platform": "douyin",
            "rewrite_strength": "light",
            "rewrite_variants": 1,
        },
        user_id="local",
    )

    api_server._run_task(task_id)

    item = task_store.get_task(task_id, include_payload=True, user_id="local")
    assert item is not None
    assert item["status"] == "success"
    assert item["progress"] == 100
    assert item["result"]["task_id"] == task_id
    assert item["result"]["final_script"]


def test_rewrite_prompt_keeps_realtor_context():
    payload = api_server.RewritePayload(
        reference_text="房产生成提示词",
        realtor_context={
            "community": "江南府",
            "highlights": ["采光好", "户型方正"],
            "audience": ["改善家庭"],
        },
        rewrite_style="sales",
        rewrite_tone="professional",
    )

    _, user = api_server._rewrite_prompt(payload)

    assert "结构化房源字段" in user
    assert "江南府" in user
    assert "采光好" in user
    assert "改善家庭" in user


def test_format_script_lines_keeps_sentences_as_paragraphs():
    text = "这套房最适合想改善又不想增加太多通勤成本的家庭。老人接送孩子也方便。"

    formatted = api_server._format_script_lines(text)

    lines = formatted.splitlines()
    assert lines == [
        "这套房最适合想改善又不想增加太多通勤成本的家庭。",
        "老人接送孩子也方便。",
    ]


def test_run_task_marks_failed_when_kind_is_unknown(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)

    task_id = "unknown_dispatch_test"
    task_store.create_task(task_id, "unknown", "unknown", {}, user_id="local")

    try:
        api_server._run_task(task_id)
    except RuntimeError:
        pass

    item = task_store.get_task(task_id, include_payload=True, user_id="local")
    assert item is not None
    assert item["status"] == "failed"
    assert "不支持执行" in item["error"]


def test_extract_reference_text_bypasses_asr_and_fallbacks(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)

    def fail_external_call(*args, **kwargs):
        raise AssertionError("reference_text should not call external ASR or fallback helpers")

    monkeypatch.setattr(api_server, "call_asr_url", fail_external_call)
    monkeypatch.setattr(api_server, "call_asr_media", fail_external_call)
    monkeypatch.setattr(api_server, "call_asr", fail_external_call)
    monkeypatch.setattr(api_server, "_extract_audio_from_url", fail_external_call)
    monkeypatch.setattr(api_server, "_extract_audio_from_media_file", fail_external_call)

    task_id = "extract_text_dispatch_test"
    task_store.create_task(
        task_id,
        "extract",
        "extract text",
        {
            "reference_text": "这是用户直接输入的文案，不需要转写。",
            "reference_url": "https://example.com/should-not-be-used.mp4",
            "source_file": "/tmp/should-not-be-used.mp4",
            "model": "base",
        },
        user_id="local",
    )

    api_server._run_task(task_id)

    item = task_store.get_task(task_id, include_payload=True, user_id="local")
    assert item is not None
    assert item["status"] == "success"
    assert item["result"] == {
        "task_id": task_id,
        "extracted_script": "这是用户直接输入的文案，不需要转写。",
        "segments": [],
    }


def test_extract_url_uses_remote_url_transcribe(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)

    calls = []

    def fake_call_asr_url(reference_url, model=None, language=None):
        calls.append((reference_url, model, language))
        return {"text": "链接转写文案", "segments": [{"text": "链接转写文案"}]}

    monkeypatch.setattr(api_server, "call_asr_url", fake_call_asr_url)

    task_id = "extract_url_dispatch_test"
    task_store.create_task(
        task_id,
        "extract",
        "extract url",
        {"reference_url": "https://example.com/video.mp4", "model": "base"},
        user_id="local",
    )

    api_server._run_task(task_id)

    item = task_store.get_task(task_id, include_payload=True, user_id="local")
    assert item is not None
    assert item["status"] == "success"
    assert item["result"]["extracted_script"] == "链接转写文案"
    assert item["result"]["transcribe_method"] == "url_transcribe"
    assert calls == [("https://example.com/video.mp4", "base", None)]


def test_extract_url_failure_returns_error_without_audio_fallback(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)

    fallback_calls = []

    def fake_call_asr_url(reference_url, model=None, language=None):
        raise RuntimeError("链接转写接口失败")

    def fake_extract_audio_from_url(*args, **kwargs):
        fallback_calls.append(args)
        return tmp_path / "fallback.wav"

    monkeypatch.setattr(api_server, "call_asr_url", fake_call_asr_url)
    monkeypatch.setattr(api_server, "_extract_audio_from_url", fake_extract_audio_from_url)
    monkeypatch.setattr(api_server, "call_asr", lambda *args, **kwargs: fallback_calls.append(args))

    task_id = "extract_url_failure_test"
    task_store.create_task(
        task_id,
        "extract",
        "extract url failure",
        {"reference_url": "https://example.com/video.mp4", "model": "base"},
        user_id="local",
    )

    try:
        api_server._run_task(task_id)
    except RuntimeError:
        pass

    item = task_store.get_task(task_id, include_payload=True, user_id="local")
    assert item is not None
    assert item["status"] == "failed"
    assert "链接转写接口失败" in item["error"]
    assert fallback_calls == []


def test_extract_uploaded_video_uses_remote_video_transcribe(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake video")
    calls = []

    def fake_call_asr_media(media_path, *, is_video=False, model=None, language=None):
        calls.append((media_path, is_video, model, language))
        return {"text": "视频转写文案", "segments": []}

    monkeypatch.setattr(api_server, "call_asr_media", fake_call_asr_media)

    task_id = "extract_video_dispatch_test"
    task_store.create_task(
        task_id,
        "extract",
        "extract video",
        {"source_file": str(source), "filename": "source.mp4", "model": "base"},
        user_id="local",
    )

    api_server._run_task(task_id)

    item = task_store.get_task(task_id, include_payload=True, user_id="local")
    assert item is not None
    assert item["status"] == "success"
    assert item["result"]["extracted_script"] == "视频转写文案"
    assert item["result"]["transcribe_method"] == "video_transcribe"
    assert calls == [(source, True, "base", None)]


def test_extract_uploaded_video_failure_returns_error_without_audio_fallback(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)

    source = tmp_path / "source.mp4"
    source.write_bytes(b"fake video")
    fallback_calls = []

    def fake_call_asr_media(media_path, *, is_video=False, model=None, language=None):
        raise RuntimeError("视频转写接口失败")

    def fake_extract_audio_from_media_file(*args, **kwargs):
        fallback_calls.append(args)
        return tmp_path / "fallback.wav"

    monkeypatch.setattr(api_server, "call_asr_media", fake_call_asr_media)
    monkeypatch.setattr(api_server, "_extract_audio_from_media_file", fake_extract_audio_from_media_file)
    monkeypatch.setattr(api_server, "call_asr", lambda *args, **kwargs: fallback_calls.append(args))

    task_id = "extract_video_failure_test"
    task_store.create_task(
        task_id,
        "extract",
        "extract video failure",
        {"source_file": str(source), "filename": "source.mp4", "model": "base"},
        user_id="local",
    )

    try:
        api_server._run_task(task_id)
    except RuntimeError:
        pass

    item = task_store.get_task(task_id, include_payload=True, user_id="local")
    assert item is not None
    assert item["status"] == "failed"
    assert "视频转写接口失败" in item["error"]
    assert fallback_calls == []


def test_video_compose_uses_signed_oss_urls_for_uploaded_video_and_audio(tmp_path, monkeypatch):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    monkeypatch.setattr(api_server, "task_store", task_store)
    monkeypatch.setattr(
        api_server,
        "load_service_config",
        lambda mask_secret=False: {"videoCompose": {"enabled": True, "url": "http://compose.local/v1/video/compose"}},
    )
    monkeypatch.setattr(api_server.object_storage, "enabled", lambda: True)
    monkeypatch.setattr(api_server.object_storage, "signed_url", lambda key: f"https://oss.example/{key}?signed=1")

    user_id = "user_video_compose"
    task_store.record_upload(
        "background.mp4",
        {
            "video_url": "/api/v1/uploads/background.mp4",
            "video_object_key": "uploads/background.mp4",
            "size_bytes": 123,
        },
        user_id=user_id,
    )
    task_store.create_task("tts_audio_for_video", "tts", "audio", {}, user_id=user_id)
    task_store.update_task(
        "tts_audio_for_video",
        status="success",
        progress=100,
        message="完成",
        result={"audio_url": "/api/v1/audio/tts_audio_for_video", "audio_object_key": "outputs/audio.wav"},
    )

    calls = []

    def fake_call_video_compose(payload, output_path):
        calls.append((payload, output_path))
        return {"video_path": str(output_path), "duration": 1.0}

    monkeypatch.setattr(api_server, "call_video_compose", fake_call_video_compose)

    task_id = "video_compose_oss_dispatch_test"
    task_store.create_task(
        task_id,
        "video",
        "video compose",
        {
            "videoUrls": ["/api/v1/uploads/background.mp4"],
            "audioUrl": "/api/v1/audio/tts_audio_for_video",
            "subtitle": "字幕",
            "options": {"addSubtitle": True, "maxClipSeconds": 0},
            "_base_url": "http://127.0.0.1:8010",
        },
        user_id=user_id,
    )

    api_server._run_task(task_id)

    assert calls
    payload, _ = calls[0]
    assert payload["video_urls"] == ["https://oss.example/uploads/background.mp4?signed=1"]
    assert payload["audio_url"] == "https://oss.example/outputs/audio.wav?signed=1"
    assert payload["options"]["add_subtitle"] is True
    assert "addSubtitle" not in payload["options"]
    assert "max_clip_seconds" not in payload["options"]

    item = task_store.get_task(task_id, include_payload=True, user_id=user_id)
    assert item is not None
    assert item["status"] == "success"
    assert item["result"]["compose_method"] == "external_video_compose"


def test_record_upload_persists_object_storage_fields(tmp_path):
    task_store = TaskStore(tmp_path / "task_store.sqlite3")

    item = task_store.record_upload(
        "background.mp4",
        {
            "video_url": "/api/v1/uploads/background.mp4",
            "video_storage_provider": "aliyun_oss",
            "video_object_key": "users/local/uploads/videos/background.mp4",
            "video_object_url": "https://oss.example/background.mp4",
            "size_bytes": 123,
        },
        user_id="local",
    )

    assert item["object_key"] == "users/local/uploads/videos/background.mp4"
    assert item["object_url"] == "https://oss.example/background.mp4"

    with task_store.engine.connect() as conn:
        row = conn.execute(uploads_table.select().where(uploads_table.c.filename == "background.mp4")).first()

    assert row is not None
    assert row._mapping["storage_provider"] == "aliyun_oss"
    assert row._mapping["object_key"] == "users/local/uploads/videos/background.mp4"
    assert row._mapping["object_url"] == "https://oss.example/background.mp4"

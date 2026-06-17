from __future__ import annotations

import api_clients
from pipeline.service_config_store import ServiceConfigStore


class DummyResponse:
    content = b"RIFFfake-wav"

    def raise_for_status(self):
        return None

    def json(self):
        return {}


def test_tts_synthesize_uses_speaker_field(tmp_path, monkeypatch):
    calls = []

    monkeypatch.setattr(
        api_clients,
        "load_service_config",
        lambda mask_secret=False: {
            "tts": {
                "enabled": True,
                "url": "http://model.local/v1/tts/synthesize",
                "textField": "text",
                "voiceField": "speaker",
                "speedField": "speed",
                "outputMode": "binary",
            }
        },
    )

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout, "kwargs": kwargs})
        return DummyResponse()

    monkeypatch.setattr(api_clients.requests, "post", fake_post)

    output_path = tmp_path / "tts.wav"
    api_clients.call_tts("你好", output_path, voice_id="中文女", speed=1.2)

    assert output_path.read_bytes() == b"RIFFfake-wav"
    assert calls[0]["url"] == "http://model.local/v1/tts/synthesize"
    assert calls[0]["json"] == {"text": "你好", "speed": 1.2, "speaker": "中文女"}
    assert "voice_id" not in calls[0]["json"]


def test_tts_clone_omits_prompt_text(tmp_path, monkeypatch):
    ref_audio = tmp_path / "ref.wav"
    ref_audio.write_bytes(b"ref-audio")
    calls = []

    monkeypatch.setattr(
        api_clients,
        "load_service_config",
        lambda mask_secret=False: {
            "tts": {
                "enabled": True,
                "url": "http://model.local/v1/tts/synthesize",
                "cloneUrl": "http://model.local/v1/tts/clone",
                "apiKey": "tts-secret",
                "textField": "text",
                "speedField": "speed",
                "outputMode": "binary",
                "promptAudioField": "prompt_audio",
            }
        },
    )

    def fake_post(url, headers=None, data=None, files=None, timeout=None, **kwargs):
        calls.append({"url": url, "headers": headers, "data": data, "files": files, "timeout": timeout, "kwargs": kwargs})
        return DummyResponse()

    monkeypatch.setattr(api_clients.requests, "post", fake_post)

    output_path = tmp_path / "clone.wav"
    api_clients.call_tts("克隆文本", output_path, voice_ref_wav=ref_audio, voice_ref_text="这段不会传给外部 clone", speed=0.9)

    assert output_path.read_bytes() == b"RIFFfake-wav"
    assert calls[0]["url"] == "http://model.local/v1/tts/clone"
    assert calls[0]["headers"]["Authorization"] == "Bearer tts-secret"
    assert calls[0]["data"] == {"text": "克隆文本", "speed": "0.9"}
    assert "prompt_text" not in calls[0]["data"]
    assert "prompt_audio" in calls[0]["files"]


def test_service_config_migrates_file_and_preserves_masked_key(tmp_path, monkeypatch):
    config_path = tmp_path / "service_config.json"
    config_path.write_text(
        '{"llm":{"enabled":true,"url":"http://old.local","apiKey":"secret-key"}}',
        encoding="utf-8",
    )
    store = ServiceConfigStore(tmp_path / "service_config.sqlite3")
    monkeypatch.setattr(api_clients, "CONFIG_PATH", config_path)
    monkeypatch.setattr(api_clients, "service_config_store", store)

    loaded = api_clients.load_service_config(mask_secret=False)

    assert loaded["llm"]["url"] == "http://old.local"
    assert loaded["llm"]["apiKey"] == "secret-key"
    assert store.load()["llm"]["apiKey"] == "secret-key"

    saved = api_clients.save_service_config({"llm": {"enabled": True, "url": "http://new.local", "apiKey": "********"}})

    assert saved["llm"]["apiKey"] == "********"
    persisted = store.load()
    assert persisted["llm"]["url"] == "http://new.local"
    assert persisted["llm"]["apiKey"] == "secret-key"


def test_service_config_save_does_not_write_json_backup(tmp_path, monkeypatch):
    config_path = tmp_path / "service_config.json"
    store = ServiceConfigStore(tmp_path / "service_config.sqlite3")
    monkeypatch.setattr(api_clients, "CONFIG_PATH", config_path)
    monkeypatch.setattr(api_clients, "service_config_store", store)

    api_clients.save_service_config({"llm": {"enabled": True, "url": "http://db.local", "apiKey": "secret-key"}})

    assert store.load()["llm"]["url"] == "http://db.local"
    assert not config_path.exists()


def test_openai_llm_uses_bearer_header_and_chat_endpoint(monkeypatch):
    calls = []

    class LlmResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "改写结果"}}]}

    monkeypatch.setattr(
        api_clients,
        "load_service_config",
        lambda mask_secret=False: {
            "llm": {
                "enabled": True,
                "url": "https://coding.dashscope.aliyuncs.com/v1",
                "apiKey": "sk-test",
                "model": "qwen3.6-plus",
            }
        },
    )

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout, "kwargs": kwargs})
        return LlmResponse()

    monkeypatch.setattr(api_clients.requests, "post", fake_post)

    result = api_clients.call_llm("system", "user")

    assert result == "改写结果"
    assert calls[0]["url"] == "https://coding.dashscope.aliyuncs.com/v1/chat/completions"
    assert calls[0]["headers"]["Authorization"] == "Bearer sk-test"


def test_service_config_save_prunes_legacy_fields(tmp_path, monkeypatch):
    store = ServiceConfigStore(tmp_path / "service_config.sqlite3")
    monkeypatch.setattr(api_clients, "service_config_store", store)

    api_clients.save_service_config(
        {
            "tts": {
                "enabled": True,
                "url": "http://tts.local/v1/tts/synthesize",
                "cloneUrl": "http://tts.local/v1/tts/clone",
                "promptTextField": "prompt_text",
                "outputMode": "binary",
                "base64Path": "audio",
            },
            "videoCompose": {
                "enabled": True,
                "url": "http://video.local/v1/video/compose",
                "videoPath": "video_url",
                "outputMode": "json_url",
            },
            "asr": {
                "enabled": True,
                "url": "http://model.local/v1/audio/transcribe",
                "urlTranscribeUrl": "http://legacy.local/url",
                "videoTranscribeUrl": "http://legacy.local/video",
            },
        }
    )

    persisted = store.load()
    assert "urlTranscribeUrl" not in persisted["asr"]
    assert "videoTranscribeUrl" not in persisted["asr"]
    assert persisted["asr"]["url"] == "http://legacy.local/url"
    assert persisted["asr"]["videoUrl"] == "http://legacy.local/video"
    assert persisted["tts"]["cloneUrl"] == "http://tts.local/v1/tts/clone"
    assert "promptTextField" not in persisted["tts"]
    assert "outputMode" not in persisted["tts"]
    assert "base64Path" not in persisted["tts"]
    assert "videoPath" not in persisted["videoCompose"]


def test_asr_endpoints_are_derived_from_main_transcribe_url(monkeypatch):
    config = {
        "enabled": True,
        "url": "http://model.local/v1/audio/transcribe",
    }
    normalized = api_clients._normalize_asr_config(config)

    assert normalized["url"] == "http://model.local/v1/audio/transcribe-url"
    assert normalized["videoUrl"] == "http://model.local/v1/video/transcribe"
    assert api_clients._asr_endpoint(normalized, "audio") == "http://model.local/v1/audio/transcribe"
    assert api_clients._asr_endpoint(normalized, "url") == "http://model.local/v1/audio/transcribe-url"
    assert api_clients._asr_endpoint(normalized, "video") == "http://model.local/v1/video/transcribe"


def test_asr_uses_separate_link_and_video_endpoints(monkeypatch):
    config = {
        "enabled": True,
        "url": "http://model.local/v1/audio/transcribe-url",
        "videoUrl": "http://model.local/v1/video/transcribe",
        "model": "base",
    }

    assert api_clients._asr_endpoint(config, "url") == "http://model.local/v1/audio/transcribe-url"
    assert api_clients._asr_endpoint(config, "video") == "http://model.local/v1/video/transcribe"
    assert api_clients._asr_endpoint(config, "audio") == "http://model.local/v1/audio/transcribe"


def test_asr_uses_api_key_as_bearer_token_for_url_and_file_calls(tmp_path, monkeypatch):
    calls = []

    class AsrResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"text": "转写结果", "segments": []}

    monkeypatch.setattr(
        api_clients,
        "load_service_config",
        lambda mask_secret=False: {
            "asr": {
                "enabled": True,
                "url": "http://model.local/v1/audio/transcribe-url",
                "videoUrl": "http://model.local/v1/video/transcribe",
                "apiKey": "asr-secret",
                "model": "base",
            }
        },
    )

    def fake_post(url, headers=None, json=None, data=None, files=None, timeout=None, **kwargs):
        calls.append(
            {
                "url": url,
                "headers": headers,
                "json": json,
                "data": data,
                "files": files,
                "timeout": timeout,
                "kwargs": kwargs,
            }
        )
        return AsrResponse()

    monkeypatch.setattr(api_clients.requests, "post", fake_post)

    audio_path = tmp_path / "demo.wav"
    video_path = tmp_path / "demo.mp4"
    audio_path.write_bytes(b"audio")
    video_path.write_bytes(b"video")

    url_result = api_clients.call_asr_url("https://example.test/video.mp4")
    file_result = api_clients.call_asr_media(video_path, is_video=True)
    audio_result = api_clients.call_asr(audio_path)

    assert url_result["text"] == "转写结果"
    assert file_result["text"] == "转写结果"
    assert audio_result["text"] == "转写结果"
    assert calls[0]["headers"]["Authorization"] == "Bearer asr-secret"
    assert calls[0]["headers"]["Content-Type"] == "application/json"
    assert calls[1]["headers"]["Authorization"] == "Bearer asr-secret"
    assert calls[2]["headers"]["Authorization"] == "Bearer asr-secret"


def test_video_compose_uses_api_key_as_bearer_token(tmp_path, monkeypatch):
    calls = []

    class ComposeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"video_url": "http://video.local/output.mp4"}

    monkeypatch.setattr(
        api_clients,
        "load_service_config",
        lambda mask_secret=False: {
            "videoCompose": {
                "enabled": True,
                "url": "http://video.local/v1/video/compose",
                "apiKey": "compose-secret",
                "timeout": 900,
            }
        },
    )

    def fake_post(url, headers=None, json=None, timeout=None, **kwargs):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout, "kwargs": kwargs})
        return ComposeResponse()

    def fake_download(url, output_path, timeout, base_url=None):
        output_path.write_bytes(b"video")

    monkeypatch.setattr(api_clients.requests, "post", fake_post)
    monkeypatch.setattr(api_clients, "_download_file", fake_download)

    output_path = tmp_path / "video.mp4"
    result = api_clients.call_video_compose(
        {"video_urls": ["https://oss.local/video.mp4"], "audio_url": "https://oss.local/audio.wav"},
        output_path,
    )

    assert output_path.read_bytes() == b"video"
    assert result["video_path"] == str(output_path)
    assert calls[0]["headers"]["Authorization"] == "Bearer compose-secret"
    assert calls[0]["headers"]["Content-Type"] == "application/json"


def test_lip_sync_uses_api_key_as_bearer_token(tmp_path, monkeypatch):
    calls = []

    class LipSyncResponse:
        content = b"video"

        def raise_for_status(self):
            return None

    monkeypatch.setattr(
        api_clients,
        "load_service_config",
        lambda mask_secret=False: {
            "lipSync": {
                "enabled": True,
                "url": "http://video.local/v1/avatar/latentsync",
                "apiKey": "lip-secret",
                "timeout": 900,
            }
        },
    )

    def fake_post(url, headers=None, data=None, files=None, timeout=None, **kwargs):
        calls.append({"url": url, "headers": headers, "data": data, "files": files, "timeout": timeout, "kwargs": kwargs})
        return LipSyncResponse()

    monkeypatch.setattr(api_clients.requests, "post", fake_post)

    video_path = tmp_path / "source.mp4"
    audio_path = tmp_path / "audio.wav"
    output_path = tmp_path / "lip.mp4"
    video_path.write_bytes(b"video")
    audio_path.write_bytes(b"audio")

    api_clients.call_lip_sync(video_path, audio_path, output_path, {"pads": [0, 10, 0, 0]})

    assert output_path.read_bytes() == b"video"
    assert calls[0]["headers"]["Authorization"] == "Bearer lip-secret"
    assert "Content-Type" not in calls[0]["headers"]
    assert "video" in calls[0]["files"]
    assert "audio" in calls[0]["files"]

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

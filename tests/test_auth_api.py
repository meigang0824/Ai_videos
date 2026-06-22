from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import api_server
from pipeline.auth_store import AuthStore
from pipeline.task_store import TaskStore
from pipeline.voice_store import VoiceStore


class DummyJobRunner:
    def __init__(self):
        self.submitted = []

    def submit(self, task_id, fn=None):
        self.submitted.append(task_id)

    def cancel(self, task_id):
        return False


def test_login_and_me_use_bearer_token(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", False)

    client = TestClient(api_server.app)
    username = "tester_auth"
    password = "TestPass12345"
    user = auth_store.create_user(username, password, role="admin")
    assert user["role"] == "admin"

    register = client.post("/api/v1/auth/register", json={"username": "new_user", "password": password})
    assert register.status_code == 410

    wrong_password = client.post("/api/v1/auth/login", json={"username": username, "password": "wrong-password"})
    assert wrong_password.status_code == 401

    logged_in = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert logged_in.status_code == 200
    token = logged_in.json()["token"]

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["user"]["username"] == username

    no_token = client.get("/api/v1/auth/me")
    assert no_token.status_code == 401


def test_api_routes_require_login_when_auth_is_active(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)

    client = TestClient(api_server.app)
    auth_store.create_user("locked_user", "TestPass12345", role="user")

    login = client.post("/api/v1/auth/login", json={"username": "locked_user", "password": "TestPass12345"})
    assert login.status_code == 200

    protected_requests = [
        ("GET", "/api/v1/app-config", None),
        ("GET", "/api/v1/health", None),
        ("GET", "/api/v1/rewrite-options", None),
        ("GET", "/api/v1/storage", None),
        ("POST", "/api/v1/rewrite/start", {"reference_text": "测试"}),
    ]
    for method, path, payload in protected_requests:
        response = client.request(method, path, json=payload)
        assert response.status_code == 401
        assert response.json()["detail"] == "请先登录"


def test_service_config_requires_admin(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)
    monkeypatch.setattr(api_server, "load_service_config", lambda mask_secret=True: {"llm": {"enabled": False}})
    monkeypatch.setattr(api_server, "save_service_config", lambda payload: payload)

    client = TestClient(api_server.app)

    admin_user = auth_store.create_user("admin_user", "TestPass12345", role="admin")
    member_user = auth_store.create_user("member_user", "TestPass12345", role="user")
    admin = client.post("/api/v1/auth/login", json={"username": admin_user["username"], "password": "TestPass12345"}).json()
    member = client.post("/api/v1/auth/login", json={"username": member_user["username"], "password": "TestPass12345"}).json()

    admin_headers = {"Authorization": f"Bearer {admin['token']}"}
    member_headers = {"Authorization": f"Bearer {member['token']}"}

    assert client.get("/api/v1/service-config", headers=member_headers).status_code == 403
    assert client.put("/api/v1/service-config", headers=member_headers, json={"llm": {}}).status_code == 403

    admin_read = client.get("/api/v1/service-config", headers=admin_headers)
    assert admin_read.status_code == 200
    assert admin_read.json()["config"]["llm"]["enabled"] is False

    admin_write = client.put("/api/v1/service-config", headers=admin_headers, json={"llm": {"enabled": True}})
    assert admin_write.status_code == 200
    assert admin_write.json()["config"]["llm"]["enabled"] is True


def test_admin_can_create_and_delete_users(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)

    client = TestClient(api_server.app)
    admin_user = auth_store.create_user("admin_user", "TestPass12345", role="admin")
    admin = client.post("/api/v1/auth/login", json={"username": admin_user["username"], "password": "TestPass12345"}).json()
    admin_headers = {"Authorization": f"Bearer {admin['token']}"}

    created = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "managed_user", "password": "TestPass12345", "role": "realtor"},
    )
    assert created.status_code == 200
    managed_user = created.json()["user"]
    assert managed_user["role"] == "realtor"

    managed_login = client.post(
        "/api/v1/auth/login",
        json={"username": "managed_user", "password": "TestPass12345"},
    )
    assert managed_login.status_code == 200
    assert managed_login.json()["user"]["role"] == "realtor"

    duplicate = client.post(
        "/api/v1/admin/users",
        headers=admin_headers,
        json={"username": "managed_user", "password": "TestPass12345", "role": "user"},
    )
    assert duplicate.status_code == 400

    users = client.get("/api/v1/admin/users", headers=admin_headers)
    assert users.status_code == 200
    assert any(item["username"] == "managed_user" for item in users.json()["users"])

    delete_self = client.delete(f"/api/v1/admin/users/{admin_user['id']}", headers=admin_headers)
    assert delete_self.status_code == 400

    deleted = client.delete(f"/api/v1/admin/users/{managed_user['id']}", headers=admin_headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert auth_store.get_user(managed_user["id"]) is None


def test_tts_sample_start_reuses_success_task_from_store(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    job_runner = DummyJobRunner()
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "task_store", task_store)
    monkeypatch.setattr(api_server, "job_runner", job_runner)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)

    client = TestClient(api_server.app)
    sample_user = auth_store.create_user("sample_user", "TestPass12345", role="user")
    registered = client.post("/api/v1/auth/login", json={"username": sample_user["username"], "password": "TestPass12345"}).json()
    headers = {"Authorization": f"Bearer {registered['token']}"}
    user_id = registered["user"]["id"]
    sample_id = "voice_sample_user_voice_1x"
    audio_path = tmp_path / "sample.wav"
    audio_path.write_bytes(b"RIFFsample")

    task_store.create_task(sample_id, "tts", "试听样音", {"text": "试听"}, user_id=user_id)
    task_store.update_task(
        sample_id,
        status="success",
        progress=100,
        message="完成",
        result={
            "task_id": sample_id,
            "text": "试听",
            "audio_path": str(audio_path),
            "audio_url": f"/api/v1/audio/{sample_id}",
            "size_bytes": audio_path.stat().st_size,
        },
    )

    response = client.post(
        "/api/v1/tts/sample/start",
        headers=headers,
        json={"taskId": sample_id, "text": "试听", "speed": 1.0},
    )

    assert response.status_code == 200
    assert response.json()["cached"] is True
    assert response.json()["status"] == "success"
    assert job_runner.submitted == []


def test_upload_voice_persists_voice_name_in_database(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    voice_store = VoiceStore(tmp_path / "voices.sqlite3", migrate=False)
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "voice_store", voice_store)
    monkeypatch.setattr(api_server, "VOICE_DIR", voice_dir)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)
    monkeypatch.setattr(api_server.object_storage, "enabled", lambda: False)
    monkeypatch.setattr(
        api_server,
        "call_asr",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("导入音色不应调用 ASR")),
    )

    client = TestClient(api_server.app)
    voice_user = auth_store.create_user("voice_user", "TestPass12345", role="user")
    registered = client.post("/api/v1/auth/login", json={"username": voice_user["username"], "password": "TestPass12345"}).json()
    headers = {"Authorization": f"Bearer {registered['token']}"}

    response = client.post(
        "/api/v1/upload-voice",
        headers=headers,
        files={"file": ("demo.wav", b"RIFFdemo", "audio/wav")},
    )

    assert response.status_code == 200
    voice = response.json()["voice"]
    stored = voice_store.get_voice(voice["id"])
    assert stored is not None
    assert stored["name"] == voice["name"]
    assert stored["user_id"] == registered["user"]["id"]
    assert stored["ref_text"] == ""
    assert not list(voice_dir.glob("*.json"))

    listed = client.get("/api/v1/voices", headers=headers)
    assert listed.status_code == 200
    listed_voices = listed.json()["voices"]
    names = [item["name"] for item in listed_voices]
    assert voice["name"] in names
    assert all(item["kind"] == "local" for item in listed_voices)

    renamed = client.patch(
        f"/api/v1/voices/{voice['id']}",
        headers=headers,
        json={"name": "成交男声"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["voice"]["name"] == "成交男声"
    assert voice_store.get_voice(voice["id"])["name"] == "成交男声"

    blank_name = client.patch(
        f"/api/v1/voices/{voice['id']}",
        headers=headers,
        json={"name": "  "},
    )
    assert blank_name.status_code == 400

    ref_path = Path(stored["ref_wav"])
    assert ref_path.exists()
    deleted = client.delete(f"/api/v1/voices/{voice['id']}", headers=headers)
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    assert deleted.json()["deleted_file"] is True
    assert voice_store.get_voice(voice["id"]) is None
    assert not ref_path.exists()

    listed_after_delete = client.get("/api/v1/voices", headers=headers)
    assert listed_after_delete.status_code == 200
    assert all(item["id"] != voice["id"] for item in listed_after_delete.json()["voices"])


def test_upload_voice_uses_object_storage_without_persistent_local_file(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    voice_store = VoiceStore(tmp_path / "voices.sqlite3", migrate=False)
    voice_dir = tmp_path / "voices"
    voice_dir.mkdir()
    uploaded = {}

    def fake_upload_fileobj(fileobj, key, content_type=None):
        uploaded["key"] = key
        uploaded["content_type"] = content_type
        fileobj.seek(0)
        uploaded["content"] = fileobj.read()
        return {"provider": "aliyun_oss", "key": key, "url": f"https://oss.example/{key}"}

    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "voice_store", voice_store)
    monkeypatch.setattr(api_server, "VOICE_DIR", voice_dir)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)
    monkeypatch.setattr(api_server.object_storage, "enabled", lambda: True)
    monkeypatch.setattr(api_server.object_storage, "upload_fileobj", fake_upload_fileobj)

    client = TestClient(api_server.app)
    voice_user = auth_store.create_user("oss_voice_user", "TestPass12345", role="user")
    registered = client.post(
        "/api/v1/auth/login",
        json={"username": voice_user["username"], "password": "TestPass12345"},
    ).json()
    headers = {"Authorization": f"Bearer {registered['token']}"}

    response = client.post(
        "/api/v1/upload-voice",
        headers=headers,
        files={"file": ("cloud.wav", b"RIFFcloud", "audio/wav")},
    )

    assert response.status_code == 200
    voice = response.json()["voice"]
    stored = voice_store.get_voice(voice["id"])
    assert stored is not None
    assert stored["ref_wav"].startswith("voices/")
    assert stored["object_key"] == uploaded["key"]
    assert stored["object_key"].endswith(".wav")
    assert stored["object_url"].startswith("https://oss.example/")
    assert uploaded["content"] == b"RIFFcloud"
    assert uploaded["content_type"] == "audio/wav"
    assert list(voice_dir.iterdir()) == []


def test_tts_task_resolves_object_voice_from_ref_wav_without_voice_id(tmp_path, monkeypatch):
    voice_store = VoiceStore(tmp_path / "voices.sqlite3", migrate=False)
    voice_dir = tmp_path / "voices"
    tmp_dir = tmp_path / "tmp"
    output_dir = tmp_path / "outputs"
    remote_voice = tmp_path / "remote.wav"
    user_id = "voice-user"
    voice_dir.mkdir()
    tmp_dir.mkdir()
    output_dir.mkdir()
    remote_voice.write_bytes(b"RIFFremote")
    calls = {}

    voice_store.upsert_voice(
        {
            "id": "cloud_voice",
            "user_id": user_id,
            "name": "云端音色",
            "kind": "local",
            "ref_wav": "voices/cloud_voice.wav",
            "ref_text": "",
            "size_bytes": remote_voice.stat().st_size,
            "object_key": "oss/voices/cloud_voice.wav",
            "created_at": "now",
        }
    )

    def fake_call_tts(text, output_path, *, voice_id=None, voice_ref_wav=None, voice_ref_text=None, speed=1.0):
        calls["voice_id"] = voice_id
        calls["voice_ref_wav"] = voice_ref_wav
        calls["voice_ref_bytes"] = voice_ref_wav.read_bytes() if voice_ref_wav else b""
        output_path.write_bytes(b"RIFFgenerated")
        return output_path

    monkeypatch.setattr(api_server, "voice_store", voice_store)
    monkeypatch.setattr(api_server, "VOICE_DIR", voice_dir)
    monkeypatch.setattr(api_server, "TMP_DIR", tmp_dir)
    monkeypatch.setattr(api_server, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(api_server, "call_tts", fake_call_tts)
    monkeypatch.setattr(api_server, "_upload_to_object_storage", lambda *args, **kwargs: None)
    monkeypatch.setattr(api_server.object_storage, "enabled", lambda: True)
    monkeypatch.setattr(api_server.object_storage, "signed_url", lambda key: str(remote_voice))

    result = api_server._execute_tts_task(
        {
            "task_id": "tts_cloud_voice",
            "user_id": user_id,
            "payload": {
                "text": "试听",
                "voice_ref_wav": "voices/cloud_voice.wav",
                "speed": 1.0,
            },
        }
    )

    assert calls["voice_id"] is None
    assert calls["voice_ref_wav"] is not None
    assert calls["voice_ref_bytes"] == b"RIFFremote"
    assert result["audio_url"] == "/api/v1/audio/tts_cloud_voice"


def test_tts_task_removes_local_output_after_object_upload(tmp_path, monkeypatch):
    output_dir = tmp_path / "outputs"
    output_dir.mkdir()
    uploads = []

    def fake_call_tts(text, output_path, *, voice_id=None, voice_ref_wav=None, voice_ref_text=None, speed=1.0):
        output_path.write_bytes(b"RIFFgenerated")
        return output_path

    def fake_upload(path, *, user_id, purpose, task_id):
        uploads.append({"path": path, "exists_during_upload": path.exists(), "purpose": purpose})
        return {
            "provider": "aliyun_oss",
            "key": f"cosyvoice/users/{user_id}/{purpose}/{task_id}.wav",
            "url": f"https://oss.example.com/{task_id}.wav",
        }

    monkeypatch.setattr(api_server, "OUTPUT_DIR", output_dir)
    monkeypatch.setattr(api_server, "call_tts", fake_call_tts)
    monkeypatch.setattr(api_server, "_upload_to_object_storage", fake_upload)

    result = api_server._execute_tts_task(
        {
            "task_id": "tts_delete_after_upload",
            "user_id": "user-1",
            "payload": {"text": "上传后删除", "speed": 1.0},
        }
    )

    output_path = output_dir / "tts_delete_after_upload.wav"
    assert uploads == [{"path": output_path, "exists_during_upload": True, "purpose": "outputs/audio"}]
    assert not output_path.exists()
    assert result["audio_path"] == ""
    assert result["audio_object_url"] == "https://oss.example.com/tts_delete_after_upload.wav"
    assert result["audio_url"] == "/api/v1/audio/tts_delete_after_upload"

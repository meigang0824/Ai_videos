from __future__ import annotations

from fastapi.testclient import TestClient

import api_server
from pipeline.auth_store import AuthStore
from pipeline.task_store import TaskStore


class DummyJobRunner:
    def __init__(self):
        self.submitted = []

    def submit(self, task_id, fn=None):
        self.submitted.append(task_id)

    def cancel(self, task_id):
        return False


def test_register_login_and_me_use_bearer_token(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", False)

    client = TestClient(api_server.app)
    username = "tester_auth"
    password = "TestPass12345"

    registered = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert registered.status_code == 200
    registered_body = registered.json()
    assert registered_body["user"]["username"] == username
    assert registered_body["user"]["role"] == "admin"
    assert registered_body["token"]

    duplicate = client.post("/api/v1/auth/register", json={"username": username, "password": password})
    assert duplicate.status_code == 400
    assert duplicate.json()["detail"] == "用户名已存在"

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


def test_service_config_requires_admin(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)
    monkeypatch.setattr(api_server, "load_service_config", lambda mask_secret=True: {"llm": {"enabled": False}})
    monkeypatch.setattr(api_server, "save_service_config", lambda payload: payload)

    client = TestClient(api_server.app)

    admin = client.post(
        "/api/v1/auth/register",
        json={"username": "admin_user", "password": "TestPass12345"},
    ).json()
    member = client.post(
        "/api/v1/auth/register",
        json={"username": "member_user", "password": "TestPass12345"},
    ).json()

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


def test_tts_sample_start_reuses_success_task_from_store(tmp_path, monkeypatch):
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    task_store = TaskStore(tmp_path / "task_store.sqlite3")
    job_runner = DummyJobRunner()
    monkeypatch.setattr(api_server, "auth_store", auth_store)
    monkeypatch.setattr(api_server, "task_store", task_store)
    monkeypatch.setattr(api_server, "job_runner", job_runner)
    monkeypatch.setattr(api_server, "AUTH_REQUIRED", True)

    client = TestClient(api_server.app)
    registered = client.post(
        "/api/v1/auth/register",
        json={"username": "sample_user", "password": "TestPass12345"},
    ).json()
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

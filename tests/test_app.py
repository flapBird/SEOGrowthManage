import asyncio
from datetime import date

from app.database import SessionLocal
from app.automation.base import SubmissionResult
from app.automation.engine import execute_task
from app.models import (
    AutomationTask,
    BacklinkRecord,
    Channel,
    ChannelCredential,
    PublishMethod,
    RecordStatus,
    TargetSite,
    TaskStatus,
)
from app.security import CredentialCipher


def test_protected_pages_redirect_to_login(client):
    response = client.get("/channels", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_login_crud_duplicate_warning_and_encrypted_credentials(authenticated_client):
    client = authenticated_client
    assert client.post("/sites", data={"name": "站点 A", "url": "https://a.example", "notes": ""}).status_code == 200
    assert client.post(
        "/channels",
        data={
            "name": "目录站",
            "url": "https://directory.example",
            "channel_type": "directory",
            "status": "active",
            "supports_automation": "on",
            "adapter_key": "playwright_form",
            "adapter_config": "{}",
            "notes": "",
        },
    ).status_code == 200
    with SessionLocal() as db:
        site = db.query(TargetSite).one()
        channel = db.query(Channel).one()
        site_id, channel_id = site.id, channel.id

    client.post(
        "/records",
        data={
            "target_site_id": site_id,
            "channel_id": channel_id,
            "actual_url": "https://directory.example/item/1",
            "anchor_text": "示例锚文本",
            "published_at": date.today().isoformat(),
            "method": "manual",
            "status": "live",
        },
    )
    warning = client.get(f"/records/duplicate-check?target_site_id={site_id}&channel_id={channel_id}")
    assert "可能重复发布" in warning.text
    assert date.today().isoformat() in warning.text

    client.post(
        f"/channels/{channel_id}/credential",
        data={"username": "publisher", "password": "plain-secret", "api_key": "api-secret"},
    )
    with SessionLocal() as db:
        credential = db.query(ChannelCredential).one()
        assert "plain-secret" not in credential.encrypted_password
        assert CredentialCipher().decrypt(credential.encrypted_password) == "plain-secret"
        assert CredentialCipher().decrypt_json(credential.encrypted_extra_fields)["api_key"] == "api-secret"
    detail = client.get(f"/channels/{channel_id}")
    assert "plain-secret" not in detail.text
    assert "******" in detail.text


def test_query_dashboard_marks_auto_records(authenticated_client):
    with SessionLocal() as db:
        site = TargetSite(name="站点", url="https://site.example")
        channel = Channel(name="论坛", url="https://forum.example", channel_type="forum", status="active")
        db.add_all([site, channel])
        db.flush()
        db.add(BacklinkRecord(
            target_site_id=site.id,
            channel_id=channel.id,
            actual_url="https://forum.example/post/1",
            anchor_text="锚文本",
            published_at=date.today(),
            method=PublishMethod.auto,
            status=RecordStatus.live,
        ))
        db.commit()
        site_id = site.id
    response = authenticated_client.get(f"/records?target_site_id={site_id}&method=auto&status=live")
    assert response.status_code == 200
    assert "自动引擎" in response.text
    assert "forum.example/post/1" in response.text


def test_automation_success_creates_auto_live_record(monkeypatch):
    class SuccessAdapter:
        async def submit_link(self, target_url, anchor_text, credentials, config):
            assert target_url == "https://target.example"
            return SubmissionResult(True, "https://channel.example/published/42", "ok")

    monkeypatch.setattr("app.automation.engine.get_adapter", lambda _key: SuccessAdapter())
    with SessionLocal() as db:
        site = TargetSite(name="目标", url="https://target.example")
        channel = Channel(
            name="自动渠道",
            url="https://channel.example",
            channel_type="directory",
            status="active",
            supports_automation=True,
            adapter_key="playwright_form",
            adapter_config="{}",
        )
        db.add_all([site, channel])
        db.flush()
        task = AutomationTask(target_site_id=site.id, channel_id=channel.id, anchor_text="锚文本")
        db.add(task)
        db.commit()
        task_id = task.id

    asyncio.run(execute_task(task_id))
    with SessionLocal() as db:
        task = db.get(AutomationTask, task_id)
        record = db.query(BacklinkRecord).one()
        assert task.status == TaskStatus.success
        assert record.method == PublishMethod.auto
        assert record.status == RecordStatus.live
        assert record.actual_url.endswith("/published/42")


def test_automation_failure_writes_only_log_and_needs_attention(monkeypatch):
    class FailedAdapter:
        async def submit_link(self, target_url, anchor_text, credentials, config):
            return SubmissionResult(False, message="表单拒绝提交")

    monkeypatch.setattr("app.automation.engine.get_adapter", lambda _key: FailedAdapter())
    with SessionLocal() as db:
        site = TargetSite(name="目标", url="https://target.example")
        channel = Channel(
            name="自动渠道",
            url="https://channel.example",
            channel_type="directory",
            status="active",
            supports_automation=True,
            adapter_key="playwright_form",
            adapter_config="{}",
        )
        db.add_all([site, channel])
        db.flush()
        task = AutomationTask(
            target_site_id=site.id,
            channel_id=channel.id,
            anchor_text="锚文本",
            max_retries=0,
        )
        db.add(task)
        db.commit()
        task_id = task.id

    asyncio.run(execute_task(task_id))
    with SessionLocal() as db:
        task = db.get(AutomationTask, task_id)
        assert task.status == TaskStatus.needs_attention
        assert db.query(BacklinkRecord).count() == 0
        assert task.logs

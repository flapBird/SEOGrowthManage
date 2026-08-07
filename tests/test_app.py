import asyncio
from datetime import date

from app.database import SessionLocal
from app.automation.base import SubmissionResult
from app.automation.engine import execute_task
from app.models import (
    AutomationTask,
    BacklinkRecord,
    Channel,
    ChannelBlacklist,
    ChannelCredential,
    PublishMethod,
    RecordStatus,
    SubmissionBatch,
    SubmissionBatchStatus,
    SubmissionItemStatus,
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


def test_empty_record_filters_do_not_raise_validation_error(authenticated_client):
    response = authenticated_client.get("/records?target_site_id=&channel_id=&status=&method=")
    assert response.status_code == 200
    assert "外链发布记录" in response.text
    assert authenticated_client.get("/records/duplicate-check?target_site_id=&channel_id=").status_code == 200


def test_channel_blacklist_blocks_channels_and_record_selection(authenticated_client):
    client = authenticated_client
    client.post("/sites", data={"name": "目标站", "url": "https://target.example", "notes": ""})
    allowed_data = {
        "name": "可用渠道",
        "url": "https://allowed.example/submit",
        "channel_type": "directory",
        "status": "active",
        "notes": "",
    }
    blocked_data = {**allowed_data, "name": "应被隐藏渠道", "url": "https://sub.blocked.example/submit"}
    assert client.post("/channels", data=allowed_data).status_code == 200
    assert client.post("/channels", data=blocked_data).status_code == 200

    response = client.post(
        "/channel-blacklist/import",
        data={"entries": "https://www.blocked.example/path\n*.another-bad.example", "notes": "测试黑名单"},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        assert {entry.domain for entry in db.query(ChannelBlacklist).all()} == {"blocked.example", "another-bad.example"}
        blocked_channel = db.query(Channel).filter_by(name="应被隐藏渠道").one()
        blocked_channel_id = blocked_channel.id

    record_form = client.get("/records/new")
    assert "可用渠道" in record_form.text
    assert "应被隐藏渠道" not in record_form.text
    assert 'data-select-search="target-site"' in record_form.text
    assert 'data-select-search="channel"' in record_form.text

    with SessionLocal() as db:
        site_id = db.query(TargetSite).one().id
    blocked_record = client.post(
        "/records",
        data={
            "target_site_id": site_id,
            "channel_id": blocked_channel_id,
            "actual_url": "https://sub.blocked.example/post/1",
            "anchor_text": "测试",
            "published_at": date.today().isoformat(),
            "method": "manual",
            "status": "live",
        },
    )
    assert blocked_record.status_code == 422

    rejected_channel = client.post("/channels", data={**blocked_data, "name": "新黑名单渠道"})
    assert rejected_channel.status_code == 422


def test_submission_batch_plan_partial_completion_and_record_retention(authenticated_client):
    client = authenticated_client
    with SessionLocal() as db:
        sites = [
            TargetSite(name=f"产品站 {index}", url=f"https://product-{index}.example")
            for index in range(1, 4)
        ]
        channel = Channel(
            name="个人主页渠道",
            url="https://profile.example/user/publisher",
            channel_type="directory",
            status="active",
        )
        db.add_all([*sites, channel])
        db.commit()
        site_ids = [site.id for site in sites]
        channel_id = channel.id

    response = client.post(
        "/submission-batches",
        data={
            "channel_id": str(channel_id),
            "target_site_ids": [str(site_id) for site_id in site_ids],
            "scheduled_for": date.today().isoformat(),
            "submit_action": "plan",
            "title": "三站个人主页提交",
            "shared_url": "",
            "anchor_text": "",
            "record_status": "live",
            "notes": "统一放在个人主页",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        batch = db.query(SubmissionBatch).one()
        batch_id = batch.id
        assert batch.status == SubmissionBatchStatus.planned
        assert len(batch.items) == 3
        assert db.query(BacklinkRecord).count() == 0
        first_item_ids = [item.id for item in batch.items[:2]]

    response = client.post(
        f"/submission-batches/{batch_id}/complete",
        data={
            "item_ids": [str(item_id) for item_id in first_item_ids],
            "actual_url": "https://profile.example/user/publisher",
            "anchor_text": "",
            "published_at": date.today().isoformat(),
            "record_status": "live",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        batch = db.get(SubmissionBatch, batch_id)
        assert batch.status == SubmissionBatchStatus.partial
        assert sum(item.status == SubmissionItemStatus.completed for item in batch.items) == 2
        assert sum(item.status == SubmissionItemStatus.planned for item in batch.items) == 1
        assert db.query(BacklinkRecord).count() == 2
        last_item_id = next(item.id for item in batch.items if item.status == SubmissionItemStatus.planned)

    dashboard = client.get("/")
    assert "三站个人主页提交" in dashboard.text
    assert "部分完成" in dashboard.text

    response = client.post(
        f"/submission-batches/{batch_id}/complete",
        data={
            "item_ids": str(last_item_id),
            "actual_url": "https://profile.example/user/publisher",
            "anchor_text": "",
            "published_at": date.today().isoformat(),
            "record_status": "live",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        assert db.get(SubmissionBatch, batch_id).status == SubmissionBatchStatus.completed
        assert db.query(BacklinkRecord).count() == 3

    assert client.post(f"/submission-batches/{batch_id}/delete", follow_redirects=False).status_code == 303
    with SessionLocal() as db:
        assert db.get(SubmissionBatch, batch_id) is None
        assert db.query(BacklinkRecord).count() == 3


def test_submission_batch_can_immediately_create_multiple_records(authenticated_client):
    with SessionLocal() as db:
        sites = [TargetSite(name="站点 A", url="https://a.example"), TargetSite(name="站点 B", url="https://b.example")]
        channel = Channel(name="产品列表", url="https://list.example/products", channel_type="directory", status="active")
        db.add_all([*sites, channel])
        db.commit()
        site_ids = [site.id for site in sites]
        channel_id = channel.id

    response = authenticated_client.post(
        "/submission-batches",
        data={
            "channel_id": str(channel_id),
            "target_site_ids": [str(site_id) for site_id in site_ids],
            "scheduled_for": date.today().isoformat(),
            "submit_action": "complete",
            "shared_url": "https://list.example/products",
            "anchor_text": "产品列表",
            "record_status": "pending",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        batch = db.query(SubmissionBatch).one()
        records = db.query(BacklinkRecord).all()
        assert batch.status == SubmissionBatchStatus.completed
        assert len(records) == 2
        assert {record.target_site_id for record in records} == set(site_ids)
        assert all(record.actual_url == "https://list.example/products" for record in records)
        assert all(record.status == RecordStatus.pending for record in records)
        assert all(record.method == PublishMethod.manual for record in records)


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

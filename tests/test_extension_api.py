from app.database import SessionLocal
from app.extension_security import issue_extension_token
from app.models import (
    BacklinkTask,
    BacklinkTaskStatus,
    Channel,
    ExtensionToken,
    Opportunity,
    OpportunitySource,
    OpportunityStatus,
    OpportunityType,
    TargetSite,
)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def seed_task_queue() -> tuple[int, int, str, int]:
    with SessionLocal() as db:
        site = TargetSite(name="产品项目", url="https://product.example")
        opportunity = Opportunity(
            url="https://publisher.example/submit",
            domain="publisher.example",
            opportunity_type=OpportunityType.directory,
            source=OpportunitySource.manual,
            status=OpportunityStatus.eligible,
        )
        db.add_all([site, opportunity])
        db.flush()
        first = BacklinkTask(
            target_site_id=site.id,
            opportunity_id=opportunity.id,
            target_url="https://product.example/landing",
            workflow=OpportunityType.directory,
            anchor_text="产品名称",
        )
        second = BacklinkTask(
            target_site_id=site.id,
            opportunity_id=opportunity.id,
            target_url=site.url,
            workflow=OpportunityType.directory,
        )
        db.add_all([first, second])
        db.flush()
        _token_model, plaintext = issue_extension_token(db, "测试 Chrome")
        db.refresh(first)
        return site.id, first.id, plaintext, second.id


def test_extension_api_requires_bearer_token(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 401
    assert response.json()["detail"] == "缺少有效的 Extension Token"


def test_extension_projects_and_atomic_task_claim(client):
    project_id, first_id, plaintext, second_id = seed_task_queue()

    health = client.get("/api/v1/health", headers=bearer(plaintext))
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "seo-growth-console", "apiVersion": "v1"}

    projects = client.get("/api/v1/projects", headers=bearer(plaintext))
    assert projects.status_code == 200
    assert projects.json() == [
        {"id": project_id, "name": "产品项目", "website": "https://product.example"}
    ]

    claim = client.post(
        "/api/v1/tasks/next/claim",
        headers={**bearer(plaintext), "Idempotency-Key": "claim-1"},
        json={"projectId": project_id},
    )
    assert claim.status_code == 200
    payload = claim.json()
    assert payload["id"] == first_id
    assert payload["status"] == "processing"
    assert payload["sourceUrl"] == "https://publisher.example/submit"
    assert payload["targetUrl"] == "https://product.example/landing"
    assert payload["leaseExpiresAt"]

    # 同一 Token 在租约有效期内重复领取，应恢复当前任务而不是跳到下一条。
    repeated = client.post(
        "/api/v1/tasks/next/claim",
        headers=bearer(plaintext),
        json={"projectId": project_id},
    )
    assert repeated.status_code == 200
    assert repeated.json()["id"] == first_id

    detail = client.get(f"/api/v1/tasks/{first_id}", headers=bearer(plaintext))
    assert detail.status_code == 200
    assert detail.json()["id"] == first_id

    heartbeat = client.patch(
        f"/api/v1/tasks/{first_id}",
        headers=bearer(plaintext),
        json={"status": "processing"},
    )
    assert heartbeat.status_code == 200
    assert heartbeat.json()["leaseExpiresAt"]

    prepared = client.patch(
        f"/api/v1/tasks/{first_id}",
        headers=bearer(plaintext),
        json={"status": "prepared", "note": "页面已分析"},
    )
    assert prepared.status_code == 200
    assert prepared.json()["status"] == "prepared"
    assert prepared.json()["leaseExpiresAt"] is None

    next_claim = client.post(
        "/api/v1/tasks/next/claim",
        headers=bearer(plaintext),
        json={"projectId": project_id},
    )
    assert next_claim.status_code == 200
    assert next_claim.json()["id"] == second_id


def test_extension_token_is_hashed_and_can_be_revoked(authenticated_client):
    response = authenticated_client.post(
        "/extension/tokens",
        data={"name": "我的浏览器", "expires_days": "30"},
    )
    assert response.status_code == 200
    with SessionLocal() as db:
        token = db.query(ExtensionToken).one()
        token_id = token.id
        assert token.token_hash not in response.text
        assert token.token_prefix in response.text
        assert "blx_" in response.text
        assert len(token.token_hash) == 64

    assert authenticated_client.post(
        f"/extension/tokens/{token_id}/revoke", follow_redirects=False
    ).status_code == 303
    with SessionLocal() as db:
        assert db.get(ExtensionToken, token_id).revoked_at is not None


def test_web_can_create_extension_task_and_reuse_matching_channel(authenticated_client):
    with SessionLocal() as db:
        site = TargetSite(name="官网", url="https://target.example")
        channel = Channel(
            name="Product Directory",
            url="https://directory.example",
            channel_type="directory",
            status="active",
        )
        db.add_all([site, channel])
        db.commit()
        site_id, channel_id = site.id, channel.id

    response = authenticated_client.post(
        "/extension/tasks",
        data={
            "target_site_id": str(site_id),
            "source_url": "https://directory.example/submit#form",
            "workflow": "directory",
            "target_url": "",
            "anchor_text": "目标站",
            "note": "人工发现",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        opportunity = db.query(Opportunity).one()
        task = db.query(BacklinkTask).one()
        assert opportunity.url == "https://directory.example/submit"
        assert opportunity.channel_id == channel_id
        assert task.target_url == "https://target.example"
        assert task.status == BacklinkTaskStatus.ready

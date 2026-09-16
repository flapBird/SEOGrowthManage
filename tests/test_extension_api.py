from sqlalchemy import create_engine, inspect, text

from app.database import SessionLocal, run_lightweight_migrations
from app.extension_security import issue_extension_token
from app.models import (
    BacklinkTask,
    BacklinkTaskStatus,
    BacklinkOrigin,
    BacklinkVerification,
    BacklinkRecord,
    Channel,
    ChannelBlacklist,
    ExtensionToken,
    Opportunity,
    OpportunitySource,
    OpportunityStatus,
    OpportunityType,
    RecordStatus,
    Submission,
    TargetSite,
)


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def test_lightweight_migration_adds_submission_backlink_reference(tmp_path):
    legacy_engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with legacy_engine.begin() as connection:
        connection.execute(text("CREATE TABLE submissions (id INTEGER PRIMARY KEY)"))
        connection.execute(text("CREATE TABLE backlink_records (id INTEGER PRIMARY KEY, method VARCHAR(20))"))
        connection.execute(text("INSERT INTO backlink_records (id, method) VALUES (1, 'auto')"))
    run_lightweight_migrations(legacy_engine)
    columns = {column["name"] for column in inspect(legacy_engine).get_columns("submissions")}
    assert "backlink_record_id" in columns
    record_columns = {column["name"] for column in inspect(legacy_engine).get_columns("backlink_records")}
    assert {"target_url", "link_rel", "first_seen_at", "last_verified_at"} <= record_columns
    with legacy_engine.connect() as connection:
        assert connection.execute(text(
            "SELECT origin FROM backlink_records WHERE id = 1"
        )).scalar_one() == "automation"


def seed_task_queue() -> tuple[int, int, str, int]:
    with SessionLocal() as db:
        site = TargetSite(
            name="产品项目",
            url="https://product.example",
            author_name="产品作者",
            email="author@product.example",
            tagline="一句话介绍",
            short_description="简短介绍",
            medium_description="中等介绍",
            long_description="完整介绍",
            keywords="seo, backlink",
        )
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


def test_project_profile_can_be_saved_for_extension_prefill(authenticated_client):
    response = authenticated_client.post(
        "/sites",
        data={
            "name": "资料完整项目",
            "url": "https://profile.example",
            "author_name": "Alice",
            "email": "alice@profile.example",
            "tagline": "Make backlinks observable",
            "short_description": "Short profile",
            "medium_description": "Medium profile",
            "long_description": "Long profile",
            "keywords": "seo, growth",
            "notes": "插件预填资料",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        site = db.query(TargetSite).one()
        assert site.author_name == "Alice"
        assert site.email == "alice@profile.example"
        assert site.medium_description == "Medium profile"
        assert site.keywords == "seo, growth"


def test_extension_projects_and_atomic_task_claim(client):
    project_id, first_id, plaintext, second_id = seed_task_queue()

    health = client.get("/api/v1/health", headers=bearer(plaintext))
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "service": "seo-growth-console", "apiVersion": "v1"}

    projects = client.get("/api/v1/projects", headers=bearer(plaintext))
    assert projects.status_code == 200
    assert projects.json() == [
        {
            "id": project_id,
            "name": "产品项目",
            "website": "https://product.example",
            "authorName": "产品作者",
            "email": "author@product.example",
            "tagline": "一句话介绍",
            "shortDescription": "简短介绍",
            "mediumDescription": "中等介绍",
            "longDescription": "完整介绍",
            "keywords": ["seo", "backlink"],
        }
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
    assert payload["project"]["authorName"] == "产品作者"

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

    direct_prepared = client.patch(
        f"/api/v1/tasks/{first_id}",
        headers=bearer(plaintext),
        json={"status": "prepared"},
    )
    assert direct_prepared.status_code == 409

    duplicate_check = client.get(
        "/api/v1/submissions/check",
        headers=bearer(plaintext),
        params={"projectId": project_id, "sourceUrl": "https://publisher.example/submit#form"},
    )
    assert duplicate_check.status_code == 200
    assert duplicate_check.json() == {
        "exactSubmissionCount": 0,
        "domainSubmissionCount": 0,
        "domainBacklinkCount": 0,
        "latestStatus": None,
    }

    wrong_domain = client.post(
        "/api/v1/submissions",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "status": "prepared",
            "targetUrl": "https://product.example/landing",
            "sourceUrl": "https://unrelated.example/form",
            "workflow": "directory",
        },
    )
    assert wrong_domain.status_code == 422

    prepared = client.post(
        "/api/v1/submissions",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "status": "prepared",
            "targetUrl": "https://product.example/landing",
            "sourceUrl": "https://publisher.example/submit#form",
            "workflow": "directory",
            "submittedContent": "中等介绍",
            "submittedWebsite": "https://product.example/landing",
            "anchorText": "产品名称",
            "resultMessage": "安全预填 4 个字段",
        },
    )
    assert prepared.status_code == 200
    assert prepared.json()["status"] == "prepared"
    submission_id = prepared.json()["id"]
    assert prepared.json()["sourceUrl"] == "https://publisher.example/submit"

    repeated_submission = client.post(
        "/api/v1/submissions",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "status": "prepared",
            "targetUrl": "https://product.example/landing",
            "sourceUrl": "https://publisher.example/submit",
            "workflow": "directory",
            "resultMessage": "再次确认预填",
        },
    )
    assert repeated_submission.status_code == 200
    assert repeated_submission.json()["id"] == submission_id
    with SessionLocal() as db:
        assert db.query(Submission).count() == 1

    history = client.get(
        "/api/v1/submissions",
        headers=bearer(plaintext),
        params={"projectId": project_id},
    )
    assert history.status_code == 200
    assert [item["id"] for item in history.json()] == [submission_id]

    duplicate_after_fill = client.get(
        "/api/v1/submissions/check",
        headers=bearer(plaintext),
        params={"projectId": project_id, "sourceUrl": "https://publisher.example/submit"},
    )
    assert duplicate_after_fill.json()["exactSubmissionCount"] == 1
    assert duplicate_after_fill.json()["domainSubmissionCount"] == 1
    assert duplicate_after_fill.json()["latestStatus"] == "prepared"

    task_after_fill = client.get(f"/api/v1/tasks/{first_id}", headers=bearer(plaintext))
    assert task_after_fill.json()["status"] == "prepared"
    assert task_after_fill.json()["leaseExpiresAt"] is None

    with SessionLocal() as db:
        _other_token, other_plaintext = issue_extension_token(db, "另一台 Chrome")
    wrong_owner = client.patch(
        f"/api/v1/submissions/{submission_id}",
        headers=bearer(other_plaintext),
        json={"status": "submitted"},
    )
    assert wrong_owner.status_code == 409

    direct_published = client.patch(
        f"/api/v1/submissions/{submission_id}",
        headers=bearer(plaintext),
        json={"status": "published"},
    )
    assert direct_published.status_code == 422

    verification_before_submit = client.post(
        "/api/v1/verifications",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "submissionId": submission_id,
            "sourceUrl": "https://publisher.example/success",
            "targetUrl": "https://product.example/landing",
            "outcome": "active",
            "anchorText": "产品名称",
            "linkRel": ["nofollow"],
            "checkedAt": "2026-09-02T10:00:00+08:00",
            "message": "找到目标链接",
        },
    )
    assert verification_before_submit.status_code == 409

    submitted = client.patch(
        f"/api/v1/submissions/{submission_id}",
        headers=bearer(plaintext),
        json={
            "status": "submitted",
            "submissionUrl": "https://publisher.example/success#result",
            "resultMessage": "用户确认已经点击提交",
            "note": "等待页面结果",
        },
    )
    assert submitted.status_code == 200
    assert submitted.json()["status"] == "submitted"
    assert submitted.json()["submissionUrl"] == "https://publisher.example/success#result"
    assert submitted.json()["submittedAt"]
    assert submitted.json()["backlinkRecordId"] is None

    missing = client.post(
        "/api/v1/verifications",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "submissionId": submission_id,
            "sourceUrl": "https://publisher.example/success",
            "targetUrl": "https://product.example/landing",
            "outcome": "link_missing",
            "linkRel": [],
            "checkedAt": "2026-09-02T10:01:00+08:00",
            "message": "当前页面没有目标链接",
        },
    )
    assert missing.status_code == 200
    assert missing.json()["verification"]["outcome"] == "link_missing"
    assert missing.json()["submission"]["status"] == "submitted"
    assert missing.json()["submission"]["backlinkRecordId"] is None
    with SessionLocal() as db:
        assert db.query(BacklinkRecord).count() == 0

    wrong_target = client.post(
        "/api/v1/verifications",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "submissionId": submission_id,
            "sourceUrl": "https://publisher.example/success",
            "targetUrl": "https://product.example/wrong",
            "outcome": "active",
            "checkedAt": "2026-09-02T10:02:00+08:00",
        },
    )
    assert wrong_target.status_code == 422

    active = client.post(
        "/api/v1/verifications",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "submissionId": submission_id,
            "sourceUrl": "https://publisher.example/success#comment-10",
            "targetUrl": "https://product.example/landing",
            "outcome": "active",
            "anchorText": "产品名称",
            "linkRel": ["ugc", "nofollow"],
            "checkedAt": "2026-09-02T10:03:00+08:00",
            "message": "当前页面发现精确目标链接",
        },
    )
    assert active.status_code == 200
    active_payload = active.json()
    assert active_payload["submission"]["status"] == "published"
    assert active_payload["submission"]["verifiedAt"]
    assert active_payload["submission"]["backlinkRecordId"]
    assert active_payload["task"]["status"] == "completed"
    assert active_payload["verification"]["linkRel"] == ["ugc", "nofollow"]
    backlink_id = active_payload["submission"]["backlinkRecordId"]
    with SessionLocal() as db:
        record = db.get(BacklinkRecord, backlink_id)
        assert record.status == RecordStatus.live
        assert record.origin == BacklinkOrigin.extension_verified
        assert record.actual_url == "https://publisher.example/success#comment-10"
        assert record.target_url == "https://product.example/landing"
        assert record.link_rel == '["ugc", "nofollow"]'
        assert record.first_seen_at
        assert record.last_verified_at
        assert db.query(BacklinkRecord).count() == 1

    repeated_active = client.post(
        "/api/v1/verifications",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "submissionId": submission_id,
            "sourceUrl": "https://publisher.example/success",
            "targetUrl": "https://product.example/landing",
            "outcome": "active",
            "anchorText": "产品名称",
            "checkedAt": "2026-09-02T10:04:00+08:00",
        },
    )
    assert repeated_active.status_code == 200
    assert repeated_active.json()["submission"]["backlinkRecordId"] == backlink_id
    with SessionLocal() as db:
        assert db.query(BacklinkRecord).count() == 1
        assert db.query(BacklinkVerification).count() == 3

    backlink_history = client.get(
        "/api/v1/backlinks/history",
        headers=bearer(plaintext),
        params={"projectId": project_id},
    )
    assert backlink_history.status_code == 200
    assert backlink_history.json()[0]["firstSeenAt"]
    assert backlink_history.json()[0]["lastVerifiedAt"]
    assert backlink_history.json() == [{
        "id": backlink_id,
        "projectId": project_id,
        "projectName": "产品项目",
        "channelId": backlink_history.json()[0]["channelId"],
        "channelName": "publisher.example",
        "channelUrl": "https://publisher.example",
        "actualUrl": "https://publisher.example/success#comment-10",
        "targetUrl": "https://product.example/landing",
        "anchorText": "产品名称",
        "linkRel": ["ugc", "nofollow"],
        "status": "live",
        "origin": "extension_verified",
        "publishedAt": backlink_history.json()[0]["publishedAt"],
        "firstSeenAt": backlink_history.json()[0]["firstSeenAt"],
        "lastVerifiedAt": backlink_history.json()[0]["lastVerifiedAt"],
        "submissionId": submission_id,
    }]

    removed = client.post(
        "/api/v1/verifications",
        headers=bearer(plaintext),
        json={
            "taskId": first_id,
            "submissionId": submission_id,
            "sourceUrl": "https://publisher.example/success",
            "targetUrl": "https://product.example/landing",
            "outcome": "link_missing",
            "checkedAt": "2026-09-02T10:05:00+08:00",
            "message": "已发布链接后来消失",
        },
    )
    assert removed.status_code == 200
    assert removed.json()["submission"]["status"] == "removed"
    with SessionLocal() as db:
        assert db.get(BacklinkRecord, backlink_id).status == RecordStatus.removed

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


def test_extension_api_creates_task_directly_and_records_submission(client):
    project_id, _seed_task_id, plaintext, _second_id = seed_task_queue()

    created = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={
            "projectId": project_id,
            "sourceUrl": "https://www.toolify.ai/submit",
            "workflow": "directory",
            "targetUrl": "https://product.example/landing",
            "anchorText": "产品名称",
            "note": "backlink-submit skill",
        },
    )
    assert created.status_code == 200
    data = created.json()
    assert data["status"] == "processing"
    assert data["sourceUrl"] == "https://www.toolify.ai/submit"
    assert data["sourceDomain"] == "toolify.ai"
    assert data["targetUrl"] == "https://product.example/landing"
    assert data["anchorText"] == "产品名称"
    assert data["leaseExpiresAt"] is not None
    task_id = data["id"]

    # 同一来源重复创建返回同一任务，保证重试幂等
    repeat = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": project_id, "sourceUrl": "https://www.toolify.ai/submit"},
    )
    assert repeat.status_code == 200
    assert repeat.json()["id"] == task_id

    # 目标 URL 省略时回落到项目官网
    fallback = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": project_id, "sourceUrl": "https://news.ycombinator.com/submit"},
    )
    assert fallback.status_code == 200
    assert fallback.json()["targetUrl"] == "https://product.example/"

    submission = client.post(
        "/api/v1/submissions",
        headers=bearer(plaintext),
        json={
            "taskId": task_id,
            "status": "prepared",
            "targetUrl": "https://product.example/landing",
            "sourceUrl": "https://www.toolify.ai/submit",
            "workflow": "directory",
            "submittedContent": "填入的介绍",
            "submittedWebsite": "https://product.example/landing",
            "anchorText": "产品名称",
            "resultMessage": "安全预填 3 个字段",
        },
    )
    assert submission.status_code == 200
    submission_id = submission.json()["id"]

    result = client.patch(
        f"/api/v1/submissions/{submission_id}",
        headers=bearer(plaintext),
        json={"status": "pending", "resultMessage": "页面提示 awaiting review"},
    )
    assert result.status_code == 200
    assert result.json()["status"] == "pending"

    with SessionLocal() as db:
        opportunity = db.query(Opportunity).filter(
            Opportunity.url == "https://www.toolify.ai/submit"
        ).one()
        assert opportunity.domain == "toolify.ai"
        task = db.query(BacklinkTask).get(task_id)
        assert task.status == BacklinkTaskStatus.completed
        assert task.opportunity_id == opportunity.id


def test_extension_api_task_create_rejects_invalid_and_blacklisted(client):
    project_id, _first, plaintext, _second = seed_task_queue()

    missing_project = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": 99999, "sourceUrl": "https://a.example/submit"},
    )
    assert missing_project.status_code == 404

    unknown_workflow = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": project_id, "sourceUrl": "https://a.example/submit", "workflow": "unknown"},
    )
    assert unknown_workflow.status_code == 422

    bad_url = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": project_id, "sourceUrl": "not-a-url"},
    )
    assert bad_url.status_code == 422

    with SessionLocal() as db:
        db.add(ChannelBlacklist(domain="blocked.example"))
        db.commit()
    blacklisted = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": project_id, "sourceUrl": "https://sub.blocked.example/submit"},
    )
    assert blacklisted.status_code == 422
    assert "blocked.example" in blacklisted.json()["detail"]


def test_extension_api_task_create_reuses_and_conflicts_on_active_claims(client):
    project_id, _first, plaintext, _second = seed_task_queue()

    first = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": project_id, "sourceUrl": "https://a.example/submit"},
    )
    assert first.status_code == 200
    task_id = first.json()["id"]

    # 其他 Token 持有有效租约时应冲突
    _other_model, other_plaintext = issue_extension_token(SessionLocal(), "另一台浏览器")
    conflict = client.post(
        "/api/v1/tasks",
        headers=bearer(other_plaintext),
        json={"projectId": project_id, "sourceUrl": "https://a.example/submit"},
    )
    assert conflict.status_code == 409

    # 同一 Token 重复调用返回同一任务
    repeat = client.post(
        "/api/v1/tasks",
        headers=bearer(plaintext),
        json={"projectId": project_id, "sourceUrl": "https://a.example/submit"},
    )
    assert repeat.status_code == 200
    assert repeat.json()["id"] == task_id

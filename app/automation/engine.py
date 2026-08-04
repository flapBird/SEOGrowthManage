from __future__ import annotations

import json
from datetime import date

from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from ..config import get_settings
from ..channel_blacklist import is_channel_blacklisted
from ..database import SessionLocal
from ..models import (
    AutomationTask,
    AutomationTaskLog,
    BacklinkRecord,
    Channel,
    ChannelStatus,
    PublishMethod,
    RecordStatus,
    TaskStatus,
)
from ..security import CredentialCipher
from .registry import get_adapter


def add_log(db, task_id: int, level: str, message: str) -> None:
    db.add(AutomationTaskLog(task_id=task_id, level=level, message=message[:4000]))


async def execute_task(task_id: int) -> None:
    with SessionLocal() as db:
        claimed = db.execute(
            update(AutomationTask)
            .where(
                AutomationTask.id == task_id,
                AutomationTask.status.in_([TaskStatus.pending, TaskStatus.failed]),
            )
            .values(status=TaskStatus.running)
        )
        db.commit()
        if claimed.rowcount != 1:
            return
        task = db.scalar(
            select(AutomationTask)
            .options(
                joinedload(AutomationTask.target_site),
                joinedload(AutomationTask.channel).joinedload(Channel.credential),
            )
            .where(AutomationTask.id == task_id)
        )
        if task is None:
            return
        if task.channel.status != ChannelStatus.active or not task.channel.supports_automation or is_channel_blacklisted(db, task.channel):
            task.status = TaskStatus.needs_attention
            task.last_error = "渠道已失效、被封禁、进入黑名单或已关闭自动化，任务自动停止"
            add_log(db, task.id, "warning", task.last_error)
            db.commit()
            return

        add_log(db, task.id, "info", f"开始第 {task.retry_count + 1} 次尝试")
        db.commit()

        try:
            adapter = get_adapter(task.channel.adapter_key)
            config = json.loads(task.channel.adapter_config or "{}")
            config.setdefault("headless", get_settings().playwright_headless)
            credentials = {}
            if task.channel.credential:
                cipher = CredentialCipher()
                credential = task.channel.credential
                credentials = cipher.decrypt_json(credential.encrypted_extra_fields)
                credentials.update(
                    username=credential.username,
                    password=cipher.decrypt(credential.encrypted_password),
                )
            result = await adapter.submit_link(task.target_site.url, task.anchor_text, credentials, config)
            if not result.success or not result.actual_url:
                raise RuntimeError(result.message or "适配器未返回发布 URL")

            task.status = TaskStatus.success
            task.actual_url = result.actual_url
            task.last_error = None
            db.add(BacklinkRecord(
                target_site_id=task.target_site_id,
                channel_id=task.channel_id,
                actual_url=result.actual_url,
                anchor_text=task.anchor_text,
                published_at=date.today(),
                method=PublishMethod.auto,
                status=RecordStatus.live,
            ))
            add_log(db, task.id, "success", result.message or f"发布成功: {result.actual_url}")
        except Exception as exc:
            task.retry_count += 1
            task.last_error = str(exc)[:4000]
            if task.retry_count > task.max_retries:
                task.status = TaskStatus.needs_attention
                add_log(db, task.id, "error", f"已超过 {task.max_retries} 次重试上限，需人工介入: {task.last_error}")
            else:
                task.status = TaskStatus.failed
                add_log(db, task.id, "error", f"执行失败，将自动重试: {task.last_error}")
        db.commit()


async def process_pending_tasks() -> None:
    settings = get_settings()
    with SessionLocal() as db:
        task_ids = db.scalars(
            select(AutomationTask.id)
            .where(
                AutomationTask.status.in_([TaskStatus.pending, TaskStatus.failed]),
                AutomationTask.retry_count <= AutomationTask.max_retries,
            )
            .order_by(AutomationTask.created_at)
            .limit(settings.automation_batch_size)
        ).all()
    for task_id in task_ids:
        await execute_task(task_id)

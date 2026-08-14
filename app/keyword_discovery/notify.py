from __future__ import annotations

import asyncio
import smtplib
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import NotifyChannel, NotifyChannelType, now_local
from ..security import CredentialCipher


async def _push_serverchan(client: httpx.AsyncClient, config: dict[str, Any], title: str, desp: str) -> None:
    """Server酱推送到微信。desp 支持 markdown。"""
    sendkey = config["sendkey"]
    response = await client.post(
        f"https://sctapi.ftqq.com/{sendkey}.send",
        data={"title": title, "desp": desp},
        timeout=15,
    )
    response.raise_for_status()


async def _push_wecom_bot(client: httpx.AsyncClient, config: dict[str, Any], content: str) -> None:
    """企业微信群机器人，推送 markdown 内容。"""
    response = await client.post(
        config["webhook"],
        json={"msgtype": "markdown", "markdown": {"content": content}},
        timeout=15,
    )
    response.raise_for_status()


def _send_email_sync(cfg: dict[str, Any], title: str, body_text: str) -> None:
    """同步发送邮件。国内服务器建议用 smtp.qq.com / smtp.163.com（国内可达、稳定）。
    smtp_password 是邮箱后台生成的“授权码”，不是登录密码。"""
    msg = MIMEMultipart()
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    msg["Subject"] = Header(title, "utf-8")
    msg["From"] = cfg["mail_from"]
    msg["To"] = cfg["mail_to"]
    # 手动补上这两个头：smtplib 默认不加，缺了是垃圾邮件识别系统的经典信号，容易进垃圾箱。
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=cfg["mail_from"].split("@")[-1])

    with smtplib.SMTP_SSL(cfg["smtp_host"], int(cfg.get("smtp_port", 465)), timeout=20) as server:
        server.login(cfg["smtp_user"], cfg["smtp_password"])
        server.sendmail(cfg["mail_from"], [cfg["mail_to"]], msg.as_string())


async def _push_email(config: dict[str, Any], title: str, body_text: str) -> None:
    """smtplib 是同步阻塞，用 to_thread 包裹避免阻塞事件循环。"""
    await asyncio.to_thread(_send_email_sync, config, title, body_text)


async def _dispatch_one(channel: NotifyChannel, cipher: CredentialCipher, title: str, body_markdown: str) -> bool:
    """向单个通道推送，成功返回 True。异常向上抛由调用方记录。"""
    config = cipher.decrypt_json(channel.config_json)
    async with httpx.AsyncClient() as client:
        if channel.channel_type == NotifyChannelType.serverchan:
            await _push_serverchan(client, config, title, body_markdown)
        elif channel.channel_type == NotifyChannelType.wecom_bot:
            await _push_wecom_bot(client, config, f"**{title}**\n\n{body_markdown}")
        elif channel.channel_type == NotifyChannelType.email:
            await _push_email(config, title, body_markdown)
    return True


async def notify(db: Session, title: str, body_markdown: str) -> int:
    """向所有启用的通知通道推送一条消息，返回成功推送的通道数。
    每个通道独立 try/except：失败写 last_error 并累加 consecutive_failures，成功清零。
    只要数据库里没有可用通道或全部失败，也只返回 0，绝不抛错打断调用方。"""
    channels = list(db.scalars(
        select(NotifyChannel).where(NotifyChannel.enabled.is_(True)).order_by(NotifyChannel.id)
    ).all())
    if not channels:
        return 0
    cipher = CredentialCipher()
    succeeded = 0
    for channel in channels:
        try:
            await _dispatch_one(channel, cipher, title, body_markdown)
            channel.last_used_at = now_local()
            channel.consecutive_failures = 0
            channel.last_error = None
            succeeded += 1
        except Exception as exc:
            channel.consecutive_failures += 1
            channel.last_error = f"{type(exc).__name__}: {exc}"[:1000]
    db.commit()
    return succeeded


async def notify_one(channel: NotifyChannel, title: str, body_markdown: str) -> bool:
    """向单个通道推送（用于通道测试）。成功返回 True，失败返回 False 并把错误写回通道。"""
    cipher = CredentialCipher()
    try:
        await _dispatch_one(channel, cipher, title, body_markdown)
        channel.last_used_at = now_local()
        channel.consecutive_failures = 0
        channel.last_error = None
        return True
    except Exception as exc:
        channel.consecutive_failures += 1
        channel.last_error = f"{type(exc).__name__}: {exc}"[:1000]
        return False

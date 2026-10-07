#!/usr/bin/env python3
"""外链提交技能的线上 API 助手（仅标准库，无第三方依赖）。

封装 SEO Growth Console Extension API 的查重、选渠道、建任务、
记录提交、回写结果、验证全链路。SKILL.md 的执行步骤直接调用本脚本，
不要手写 curl。

用法:
    api.py config                       # 查看当前配置（token 打码）
    api.py projects                     # 列出线上项目
    api.py history [--limit 200]        # 线上已提交域名汇总（查重总览）
    api.py check --url <URL>            # 单渠道线上查重
    api.py plan [--limit 5] [--tier 1] [--category launch] [--key producthunt]...
                                        # 选出本轮目标渠道（本地台账+线上查重过滤）
    api.py task-create --url <URL> [--workflow directory] [--target-url X]
                        [--anchor X] [--note X]     # 线上直建任务并认领
    api.py prepared --task-id N --url <SOURCE> --target <TARGET>
            [--content X] [--website X] [--anchor X] [--message X]   # 记录 prepared
    api.py result --submission-id N --status submitted|pending|duplicate|
            rejected|failed|unknown [--submission-url X] [--message X] [--note X]
    api.py verify --task-id N --submission-id N --source-url X --target-url X
            --outcome active|pending|removed|page_404|link_missing|unknown
            [--anchor X] [--rel ugc,nofollow] [--http-status N] [--message X]
    api.py ledger-set --key producthunt --status submitted [--url X] [--note X]
                                        # 更新本地台账

配置优先级: 环境变量 SEO_CONSOLE_URL / SEO_CONSOLE_TOKEN / SEO_CONSOLE_PROJECT
> data/backlink_submit/config.json。token 属于敏感信息，config.json 已被 gitignore。
"""

from __future__ import annotations

import argparse
import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

SCRIPT_DIR = Path(__file__).resolve().parent
SKILL_DIR = SCRIPT_DIR.parent
WORKSPACE = SCRIPT_DIR.parents[3]
CONFIG_PATH = WORKSPACE / "data" / "backlink_submit" / "config.json"
LEDGER_PATH = WORKSPACE / "data" / "backlink_submit" / "ledger.json"
CHANNELS_PATH = SKILL_DIR / "data" / "channels.json"

# 单提交语义的渠道分类：线上同域名已有任何提交就跳过；
# 多内容语义（blog/community/social/profile/repo/design/other）只做精确 URL 查重。
SINGLE_SUBMIT_CATEGORIES = {"launch", "ai-directory", "review", "software-directory", "media"}
# 本地台账中已完成/已否决的状态：无论如何都跳过
# needs_*（等用户动作）与 failed/unknown 默认跳过，--include-failed 可重试
ALWAYS_SKIP_STATUSES = {
    "submitted", "pending", "live", "prepared", "duplicate", "rejected", "skipped", "paid_only",
}


class ApiError(SystemExit):
    def __init__(self, status_code: int, message: str):
        super().__init__(f"API {status_code}: {message}")


def load_config() -> dict:
    import os

    config: dict = {}
    if CONFIG_PATH.exists():
        config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    for env_key, cfg_key in (
        ("SEO_CONSOLE_URL", "server_url"),
        ("SEO_CONSOLE_TOKEN", "token"),
    ):
        if os.environ.get(env_key):
            config[cfg_key] = os.environ[env_key]
    if os.environ.get("SEO_CONSOLE_PROJECT"):
        config["project_id"] = int(os.environ["SEO_CONSOLE_PROJECT"])
    if not config.get("server_url") or not config.get("token"):
        print(
            json.dumps({
                "error": "缺少配置",
                "hint": f"在 {CONFIG_PATH} 写入 server_url / token / project_id，"
                        "token 在 Web 控制台 /extension 页创建",
            }, ensure_ascii=False)
        )
        raise SystemExit(2)
    config["server_url"] = config["server_url"].rstrip("/")
    return config


def call_api(config: dict, method: str, path: str, payload: dict | None = None,
             idempotency_key: str | None = None) -> dict | list:
    url = f"{config['server_url']}{path}"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {
        "Authorization": f"Bearer {config['token']}",
        "Content-Type": "application/json",
        # 站点在 Cloudflare 之后，默认 python-urllib UA 会被 1010 拦截
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        # macOS python.org 发行版常缺系统 CA；有 certifi 就用它的证书包（可选依赖）
        kwargs: dict = {"timeout": 30}
        try:
            import certifi
            kwargs["context"] = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            pass
        with urllib.request.urlopen(request, **kwargs) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        try:
            detail = json.loads(body).get("detail", body)
        except json.JSONDecodeError:
            detail = body
        raise ApiError(exc.code, str(detail)) from None


def load_ledger() -> dict:
    if LEDGER_PATH.exists():
        return json.loads(LEDGER_PATH.read_text(encoding="utf-8"))
    return {"channels": {}}


def save_ledger(ledger: dict) -> None:
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    LEDGER_PATH.write_text(json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def require_project(config: dict, args) -> int:
    project_id = getattr(args, "project", None) or config.get("project_id")
    if not project_id:
        print(json.dumps({"error": "未指定项目", "hint": "先运行 api.py projects，再在 config.json 填 project_id 或用 --project"}, ensure_ascii=False))
        raise SystemExit(2)
    return int(project_id)


def cmd_config(_args) -> None:
    config = load_config()
    token = config.get("token", "")
    masked = token[:8] + "…" + token[-4:] if len(token) > 14 else "…"
    print(json.dumps({"server_url": config["server_url"], "token": masked,
                      "project_id": config.get("project_id"),
                      "config_path": str(CONFIG_PATH), "ledger_path": str(LEDGER_PATH)}, ensure_ascii=False))


def cmd_projects(args) -> None:
    config = load_config()
    projects = call_api(config, "GET", "/api/v1/projects")
    if getattr(args, "project", None):
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
        persisted: dict = {}
        if CONFIG_PATH.exists():
            persisted = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        persisted["project_id"] = args.project
        CONFIG_PATH.write_text(json.dumps(persisted, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(projects, ensure_ascii=False, indent=2))


def normalize_host(value: str) -> str:
    host = (urlparse(value if "://" in value else f"//{value}").hostname or value or "").lower().rstrip(".")
    return host.removeprefix("www.")


def cmd_history(args) -> None:
    config = load_config()
    project_id = require_project(config, args)
    limit = min(max(args.limit, 1), 200)
    submissions = call_api(config, "GET", f"/api/v1/submissions?projectId={project_id}&limit={limit}")
    backlinks = call_api(config, "GET", f"/api/v1/backlinks/history?projectId={project_id}&limit={limit}")
    domains: dict[str, dict] = {}
    for item in submissions:
        domain = normalize_host(item.get("sourceDomain") or item.get("sourceUrl", ""))
        entry = domains.setdefault(domain, {"statuses": [], "sources": []})
        entry["statuses"].append(item.get("status"))
        entry["sources"].append(item.get("sourceUrl"))
    for item in backlinks:
        domain = normalize_host(item.get("channelUrl", "") or item.get("channelName", ""))
        entry = domains.setdefault(domain, {"statuses": [], "sources": []})
        entry["statuses"].append(f"backlink:{item.get('status')}")
    summary = {domain: {"statuses": sorted(set(v["statuses"])), "sources": v["sources"][:3]}
               for domain, v in sorted(domains.items())}
    print(json.dumps({"project_id": project_id, "submitted_domain_count": len(summary),
                      "domains": summary}, ensure_ascii=False, indent=2))


def cmd_check(args) -> None:
    config = load_config()
    project_id = require_project(config, args)
    query = urllib.parse.urlencode({"projectId": project_id, "sourceUrl": args.url})
    print(json.dumps(call_api(config, "GET", f"/api/v1/submissions/check?{query}"),
                     ensure_ascii=False, indent=2))


def online_block_reason(config: dict, project_id: int, channel: dict) -> dict | None:
    """线上查重：返回 {reason, counts}；无冲突返回 None。"""
    url = channel.get("submit_url") or channel["url"]
    if not url:
        return None
    try:
        query = urllib.parse.urlencode({"projectId": project_id, "sourceUrl": url})
        counts = call_api(config, "GET", f"/api/v1/submissions/check?{query}")
    except ApiError as exc:
        return {"reason": f"check_failed: {exc}", "counts": None}
    exact = counts.get("exactSubmissionCount", 0)
    domain = counts.get("domainSubmissionCount", 0)
    backlinks = counts.get("domainBacklinkCount", 0)
    if exact > 0:
        return {"reason": "线上已有同 URL 提交", "counts": counts}
    if domain > 0 and channel.get("category") in SINGLE_SUBMIT_CATEGORIES:
        return {"reason": "线上该域名已有提交（单提交类渠道）", "counts": counts}
    if backlinks > 0 and channel.get("category") in SINGLE_SUBMIT_CATEGORIES:
        return {"reason": "线上该域名已有正式外链（单提交类渠道）", "counts": counts}
    return None


def cmd_plan(args) -> None:
    config = load_config()
    project_id = require_project(config, args)
    data = json.loads(CHANNELS_PATH.read_text(encoding="utf-8"))
    ledger = load_ledger()
    keys = set(args.key or [])
    matched_keys: set[str] = set()
    selected, skipped = [], []
    for channel in data["channels"]:
        if keys and channel["key"] not in keys:
            continue
        matched_keys.add(channel["key"])
        if args.tier and channel["tier"] != args.tier:
            continue
        if args.category and channel["category"] != args.category:
            continue
        entry = ledger["channels"].get(channel["key"], {})
        status = entry.get("status")
        if status in ALWAYS_SKIP_STATUSES:
            skipped.append({"key": channel["key"], "reason": f"本地台账: {status}"})
            continue
        if status and not args.include_failed:
            skipped.append({"key": channel["key"], "reason": f"本地台账: {status}（--include-failed 可重试）"})
            continue
        if len(selected) >= args.limit:
            break
        block = online_block_reason(config, project_id, channel)
        if block:
            skipped.append({"key": channel["key"], "reason": block["reason"], "counts": block["counts"]})
            continue
        selected.append({k: channel[k] for k in ("key", "name", "url", "submit_url", "category",
                                                 "tier", "votes", "paid_tier", "needs_badge")})
    print(json.dumps({"project_id": project_id, "selected": selected,
                      "selected_count": len(selected), "skipped": skipped[:30],
                      "unknown_keys": sorted(keys - matched_keys)},
                     ensure_ascii=False, indent=2))


def cmd_task_create(args) -> None:
    config = load_config()
    project_id = require_project(config, args)
    payload: dict = {"projectId": project_id, "sourceUrl": args.url}
    if args.workflow:
        payload["workflow"] = args.workflow
    if args.target_url:
        payload["targetUrl"] = args.target_url
    if args.anchor:
        payload["anchorText"] = args.anchor
    if args.note:
        payload["note"] = args.note
    key = datetime.now().strftime("%Y%m%d%H%M%S%f")
    task = call_api(config, "POST", "/api/v1/tasks", payload, idempotency_key=f"skill-task-{key}")
    print(json.dumps(task, ensure_ascii=False, indent=2))


def cmd_prepared(args) -> None:
    config = load_config()
    payload: dict = {
        "taskId": args.task_id,
        "status": "prepared",
        "targetUrl": args.target,
        "sourceUrl": args.url,
        "workflow": args.workflow,
    }
    if args.content:
        payload["submittedContent"] = args.content
    if args.website:
        payload["submittedWebsite"] = args.website
    if args.anchor:
        payload["anchorText"] = args.anchor
    if args.message:
        payload["resultMessage"] = args.message
    key = datetime.now().strftime("%Y%m%d%H%M%S%f")
    print(json.dumps(call_api(config, "POST", "/api/v1/submissions", payload,
                              idempotency_key=f"skill-prepared-{key}"), ensure_ascii=False, indent=2))


def cmd_result(args) -> None:
    config = load_config()
    payload: dict = {"status": args.status}
    if args.submission_url:
        payload["submissionUrl"] = args.submission_url
    if args.message:
        payload["resultMessage"] = args.message
    if args.note:
        payload["note"] = args.note
    print(json.dumps(call_api(config, "PATCH", f"/api/v1/submissions/{args.submission_id}", payload),
                     ensure_ascii=False, indent=2))


def cmd_verify(args) -> None:
    config = load_config()
    payload: dict = {
        "taskId": args.task_id,
        "submissionId": args.submission_id,
        "sourceUrl": args.source_url,
        "targetUrl": args.target_url,
        "outcome": args.outcome,
        "checkedAt": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if args.anchor:
        payload["anchorText"] = args.anchor
    if args.rel:
        payload["linkRel"] = [item.strip() for item in args.rel.split(",") if item.strip()]
    if args.http_status:
        payload["httpStatus"] = args.http_status
    if args.message:
        payload["message"] = args.message
    key = datetime.now().strftime("%Y%m%d%H%M%S%f")
    print(json.dumps(call_api(config, "POST", "/api/v1/verifications", payload,
                              idempotency_key=f"skill-verify-{key}"), ensure_ascii=False, indent=2))


def cmd_ledger_set(args) -> None:
    ledger = load_ledger()
    entry = ledger["channels"].setdefault(args.key, {})
    entry["status"] = args.status
    if args.url:
        entry["url"] = args.url
    if args.note:
        entry["note"] = args.note
    entry["updated_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
    save_ledger(ledger)
    print(json.dumps({"key": args.key, **entry}, ensure_ascii=False, indent=2))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="外链提交技能 API 助手")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("config")
    p.set_defaults(func=cmd_config)

    p = sub.add_parser("projects")
    p.add_argument("--project", type=int, default=None, help="写入 project_id 到配置")
    p.set_defaults(func=cmd_projects)

    p = sub.add_parser("history")
    p.add_argument("--project", type=int, default=None)
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=cmd_history)

    p = sub.add_parser("check")
    p.add_argument("--project", type=int, default=None)
    p.add_argument("--url", required=True)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("plan")
    p.add_argument("--project", type=int, default=None)
    p.add_argument("--limit", type=int, default=5)
    p.add_argument("--tier", type=int, choices=(1, 2, 3), default=None)
    p.add_argument("--category", default=None)
    p.add_argument("--key", action="append", help="指定渠道 key，可重复")
    p.add_argument("--include-failed", action="store_true", help="允许重试 failed/unknown")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("task-create")
    p.add_argument("--project", type=int, default=None)
    p.add_argument("--url", required=True, help="渠道提交页 URL")
    p.add_argument("--workflow", default="directory",
                   choices=("directory", "blog_comment", "article", "guest_post", "forum", "other"))
    p.add_argument("--target-url", default=None)
    p.add_argument("--anchor", default=None)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_task_create)

    p = sub.add_parser("prepared")
    p.add_argument("--project", type=int, default=None, help="兼容批量脚本传入，实际以 task 归属为准")
    p.add_argument("--task-id", type=int, required=True)
    p.add_argument("--url", required=True, help="来源页 URL（与任务一致）")
    p.add_argument("--target", required=True, help="目标产品 URL（与任务一致）")
    p.add_argument("--workflow", default="directory")
    p.add_argument("--content", default=None)
    p.add_argument("--website", default=None)
    p.add_argument("--anchor", default=None)
    p.add_argument("--message", default=None)
    p.set_defaults(func=cmd_prepared)

    p = sub.add_parser("result")
    p.add_argument("--submission-id", type=int, required=True)
    p.add_argument("--status", required=True,
                   choices=("submitted", "pending", "duplicate", "rejected", "failed", "unknown"))
    p.add_argument("--submission-url", default=None)
    p.add_argument("--message", default=None)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_result)

    p = sub.add_parser("verify")
    p.add_argument("--task-id", type=int, required=True)
    p.add_argument("--submission-id", type=int, required=True)
    p.add_argument("--source-url", required=True)
    p.add_argument("--target-url", required=True)
    p.add_argument("--outcome", required=True,
                   choices=("active", "pending", "removed", "page_404", "link_missing", "unknown"))
    p.add_argument("--anchor", default=None)
    p.add_argument("--rel", default=None, help="逗号分隔，如 ugc,nofollow")
    p.add_argument("--http-status", type=int, default=None)
    p.add_argument("--message", default=None)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("ledger-set")
    p.add_argument("--key", required=True)
    p.add_argument("--status", required=True)
    p.add_argument("--url", default=None)
    p.add_argument("--note", default=None)
    p.set_defaults(func=cmd_ledger_set)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        args.func(args)
    except ApiError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

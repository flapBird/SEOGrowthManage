from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import get_settings
from .engine import process_pending_tasks
from ..keyword_discovery.pipeline import enrich_due_candidates, fetch_due_sources
from ..keyword_discovery.agent_queue import dispatch_due_to_agent, collect_agent_results


settings = get_settings()
scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
scheduler.add_job(
    process_pending_tasks,
    "interval",
    seconds=settings.scheduler_interval_seconds,
    id="process_pending_automation_tasks",
    replace_existing=True,
    max_instances=1,
    coalesce=True,
)
if settings.keyword_discovery_enabled:
    scheduler.add_job(
        fetch_due_sources,
        "interval",
        seconds=settings.keyword_fetch_interval_seconds,
        id="fetch_keyword_sources",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        enrich_due_candidates,
        "interval",
        seconds=settings.keyword_enrichment_interval_seconds,
        id="enrich_keyword_candidates",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
if settings.agent_integration_enabled:
    scheduler.add_job(
        dispatch_due_to_agent,
        "interval",
        seconds=settings.agent_dispatch_interval_seconds,
        id="dispatch_candidates_to_agent",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.add_job(
        collect_agent_results,
        "interval",
        seconds=settings.agent_collect_interval_seconds,
        id="collect_agent_results",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

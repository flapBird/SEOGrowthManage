from apscheduler.schedulers.asyncio import AsyncIOScheduler

from ..config import get_settings
from .engine import process_pending_tasks
from ..itch_radar.fetcher import run_radar_cycle


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
if settings.itch_radar_enabled:
    scheduler.add_job(
        run_radar_cycle,
        "interval",
        seconds=settings.itch_radar_poll_interval_seconds,
        id="poll_itch_radar",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )

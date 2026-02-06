"""APScheduler job definitions — daily trading pipeline triggers."""

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from src.pipeline.orchestrator import DailyPipelineOrchestrator

orchestrator = DailyPipelineOrchestrator()


def create_scheduler() -> BlockingScheduler:
    scheduler = BlockingScheduler(timezone="America/New_York")

    # 5:00 AM NY — Morning pipeline (Agents 1→2→3)
    scheduler.add_job(
        orchestrator.run_morning_pipeline,
        CronTrigger(hour=5, minute=0, day_of_week="mon-fri", timezone="America/New_York"),
        id="morning_pipeline",
        name="Morning Pipeline (5:00 AM)",
    )

    # 7:30 AM NY — Pre-market pipeline (Agent 4)
    scheduler.add_job(
        orchestrator.run_premarket_pipeline,
        CronTrigger(hour=7, minute=30, day_of_week="mon-fri", timezone="America/New_York"),
        id="premarket_pipeline",
        name="Pre-Market Pipeline (7:30 AM)",
    )

    # 10:00 AM NY — Trading pipeline (Agents 5→6 + execute)
    scheduler.add_job(
        orchestrator.run_trading_pipeline,
        CronTrigger(hour=10, minute=0, day_of_week="mon-fri", timezone="America/New_York"),
        id="trading_pipeline",
        name="Trading Pipeline (10:00 AM)",
    )

    # 10:15 AM NY — Start monitoring loop
    scheduler.add_job(
        orchestrator.run_monitor_loop,
        CronTrigger(hour=10, minute=15, day_of_week="mon-fri", timezone="America/New_York"),
        id="monitor_loop",
        name="Monitor Loop (10:15 AM)",
    )

    # 4:00 PM NY — EOD
    scheduler.add_job(
        orchestrator.run_eod,
        CronTrigger(hour=16, minute=0, day_of_week="mon-fri", timezone="America/New_York"),
        id="eod",
        name="End of Day (4:00 PM)",
    )

    return scheduler

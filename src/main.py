"""Trading Bot — Entry Point."""

import structlog

from src.config import settings
from src.db.models import Base
from src.db.session import engine

structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.make_filtering_bound_logger(0),
)

logger = structlog.get_logger()


def check_config():
    """Verify required configuration is set."""
    issues = []
    if not settings.llm_api_key:
        issues.append("LLM_API_KEY not set")
    if "password" in settings.database_url:
        issues.append("DATABASE_URL still has default password")
    if issues:
        for issue in issues:
            logger.warning("config_issue", issue=issue)
    return len(issues) == 0


def init_db():
    """Create all tables if they don't exist."""
    Base.metadata.create_all(engine)
    logger.info("database_initialized")


def main():
    logger.info("trading_bot_starting")
    check_config()
    init_db()

    from src.scheduler.jobs import create_scheduler

    scheduler = create_scheduler()
    logger.info("scheduler_ready", jobs=[job.name for job in scheduler.get_jobs()])

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("trading_bot_shutdown")


if __name__ == "__main__":
    main()

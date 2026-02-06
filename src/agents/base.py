import time
from abc import ABC, abstractmethod
from datetime import date

import structlog
from sqlalchemy.orm import Session

from src.db.models import AgentLog
from src.db.session import SessionLocal
from src.services.llm_client import call_llm, call_llm_json

logger = structlog.get_logger()


class BaseAgent(ABC):
    name: str = "base_agent"

    def run(self, input_data: dict) -> dict:
        start = time.time()
        log = logger.bind(agent=self.name)
        log.info("agent_start")

        try:
            result = self.execute(input_data)
            duration_ms = int((time.time() - start) * 1000)
            log.info("agent_success", duration_ms=duration_ms)
            self._log_to_db(input_data, result, "SUCCESS", duration_ms)
            return result
        except Exception as e:
            duration_ms = int((time.time() - start) * 1000)
            log.error("agent_error", error=str(e), duration_ms=duration_ms)
            self._log_to_db(input_data, None, "ERROR", duration_ms, str(e))
            raise

    @abstractmethod
    def execute(self, input_data: dict) -> dict:
        ...

    def call_llm(self, system_prompt: str, user_prompt: str) -> str:
        return call_llm(system_prompt, user_prompt)

    def call_llm_json(self, system_prompt: str, user_prompt: str) -> dict:
        return call_llm_json(system_prompt, user_prompt)

    def _log_to_db(
        self,
        input_data: dict,
        output_data: dict | None,
        status: str,
        duration_ms: int,
        error_message: str | None = None,
    ):
        try:
            session = SessionLocal()
            log_entry = AgentLog(
                agent_name=self.name,
                run_date=date.today(),
                input_data=input_data,
                output_data=output_data,
                status=status,
                duration_ms=duration_ms,
                error_message=error_message,
            )
            session.add(log_entry)
            session.commit()
            session.close()
        except Exception as e:
            logger.warning("agent_log_db_error", error=str(e))

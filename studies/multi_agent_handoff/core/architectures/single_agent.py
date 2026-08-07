import uuid
from datetime import datetime, timezone
from typing import Dict, Any, List

from core.trace import TraceLogger, TraceEvent
from core.agent import Agent
from core.tools.ticketing import TicketingSystem
from core.tools.mock_api import MockCustomerAPI
from core.providers import ModelProvider

class SingleAgentArchitecture:
    def __init__(self, provider: ModelProvider, trace_filepath: str, db_path: str = ":memory:", api_failure_rate: float = 0.0, api_rate_limit_prob: float = 0.0):
        self.trace_logger = TraceLogger(trace_filepath)
        self.run_id = str(uuid.uuid4())
        
        self.ticketing_tool = TicketingSystem(db_path=db_path)
        self.mock_api_tool = MockCustomerAPI(failure_rate=api_failure_rate, rate_limit_prob=api_rate_limit_prob)
        
        self.agent = Agent(
            provider=provider,
            system_prompt=(
                "You are an AI assistant designed to solve customer support escalations. "
                "You have access to a Mock Customer API and a Ticketing System. "
                "If a tool fails with an error like a Rate Limit or Timeout, you should retry "
                "your tool call or handle it gracefully."
            ),
            tools_providers=[self.ticketing_tool, self.mock_api_tool],
            max_iterations=15,
            trace_logger=self.trace_logger,
            run_id=self.run_id
        )

    def run_task(self, prompt: str) -> str:
        run_start_id = str(uuid.uuid4())
        self.trace_logger.log(TraceEvent(
            event_id=run_start_id,
            timestamp=datetime.now(timezone.utc).isoformat(),
            event_type="run_start",
            payload={"architecture": "single_agent", "task_prompt": prompt},
            metadata={"run_id": self.run_id}
        ))
        
        result = self.agent.run(prompt, parent_event_id=run_start_id)
        return result

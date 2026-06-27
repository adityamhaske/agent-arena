import uuid
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

from core.trace import TraceLogger, TraceEvent
from core.agent import Agent
from core.tools.ticketing import TicketingSystem
from core.tools.mock_api import MockCustomerAPI
from core.providers import ModelProvider


class PeerToPeerArchitecture:
    """
    Two peer agents collaborate via a shared message bus (a Python list).

    - Agent A (CRM Peer): handles CRM lookups. Has access to get_customer_profile.
    - Agent B (Ticketing Peer): handles ticketing. Has access to search_tickets,
      get_ticket, update_ticket, create_ticket.

    The flow:
    1. Agent A receives the original task prompt.
    2. Agent A does its CRM work, then hands off a structured message to Agent B
       via the shared bus.
    3. Agent B receives the handoff message (containing CRM context) plus the
       original task and completes the ticketing work.
    4. Agent B's final output is the architecture's final result.

    Each agent runs a full ReAct loop with its own tools. The shared bus is
    appended to each agent's context as a user message before it runs.

    Extra trace event types:
    - 'peer_handoff': emitted when Agent A passes context to Agent B.
    """

    def __init__(
        self,
        provider: ModelProvider,
        trace_filepath: str,
        db_path: str = ":memory:",
        api_failure_rate: float = 0.0,
        api_rate_limit_prob: float = 0.0,
    ):
        self.trace_logger = TraceLogger(trace_filepath)
        self.run_id = str(uuid.uuid4())

        self.ticketing_tool = TicketingSystem(db_path=db_path)
        self.mock_api_tool = MockCustomerAPI(
            failure_rate=api_failure_rate, rate_limit_prob=api_rate_limit_prob
        )
        self.provider = provider

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _log(self, event_type: str, payload: Dict, parent_id: str = None) -> str:
        event_id = str(uuid.uuid4())
        self.trace_logger.log(
            TraceEvent(
                event_id=event_id,
                parent_event_id=parent_id,
                timestamp=self._now(),
                event_type=event_type,
                payload=payload,
                metadata={"run_id": self.run_id},
            )
        )
        return event_id

    def run_task(self, prompt: str) -> str:
        run_start_id = self._log(
            "run_start",
            {"architecture": "peer_to_peer", "task_prompt": prompt},
        )

        # --- Agent A: CRM Peer ---
        agent_a_system = (
            "You are the CRM Peer Agent in a two-agent pipeline. "
            "Your responsibility is to look up customer information using the get_customer_profile tool. "
            "Once you have retrieved the customer profile, produce a structured handoff message "
            "in this exact format:\n"
            "HANDOFF: customer_id=<id>, tier=<tier>, name=<name>, status=<status>\n"
            "Do not attempt any ticketing operations — that is handled by your peer."
        )

        agent_a = Agent(
            provider=self.provider,
            system_prompt=agent_a_system,
            tools_providers=[self.mock_api_tool],
            max_iterations=10,
            trace_logger=self.trace_logger,
            run_id=self.run_id,
        )

        agent_a_result = agent_a.run(prompt, parent_event_id=run_start_id)

        # Emit the peer handoff event
        handoff_id = self._log(
            "peer_handoff",
            {
                "from_agent": "crm_peer",
                "to_agent": "ticketing_peer",
                "handoff_message": agent_a_result,
            },
            parent_id=run_start_id,
        )

        # --- Agent B: Ticketing Peer ---
        agent_b_system = (
            "You are the Ticketing Peer Agent in a two-agent pipeline. "
            "Your peer (the CRM Agent) has already looked up the customer and is passing you the result. "
            "Your responsibility is to find the customer's open ticket in the ticketing system, "
            "update its tier to match the customer's tier, and set its status to 'escalated'. "
            "Use only the ticketing tools available to you."
        )

        # Construct the prompt for Agent B: original task + handoff context
        agent_b_prompt = (
            f"Original task: {prompt.strip()}\n\n"
            f"Context from CRM Peer: {agent_a_result}"
        )

        agent_b = Agent(
            provider=self.provider,
            system_prompt=agent_b_system,
            tools_providers=[self.ticketing_tool],
            max_iterations=10,
            trace_logger=self.trace_logger,
            run_id=self.run_id,
        )

        agent_b_result = agent_b.run(agent_b_prompt, parent_event_id=handoff_id)

        self._log(
            "run_finish",
            {"architecture": "peer_to_peer", "final_output": agent_b_result},
            parent_id=run_start_id,
        )

        return agent_b_result

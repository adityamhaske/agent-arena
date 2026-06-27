import uuid
import json
from datetime import datetime, timezone
from typing import Dict, Any

from core.trace import TraceLogger, TraceEvent
from core.agent import Agent
from core.tools.ticketing import TicketingSystem
from core.tools.mock_api import MockCustomerAPI
from core.providers import ModelProvider


class DebateCriticArchitecture:
    """
    A three-phase architecture:
    1. Proposer Agent: attempts to solve the full task (has all tools).
       Produces a draft answer and its full tool-call sequence.
    2. Critic Agent: receives the task, the proposer's draft answer, and
       the full list of tool calls made — reviews for mistakes, omissions,
       or wrong values. Produces a structured critique.
    3. Proposer Agent (revision round): receives the original task, its
       own previous answer, and the critic's critique. Revises the answer
       and performs any corrective tool calls.

    Extra trace event types:
    - 'critic_review': the critic's structured critique
    - 'revision_start': the start of the proposer's revision round
    - 'revision_finish': the final revised output
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

    def _extract_tool_call_summary(self, trace_filepath: str, run_id: str) -> str:
        """
        Build a readable summary of tool calls and results for the critic.
        Reads the trace file flat (no DAG reconstruction) so it works correctly
        mid-run and avoids the DAG flatten bug.
        """
        import json as _json
        try:
            all_events = []
            with open(trace_filepath, 'r') as f:
                for line in f:
                    line = line.strip()
                    if line:
                        all_events.append(_json.loads(line))
        except Exception:
            return "(unable to read trace)"

        # Index tool_calls by their tool_call_id
        tool_calls = {}
        for e in all_events:
            if e.get("event_type") == "tool_call":
                call_id = e["payload"].get("tool_call_id")
                if call_id:
                    tool_calls[call_id] = e

        lines = []
        for e in all_events:
            if e.get("event_type") == "tool_result":
                call_id = e["payload"].get("tool_call_id")
                tc = tool_calls.get(call_id)
                if tc:
                    args = tc["payload"].get("arguments", {})
                    result = e["payload"].get("result", "")
                    error = e["payload"].get("error", False)
                    lines.append(
                        f"- {tc['payload']['tool_name']}({args}) → "
                        + (f"ERROR: {result}" if error else str(result))
                    )
        return "\n".join(lines) if lines else "(no tool calls recorded)"


    def run_task(self, prompt: str) -> str:
        # Store trace filepath for critic to read
        import os
        trace_filepath = self.trace_logger.filepath

        run_start_id = self._log(
            "run_start",
            {"architecture": "debate_critic", "task_prompt": prompt},
        )

        proposer_system = (
            "You are a Proposer Agent solving a customer support escalation task. "
            "Use the available tools to complete the task fully. "
            "Your answer will be reviewed by a Critic — be thorough and accurate."
        )

        # === Phase 1: Proposer initial attempt ===
        proposer = Agent(
            provider=self.provider,
            system_prompt=proposer_system,
            tools_providers=[self.mock_api_tool, self.ticketing_tool],
            max_iterations=12,
            trace_logger=self.trace_logger,
            run_id=self.run_id,
        )

        draft_answer = proposer.run(prompt, parent_event_id=run_start_id)

        # Gather tool call summary from trace for critic context
        tool_summary = self._extract_tool_call_summary(trace_filepath, self.run_id)

        # === Phase 2: Critic review ===
        critic_system = (
            "You are a Critic Agent reviewing the work of a Proposer Agent on a customer support task. "
            "You will receive: (1) the original task, (2) the proposer's final answer, "
            "and (3) a log of every tool call made and its actual result.\n\n"
            "Your job is to cross-check the proposer's CLAIMED outcome against the actual tool call RESULTS. "
            "Specifically:\n"
            "- If the proposer claims a customer has tier=X, verify that get_customer_profile actually returned tier=X.\n"
            "- If the proposer claims a ticket was updated, verify that update_ticket returned status='updated'.\n"
            "- If the proposer claims a step was completed but no corresponding tool call is in the log, flag it as a hallucination.\n"
            "- If any tool call returned an ERROR and the proposer did not mention it or retry it, flag it.\n"
            "- If all values in the proposer's answer match the tool results and all required steps are complete, "
            "say exactly: 'LGTM: no issues found.'\n\n"
            "Be specific — quote the exact discrepancy (e.g. 'tool returned tier=basic but proposer claimed tier=enterprise')."
        )

        critic_prompt = (
            f"ORIGINAL TASK:\n{prompt.strip()}\n\n"
            f"PROPOSER'S ANSWER:\n{draft_answer}\n\n"
            f"TOOL CALLS MADE:\n{tool_summary}\n\n"
            "Review the above and provide your critique."
        )

        # Critic runs without tools — it only reasons
        critic = Agent(
            provider=self.provider,
            system_prompt=critic_system,
            tools_providers=[],
            max_iterations=3,
            trace_logger=self.trace_logger,
            run_id=self.run_id,
        )

        critic_output = critic.run(critic_prompt, parent_event_id=run_start_id)

        critic_review_id = self._log(
            "critic_review",
            {
                "draft_answer": draft_answer,
                "tool_summary": tool_summary,
                "critique": critic_output,
            },
            parent_id=run_start_id,
        )

        # === Phase 3: Proposer revision ===
        revision_start_id = self._log(
            "revision_start",
            {"critique": critic_output},
            parent_id=run_start_id,
        )

        revision_prompt = (
            f"ORIGINAL TASK:\n{prompt.strip()}\n\n"
            f"YOUR PREVIOUS ANSWER:\n{draft_answer}\n\n"
            f"CRITIC'S REVIEW:\n{critic_output}\n\n"
            "Address the critic's concerns. If corrections require tool calls, make them. "
            "Then provide your final, revised answer."
        )

        proposer_v2 = Agent(
            provider=self.provider,
            system_prompt=proposer_system,
            tools_providers=[self.mock_api_tool, self.ticketing_tool],
            max_iterations=8,
            trace_logger=self.trace_logger,
            run_id=self.run_id,
        )

        final_answer = proposer_v2.run(revision_prompt, parent_event_id=revision_start_id)

        self._log(
            "revision_finish",
            {"final_output": final_answer},
            parent_id=revision_start_id,
        )

        self._log(
            "run_finish",
            {"architecture": "debate_critic", "final_output": final_answer},
            parent_id=run_start_id,
        )

        return final_answer

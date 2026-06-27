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
        Build a readable summary of tool calls and results so far for the critic.
        Reads the current trace file and extracts tool_call/tool_result pairs.
        """
        from core.trace import TraceLogger
        try:
            events = TraceLogger.reconstruct_dag(trace_filepath)
        except Exception:
            return "(unable to read trace)"

        # Flatten DAG back to list for easy filtering
        all_events = []
        def flatten(evts):
            for e in evts:
                all_events.append(e)
                flatten(e.get("children", []))
        flatten(events)

        lines = []
        tool_calls = {e["event_id"]: e for e in all_events if e.get("event_type") == "tool_call"}
        tool_results = [e for e in all_events if e.get("event_type") == "tool_result"]

        for tr in tool_results:
            call_id = tr["payload"].get("tool_call_id", "?")
            tc = next((v for v in tool_calls.values() if v["payload"].get("tool_call_id") == call_id), None)
            if tc:
                args = tc["payload"].get("arguments", {})
                result = tr["payload"].get("result", "")
                error = tr["payload"].get("error", False)
                lines.append(
                    f"- {tc['payload']['tool_name']}({args}) → "
                    + (f"ERROR: {result}" if error else f"{result}")
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
            "You are a Critic Agent reviewing the work of a Proposer Agent. "
            "You will receive: the original task, the proposer's answer, and a log of tool calls made. "
            "Identify any mistakes, missing steps, wrong values, or unresolved tool errors. "
            "Be specific — point to exactly what is wrong and what the correct action should be. "
            "If the answer is fully correct, say 'LGTM: no issues found.'"
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

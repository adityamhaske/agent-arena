import uuid
import json
from datetime import datetime, timezone
from typing import List, Dict, Any

from core.trace import TraceLogger, TraceEvent
from core.agent import Agent
from core.tools.ticketing import TicketingSystem
from core.tools.mock_api import MockCustomerAPI
from core.providers import ModelProvider


class SupervisorWorkerArchitecture:
    """
    A two-tier architecture:
    - Supervisor agent: receives the task, decomposes it into sub-tasks,
      delegates them to specialized worker agents, and assembles a final answer.
    - Worker A (CRM Worker): has access only to the MockCustomerAPI tool.
    - Worker B (Ticketing Worker): has access only to the TicketingSystem tools.

    The Supervisor calls workers by issuing special tool calls ('delegate_to_crm_worker'
    and 'delegate_to_ticketing_worker'). Each worker runs its own inner ReAct loop
    and returns a result string. The Supervisor sees only the result, not the
    worker's internal trace events, though all events are logged to the same trace
    file with correct parent_event_id relationships.

    Extra trace event types produced by this architecture:
    - 'supervisor_start', 'supervisor_finish'
    - 'worker_start', 'worker_finish'
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

        # Build supervisor's "tool" schema — these are virtual tools that
        # the supervisor uses to delegate to workers.
        self._delegation_schema = [
            {
                "name": "delegate_to_crm_worker",
                "description": (
                    "Delegate a CRM lookup sub-task to the CRM Worker agent. "
                    "The worker has access to get_customer_profile only. "
                    "Provide a clear instruction for what to retrieve."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": "The exact sub-task for the CRM worker to perform.",
                        }
                    },
                    "required": ["instruction"],
                },
            },
            {
                "name": "delegate_to_ticketing_worker",
                "description": (
                    "Delegate a ticketing sub-task to the Ticketing Worker agent. "
                    "The worker has access to search_tickets, get_ticket, update_ticket, create_ticket. "
                    "Provide all context the worker needs (e.g. customer ID, tier, desired status)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "instruction": {
                            "type": "string",
                            "description": "The exact sub-task for the Ticketing worker to perform.",
                        }
                    },
                    "required": ["instruction"],
                },
            },
        ]

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

    def _run_worker(
        self,
        worker_name: str,
        instruction: str,
        tools_providers: List[Any],
        parent_event_id: str,
    ) -> str:
        """Run a worker agent and return its final text output."""
        worker_start_id = self._log(
            "worker_start",
            {
                "worker": worker_name,
                "instruction": instruction,
                "model": self.provider.model_name,
                "provider": self.provider.provider_name,
            },
            parent_id=parent_event_id,
        )

        worker = Agent(
            provider=self.provider,
            system_prompt=(
                f"You are a specialized {worker_name}. "
                "Perform only the specific sub-task you are given using only the tools available to you. "
                "Return a concise summary of what you did and what you found. "
                "If a tool fails with a transient error (rate limit, timeout), retry it."
            ),
            tools_providers=tools_providers,
            max_iterations=10,
            trace_logger=self.trace_logger,
            run_id=self.run_id,
        )

        result = worker.run(instruction, parent_event_id=worker_start_id)

        self._log(
            "worker_finish",
            {"worker": worker_name, "result": result},
            parent_id=worker_start_id,
        )
        return result

    def run_task(self, prompt: str) -> str:
        run_start_id = self._log(
            "run_start",
            {"architecture": "supervisor_worker", "task_prompt": prompt},
        )
        supervisor_start_id = self._log(
            "supervisor_start",
            {
                "prompt": prompt,
                "model": self.provider.model_name,
                "provider": self.provider.provider_name,
            },
            parent_id=run_start_id,
        )

        # The supervisor runs its own ReAct loop but its "tools" are delegation
        # calls, which we intercept ourselves.
        messages = [{"role": "user", "content": prompt}]
        supervisor_system = (
            "You are a Supervisor Agent coordinating a customer support escalation. "
            "You have two worker agents available: a CRM Worker (can look up customer profiles) "
            "and a Ticketing Worker (can search, view, and update support tickets). "
            "Break the task into sub-tasks, delegate each to the right worker, then compose "
            "a final answer from the workers' results. "
            "Do not perform any lookups yourself — always delegate."
        )

        max_supervisor_iterations = 10
        for iteration in range(max_supervisor_iterations):
            llm_call_id = self._log(
                "llm_call",
                {
                    "messages": messages,
                    "provider": self.provider.provider_name,
                    "model": self.provider.model_name,
                    "role": "supervisor",
                },
                parent_id=supervisor_start_id,
            )

            try:
                response = self.provider.send_message(
                    messages, self._delegation_schema, supervisor_system
                )
            except Exception as e:
                import traceback
                self._log(
                    "error",
                    {
                        "error_type": type(e).__name__,
                        "message": str(e),
                        "traceback": traceback.format_exc(),
                    },
                    parent_id=llm_call_id,
                )
                return f"Error calling LLM (supervisor): {str(e)}"

            # Log supervisor LLM response
            assistant_msg = {"role": "assistant"}
            if response.text:
                assistant_msg["text"] = response.text
            if response.tool_calls:
                assistant_msg["tool_calls"] = [
                    {"id": tc.id, "name": tc.name, "arguments": tc.arguments}
                    for tc in response.tool_calls
                ]
            messages.append(assistant_msg)

            self._log(
                "llm_response",
                {
                    "stop_reason": response.stop_reason,
                    "tool_calls": assistant_msg.get("tool_calls", []),
                    "text": response.text,
                    "usage": response.usage,
                    "role": "supervisor",
                },
                parent_id=llm_call_id,
            )

            if response.stop_reason == "tool_use" or response.tool_calls:
                tool_results = []
                for tc in response.tool_calls:
                    delegation_id = self._log(
                        "tool_call",
                        {
                            "tool_name": tc.name,
                            "tool_call_id": tc.id,
                            "arguments": tc.arguments,
                            "role": "supervisor_delegation",
                        },
                        parent_id=supervisor_start_id,
                    )

                    instruction = tc.arguments.get("instruction", "")
                    is_error = False

                    if tc.name == "delegate_to_crm_worker":
                        worker_result = self._run_worker(
                            "CRM Worker",
                            instruction,
                            [self.mock_api_tool],
                            parent_event_id=delegation_id,
                        )
                    elif tc.name == "delegate_to_ticketing_worker":
                        worker_result = self._run_worker(
                            "Ticketing Worker",
                            instruction,
                            [self.ticketing_tool],
                            parent_event_id=delegation_id,
                        )
                    else:
                        worker_result = f"Unknown delegation target: {tc.name}"
                        is_error = True

                    self._log(
                        "tool_result",
                        {
                            "tool_call_id": tc.id,
                            "tool_name": tc.name,
                            "result": worker_result,
                            "error": is_error,
                            "role": "supervisor_delegation",
                        },
                        parent_id=delegation_id,
                    )

                    tool_results.append(
                        {
                            "type": "tool_result",
                            "tool_call_id": tc.id,
                            "tool_name": tc.name,
                            "content": worker_result,
                            "is_error": is_error,
                        }
                    )

                messages.append({"role": "user", "content": tool_results})

            else:
                final_text = response.text
                self._log(
                    "supervisor_finish",
                    {"final_output": final_text},
                    parent_id=supervisor_start_id,
                )
                return final_text

        return "Error: Supervisor reached max iterations without finishing."

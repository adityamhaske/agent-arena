import uuid
import json
import traceback
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from .trace import TraceLogger, TraceEvent
from .providers import ModelProvider

class Agent:
    def __init__(self, 
                 provider: ModelProvider,
                 system_prompt: str = "You are a helpful assistant.",
                 tools_providers: List[Any] = None,
                 max_iterations: int = 10,
                 trace_logger: Optional[TraceLogger] = None,
                 run_id: str = None):
        self.provider = provider
        self.system_prompt = system_prompt
        self.tools_providers = tools_providers or []
        self.max_iterations = max_iterations
        self.trace_logger = trace_logger
        self.run_id = run_id or str(uuid.uuid4())
        
        self.generic_tools = []
        for tp in self.tools_providers:
            self.generic_tools.extend(tp.get_json_schema())
            
    def _get_provider_for_tool(self, tool_name: str) -> Any:
        for provider in self.tools_providers:
            for t in provider.get_json_schema():
                if t['name'] == tool_name:
                    return provider
        return None

    def _now(self):
        return datetime.now(timezone.utc).isoformat()

    def run(self, prompt: str, parent_event_id: str = None) -> str:
        messages = [{"role": "user", "content": prompt}]
        
        agent_start_id = str(uuid.uuid4())
        if self.trace_logger:
            self.trace_logger.log(TraceEvent(
                event_id=agent_start_id,
                parent_event_id=parent_event_id,
                timestamp=self._now(),
                event_type="agent_start",
                payload={"prompt": prompt, "model": self.provider.model_name, "provider": self.provider.provider_name},
                metadata={"run_id": self.run_id}
            ))
            
        current_parent_id = agent_start_id
        
        for iteration in range(self.max_iterations):
            llm_call_id = str(uuid.uuid4())
            if self.trace_logger:
                self.trace_logger.log(TraceEvent(
                    event_id=llm_call_id,
                    parent_event_id=current_parent_id,
                    timestamp=self._now(),
                    event_type="llm_call",
                    payload={"messages": messages, "provider": self.provider.provider_name, "model": self.provider.model_name},
                    metadata={"run_id": self.run_id}
                ))
            
            try:
                response = self.provider.send_message(messages, self.generic_tools, self.system_prompt)
            except Exception as e:
                if self.trace_logger:
                    self.trace_logger.log(TraceEvent(
                        event_id=str(uuid.uuid4()),
                        parent_event_id=llm_call_id,
                        timestamp=self._now(),
                        event_type="error",
                        payload={"error_type": type(e).__name__, "message": str(e), "traceback": traceback.format_exc()},
                        metadata={"run_id": self.run_id}
                    ))
                return f"Error calling LLM: {str(e)}"
                
            assistant_msg = {"role": "assistant"}
            if response.text:
                assistant_msg["text"] = response.text
            if response.tool_calls:
                assistant_msg["tool_calls"] = [{"id": tc.id, "name": tc.name, "arguments": tc.arguments} for tc in response.tool_calls]
            messages.append(assistant_msg)
            
            if self.trace_logger:
                self.trace_logger.log(TraceEvent(
                    event_id=str(uuid.uuid4()),
                    parent_event_id=llm_call_id,
                    timestamp=self._now(),
                    event_type="llm_response",
                    payload={"stop_reason": response.stop_reason, "tool_calls": assistant_msg.get("tool_calls", []), "text": response.text, "usage": response.usage},
                    metadata={"run_id": self.run_id}
                ))

            if response.stop_reason == "tool_use" or response.tool_calls:
                tool_results = []
                
                for tc in response.tool_calls:
                    tool_call_id = str(uuid.uuid4())
                    
                    if self.trace_logger:
                        self.trace_logger.log(TraceEvent(
                            event_id=tool_call_id,
                            parent_event_id=current_parent_id,
                            timestamp=self._now(),
                            event_type="tool_call",
                            payload={"tool_name": tc.name, "tool_call_id": tc.id, "arguments": tc.arguments},
                            metadata={"run_id": self.run_id}
                        ))
                        
                    provider = self._get_provider_for_tool(tc.name)
                    is_error = False
                    
                    try:
                        if not provider:
                            raise ValueError(f"Tool {tc.name} not found")
                        result = provider.execute_tool(tc.name, tc.arguments)
                    except Exception as e:
                        result = f"Error executing tool: {type(e).__name__}: {str(e)}"
                        is_error = True
                        
                    if self.trace_logger:
                        self.trace_logger.log(TraceEvent(
                            event_id=str(uuid.uuid4()),
                            parent_event_id=tool_call_id,
                            timestamp=self._now(),
                            event_type="tool_result",
                            payload={"tool_call_id": tc.id, "tool_name": tc.name, "result": result, "error": is_error},
                            metadata={"run_id": self.run_id}
                        ))
                        
                    tool_results.append({
                        "type": "tool_result",
                        "tool_call_id": tc.id,
                        "tool_name": tc.name,
                        "content": json.dumps(result) if not isinstance(result, str) else result,
                        "is_error": is_error
                    })
                    
                messages.append({"role": "user", "content": tool_results})
            else:
                final_text = response.text
                if self.trace_logger:
                    self.trace_logger.log(TraceEvent(
                        event_id=str(uuid.uuid4()),
                        parent_event_id=agent_start_id,
                        timestamp=self._now(),
                        event_type="agent_finish",
                        payload={"final_output": final_text},
                        metadata={"run_id": self.run_id}
                    ))
                return final_text
                
        return "Error: Max iterations reached."

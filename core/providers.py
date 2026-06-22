import os
import uuid
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

import anthropic
import google.generativeai as genai
from google.generativeai.types import content_types
import google.api_core.exceptions

from tenacity import retry, wait_exponential, stop_after_attempt, retry_if_exception_type

@dataclass
class NormalizedToolCall:
    id: str
    name: str
    arguments: Dict[str, Any]

@dataclass
class NormalizedResponse:
    text: str
    tool_calls: List[NormalizedToolCall]
    stop_reason: str
    usage: Dict[str, int]

class ModelProvider(ABC):
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.provider_name = "abstract"

    @abstractmethod
    def send_message(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], system_prompt: str) -> NormalizedResponse:
        pass


class AnthropicProvider(ModelProvider):
    def __init__(self, model_name: str = "claude-sonnet-4-6", api_key: str = None):
        super().__init__(model_name)
        self.provider_name = "anthropic"
        self.client = anthropic.Anthropic(api_key=api_key or os.environ.get("ANTHROPIC_API_KEY", "dummy_key"))

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((anthropic.RateLimitError, anthropic.APIConnectionError, anthropic.InternalServerError))
    )
    def _call_api(self, **kwargs):
        return self.client.messages.create(**kwargs)

    def _convert_schema(self, generic_tool: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "name": generic_tool["name"],
            "description": generic_tool["description"],
            "input_schema": generic_tool["parameters"]
        }

    def send_message(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], system_prompt: str) -> NormalizedResponse:
        anthropic_messages = []
        for msg in messages:
            if msg["role"] == "user":
                if isinstance(msg["content"], str):
                    anthropic_messages.append({"role": "user", "content": msg["content"]})
                else:
                    content = []
                    for item in msg["content"]:
                        if item["type"] == "tool_result":
                            content.append({
                                "type": "tool_result",
                                "tool_use_id": item["tool_call_id"],
                                "content": item["content"],
                                "is_error": item["is_error"]
                            })
                        else:
                            content.append(item)
                    anthropic_messages.append({"role": "user", "content": content})
            elif msg["role"] == "assistant":
                content = []
                if "text" in msg and msg["text"]:
                    content.append({"type": "text", "text": msg["text"]})
                if "tool_calls" in msg and msg["tool_calls"]:
                    for tc in msg["tool_calls"]:
                        content.append({
                            "type": "tool_use",
                            "id": tc["id"],
                            "name": tc["name"],
                            "input": tc["arguments"]
                        })
                if not content:
                    content.append({"type": "text", "text": " "})
                anthropic_messages.append({"role": "assistant", "content": content})

        anthropic_tools = [self._convert_schema(t) for t in tools]
        
        response = self._call_api(
            model=self.model_name,
            max_tokens=1024,
            system=system_prompt,
            messages=anthropic_messages,
            tools=anthropic_tools if anthropic_tools else None
        )
        
        text = ""
        tool_calls = []
        
        for block in response.content:
            if block.type == "text":
                text += block.text
            elif block.type == "tool_use":
                tool_calls.append(NormalizedToolCall(
                    id=block.id,
                    name=block.name,
                    arguments=block.input
                ))
                
        return NormalizedResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=response.stop_reason,
            usage={"input": response.usage.input_tokens, "output": response.usage.output_tokens}
        )

class GeminiProvider(ModelProvider):
    def __init__(self, model_name: str = "gemini-1.5-pro", api_key: str = None):
        super().__init__(model_name)
        self.provider_name = "gemini"
        if api_key or os.environ.get("GEMINI_API_KEY"):
            genai.configure(api_key=api_key or os.environ.get("GEMINI_API_KEY"))

    @retry(
        wait=wait_exponential(multiplier=1, min=2, max=60),
        stop=stop_after_attempt(5),
        retry=retry_if_exception_type((google.api_core.exceptions.ResourceExhausted, google.api_core.exceptions.ServiceUnavailable, google.api_core.exceptions.InternalServerError))
    )
    def _call_api(self, model, contents, tools):
        return model.generate_content(contents, tools=tools)

    def send_message(self, messages: List[Dict[str, Any]], tools: List[Dict[str, Any]], system_prompt: str) -> NormalizedResponse:
        gemini_messages = []
        for msg in messages:
            if msg["role"] == "user":
                if isinstance(msg["content"], str):
                    gemini_messages.append({"role": "user", "parts": [msg["content"]]})
                else:
                    parts = []
                    for item in msg["content"]:
                        if item["type"] == "tool_result":
                            content_dict = {"result": item["content"]}
                            if item["is_error"]:
                                content_dict["error"] = True
                            parts.append(content_types.Part.from_function_response(name=item["tool_name"], response=content_dict))
                    if parts:
                        gemini_messages.append({"role": "user", "parts": parts})
            elif msg["role"] == "assistant":
                parts = []
                if "text" in msg and msg["text"]:
                    parts.append(msg["text"])
                if "tool_calls" in msg and msg["tool_calls"]:
                    for tc in msg["tool_calls"]:
                        parts.append(content_types.Part.from_function_call(name=tc["name"], args=tc["arguments"]))
                if parts:
                    gemini_messages.append({"role": "model", "parts": parts})
                    
        model = genai.GenerativeModel(model_name=self.model_name, system_instruction=system_prompt)
        gemini_tools = [{"function_declarations": tools}] if tools else None

        response = self._call_api(model, gemini_messages, gemini_tools)
        
        text = ""
        tool_calls = []
        
        for part in response.parts:
            if part.text:
                text += part.text
            elif part.function_call:
                tool_calls.append(NormalizedToolCall(
                    id=str(uuid.uuid4()),
                    name=part.function_call.name,
                    arguments=dict(part.function_call.args)
                ))
                
        usage = {"input": 0, "output": 0}
        if response.usage_metadata:
            usage["input"] = response.usage_metadata.prompt_token_count
            usage["output"] = response.usage_metadata.candidates_token_count
            
        stop_reason = "stop"
        if tool_calls:
            stop_reason = "tool_use"
            
        return NormalizedResponse(
            text=text,
            tool_calls=tool_calls,
            stop_reason=stop_reason,
            usage=usage
        )

"""Provider-neutral tools exposed to the realtime voice model.

Tool semantics and Qwen compatibility aliases are adapted from
QwenAudio/qwen-audio-agent ``server/src/voice/frontend-tools.mjs`` at commit
``c66cde03e9946e3cc8503cb917d9cd0ee7712989``. Qwen Audio Agent is licensed
under Apache-2.0. See ``docs/third-party/qwen-audio-agent.md``.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any, Protocol


@dataclass(frozen=True)
class VoiceToolContext:
    owner_id: str
    voice_session_id: str
    tool_call_id: str | None = None


class HermesFrontstagePort(Protocol):
    async def memory(self, request: dict[str, Any], context: VoiceToolContext) -> Any: ...

    async def spawn_work(self, request: dict[str, Any], context: VoiceToolContext) -> Any: ...

    async def get_work_status(self, request: dict[str, Any], context: VoiceToolContext) -> Any: ...

    async def cancel_work(self, request: dict[str, Any], context: VoiceToolContext) -> Any: ...

    async def respond_to_work_permission(
        self, request: dict[str, Any], context: VoiceToolContext
    ) -> Any: ...


def _object_schema(properties: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": properties,
        "additionalProperties": False,
    }
    if required:
        schema["required"] = required
    return schema


FRONTSTAGE_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "memory",
            "description": "Read durable Hermes user context. This tool is read-only.",
            "parameters": _object_schema(
                {
                    "document": {"type": "string", "enum": ["all", "user", "memory"]},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "spawn_work",
            "description": (
                "Delegate substantive or durable work to Hermes without blocking the "
                "realtime voice conversation. Accepted means queued, not completed."
            ),
            "parameters": _object_schema(
                {
                    "objective": {"type": "string"},
                    "input_refs": {
                        "type": "array",
                        "items": {"type": "string"},
                        "maxItems": 8,
                    },
                },
                ["objective"],
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_work_status",
            "description": "Read the status or current result of previously delegated Hermes Work.",
            "parameters": _object_schema(
                {
                    "work_id": {"type": "string"},
                    "question": {"type": "string"},
                    "list_all": {"type": "boolean"},
                }
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "cancel_work",
            "description": "Cancel one or all cancellable Hermes Work items from this voice session.",
            "parameters": _object_schema(
                {"work_id": {"type": "string"}, "all": {"type": "boolean"}}
            ),
        },
    },
    {
        "type": "function",
        "function": {
            "name": "respond_to_work_permission",
            "description": "Answer a pending permission request from delegated Hermes Work.",
            "parameters": _object_schema(
                {
                    "authorization_id": {"type": "string"},
                    "decision": {"type": "string", "enum": ["always", "reject"]},
                },
                ["authorization_id", "decision"],
            ),
        },
    },
]


_ALIASES = {
    "memory": "memory",
    "spawn_work": "spawn_work",
    "spawn_thinking": "spawn_work",
    "get_work_status": "get_work_status",
    "get_agent_task_status": "get_work_status",
    "cancel_work": "cancel_work",
    "cancel_agent_task": "cancel_work",
    "respond_to_work_permission": "respond_to_work_permission",
    "respond_agent_permission": "respond_to_work_permission",
}


def _optional_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _required_string(value: Any, field: str) -> str:
    result = _optional_string(value)
    if result is None:
        raise ValueError(f"Realtime frontstage tool requires {field}")
    return result


def _string_list(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    items = [item.strip() for item in value if isinstance(item, str) and item.strip()]
    return items or None


class FrontstageToolRouter:
    def __init__(self, hermes: HermesFrontstagePort) -> None:
        self._hermes = hermes

    async def execute(self, call: dict[str, Any], context: VoiceToolContext) -> Any:
        raw_name = str(call.get("name") or "").strip().lower()
        name = _ALIASES.get(raw_name)
        arguments = call.get("arguments")
        args = arguments if isinstance(arguments, dict) else {}
        call_id = _optional_string(call.get("call_id"))
        if call_id:
            context = replace(context, tool_call_id=call_id)

        if name == "memory":
            action = _optional_string(args.get("action"))
            if action and action != "read":
                raise ValueError("Realtime frontstage memory is read-only")
            request = {"action": "read"}
            if document := _optional_string(args.get("document")):
                request["document"] = document
            return await self._hermes.memory(request, context)

        if name == "spawn_work":
            request: dict[str, Any] = {
                "objective": _required_string(args.get("objective"), "objective")
            }
            if input_refs := _string_list(args.get("input_refs")):
                request["input_refs"] = input_refs
            return await self._hermes.spawn_work(request, context)

        if name == "get_work_status":
            request = {}
            if work_id := _optional_string(args.get("work_id") or args.get("job_id")):
                request["work_id"] = work_id
            if question := _optional_string(args.get("question")):
                request["question"] = question
            if isinstance(args.get("list_all"), bool):
                request["list_all"] = args["list_all"]
            return await self._hermes.get_work_status(request, context)

        if name == "cancel_work":
            request = {}
            if work_id := _optional_string(args.get("work_id") or args.get("job_id")):
                request["work_id"] = work_id
            if isinstance(args.get("all"), bool):
                request["all"] = args["all"]
            return await self._hermes.cancel_work(request, context)

        if name == "respond_to_work_permission":
            return await self._hermes.respond_to_work_permission(
                {
                    "authorization_id": _required_string(
                        args.get("authorization_id"), "authorization_id"
                    ),
                    "decision": _required_string(args.get("decision"), "decision"),
                },
                context,
            )

        raise ValueError(f"Unsupported realtime frontstage tool: {raw_name}")

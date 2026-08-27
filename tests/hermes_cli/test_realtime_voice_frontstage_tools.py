from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hermes_cli.realtime_voice.tools import (
    FRONTSTAGE_TOOLS,
    FrontstageToolRouter,
    VoiceToolContext,
)


def make_port():
    port = AsyncMock()
    port.spawn_work.return_value = {"status": "accepted", "work_id": "work-1"}
    port.get_work_status.return_value = {"status": "running", "work_id": "work-1"}
    port.cancel_work.return_value = {"status": "cancelled", "work_id": "work-1"}
    port.memory.return_value = {"action": "read", "content": "memory"}
    port.respond_to_work_permission.return_value = {"decision": "always"}
    return port


CONTEXT = VoiceToolContext(owner_id="owner-1", voice_session_id="voice-1")


def test_first_slice_exposes_only_five_provider_neutral_tools():
    assert [tool["function"]["name"] for tool in FRONTSTAGE_TOOLS] == [
        "memory",
        "spawn_work",
        "get_work_status",
        "cancel_work",
        "respond_to_work_permission",
    ]


def test_memory_tool_is_read_only():
    memory = FRONTSTAGE_TOOLS[0]["function"]

    assert memory["parameters"] == {
        "type": "object",
        "properties": {
            "document": {"type": "string", "enum": ["all", "user", "memory"]}
        },
        "additionalProperties": False,
    }


@pytest.mark.asyncio
async def test_memory_call_is_forced_to_read_only():
    port = make_port()
    router = FrontstageToolRouter(port)

    result = await router.execute(
        {"name": "memory", "arguments": {"document": "user"}},
        CONTEXT,
    )

    assert result == {"action": "read", "content": "memory"}
    port.memory.assert_awaited_once_with(
        {"action": "read", "document": "user"},
        CONTEXT,
    )


@pytest.mark.asyncio
async def test_memory_write_alias_is_rejected():
    port = make_port()
    router = FrontstageToolRouter(port)

    with pytest.raises(ValueError, match="memory is read-only"):
        await router.execute(
            {"name": "memory", "arguments": {"action": "append", "content": "x"}},
            CONTEXT,
        )

    port.memory.assert_not_awaited()


@pytest.mark.asyncio
async def test_spawn_work_routes_to_hermes_without_using_speech_as_coordinator():
    port = make_port()
    router = FrontstageToolRouter(port)

    result = await router.execute(
        {"name": "spawn_work", "arguments": {"objective": "Research vendors"}},
        CONTEXT,
    )

    assert result == {"status": "accepted", "work_id": "work-1"}
    port.spawn_work.assert_awaited_once_with(
        {"objective": "Research vendors"},
        CONTEXT,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alias", "method", "arguments"),
    [
        ("spawn_thinking", "spawn_work", {"objective": "Draft the plan"}),
        ("get_agent_task_status", "get_work_status", {"job_id": "work-1"}),
        ("cancel_agent_task", "cancel_work", {"job_id": "work-1"}),
        (
            "respond_agent_permission",
            "respond_to_work_permission",
            {"authorization_id": "auth-1", "decision": "always"},
        ),
    ],
)
async def test_qwen_aliases_route_to_provider_neutral_methods(alias, method, arguments):
    port = make_port()
    router = FrontstageToolRouter(port)

    await router.execute({"name": alias, "arguments": arguments}, CONTEXT)

    getattr(port, method).assert_awaited_once()


@pytest.mark.asyncio
async def test_unknown_tool_is_rejected_before_reaching_hermes():
    port = make_port()
    router = FrontstageToolRouter(port)

    with pytest.raises(ValueError, match="Unsupported realtime frontstage tool: shell"):
        await router.execute({"name": "shell", "arguments": {}}, CONTEXT)

    port.spawn_work.assert_not_awaited()

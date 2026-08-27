from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hermes_cli.realtime_voice.announcements import WorkEvent
from hermes_cli.realtime_voice.livekit_runtime import LiveKitRealtimeVoiceSession
from hermes_cli.realtime_voice.runtime import RealtimeVoiceConfig, TranscriptTurn
from hermes_cli.realtime_voice.tools import FrontstageToolRouter


class FakeSpeechHandle:
    def __init__(self) -> None:
        self.interrupted = False
        self.playout_waited = False

    async def wait_for_playout(self) -> None:
        self.playout_waited = True


class FakeAgentSession:
    def __init__(self, **kwargs) -> None:
        self.options = kwargs
        self.callbacks = {}
        self.start_args = None
        self.closed = False
        self.interruptions = 0
        self.reply_args = None
        self.reply_handle = FakeSpeechHandle()

    def on(self, name, callback) -> None:
        self.callbacks[name] = callback

    async def start(self, **kwargs) -> None:
        self.start_args = kwargs

    def generate_reply(self, **kwargs):
        self.reply_args = kwargs
        return self.reply_handle

    def interrupt(self) -> None:
        self.interruptions += 1

    async def aclose(self) -> None:
        self.closed = True


class FakeSdk:
    def __init__(self) -> None:
        self.sessions = []

    def Agent(self, **kwargs):
        return SimpleNamespace(**kwargs)

    def AgentSession(self, **kwargs):
        session = FakeAgentSession(**kwargs)
        self.sessions.append(session)
        return session

    def RoomOptions(self, **kwargs):
        return SimpleNamespace(**kwargs)

    def function_tool(self, handler, *, raw_schema):
        return SimpleNamespace(handler=handler, raw_schema=raw_schema)


@pytest.fixture
def harness():
    port = AsyncMock()
    port.spawn_work.return_value = {"status": "accepted", "work_id": "work-1"}
    conversation = AsyncMock()
    sdk = FakeSdk()
    runtime = LiveKitRealtimeVoiceSession(
        tools=FrontstageToolRouter(port),
        conversation=conversation,
        sdk=sdk,
    )
    config = RealtimeVoiceConfig(
        conversation_id="voice-conversation",
        owner_id="owner-1",
        participant_identity="desktop-1",
        instructions="Reply quickly. Delegate every action to Hermes Work.",
        realtime_model=object(),
    )
    return runtime, sdk, port, conversation, config


@pytest.mark.asyncio
async def test_livekit_owns_media_while_hermes_tools_remain_the_action_boundary(harness):
    runtime, sdk, port, _, config = harness
    room = object()

    await runtime.start(room=room, config=config)

    session = sdk.sessions[0]
    assert session.options == {"llm": config.realtime_model}
    assert session.start_args["room"] is room
    assert session.start_args["agent"].instructions == config.instructions
    assert session.start_args["room_options"].audio_input is True
    assert session.start_args["room_options"].audio_output is True
    assert session.start_args["room_options"].video_input is False
    assert session.start_args["room_options"].close_on_disconnect is False
    tools = session.start_args["agent"].tools
    assert [tool.raw_schema["name"] for tool in tools] == [
        "memory",
        "spawn_work",
        "get_work_status",
        "cancel_work",
        "respond_to_work_permission",
    ]

    spawn = next(tool for tool in tools if tool.raw_schema["name"] == "spawn_work")
    run_context = SimpleNamespace(
        function_call=SimpleNamespace(call_id="call-1")
    )
    result = await spawn.handler({"objective": "Compare vendors"}, run_context)

    assert result == {"status": "accepted", "work_id": "work-1"}
    context = port.spawn_work.await_args.args[1]
    assert context.owner_id == "owner-1"
    assert context.voice_session_id == "voice-conversation"
    assert context.tool_call_id == "call-1"


@pytest.mark.asyncio
async def test_only_final_provider_transcript_enters_the_one_voice_conversation(harness):
    runtime, sdk, _, conversation, config = harness
    await runtime.start(room=object(), config=config)
    session = sdk.sessions[0]

    session.callbacks["user_input_transcribed"](
        SimpleNamespace(is_final=False, transcript="partial", item_id="user-1")
    )
    session.callbacks["user_input_transcribed"](
        SimpleNamespace(is_final=True, transcript="final request", item_id="user-1")
    )
    session.callbacks["conversation_item_added"](
        SimpleNamespace(
            item=SimpleNamespace(
                role="assistant",
                text_content="I delegated that.",
                id="assistant-1",
                interrupted=True,
            )
        )
    )
    await asyncio.sleep(0)

    assert conversation.append_turn.await_args_list[0].args[0] == TranscriptTurn(
        conversation_id="voice-conversation",
        role="user",
        text="final request",
        item_id="user-1",
    )
    assert conversation.append_turn.await_args_list[1].args[0] == TranscriptTurn(
        conversation_id="voice-conversation",
        role="assistant",
        text="I delegated that.",
        item_id="assistant-1",
        interrupted=True,
    )
    assert conversation.append_turn.await_count == 2


@pytest.mark.asyncio
async def test_work_result_is_spoken_without_exposing_livekit_as_durable_authority(harness):
    runtime, sdk, port, _, config = harness
    await runtime.start(room=object(), config=config)
    event = WorkEvent(
        event_id=4,
        kind="completed",
        payload={"summary": "The comparison is ready."},
        work_id="work-1",
    )

    delivered = await runtime.announce(event)
    await runtime.interrupt()

    session = sdk.sessions[0]
    assert delivered is True
    assert "The comparison is ready." in session.reply_args["instructions"]
    assert session.reply_args["tool_choice"] == "none"
    assert session.reply_handle.playout_waited is True
    assert session.interruptions == 1
    port.cancel_work.assert_not_awaited()


@pytest.mark.asyncio
async def test_close_ends_only_the_ephemeral_livekit_session(harness):
    runtime, sdk, _, _, config = harness
    await runtime.start(room=object(), config=config)

    await runtime.close()

    assert sdk.sessions[0].closed is True
    with pytest.raises(RuntimeError, match="not started"):
        await runtime.interrupt()

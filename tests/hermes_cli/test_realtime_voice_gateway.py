from __future__ import annotations

import asyncio
import base64
from unittest.mock import AsyncMock

import pytest

from hermes_cli.realtime_voice.announcements import WorkEvent
from hermes_cli.realtime_voice.gateway import RealtimeVoiceGateway
from hermes_cli.realtime_voice.provider import RealtimeProviderRegistry
from hermes_cli.realtime_voice.tools import FrontstageToolRouter, VoiceToolContext


class FakeProvider:
    key = "fake"
    label = "Fake Native S2S"
    aliases = ()
    input_sample_rate = 16_000
    output_sample_rate = 24_000

    def __init__(self, session: AsyncMock) -> None:
        self.session = session
        self.options = None

    def is_configured(self) -> bool:
        return True

    async def connect(self, options):
        self.options = options
        return self.session


@pytest.fixture
def harness():
    client = AsyncMock()
    provider_session = AsyncMock()
    provider = FakeProvider(provider_session)
    port = AsyncMock()
    port.spawn_work.return_value = {"accepted": True, "work_id": "work-7"}
    gateway = RealtimeVoiceGateway(
        providers=RealtimeProviderRegistry([provider]),
        tools=FrontstageToolRouter(port),
        client=client,
        context=VoiceToolContext(owner_id="user-1", voice_session_id="voice-1"),
        instructions="Stay conversational and delegate durable work.",
    )
    return gateway, client, provider, provider_session, port


@pytest.mark.asyncio
async def test_starts_native_provider_with_frontstage_tools(harness):
    gateway, client, provider, provider_session, _ = harness

    await gateway.start("fake")

    assert provider.options["instructions"] == "Stay conversational and delegate durable work."
    assert {tool["function"]["name"] for tool in provider.options["tools"]} == {
        "memory",
        "spawn_work",
        "get_work_status",
        "cancel_work",
        "respond_to_work_permission",
    }
    client.send_json.assert_awaited_with(
        {
            "type": "voice.ready",
            "provider": "fake",
            "inputSampleRate": 16_000,
            "outputSampleRate": 24_000,
        }
    )


@pytest.mark.asyncio
async def test_forwards_live_pcm_and_barge_in_without_cancelling_work(harness):
    gateway, client, _, provider_session, port = harness
    await gateway.start("fake")

    await gateway.handle_client(
        {"type": "audio.append", "audio": base64.b64encode(b"pcm").decode("ascii")}
    )
    await gateway.handle_client({"type": "interrupt"})

    provider_session.append_audio.assert_awaited_once_with(b"pcm")
    provider_session.interrupt_speech.assert_awaited_once()
    port.cancel_work.assert_not_awaited()
    client.send_json.assert_any_await(
        {"type": "playback.clear", "reason": "user_interruption"}
    )


@pytest.mark.asyncio
async def test_provider_events_stream_audio_and_execute_tools(harness):
    gateway, client, provider, provider_session, port = harness
    await gateway.start("fake")
    on_event = provider.options["on_event"]

    await on_event({"type": "speech.started", "item_id": "input-1"})
    await on_event({"type": "transcript.delta", "item_id": "input-1", "text": "compare"})
    await on_event(
        {
            "type": "tool.call",
            "response_id": "response-1",
            "call_id": "call-1",
            "name": "spawn_work",
            "arguments": {"objective": "compare vendors"},
        }
    )
    await on_event(
        {
            "type": "audio.delta",
            "response_id": "response-1",
            "audio": b"pcm-out",
            "sample_rate": 24_000,
        }
    )

    port.spawn_work.assert_awaited_once()
    provider_session.submit_tool_result.assert_awaited_once_with(
        "call-1", {"accepted": True, "work_id": "work-7"}
    )
    client.send_json.assert_any_await(
        {"type": "transcript.delta", "role": "user", "content": "compare"}
    )
    client.send_json.assert_any_await(
        {
            "type": "audio.delta",
            "audio": base64.b64encode(b"pcm-out").decode("ascii"),
            "sampleRate": 24_000,
            "responseId": "response-1",
        }
    )


@pytest.mark.asyncio
async def test_work_completion_is_spoken_and_confirmed_only_by_actual_playback(harness):
    gateway, client, provider, provider_session, _ = harness
    await gateway.start("fake")
    provider_session.inject_announcement.side_effect = _announcement_side_effect(
        provider.options["wait_for_playback_started"]
    )
    gateway.track_work("work-7")

    delivery = gateway.announce_work(
        WorkEvent(
            event_id=12,
            kind="completed",
            payload={"summary": "The comparison is ready."},
            work_id="work-7",
        )
    )
    await asyncio.sleep(0)
    await provider.options["on_event"](
        {"type": "response.started", "response_id": "response-announcement"}
    )
    await gateway.handle_client(
        {"type": "playback.started", "responseId": "response-announcement"}
    )
    await delivery

    provider_session.inject_announcement.assert_awaited_once()


async def _await_playback(waiter, announcement_id):
    return {"playback_started": await waiter(announcement_id)}


def _announcement_side_effect(waiter):
    async def inject(payload):
        return await _await_playback(waiter, payload["id"])

    return inject

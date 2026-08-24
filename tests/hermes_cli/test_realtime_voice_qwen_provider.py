from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from hermes_cli.realtime_voice.providers.qwen import QwenRealtimeProvider


class FakeWebSocket:
    def __init__(self, incoming: list[dict[str, Any]] | None = None) -> None:
        self.incoming = list(incoming or [])
        self.sent: list[dict[str, Any]] = []
        self.closed = False

    async def send(self, message: str) -> None:
        self.sent.append(json.loads(message))

    async def close(self) -> None:
        self.closed = True

    def __aiter__(self) -> AsyncIterator[str]:
        return self._messages()

    async def _messages(self) -> AsyncIterator[str]:
        for event in self.incoming:
            await asyncio.sleep(0)
            yield json.dumps(event)


class FakeConnector:
    def __init__(self, socket: FakeWebSocket) -> None:
        self.socket = socket
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def __call__(self, url: str, **kwargs: Any) -> FakeWebSocket:
        self.calls.append((url, kwargs))
        return self.socket


@pytest.mark.asyncio
async def test_connects_to_dashscope_and_configures_native_realtime_session():
    socket = FakeWebSocket()
    connector = FakeConnector(socket)
    provider = QwenRealtimeProvider(
        api_key="secret",
        base_url="wss://voice.example/api-ws/v1/realtime",
        model="qwen-audio-3.0-realtime-plus",
        voice="longanqian",
        connector=connector,
    )

    session = await provider.connect(
        {
            "instructions": "You are the fast realtime frontstage.",
            "tools": [{"type": "function", "function": {"name": "spawn_work"}}],
        }
    )

    assert connector.calls == [
        (
            "wss://voice.example/api-ws/v1/realtime?model=qwen-audio-3.0-realtime-plus",
            {"additional_headers": {"Authorization": "Bearer secret"}},
        )
    ]
    update = socket.sent[0]
    assert update["type"] == "session.update"
    assert update["session"] == {
        "instructions": "You are the fast realtime frontstage.",
        "tools": [{"type": "function", "function": {"name": "spawn_work"}}],
        "modalities": ["text", "audio"],
        "voice": "longanqian",
        "input_audio_format": "pcm",
        "output_audio_format": "pcm",
        "turn_detection": {"type": "smart_turn"},
    }

    await session.close()


@pytest.mark.asyncio
async def test_streams_pcm_audio_and_interrupts_the_active_response():
    socket = FakeWebSocket()
    provider = QwenRealtimeProvider(api_key="secret", connector=FakeConnector(socket))
    session = await provider.connect({"instructions": "frontstage"})

    await session.append_audio(b"\x01\x02")
    await session.interrupt_speech()

    assert socket.sent[1]["type"] == "input_audio_buffer.append"
    assert socket.sent[1]["audio"] == base64.b64encode(b"\x01\x02").decode("ascii")
    assert socket.sent[2]["type"] == "response.cancel"

    await session.close()


@pytest.mark.asyncio
async def test_normalizes_audio_transcripts_and_tool_calls_from_provider():
    socket = FakeWebSocket(
        [
            {"type": "input_audio_buffer.speech_started", "item_id": "input-1"},
            {
                "type": "conversation.item.input_audio_transcription.delta",
                "item_id": "input-1",
                "delta": "hello",
            },
            {
                "type": "response.audio.delta",
                "response_id": "response-1",
                "delta": base64.b64encode(b"pcm").decode("ascii"),
            },
            {
                "type": "response.function_call_arguments.done",
                "response_id": "response-1",
                "call_id": "call-1",
                "name": "spawn_work",
                "arguments": '{"objective":"compare vendors"}',
            },
            {"type": "response.done", "response": {"id": "response-1"}},
        ]
    )
    events: list[dict[str, Any]] = []

    async def on_event(event: dict[str, Any]) -> None:
        events.append(event)

    provider = QwenRealtimeProvider(api_key="secret", connector=FakeConnector(socket))
    session = await provider.connect({"instructions": "frontstage", "on_event": on_event})
    await session.wait_closed()

    assert events == [
        {"type": "speech.started", "item_id": "input-1"},
        {"type": "transcript.delta", "item_id": "input-1", "text": "hello"},
        {
            "type": "audio.delta",
            "response_id": "response-1",
            "audio": b"pcm",
            "sample_rate": 24_000,
        },
        {
            "type": "tool.call",
            "response_id": "response-1",
            "call_id": "call-1",
            "name": "spawn_work",
            "arguments": {"objective": "compare vendors"},
        },
        {"type": "response.done", "response_id": "response-1"},
    ]

    await session.close()


@pytest.mark.asyncio
async def test_returns_tool_output_to_the_native_voice_model():
    socket = FakeWebSocket()
    provider = QwenRealtimeProvider(api_key="secret", connector=FakeConnector(socket))
    session = await provider.connect({"instructions": "frontstage"})

    await session.submit_tool_result("call-1", {"accepted": True, "work_id": "work-7"})

    output = socket.sent[1]
    assert output["type"] == "conversation.item.create"
    assert output["item"]["type"] == "function_call_output"
    assert output["item"]["call_id"] == "call-1"
    assert json.loads(output["item"]["output"]) == {"accepted": True, "work_id": "work-7"}
    assert socket.sent[2]["type"] == "response.create"

    await session.close()


@pytest.mark.asyncio
async def test_injects_background_work_result_and_waits_for_real_playback_start():
    socket = FakeWebSocket()
    playback_requests: list[str] = []

    async def wait_for_playback_started(announcement_id: str) -> bool:
        playback_requests.append(announcement_id)
        return True

    provider = QwenRealtimeProvider(api_key="secret", connector=FakeConnector(socket))
    session = await provider.connect(
        {
            "instructions": "frontstage",
            "wait_for_playback_started": wait_for_playback_started,
        }
    )

    outcome = await session.inject_announcement(
        {"id": "work-event:12", "text": "The vendor comparison is ready."}
    )

    item = socket.sent[1]
    assert item["type"] == "conversation.item.create"
    assert item["item"]["role"] == "user"
    assert item["item"]["content"][0]["text"] == "The vendor comparison is ready."
    response = socket.sent[2]
    assert response["type"] == "response.create"
    assert response["response"]["tool_choice"] == "none"
    assert playback_requests == ["work-event:12"]
    assert outcome == {"playback_started": True}

    await session.close()

"""Qwen Audio Realtime provider for Hermes' native realtime frontstage.

The wire protocol is adapted from QwenAudio/qwen-audio-agent
``server/src/voice/providers/dashscope.mjs`` and
``server/src/voice/providers/openai-compatible-protocol.mjs`` at commit
``c66cde03e9946e3cc8503cb917d9cd0ee7712989``. Qwen Audio Agent is licensed
under Apache-2.0. See ``docs/third-party/qwen-audio-agent.md``.
"""

from __future__ import annotations

import asyncio
import base64
import inspect
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Any
from urllib.parse import quote
from uuid import uuid4

from websockets.asyncio.client import connect as websocket_connect


DEFAULT_REALTIME_URL = "wss://dashscope.aliyuncs.com/api-ws/v1/realtime"
DEFAULT_MODEL = "qwen-audio-3.0-realtime-plus"
DEFAULT_VOICE = "longanqian"

EventHandler = Callable[[dict[str, Any]], Awaitable[None] | None]
PlaybackWaiter = Callable[[str], Awaitable[bool]]
Connector = Callable[..., Awaitable[Any]]


def _event_id() -> str:
    return f"event_{uuid4().hex}"


def _response_id(event: dict[str, Any]) -> str:
    direct = event.get("response_id")
    if isinstance(direct, str):
        return direct
    response = event.get("response")
    if isinstance(response, dict) and isinstance(response.get("id"), str):
        return response["id"]
    return ""


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


class QwenRealtimeSession:
    def __init__(
        self,
        socket: Any,
        *,
        on_event: EventHandler | None = None,
        wait_for_playback_started: PlaybackWaiter | None = None,
    ) -> None:
        self._socket = socket
        self._on_event = on_event
        self._wait_for_playback_started = wait_for_playback_started
        self._send_lock = asyncio.Lock()
        self._reader = asyncio.create_task(self._read_events())

    async def _send(self, payload: dict[str, Any]) -> None:
        message = json.dumps({"event_id": _event_id(), **payload}, separators=(",", ":"))
        async with self._send_lock:
            await self._socket.send(message)

    async def configure(self, session: dict[str, Any]) -> None:
        await self._send({"type": "session.update", "session": session})

    async def append_audio(self, audio: bytes) -> None:
        await self._send(
            {
                "type": "input_audio_buffer.append",
                "audio": base64.b64encode(audio).decode("ascii"),
            }
        )

    async def submit_tool_result(self, call_id: str, output: Any) -> None:
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": json.dumps(output, separators=(",", ":")),
                },
            }
        )
        await self._send({"type": "response.create"})

    async def inject_announcement(self, announcement: dict[str, Any]) -> dict[str, Any]:
        announcement_id = str(announcement.get("id") or f"announcement:{uuid4().hex}")
        await self._send(
            {
                "type": "conversation.item.create",
                "item": {
                    "type": "message",
                    "role": "user",
                    "content": [{"type": "input_text", "text": str(announcement["text"])}],
                },
            }
        )
        await self._send(
            {
                "type": "response.create",
                "response": {
                    "modalities": ["text", "audio"],
                    "tool_choice": "none",
                    "instructions": (
                        "Speak this background result naturally and briefly. Do not invoke tools."
                    ),
                },
            }
        )
        started = False
        if self._wait_for_playback_started is not None:
            started = await self._wait_for_playback_started(announcement_id)
        return {"playback_started": started}

    async def interrupt_speech(self) -> None:
        await self._send({"type": "response.cancel"})

    async def wait_closed(self) -> None:
        await self._reader

    async def close(self) -> None:
        if not self._reader.done():
            self._reader.cancel()
            try:
                await self._reader
            except asyncio.CancelledError:
                pass
        await self._socket.close()

    async def _emit(self, event: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        result = self._on_event(event)
        if inspect.isawaitable(result):
            await result

    async def _read_events(self) -> None:
        async for raw in self._socket:
            try:
                event = json.loads(raw)
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(event, dict):
                continue
            normalized = self._normalize(event)
            if normalized is not None:
                await self._emit(normalized)

    @staticmethod
    def _normalize(event: dict[str, Any]) -> dict[str, Any] | None:
        kind = event.get("type")
        item_id = event.get("item_id")
        if kind == "input_audio_buffer.speech_started":
            return {"type": "speech.started", "item_id": item_id}
        if kind == "input_audio_buffer.speech_stopped":
            return {"type": "speech.stopped", "item_id": item_id}
        if kind in {
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.text",
        }:
            return {
                "type": "transcript.delta",
                "item_id": item_id,
                "text": str(event.get("delta") or event.get("text") or ""),
            }
        if kind == "conversation.item.input_audio_transcription.completed":
            return {
                "type": "transcript.final",
                "item_id": item_id,
                "text": str(event.get("transcript") or ""),
            }
        if kind in {"response.audio.delta", "response.output_audio.delta"}:
            try:
                audio = base64.b64decode(str(event.get("delta") or ""), validate=True)
            except (ValueError, TypeError):
                return None
            return {
                "type": "audio.delta",
                "response_id": _response_id(event),
                "audio": audio,
                "sample_rate": int(event.get("sampleRate") or 24_000),
            }
        if kind in {
            "response.audio_transcript.delta",
            "response.output_audio_transcript.delta",
        }:
            return {
                "type": "assistant_transcript.delta",
                "response_id": _response_id(event),
                "text": str(event.get("delta") or ""),
            }
        if kind == "response.function_call_arguments.done":
            raw_item = event.get("item")
            item: dict[str, Any] = raw_item if isinstance(raw_item, dict) else {}
            return {
                "type": "tool.call",
                "response_id": _response_id(event),
                "call_id": str(event.get("call_id") or item.get("call_id") or ""),
                "name": str(event.get("name") or item.get("name") or ""),
                "arguments": _arguments(event.get("arguments") or item.get("arguments")),
            }
        if kind == "response.created":
            return {"type": "response.started", "response_id": _response_id(event)}
        if kind == "response.done":
            return {"type": "response.done", "response_id": _response_id(event)}
        if kind == "error":
            error = event.get("error")
            message = error.get("message") if isinstance(error, dict) else event.get("message")
            return {"type": "error", "message": str(message or "Realtime provider error")}
        return None


class QwenRealtimeProvider:
    key = "qwen"
    label = "Qwen Audio Realtime"
    aliases: Sequence[str] = ("dashscope",)
    input_sample_rate = 16_000
    output_sample_rate = 24_000

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = DEFAULT_REALTIME_URL,
        model: str = DEFAULT_MODEL,
        voice: str = DEFAULT_VOICE,
        connector: Connector = websocket_connect,
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = base_url.strip().rstrip("?")
        self._model = model.strip() or DEFAULT_MODEL
        self._voice = voice.strip() or DEFAULT_VOICE
        self._connector = connector

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def connect(self, options: dict[str, Any]) -> QwenRealtimeSession:
        if not self.is_configured():
            raise ValueError("Qwen realtime requires DASHSCOPE_API_KEY")
        separator = "&" if "?" in self._base_url else "?"
        url = f"{self._base_url}{separator}model={quote(self._model, safe='')}"
        socket = await self._connector(
            url,
            additional_headers={"Authorization": f"Bearer {self._api_key}"},
        )
        session = QwenRealtimeSession(
            socket,
            on_event=options.get("on_event"),
            wait_for_playback_started=options.get("wait_for_playback_started"),
        )
        configured = {
            "instructions": str(options.get("instructions") or ""),
            **({"tools": options["tools"]} if options.get("tools") else {}),
            "modalities": ["text", "audio"],
            "voice": self._voice,
            "input_audio_format": "pcm",
            "output_audio_format": "pcm",
            "turn_detection": {"type": "smart_turn"},
        }
        await session.configure(configured)
        return session

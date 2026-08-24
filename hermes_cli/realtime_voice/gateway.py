"""Provider-neutral native realtime voice gateway.

This is a new Hermes backend path. It does not call Hermes' existing
turn-based STT, TTS, auto-speak, or voice-conversation primitives.

The client event shape and playback acknowledgement lifecycle are adapted
from QwenAudio/qwen-audio-agent ``shared/realtime-events.mjs`` and
``server/src/voice/realtime-gateway.mjs`` at commit
``c66cde03e9946e3cc8503cb917d9cd0ee7712989``. Qwen Audio Agent is licensed
under Apache-2.0. See ``docs/third-party/qwen-audio-agent.md``.
"""

from __future__ import annotations

import asyncio
import base64
from collections import deque
from typing import Any, Protocol

from .announcements import AnnouncementDelivery, WorkEvent
from .provider import RealtimeProviderRegistry, RealtimeSession
from .tools import FRONTSTAGE_TOOLS, FrontstageToolRouter, VoiceToolContext


class RealtimeClient(Protocol):
    async def send_json(self, payload: dict[str, Any]) -> None: ...


class RealtimeVoiceGateway:
    def __init__(
        self,
        *,
        providers: RealtimeProviderRegistry,
        tools: FrontstageToolRouter,
        client: RealtimeClient,
        context: VoiceToolContext,
        instructions: str,
    ) -> None:
        self._providers = providers
        self._tools = tools
        self._client = client
        self._context = context
        self._instructions = instructions
        self._session: RealtimeSession | None = None
        self._delivery: AnnouncementDelivery | None = None
        self._turn = 0
        self._playback_waiters: dict[str, asyncio.Future[bool]] = {}
        self._unmatched_announcements: deque[str] = deque()
        self._unmatched_responses: deque[str] = deque()
        self._response_announcements: dict[str, str] = {}

    async def start(self, provider_name: str) -> None:
        if self._session is not None:
            raise RuntimeError("Realtime voice gateway is already started")
        provider = self._providers.resolve(provider_name)
        self._session = await provider.connect(
            {
                "instructions": self._instructions,
                "tools": FRONTSTAGE_TOOLS,
                "on_event": self._handle_provider,
                "wait_for_playback_started": self._wait_for_playback_started,
            }
        )
        self._delivery = AnnouncementDelivery(self._session)
        await self._client.send_json(
            {
                "type": "voice.ready",
                "provider": provider.key,
                "inputSampleRate": provider.input_sample_rate,
                "outputSampleRate": provider.output_sample_rate,
            }
        )

    def track_work(self, work_id: str) -> None:
        if self._delivery is None:
            raise RuntimeError("Realtime voice gateway is not started")
        self._delivery.add_work(work_id)

    def announce_work(self, event: WorkEvent) -> asyncio.Task[None]:
        if self._delivery is None:
            raise RuntimeError("Realtime voice gateway is not started")
        return asyncio.create_task(self._delivery.receive(event))

    async def handle_client(self, event: dict[str, Any]) -> None:
        session = self._require_session()
        kind = str(event.get("type") or "")
        if kind == "audio.append":
            encoded = event.get("audio")
            if not isinstance(encoded, str):
                raise ValueError("audio.append requires base64 audio")
            try:
                audio = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise ValueError("audio.append contains invalid base64 audio") from exc
            await session.append_audio(audio)
            return
        if kind == "interrupt":
            await session.interrupt_speech()
            await self._client.send_json(
                {"type": "playback.clear", "reason": "user_interruption"}
            )
            await self._client.send_json({"type": "response.interrupted"})
            return
        if kind == "playback.started":
            response_id = str(event.get("responseId") or event.get("response_id") or "")
            self._confirm_playback(response_id)
            return
        if kind in {"playback.cancelled", "playback.ended"}:
            return
        raise ValueError(f"Unsupported realtime client event: {kind}")

    async def close(self) -> None:
        if self._session is not None:
            await self._session.close()
            self._session = None
        for future in self._playback_waiters.values():
            if not future.done():
                future.set_result(False)
        self._playback_waiters.clear()

    async def _handle_provider(self, event: dict[str, Any]) -> None:
        kind = event.get("type")
        if kind == "speech.started":
            self._turn += 1
            await self._client.send_json(
                {"type": "playback.clear", "reason": "user_interruption"}
            )
            await self._client.send_json({"type": "turn.started", "turnId": self._turn})
            await self._client.send_json(
                {"type": "voice.state", "state": "listening", "turnId": self._turn}
            )
            return
        if kind == "speech.stopped":
            await self._client.send_json(
                {"type": "voice.state", "state": "processing", "turnId": self._turn}
            )
            return
        if kind in {"transcript.delta", "transcript.final"}:
            await self._client.send_json(
                {
                    "type": kind,
                    "role": "user",
                    "content": str(event.get("text") or ""),
                }
            )
            return
        if kind == "assistant_transcript.delta":
            await self._client.send_json(
                {
                    "type": "transcript.delta",
                    "role": "assistant",
                    "content": str(event.get("text") or ""),
                    "responseId": str(event.get("response_id") or ""),
                }
            )
            return
        if kind == "response.started":
            response_id = str(event.get("response_id") or "")
            self._register_response(response_id)
            await self._client.send_json(
                {"type": "response.started", "responseId": response_id}
            )
            return
        if kind == "audio.delta":
            response_id = str(event.get("response_id") or "")
            self._register_response(response_id)
            await self._client.send_json(
                {
                    "type": "audio.delta",
                    "audio": base64.b64encode(event["audio"]).decode("ascii"),
                    "sampleRate": int(event.get("sample_rate") or 24_000),
                    "responseId": response_id,
                }
            )
            return
        if kind == "tool.call":
            result = await self._tools.execute(
                {
                    "name": event.get("name"),
                    "arguments": event.get("arguments"),
                    "call_id": event.get("call_id"),
                },
                self._context,
            )
            if isinstance(result, dict) and isinstance(result.get("work_id"), str):
                self.track_work(result["work_id"])
            await self._require_session().submit_tool_result(
                str(event.get("call_id") or ""), result
            )
            return
        if kind == "response.done":
            response_id = str(event.get("response_id") or "")
            await self._client.send_json({"type": "audio.done", "responseId": response_id})
            await self._client.send_json(
                {"type": "voice.state", "state": "idle", "turnId": self._turn}
            )
            return
        if kind == "error":
            await self._client.send_json(
                {"type": "error", "message": str(event.get("message") or "Realtime error")}
            )

    async def _wait_for_playback_started(self, announcement_id: str) -> bool:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._playback_waiters[announcement_id] = future
        self._unmatched_announcements.append(announcement_id)
        self._pair_playback()
        try:
            return await future
        finally:
            self._playback_waiters.pop(announcement_id, None)

    def _register_response(self, response_id: str) -> None:
        if not response_id or response_id in self._response_announcements:
            return
        if response_id in self._unmatched_responses:
            return
        self._unmatched_responses.append(response_id)
        self._pair_playback()

    def _pair_playback(self) -> None:
        while self._unmatched_announcements and self._unmatched_responses:
            announcement_id = self._unmatched_announcements.popleft()
            response_id = self._unmatched_responses.popleft()
            self._response_announcements[response_id] = announcement_id

    def _confirm_playback(self, response_id: str) -> None:
        announcement_id = self._response_announcements.pop(response_id, None)
        if announcement_id is None:
            return
        future = self._playback_waiters.get(announcement_id)
        if future is not None and not future.done():
            future.set_result(True)

    def _require_session(self) -> RealtimeSession:
        if self._session is None:
            raise RuntimeError("Realtime voice gateway is not started")
        return self._session

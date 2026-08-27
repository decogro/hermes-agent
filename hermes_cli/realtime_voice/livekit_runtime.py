"""LiveKit implementation of the ephemeral realtime voice session.

LiveKit types are contained in this module. The rest of Hermes depends only on
``RealtimeVoiceSession`` from ``runtime.py``.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any, Callable

from .announcements import WorkEvent, format_work_announcement
from .runtime import RealtimeVoiceConfig, TranscriptTurn, VoiceConversationPort
from .tools import FRONTSTAGE_TOOLS, FrontstageToolRouter, VoiceToolContext


def _load_livekit() -> Any:
    try:
        from livekit.agents import Agent, AgentSession, function_tool, room_io
    except ImportError as exc:
        raise RuntimeError(
            "Native realtime voice requires the optional LiveKit dependencies. "
            "Install Hermes with the realtime-voice extra."
        ) from exc
    return SimpleNamespace(
        Agent=Agent,
        AgentSession=AgentSession,
        function_tool=function_tool,
        RoomOptions=room_io.RoomOptions,
    )


@dataclass(frozen=True)
class _SessionState:
    config: RealtimeVoiceConfig
    session: Any


class LiveKitRealtimeVoiceSession:
    """One active WebRTC plus speech-to-speech session.

    This Implementation deliberately does not expose LiveKit task, workflow,
    memory, or handoff primitives. All durable authority remains in Hermes.
    """

    def __init__(
        self,
        *,
        tools: FrontstageToolRouter,
        conversation: VoiceConversationPort,
        sdk: Any | None = None,
    ) -> None:
        self._tools = tools
        self._conversation = conversation
        self._sdk = sdk
        self._state: _SessionState | None = None
        self._event_tasks: set[asyncio.Task[None]] = set()

    async def start(self, *, room: Any, config: RealtimeVoiceConfig) -> None:
        if self._state is not None:
            raise RuntimeError("Realtime voice session is already started")
        sdk = self._sdk or _load_livekit()
        context = VoiceToolContext(
            owner_id=config.owner_id,
            voice_session_id=config.conversation_id,
        )
        agent = sdk.Agent(
            instructions=config.instructions,
            tools=self._build_tools(sdk, context),
        )
        session = sdk.AgentSession(llm=config.realtime_model)
        session.on("user_input_transcribed", self._on_user_transcribed)
        session.on("conversation_item_added", self._on_conversation_item_added)
        self._state = _SessionState(config=config, session=session)
        try:
            await session.start(
                room=room,
                agent=agent,
                room_options=sdk.RoomOptions(
                    audio_input=True,
                    audio_output=True,
                    text_input=False,
                    text_output=True,
                    video_input=False,
                    participant_identity=config.participant_identity,
                    close_on_disconnect=False,
                ),
            )
        except BaseException:
            self._state = None
            raise

    async def announce(self, event: WorkEvent) -> bool:
        state = self._require_state()
        handle = state.session.generate_reply(
            instructions=format_work_announcement(event),
            tool_choice="none",
            allow_interruptions=True,
        )
        await handle.wait_for_playout()
        return not bool(getattr(handle, "interrupted", False))

    async def interrupt(self, reason: str = "user_barge_in") -> None:
        del reason
        result = self._require_state().session.interrupt()
        if hasattr(result, "__await__"):
            await result

    async def close(self, reason: str = "user_ended") -> None:
        del reason
        state, self._state = self._state, None
        if state is not None:
            await state.session.aclose()
        if self._event_tasks:
            await asyncio.gather(*tuple(self._event_tasks), return_exceptions=True)

    def _build_tools(self, sdk: Any, context: VoiceToolContext) -> list[Any]:
        built = []
        for definition in FRONTSTAGE_TOOLS:
            function = definition["function"]
            raw_schema = {
                "type": "function",
                "name": function["name"],
                "description": function["description"],
                "parameters": function["parameters"],
            }

            async def handler(
                raw_arguments: dict[str, object],
                run_context: Any,
                *,
                _name: str = function["name"],
            ) -> Any:
                function_call = getattr(run_context, "function_call", None)
                return await self._tools.execute(
                    {
                        "name": _name,
                        "arguments": raw_arguments,
                        "call_id": getattr(function_call, "call_id", None),
                    },
                    context,
                )

            built.append(sdk.function_tool(handler, raw_schema=raw_schema))
        return built

    def _on_user_transcribed(self, event: Any) -> None:
        if not bool(getattr(event, "is_final", False)):
            return
        self._schedule_turn(
            role="user",
            text=getattr(event, "transcript", ""),
            item_id=getattr(event, "item_id", None),
        )

    def _on_conversation_item_added(self, event: Any) -> None:
        item = getattr(event, "item", None)
        if getattr(item, "role", None) != "assistant":
            return
        text = getattr(item, "text_content", "")
        self._schedule_turn(
            role="assistant",
            text=text,
            item_id=getattr(item, "id", None),
            interrupted=bool(getattr(item, "interrupted", False)),
        )

    def _schedule_turn(
        self,
        *,
        role: str,
        text: Any,
        item_id: Any,
        interrupted: bool = False,
    ) -> None:
        clean_text = text.strip() if isinstance(text, str) else ""
        state = self._state
        if not clean_text or state is None:
            return
        turn = TranscriptTurn(
            conversation_id=state.config.conversation_id,
            role=role,
            text=clean_text,
            item_id=item_id if isinstance(item_id, str) and item_id else None,
            interrupted=interrupted,
        )
        task = asyncio.create_task(self._conversation.append_turn(turn))
        self._event_tasks.add(task)
        task.add_done_callback(self._event_tasks.discard)

    def _require_state(self) -> _SessionState:
        if self._state is None:
            raise RuntimeError("Realtime voice session is not started")
        return self._state

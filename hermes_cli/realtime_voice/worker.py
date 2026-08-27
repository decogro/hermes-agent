"""Launch the Hermes realtime voice module as a LiveKit Agents worker."""

from __future__ import annotations

import importlib
import inspect
import os
import sys
from typing import Any, Callable

from hermes_state import SessionDB

from .authority import HermesAuthorityAdapter, HermesAuthorityConfig
from .conversation import HermesVoiceConversation
from .coordinator import (
    HermesApiCoordinatorConfig,
    HermesApiCoordinatorWake,
    KanbanCoordinatorEventSink,
    PrimaryCoordinatorConfig,
    PrimaryCoordinatorPump,
)
from .delivery import WorkAnnouncementConfig, WorkAnnouncementPump
from .host import RealtimeVoiceHost
from .livekit_runtime import LiveKitRealtimeVoiceSession
from .runtime import RealtimeVoiceConfig
from .tools import FrontstageToolRouter


DEFAULT_INSTRUCTIONS = """You are the fast realtime voice frontstage for Hermes.
Respond conversationally to questions using read-only Hermes memory.
For every requested action or substantive task, call spawn_work immediately,
confirm that Hermes accepted it, and keep the voice conversation available.
Never claim Work is complete until Hermes sends a Work announcement.
"""


def _required_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"Missing required realtime voice setting: {name}")
    return value


def load_model_factory(spec: str) -> Callable[[], Any]:
    """Load a zero-argument LiveKit RealtimeModel factory by dotted path."""
    module_name, separator, object_name = spec.partition(":")
    if not separator or not module_name or not object_name:
        raise ValueError(
            "HERMES_REALTIME_MODEL_FACTORY must use module:function syntax"
        )
    factory = getattr(importlib.import_module(module_name), object_name)
    if not callable(factory):
        raise TypeError(f"Realtime model factory is not callable: {spec}")
    return factory


async def _build_model(factory: Callable[[], Any]) -> Any:
    model = factory()
    return await model if inspect.isawaitable(model) else model


def create_server() -> Any:
    try:
        from livekit.agents import AgentServer
    except ImportError as exc:
        raise RuntimeError(
            "Install Hermes with the realtime-voice extra before starting this worker"
        ) from exc

    model_factory = load_model_factory(_required_env("HERMES_REALTIME_MODEL_FACTORY"))
    conversation_id = os.environ.get(
        "HERMES_VOICE_CONVERSATION_ID", "realtime-voice-main"
    ).strip()
    coordinator_session_id = os.environ.get(
        "HERMES_COORDINATOR_SESSION_ID", "realtime-voice-coordinator"
    ).strip()
    coordinator_profile = os.environ.get(
        "HERMES_COORDINATOR_PROFILE", "default"
    ).strip()
    owner_id = os.environ.get("HERMES_REALTIME_OWNER_ID", "local-owner").strip()
    api_key = _required_env("API_SERVER_KEY")
    api_base_url = os.environ.get("HERMES_API_BASE_URL", "http://127.0.0.1:8642")
    board = os.environ.get("HERMES_KANBAN_BOARD", "").strip() or None
    lane = os.environ.get("HERMES_REALTIME_COORDINATOR_LANE", "realtime-voice-control")
    instructions = os.environ.get("HERMES_REALTIME_INSTRUCTIONS", DEFAULT_INSTRUCTIONS)

    server = AgentServer()

    @server.rtc_session(agent_name="hermes-realtime-voice")
    async def entrypoint(ctx: Any) -> None:
        await ctx.connect()
        participant = await ctx.wait_for_participant()
        model = await _build_model(model_factory)
        session_db = SessionDB()
        event_sink = KanbanCoordinatorEventSink(board=board)
        coordinator_wake = HermesApiCoordinatorWake(
            HermesApiCoordinatorConfig(
                base_url=api_base_url,
                api_key=api_key,
                profile=coordinator_profile,
            ),
            event_handler=event_sink.handle,
        )
        authority = HermesAuthorityAdapter(
            HermesAuthorityConfig(
                coordinator_session_id=coordinator_session_id,
                coordinator_profile=coordinator_profile,
                board=board,
                coordinator_lane=lane,
            ),
            approval_resolver=coordinator_wake.respond_approval,
        )
        runtime = LiveKitRealtimeVoiceSession(
            tools=FrontstageToolRouter(authority),
            conversation=HermesVoiceConversation(session_db),
        )
        coordinator = PrimaryCoordinatorPump(
            PrimaryCoordinatorConfig(
                session_id=coordinator_session_id,
                profile=coordinator_profile,
                board=board,
                lane=lane,
            ),
            coordinator_wake,
        )
        announcements = WorkAnnouncementPump(
            WorkAnnouncementConfig(conversation_id=conversation_id, board=board),
            runtime,
        )
        host = RealtimeVoiceHost(
            session=runtime,
            coordinator=coordinator,
            announcements=announcements,
        )

        async def shutdown(reason: str = "job_shutdown") -> None:
            try:
                await host.close(reason)
            finally:
                session_db.close()

        ctx.add_shutdown_callback(shutdown)
        await host.start(
            room=ctx.room,
            config=RealtimeVoiceConfig(
                conversation_id=conversation_id,
                owner_id=owner_id,
                participant_identity=participant.identity,
                instructions=instructions,
                realtime_model=model,
            ),
        )

    return server


def main() -> None:
    from livekit.agents import AgentServer, cli

    server = (
        AgentServer()
        if any(argument in {"-h", "--help"} for argument in sys.argv[1:])
        else create_server()
    )
    cli.run_app(server)

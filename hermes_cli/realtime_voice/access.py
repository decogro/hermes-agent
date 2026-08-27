"""Server-owned LiveKit access for Hermes realtime voice frontends."""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import timedelta
from typing import Callable


class RealtimeVoiceNotConfigured(RuntimeError):
    pass


class RealtimeVoiceRuntimeMissing(RuntimeError):
    pass


@dataclass(frozen=True)
class RealtimeVoiceAccessSettings:
    url: str
    api_key: str
    api_secret: str
    room: str
    conversation_id: str

    @classmethod
    def load(
        cls,
        getter: Callable[[str, str], str | None] = os.getenv,
    ) -> "RealtimeVoiceAccessSettings":
        def read(name: str, default: str = "") -> str:
            return str(getter(name, default) or default).strip()

        return cls(
            url=read("LIVEKIT_URL"),
            api_key=read("LIVEKIT_API_KEY"),
            api_secret=read("LIVEKIT_API_SECRET"),
            room=read("HERMES_REALTIME_ROOM", "hermes-realtime-voice"),
            conversation_id=read(
                "HERMES_VOICE_CONVERSATION_ID", "realtime-voice-main"
            ),
        )

    @property
    def enabled(self) -> bool:
        return self.url.startswith(("ws://", "wss://")) and all(
            (self.api_key, self.api_secret, self.room, self.conversation_id)
        )


def mint_realtime_voice_connection(
    settings: RealtimeVoiceAccessSettings,
    *,
    profile: str = "default",
) -> dict[str, object]:
    if not settings.enabled:
        raise RealtimeVoiceNotConfigured

    try:
        from livekit import api as livekit_api
    except ImportError as exc:
        raise RealtimeVoiceRuntimeMissing from exc

    participant_identity = f"hermes-desktop-{uuid.uuid4().hex}"
    grants = livekit_api.VideoGrants(
        room_join=True,
        room=settings.room,
        can_publish=True,
        can_subscribe=True,
        can_publish_data=True,
    )
    token = (
        livekit_api.AccessToken(settings.api_key, settings.api_secret)
        .with_identity(participant_identity)
        .with_name("Hermes Desktop")
        .with_metadata(json.dumps({"profile": profile}, separators=(",", ":")))
        .with_grants(grants)
        .with_ttl(timedelta(minutes=10))
        .to_jwt()
    )

    return {
        "object": "hermes.realtime_voice.connection",
        "transport": "livekit-webrtc",
        "url": settings.url,
        "room": settings.room,
        "token": token,
        "participant_identity": participant_identity,
        "conversation_id": settings.conversation_id,
        "expires_in": 600,
    }

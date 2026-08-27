"""Deep interface for Hermes' native realtime voice frontstage.

Hermes owns durable conversation, memory, Work, permissions, and delivery
state. Implementations own only an ephemeral realtime media/model session.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Protocol

from .announcements import WorkEvent


TranscriptRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class RealtimeVoiceConfig:
    conversation_id: str
    owner_id: str
    participant_identity: str
    instructions: str
    realtime_model: Any


@dataclass(frozen=True)
class TranscriptTurn:
    conversation_id: str
    role: TranscriptRole
    text: str
    item_id: str | None = None
    interrupted: bool = False


class VoiceConversationPort(Protocol):
    async def append_turn(self, turn: TranscriptTurn) -> None: ...


class RealtimeVoiceSession(Protocol):
    async def start(self, *, room: Any, config: RealtimeVoiceConfig) -> None: ...

    async def announce(self, event: WorkEvent) -> bool: ...

    async def interrupt(self, reason: str = "user_barge_in") -> None: ...

    async def close(self, reason: str = "user_ended") -> None: ...

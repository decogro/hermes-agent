"""Hermes-owned persistence for the one durable Voice Conversation."""

from __future__ import annotations

import asyncio

from hermes_state import SessionDB

from .runtime import TranscriptTurn


class HermesVoiceConversation:
    """Persist final realtime turns in Hermes' existing session database."""

    def __init__(self, db: SessionDB, *, source: str = "realtime_voice") -> None:
        self._db = db
        self._source = source
        self._create_locks: dict[str, asyncio.Lock] = {}

    async def append_turn(self, turn: TranscriptTurn) -> None:
        await self._ensure_conversation(turn.conversation_id)
        platform_message_id = self._platform_message_id(turn)
        if platform_message_id and await asyncio.to_thread(
            self._db.has_platform_message_id,
            turn.conversation_id,
            platform_message_id,
        ):
            return
        await asyncio.to_thread(
            self._db.append_message,
            turn.conversation_id,
            turn.role,
            turn.text,
            platform_message_id=platform_message_id,
            display_kind="realtime_voice",
            display_metadata={"interrupted": turn.interrupted},
        )

    async def _ensure_conversation(self, conversation_id: str) -> None:
        lock = self._create_locks.setdefault(conversation_id, asyncio.Lock())
        async with lock:
            existing = await asyncio.to_thread(self._db.get_session, conversation_id)
            if existing is None:
                await asyncio.to_thread(
                    self._db.create_session,
                    conversation_id,
                    self._source,
                    display_name="Voice Conversation",
                )

    @staticmethod
    def _platform_message_id(turn: TranscriptTurn) -> str | None:
        if not turn.item_id:
            return None
        return f"realtime-voice:{turn.role}:{turn.item_id}"

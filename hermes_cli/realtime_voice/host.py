"""Composition root for one active Hermes realtime Voice Session."""

from __future__ import annotations

import asyncio
from typing import Any

from .coordinator import PrimaryCoordinatorPump
from .delivery import WorkAnnouncementPump
from .runtime import RealtimeVoiceConfig, RealtimeVoiceSession


class RealtimeVoiceHost:
    """Run ephemeral speech while Hermes owns Work and durable conversation."""

    def __init__(
        self,
        *,
        session: RealtimeVoiceSession,
        coordinator: PrimaryCoordinatorPump,
        announcements: WorkAnnouncementPump,
    ) -> None:
        self._session = session
        self._coordinator = coordinator
        self._announcements = announcements
        self._tasks: list[asyncio.Task[None]] = []

    async def start(self, *, room: Any, config: RealtimeVoiceConfig) -> None:
        await self._session.start(room=room, config=config)
        self._tasks = [
            asyncio.create_task(
                self._coordinator.run(), name="realtime-voice-coordinator"
            ),
            asyncio.create_task(
                self._announcements.run(), name="realtime-voice-announcements"
            ),
        ]

    async def close(self, reason: str = "job_shutdown") -> None:
        self._coordinator.stop()
        self._announcements.stop()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
        await self._session.close(reason)

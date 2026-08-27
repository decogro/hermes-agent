"""Reliable delivery of Hermes Work events to active realtime speech."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from typing import Any

from hermes_cli import kanban_db

from .announcements import WorkEvent
from .runtime import RealtimeVoiceSession


logger = logging.getLogger(__name__)


ANNOUNCEMENT_KINDS = (
    "approval_requested",
    "completed",
    "blocked",
    "gave_up",
    "crashed",
    "timed_out",
    "review_requested",
)


@dataclass(frozen=True)
class WorkAnnouncementConfig:
    conversation_id: str
    board: str | None = None
    poll_interval_seconds: float = 1.0


class WorkAnnouncementPump:
    """Claim Kanban events and acknowledge them only after speech finishes."""

    def __init__(
        self,
        config: WorkAnnouncementConfig,
        session: RealtimeVoiceSession,
        *,
        connect=kanban_db.connect_closing,
    ) -> None:
        self._config = config
        self._session = session
        self._connect = connect
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        self._stopped.clear()
        while not self._stopped.is_set():
            try:
                delivered = await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Realtime Work announcement failed; event will retry")
                delivered = False
            if delivered:
                continue
            try:
                await asyncio.wait_for(
                    self._stopped.wait(),
                    timeout=self._config.poll_interval_seconds,
                )
            except TimeoutError:
                pass

    def stop(self) -> None:
        self._stopped.set()

    async def tick(self) -> bool:
        claimed = await asyncio.to_thread(self._claim_one)
        if claimed is None:
            return False
        task_id, old_cursor, new_cursor, events = claimed
        try:
            for event in events:
                played = await self._session.announce(
                    WorkEvent(
                        event_id=event.id,
                        kind=event.kind,
                        payload=event.payload,
                        work_id=event.task_id,
                    )
                )
                if not played:
                    raise RuntimeError("Work announcement was interrupted")
        except BaseException:
            await asyncio.to_thread(
                self._rewind,
                task_id,
                old_cursor,
                new_cursor,
            )
            raise
        return True

    def _claim_one(self) -> tuple[str, int, int, list[Any]] | None:
        with self._connect(board=self._config.board) as conn:
            rows = kanban_db.list_notify_subs(conn)
            for sub in rows:
                if (
                    sub.get("platform") != "realtime_voice"
                    or sub.get("chat_id") != self._config.conversation_id
                ):
                    continue
                old_cursor, new_cursor, events = kanban_db.claim_unseen_events_for_sub(
                    conn,
                    task_id=sub["task_id"],
                    platform="realtime_voice",
                    chat_id=self._config.conversation_id,
                    thread_id=sub.get("thread_id"),
                    kinds=ANNOUNCEMENT_KINDS,
                )
                if events:
                    return sub["task_id"], old_cursor, new_cursor, events
        return None

    def _rewind(self, task_id: str, old_cursor: int, new_cursor: int) -> None:
        with self._connect(board=self._config.board) as conn:
            kanban_db.rewind_notify_cursor(
                conn,
                task_id=task_id,
                platform="realtime_voice",
                chat_id=self._config.conversation_id,
                claimed_cursor=new_cursor,
                old_cursor=old_cursor,
            )

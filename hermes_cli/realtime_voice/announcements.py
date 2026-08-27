"""Push Hermes Work results into an active realtime voice session.

The delivery lifecycle is adapted from QwenAudio/qwen-audio-agent
``server/src/voice/announcement/announcement-manager.mjs`` at commit
``c66cde03e9946e3cc8503cb917d9cd0ee7712989``. Qwen Audio Agent is licensed
under Apache-2.0. See ``docs/third-party/qwen-audio-agent.md``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .provider import RealtimeSession


_TERMINAL_KINDS = {"blocked", "completed", "crashed", "gave_up", "timed_out"}


@dataclass(frozen=True)
class WorkEvent:
    event_id: int
    kind: str
    payload: dict[str, Any] | None
    work_id: str


def _text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _event_result(event: WorkEvent) -> str:
    payload = event.payload or {}
    if event.kind == "completed":
        return _text(payload.get("summary")) or _text(payload.get("result")) or "Work completed."
    if event.kind == "blocked":
        return _text(payload.get("reason")) or "Work is blocked and needs attention."
    return _text(payload.get("error")) or f"Work ended with status {event.kind}."


def format_work_announcement(event: WorkEvent) -> str:
    if event.kind == "approval_requested":
        payload = event.payload or {}
        return "\n".join(
            [
                "<hermes_permission_request>",
                "Hermes needs the user's permission before continuing accepted Work.",
                f"authorization_id: {_text(payload.get('authorization_id'))}",
                f"request: {_text(payload.get('description')) or _text(payload.get('command'))}",
                f"choices: {', '.join(payload.get('choices') or ['once', 'deny'])}",
                "Ask the user clearly. After they answer, call respond_to_work_permission with the authorization_id.",
                "Do not read the authorization_id aloud.",
                "</hermes_permission_request>",
            ]
        )
    return "\n".join(
        [
            "<hermes_work_event>",
            "This is the final or actionable result of previously delegated Work, not a new user request.",
            f"status: {event.kind}",
            f"result: {_event_result(event)}",
            "Briefly tell the user the result in natural speech. Do not expose internal IDs.",
            "</hermes_work_event>",
        ]
    )


class AnnouncementDelivery:
    def __init__(self, session: RealtimeSession, work_ids=()) -> None:
        self._session = session
        self._work_ids = set(work_ids)
        self._delivered: set[int] = set()
        self._in_flight: set[int] = set()

    def add_work(self, work_id: str) -> None:
        self._work_ids.add(work_id)

    def owns(self, work_id: str) -> bool:
        return work_id in self._work_ids

    async def interrupt_speech(self) -> None:
        await self._session.interrupt_speech()

    async def receive(self, event: WorkEvent) -> None:
        if (
            event.kind not in _TERMINAL_KINDS
            or not self.owns(event.work_id)
            or event.event_id in self._delivered
            or event.event_id in self._in_flight
        ):
            return

        self._in_flight.add(event.event_id)
        try:
            outcome = await self._session.inject_announcement(
                {
                    "id": f"work-event:{event.event_id}",
                    "text": format_work_announcement(event),
                    "work_ids": [event.work_id],
                }
            )
            if outcome.get("playback_started") is True:
                self._delivered.add(event.event_id)
        finally:
            self._in_flight.discard(event.event_id)

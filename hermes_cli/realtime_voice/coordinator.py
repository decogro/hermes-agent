"""Delivery from durable Voice Work to one primary Coordinator Session."""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Protocol
from urllib.parse import quote

import httpx
from hermes_cli import kanban_db


logger = logging.getLogger(__name__)


class CoordinatorWakePort(Protocol):
    async def deliver(self, *, session_id: str, work_id: str, text: str) -> None: ...


@dataclass(frozen=True)
class HermesApiCoordinatorConfig:
    base_url: str
    api_key: str
    profile: str
    model: str = "hermes-agent"
    timeout_seconds: float = 600.0


class HermesApiCoordinatorWake:
    """Resume the configured Coordinator through Hermes's observable Runs API."""

    def __init__(
        self,
        config: HermesApiCoordinatorConfig,
        *,
        event_handler: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None,
    ) -> None:
        self._config = config
        self._event_handler = event_handler

    def _profile_url(self, path: str) -> str:
        base = self._config.base_url.rstrip("/")
        profile = quote(self._config.profile, safe="")
        return f"{base}/p/{profile}{path}"

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._config.api_key}"}

    async def deliver(self, *, session_id: str, work_id: str, text: str) -> None:
        if not self._config.api_key:
            raise RuntimeError(
                "Primary Coordinator delivery requires the Hermes API server key"
            )
        payload = {
            "model": self._config.model,
            "input": text,
            "session_id": session_id,
        }
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.post(
                self._profile_url("/v1/runs"),
                headers=self._headers,
                json=payload,
            )
            response.raise_for_status()
            run_id = str(response.json()["run_id"])
            async with client.stream(
                "GET",
                self._profile_url(f"/v1/runs/{quote(run_id, safe='')}/events"),
                headers=self._headers,
            ) as events:
                events.raise_for_status()
                async for line in events.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    event = json.loads(line[6:])
                    if self._event_handler is not None:
                        await self._event_handler(work_id, event)

    async def respond_approval(self, authorization_id: str, decision: str) -> bool:
        aliases = {"approve": "once", "approved": "once", "allow": "once"}
        choice = aliases.get(decision.strip().lower(), decision.strip().lower())
        async with httpx.AsyncClient(timeout=self._config.timeout_seconds) as client:
            response = await client.post(
                self._profile_url(
                    f"/v1/runs/{quote(authorization_id, safe='')}/approval"
                ),
                headers=self._headers,
                json={"choice": choice},
            )
        if response.status_code == 409:
            return False
        response.raise_for_status()
        return bool(response.json().get("resolved"))


class KanbanCoordinatorEventSink:
    """Durably project actionable Runs API events onto the owning Work card."""

    def __init__(self, *, board: str | None = None, connect=kanban_db.connect_closing) -> None:
        self._board = board
        self._connect = connect

    async def handle(self, work_id: str, event: dict[str, Any]) -> None:
        kind = str(event.get("event") or "")
        if kind == "approval.request":
            payload = {
                "authorization_id": str(event.get("run_id") or ""),
                "command": event.get("command"),
                "description": event.get("description"),
                "choices": event.get("choices"),
            }
            await asyncio.to_thread(
                self._append,
                work_id,
                "approval_requested",
                payload,
            )
        elif kind == "run.failed":
            await asyncio.to_thread(
                self._block_if_running,
                work_id,
                str(event.get("error") or "Coordinator run failed"),
            )
        elif kind == "run.completed":
            await asyncio.to_thread(self._ensure_terminal, work_id)

    def _append(self, work_id: str, kind: str, payload: dict[str, Any]) -> None:
        with self._connect(board=self._board) as conn:
            kanban_db.append_task_event(conn, work_id, kind, payload)

    def _block_if_running(self, work_id: str, reason: str) -> None:
        with self._connect(board=self._board) as conn:
            kanban_db.block_task(conn, work_id, reason=reason, kind="transient")

    def _ensure_terminal(self, work_id: str) -> None:
        with self._connect(board=self._board) as conn:
            task = kanban_db.get_task(conn, work_id)
            if task is not None and task.status == "running":
                kanban_db.block_task(
                    conn,
                    work_id,
                    reason=(
                        "The primary Coordinator turn ended without completing, "
                        "blocking, or delegating this Work card."
                    ),
                    kind="transient",
                )


@dataclass(frozen=True)
class PrimaryCoordinatorConfig:
    session_id: str
    profile: str
    board: str | None = None
    lane: str = "realtime-voice-control"
    poll_interval_seconds: float = 1.0
    claim_ttl_seconds: int = 900


class PrimaryCoordinatorPump:
    """Claim Voice Work and resume the one configured Coordinator Session.

    The ordinary Kanban dispatcher ignores the non-profile control lane. This
    pump is the lane's sole consumer and never starts another Hermes session.
    """

    def __init__(
        self,
        config: PrimaryCoordinatorConfig,
        wake: CoordinatorWakePort,
        *,
        connect=kanban_db.connect_closing,
    ) -> None:
        self._config = config
        self._wake = wake
        self._connect = connect
        self._stopped = asyncio.Event()

    async def run(self) -> None:
        self._stopped.clear()
        while not self._stopped.is_set():
            try:
                await self.tick()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Primary Coordinator delivery failed; Work will retry")
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
        task = await asyncio.to_thread(self._claim_next)
        if task is None:
            return False
        try:
            await self._wake.deliver(
                session_id=self._config.session_id,
                work_id=task.id,
                text=self._coordinator_prompt(task),
            )
        except BaseException:
            await asyncio.to_thread(self._release_claim, task.id)
            raise
        return True

    def _claim_next(self) -> Any | None:
        with self._connect(board=self._config.board) as conn:
            tasks = kanban_db.list_tasks(
                conn,
                assignee=self._config.lane,
                status="ready",
                session_id=self._config.session_id,
                limit=1,
            )
            if not tasks:
                return None
            return kanban_db.claim_task(
                conn,
                tasks[0].id,
                ttl_seconds=self._config.claim_ttl_seconds,
                claimer=f"realtime-voice:{self._config.profile}",
            )

    def _release_claim(self, task_id: str) -> None:
        with self._connect(board=self._config.board) as conn:
            kanban_db.reclaim_task(
                conn,
                task_id,
                reason="primary coordinator delivery failed",
            )

    @staticmethod
    def _coordinator_prompt(task: Any) -> str:
        return "\n".join(
            [
                "<realtime_voice_work>",
                "This accepted Work belongs to your existing primary Coordinator Session.",
                "Inspect and manage it through Hermes Kanban. Do not create another voice conversation.",
                f"work_id: {task.id}",
                f"objective: {task.title}",
                f"details:\n{task.body or ''}",
                "Complete, block, or delegate the Work using normal Hermes tools.",
                "</realtime_voice_work>",
            ]
        )

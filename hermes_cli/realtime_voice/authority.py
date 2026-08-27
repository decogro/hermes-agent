"""Hermes authority adapter for realtime frontstage tools."""

from __future__ import annotations

import asyncio
import hashlib
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from hermes_cli import kanban_db
from tools.approval import resolve_gateway_approval
from tools.memory_tool import MemoryStore

from .tools import VoiceToolContext


@dataclass(frozen=True)
class HermesAuthorityConfig:
    coordinator_session_id: str
    coordinator_profile: str
    board: str | None = None
    coordinator_lane: str = "realtime-voice-control"


class HermesAuthorityAdapter:
    """Map the small frontstage tool set to existing Hermes authorities."""

    def __init__(
        self,
        config: HermesAuthorityConfig,
        *,
        memory_factory: Callable[[], MemoryStore] = MemoryStore,
        connect: Callable[..., Any] = kanban_db.connect_closing,
        approval_resolver: Callable[[str, str], Awaitable[bool]] | None = None,
    ) -> None:
        self._config = config
        self._memory_factory = memory_factory
        self._connect = connect
        self._approval_resolver = approval_resolver

    async def memory(self, request: dict[str, Any], context: VoiceToolContext) -> Any:
        del context
        return await asyncio.to_thread(self._read_memory, request.get("document", "all"))

    async def spawn_work(self, request: dict[str, Any], context: VoiceToolContext) -> Any:
        objective = str(request["objective"]).strip()
        work_id = await asyncio.to_thread(
            self._create_work,
            objective,
            list(request.get("input_refs") or ()),
            context,
        )
        return {"status": "accepted", "work_id": work_id}

    async def get_work_status(
        self, request: dict[str, Any], context: VoiceToolContext
    ) -> Any:
        return await asyncio.to_thread(self._get_work_status, request, context)

    async def cancel_work(self, request: dict[str, Any], context: VoiceToolContext) -> Any:
        return await asyncio.to_thread(self._cancel_work, request, context)

    async def respond_to_work_permission(
        self, request: dict[str, Any], context: VoiceToolContext
    ) -> Any:
        decision = str(request["decision"])
        authorization_id = str(request["authorization_id"])
        if self._approval_resolver is not None:
            resolved = await self._approval_resolver(authorization_id, decision)
            return {
                "status": "resolved" if resolved else "not_found",
                "resolved": resolved,
            }
        del context
        resolved = await asyncio.to_thread(
            resolve_gateway_approval,
            self._config.coordinator_session_id,
            decision,
            False,
            None,
            authorization_id,
        )
        return {
            "status": "resolved" if resolved else "not_found",
            "resolved": resolved,
        }

    def _read_memory(self, document: str) -> dict[str, Any]:
        store = self._memory_factory()
        store.load_from_disk()
        selected = ("user", "memory") if document == "all" else (document,)
        return {
            "read_only": True,
            "documents": {
                target: store.format_for_system_prompt(target) or ""
                for target in selected
                if target in {"user", "memory"}
            },
        }

    def _create_work(
        self,
        objective: str,
        input_refs: list[str],
        context: VoiceToolContext,
    ) -> str:
        title = objective.splitlines()[0][:160]
        lines = [
            objective,
            "",
            f"Originating Voice Conversation: {context.voice_session_id}",
        ]
        if context.tool_call_id:
            lines.append(f"Originating voice turn: {context.tool_call_id}")
        if input_refs:
            lines.extend(("", "Input references:", *[f"- {ref}" for ref in input_refs]))
        idempotency_key = None
        if context.tool_call_id:
            raw = f"{context.voice_session_id}:{context.tool_call_id}".encode()
            idempotency_key = "realtime-voice:" + hashlib.sha256(raw).hexdigest()
        with self._connect(board=self._config.board) as conn:
            work_id = kanban_db.create_task(
                conn,
                title=title,
                body="\n".join(lines),
                assignee=self._config.coordinator_lane,
                created_by=f"realtime_voice:{context.owner_id}",
                workspace_kind="scratch",
                idempotency_key=idempotency_key,
                session_id=self._config.coordinator_session_id,
                board=self._config.board,
            )
            kanban_db.add_notify_sub(
                conn,
                task_id=work_id,
                platform="realtime_voice",
                chat_id=context.voice_session_id,
                user_id=context.owner_id,
                chat_type="dm",
                notifier_profile=self._config.coordinator_profile,
                delivery_mode="notify",
            )
        return work_id

    def _owned_tasks(self, conn: Any, context: VoiceToolContext) -> list[Any]:
        return [
            task
            for task in kanban_db.list_tasks(
                conn,
                session_id=self._config.coordinator_session_id,
                include_archived=True,
            )
            if task.created_by == f"realtime_voice:{context.owner_id}"
        ]

    def _get_work_status(
        self, request: dict[str, Any], context: VoiceToolContext
    ) -> dict[str, Any]:
        with self._connect(board=self._config.board) as conn:
            owned = self._owned_tasks(conn, context)
            requested_id = request.get("work_id")
            if requested_id:
                owned = [task for task in owned if task.id == requested_id]
            elif not request.get("list_all"):
                owned = owned[-1:]
            items = []
            for task in owned:
                events = kanban_db.list_events(conn, task.id)
                items.append(
                    {
                        "work_id": task.id,
                        "title": task.title,
                        "status": task.status,
                        "result": task.result,
                        "latest_event": events[-1].kind if events else None,
                    }
                )
        return {"items": items}

    def _cancel_work(
        self, request: dict[str, Any], context: VoiceToolContext
    ) -> dict[str, Any]:
        requested_id = request.get("work_id")
        cancel_all = bool(request.get("all"))
        if not requested_id and not cancel_all:
            raise ValueError("cancel_work requires work_id or all=true")
        cancelled: list[str] = []
        with self._connect(board=self._config.board) as conn:
            tasks = self._owned_tasks(conn, context)
            for task in tasks:
                if requested_id and task.id != requested_id:
                    continue
                if task.status in {"done", "archived"}:
                    continue
                if task.status == "running" or task.claim_lock is not None:
                    kanban_db.reclaim_task(
                        conn,
                        task.id,
                        reason="cancelled from realtime voice",
                    )
                if kanban_db.archive_task(conn, task.id):
                    cancelled.append(task.id)
        return {"status": "cancelled", "work_ids": cancelled}

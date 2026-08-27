from __future__ import annotations

from contextlib import contextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from hermes_cli import kanban_db
from hermes_cli.realtime_voice.authority import (
    HermesAuthorityAdapter,
    HermesAuthorityConfig,
)
from hermes_cli.realtime_voice.conversation import HermesVoiceConversation
from hermes_cli.realtime_voice.coordinator import (
    KanbanCoordinatorEventSink,
    PrimaryCoordinatorConfig,
    PrimaryCoordinatorPump,
)
from hermes_cli.realtime_voice.delivery import (
    WorkAnnouncementConfig,
    WorkAnnouncementPump,
)
from hermes_cli.realtime_voice.runtime import TranscriptTurn
from hermes_cli.realtime_voice.tools import VoiceToolContext
from hermes_state import SessionDB


def connector(db_path):
    @contextmanager
    def connect(*, board=None):
        del board
        with kanban_db.connect_closing(db_path=db_path) as conn:
            yield conn

    return connect


class FakeMemory:
    def load_from_disk(self):
        pass

    def format_for_system_prompt(self, target):
        return {"user": "USER CONTEXT", "memory": "MEMORY CONTEXT"}[target]


@pytest.mark.asyncio
async def test_one_voice_conversation_persists_final_turns_once(tmp_path):
    with SessionDB(tmp_path / "state.db") as db:
        conversation = HermesVoiceConversation(db)
        turn = TranscriptTurn(
            conversation_id="voice-1",
            role="user",
            text="Do the research",
            item_id="provider-item-1",
        )

        await conversation.append_turn(turn)
        await conversation.append_turn(turn)

        assert db.get_session("voice-1")["source"] == "realtime_voice"
        messages = db.get_messages("voice-1")
        assert [(message["role"], message["content"]) for message in messages] == [
            ("user", "Do the research")
        ]


@pytest.mark.asyncio
async def test_authority_reads_memory_and_creates_idempotent_coordinator_work(tmp_path):
    connect = connector(tmp_path / "kanban.db")
    authority = HermesAuthorityAdapter(
        HermesAuthorityConfig(
            coordinator_session_id="coordinator-1",
            coordinator_profile="chief",
        ),
        memory_factory=FakeMemory,
        connect=connect,
    )
    context = VoiceToolContext(
        owner_id="owner-1",
        voice_session_id="voice-1",
        tool_call_id="call-1",
    )

    memory = await authority.memory({"document": "all"}, context)
    first = await authority.spawn_work(
        {"objective": "Compare the vendors", "input_refs": ["document-1"]},
        context,
    )
    second = await authority.spawn_work(
        {"objective": "Compare the vendors", "input_refs": ["document-1"]},
        context,
    )

    assert memory == {
        "read_only": True,
        "documents": {"user": "USER CONTEXT", "memory": "MEMORY CONTEXT"},
    }
    assert second == first
    with connect() as conn:
        tasks = kanban_db.list_tasks(conn, include_archived=True)
        assert len(tasks) == 1
        task = tasks[0]
        assert task.id == first["work_id"]
        assert task.assignee == "realtime-voice-control"
        assert task.session_id == "coordinator-1"
        assert "Originating Voice Conversation: voice-1" in task.body
        subs = kanban_db.list_notify_subs(conn, task.id)
        assert subs[0]["platform"] == "realtime_voice"
        assert subs[0]["chat_id"] == "voice-1"


@pytest.mark.asyncio
async def test_authority_routes_permission_response_to_active_coordinator_run(tmp_path):
    resolver = AsyncMock(return_value=True)
    authority = HermesAuthorityAdapter(
        HermesAuthorityConfig(
            coordinator_session_id="coordinator-1",
            coordinator_profile="chief",
        ),
        memory_factory=FakeMemory,
        connect=connector(tmp_path / "kanban.db"),
        approval_resolver=resolver,
    )

    result = await authority.respond_to_work_permission(
        {"authorization_id": "run-1", "decision": "once"},
        VoiceToolContext(owner_id="owner-1", voice_session_id="voice-1"),
    )

    assert result == {"status": "resolved", "resolved": True}
    resolver.assert_awaited_once_with("run-1", "once")


@pytest.mark.asyncio
async def test_primary_coordinator_pump_resumes_one_session_without_spawning_another(tmp_path):
    connect = connector(tmp_path / "kanban.db")
    with connect() as conn:
        task_id = kanban_db.create_task(
            conn,
            title="Research",
            body="Exact request",
            assignee="realtime-voice-control",
            created_by="realtime_voice:owner-1",
            session_id="coordinator-1",
        )
    wake = SimpleNamespace(deliver=AsyncMock())
    pump = PrimaryCoordinatorPump(
        PrimaryCoordinatorConfig(session_id="coordinator-1", profile="chief"),
        wake,
        connect=connect,
    )

    assert await pump.tick() is True

    wake.deliver.assert_awaited_once()
    assert wake.deliver.await_args.kwargs["session_id"] == "coordinator-1"
    assert wake.deliver.await_args.kwargs["work_id"] == task_id
    assert f"work_id: {task_id}" in wake.deliver.await_args.kwargs["text"]
    with connect() as conn:
        assert kanban_db.get_task(conn, task_id).status == "running"


@pytest.mark.asyncio
async def test_coordinator_delivery_failure_releases_work_for_retry(tmp_path):
    connect = connector(tmp_path / "kanban.db")
    with connect() as conn:
        task_id = kanban_db.create_task(
            conn,
            title="Research",
            assignee="realtime-voice-control",
            session_id="coordinator-1",
        )
    wake = SimpleNamespace(deliver=AsyncMock(side_effect=RuntimeError("offline")))
    pump = PrimaryCoordinatorPump(
        PrimaryCoordinatorConfig(session_id="coordinator-1", profile="chief"),
        wake,
        connect=connect,
    )

    with pytest.raises(RuntimeError, match="offline"):
        await pump.tick()

    with connect() as conn:
        assert kanban_db.get_task(conn, task_id).status == "ready"


@pytest.mark.asyncio
async def test_work_announcement_is_deduplicated_after_playout(tmp_path):
    connect = connector(tmp_path / "kanban.db")
    with connect() as conn:
        task_id = kanban_db.create_task(
            conn,
            title="Research",
            assignee="realtime-voice-control",
        )
        kanban_db.add_notify_sub(
            conn,
            task_id=task_id,
            platform="realtime_voice",
            chat_id="voice-1",
        )
        kanban_db.complete_task(conn, task_id, result="Finished")
    session = AsyncMock()
    session.announce.return_value = True
    pump = WorkAnnouncementPump(
        WorkAnnouncementConfig(conversation_id="voice-1"),
        session,
        connect=connect,
    )

    assert await pump.tick() is True
    assert await pump.tick() is False

    event = session.announce.await_args.args[0]
    assert event.work_id == task_id
    assert event.kind == "completed"


@pytest.mark.asyncio
async def test_coordinator_permission_event_is_announced_with_authorization_id(tmp_path):
    connect = connector(tmp_path / "kanban.db")
    with connect() as conn:
        task_id = kanban_db.create_task(
            conn,
            title="Install dependency",
            assignee="realtime-voice-control",
        )
        kanban_db.add_notify_sub(
            conn,
            task_id=task_id,
            platform="realtime_voice",
            chat_id="voice-1",
        )
    sink = KanbanCoordinatorEventSink(connect=connect)
    await sink.handle(
        task_id,
        {
            "event": "approval.request",
            "run_id": "run-1",
            "description": "Install the requested package",
            "choices": ["once", "deny"],
        },
    )
    session = AsyncMock()
    session.announce.return_value = True
    pump = WorkAnnouncementPump(
        WorkAnnouncementConfig(conversation_id="voice-1"),
        session,
        connect=connect,
    )

    assert await pump.tick() is True
    event = session.announce.await_args.args[0]
    assert event.kind == "approval_requested"
    assert event.payload["authorization_id"] == "run-1"


@pytest.mark.asyncio
async def test_coordinator_turn_that_leaves_work_running_is_blocked(tmp_path):
    connect = connector(tmp_path / "kanban.db")
    with connect() as conn:
        task_id = kanban_db.create_task(
            conn,
            title="Research",
            assignee="realtime-voice-control",
        )
        kanban_db.claim_task(conn, task_id, claimer="voice-test")
    sink = KanbanCoordinatorEventSink(connect=connect)

    await sink.handle(task_id, {"event": "run.completed", "run_id": "run-1"})

    with connect() as conn:
        task = kanban_db.get_task(conn, task_id)
        assert task.status == "blocked"
        blocked = [event for event in kanban_db.list_events(conn, task_id) if event.kind == "blocked"]
        assert "without completing" in blocked[-1].payload["reason"]


@pytest.mark.asyncio
async def test_interrupted_announcement_rewinds_cursor_for_retry(tmp_path):
    connect = connector(tmp_path / "kanban.db")
    with connect() as conn:
        task_id = kanban_db.create_task(conn, title="Research")
        kanban_db.add_notify_sub(
            conn,
            task_id=task_id,
            platform="realtime_voice",
            chat_id="voice-1",
        )
        kanban_db.complete_task(conn, task_id, result="Finished")
    session = AsyncMock()
    session.announce.side_effect = [False, True]
    pump = WorkAnnouncementPump(
        WorkAnnouncementConfig(conversation_id="voice-1"),
        session,
        connect=connect,
    )

    with pytest.raises(RuntimeError, match="interrupted"):
        await pump.tick()
    assert await pump.tick() is True
    assert session.announce.await_count == 2

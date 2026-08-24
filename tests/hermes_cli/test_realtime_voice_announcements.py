from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from hermes_cli.realtime_voice.announcements import AnnouncementDelivery, WorkEvent


COMPLETED = WorkEvent(
    event_id=12,
    kind="completed",
    payload={"summary": "The vendor comparison is ready."},
    work_id="work-1",
)


@pytest.mark.asyncio
async def test_terminal_event_is_pushed_into_active_speech_session():
    session = AsyncMock()
    session.inject_announcement.return_value = {"playback_started": True}
    delivery = AnnouncementDelivery(session, ["work-1"])

    await delivery.receive(COMPLETED)

    call = session.inject_announcement.await_args.args[0]
    assert call["id"] == "work-event:12"
    assert call["work_ids"] == ["work-1"]
    assert "The vendor comparison is ready." in call["text"]


@pytest.mark.asyncio
async def test_event_for_other_voice_session_work_is_ignored():
    session = AsyncMock()
    delivery = AnnouncementDelivery(session, ["work-2"])

    await delivery.receive(COMPLETED)

    session.inject_announcement.assert_not_awaited()


@pytest.mark.asyncio
async def test_event_is_deduplicated_only_after_playback_starts():
    session = AsyncMock()
    session.inject_announcement.return_value = {"playback_started": False}
    delivery = AnnouncementDelivery(session, ["work-1"])

    await delivery.receive(COMPLETED)
    await delivery.receive(COMPLETED)
    assert session.inject_announcement.await_count == 2

    session.inject_announcement.return_value = {"playback_started": True}
    await delivery.receive(COMPLETED)
    await delivery.receive(COMPLETED)
    assert session.inject_announcement.await_count == 3


@pytest.mark.asyncio
async def test_barge_in_interrupts_speech_without_cancelling_work():
    session = AsyncMock()
    delivery = AnnouncementDelivery(session, ["work-1"])

    await delivery.interrupt_speech()

    session.interrupt_speech.assert_awaited_once()
    assert delivery.owns("work-1")

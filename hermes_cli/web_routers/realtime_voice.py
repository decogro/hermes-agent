"""Authenticated dashboard route for native realtime voice access."""

from fastapi import APIRouter, HTTPException

from hermes_cli.realtime_voice.access import (
    RealtimeVoiceAccessSettings,
    RealtimeVoiceNotConfigured,
    RealtimeVoiceRuntimeMissing,
    mint_realtime_voice_connection,
)

router = APIRouter()


@router.post("/api/realtime-voice/token")
def create_realtime_voice_token() -> dict[str, object]:
    try:
        return mint_realtime_voice_connection(RealtimeVoiceAccessSettings.load())
    except RealtimeVoiceNotConfigured as exc:
        raise HTTPException(
            status_code=404,
            detail="Native realtime voice is not configured on this Hermes gateway.",
        ) from exc
    except RealtimeVoiceRuntimeMissing as exc:
        raise HTTPException(
            status_code=503,
            detail="The Hermes realtime voice runtime is not installed.",
        ) from exc

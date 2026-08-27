from __future__ import annotations

import jwt

from hermes_cli.realtime_voice.access import (
    RealtimeVoiceAccessSettings,
    mint_realtime_voice_connection,
)


def test_realtime_voice_access_is_disabled_without_durable_conversation():
    settings = RealtimeVoiceAccessSettings(
        url="wss://voice.example.test",
        api_key="livekit-key",
        api_secret="livekit-secret-that-is-long-enough",
        room="hermes-room",
        conversation_id="",
    )

    assert settings.enabled is False


def test_minted_access_is_scoped_to_server_room_and_short_lived():
    settings = RealtimeVoiceAccessSettings(
        url="wss://voice.example.test",
        api_key="livekit-key",
        api_secret="livekit-secret-that-is-long-enough",
        room="one-hermes-room",
        conversation_id="voice-conversation",
    )

    payload = mint_realtime_voice_connection(settings, profile="chief")
    claims = jwt.decode(
        payload["token"],
        settings.api_secret,
        algorithms=["HS256"],
        options={"verify_aud": False},
    )

    assert payload["transport"] == "livekit-webrtc"
    assert payload["room"] == "one-hermes-room"
    assert payload["conversation_id"] == "voice-conversation"
    assert payload["expires_in"] == 600
    assert claims["video"]["room"] == "one-hermes-room"
    assert claims["video"]["roomJoin"] is True
    assert claims["metadata"] == '{"profile":"chief"}'
    assert 0 < claims["exp"] - claims["nbf"] <= 600


def test_dashboard_registers_realtime_voice_token_route():
    from hermes_cli.web_server import app

    routes = {(method, route.path) for route in app.routes for method in getattr(route, "methods", set())}

    assert ("POST", "/api/realtime-voice/token") in routes


def test_dashboard_realtime_voice_token_uses_existing_dashboard_auth(monkeypatch):
    from fastapi.testclient import TestClient

    from hermes_cli.web_server import _SESSION_HEADER_NAME, _SESSION_TOKEN, app

    monkeypatch.setenv("LIVEKIT_URL", "wss://voice.example.test")
    monkeypatch.setenv("LIVEKIT_API_KEY", "livekit-key")
    monkeypatch.setenv(
        "LIVEKIT_API_SECRET", "livekit-secret-that-is-long-enough"
    )
    client = TestClient(app)

    assert client.post("/api/realtime-voice/token").status_code == 401
    response = client.post(
        "/api/realtime-voice/token",
        headers={_SESSION_HEADER_NAME: _SESSION_TOKEN},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["room"] == "hermes-realtime-voice"
    assert payload["conversation_id"] == "realtime-voice-main"

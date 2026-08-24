"""Provider-neutral contracts for realtime speech-to-speech sessions.

The registry design is adapted from QwenAudio/qwen-audio-agent
``server/src/voice/providers/provider-registry.mjs`` at commit
``c66cde03e9946e3cc8503cb917d9cd0ee7712989``. Qwen Audio Agent is licensed
under Apache-2.0. See ``docs/third-party/qwen-audio-agent.md``.
"""

from __future__ import annotations

import builtins
from collections.abc import Iterable, Sequence
from typing import Any, Protocol


class RealtimeSession(Protocol):
    async def append_audio(self, audio: bytes) -> None: ...

    async def submit_tool_result(self, call_id: str, output: Any) -> None: ...

    async def inject_announcement(self, announcement: dict[str, Any]) -> dict[str, Any]: ...

    async def interrupt_speech(self) -> None: ...

    async def wait_closed(self) -> None: ...

    async def close(self) -> None: ...


class RealtimeProvider(Protocol):
    key: str
    label: str
    aliases: Sequence[str]
    input_sample_rate: int
    output_sample_rate: int

    def is_configured(self) -> bool: ...

    async def connect(self, options: dict[str, Any]) -> RealtimeSession: ...


def _clean_name(value: str) -> str:
    return str(value or "").strip().lower()


def _validate_provider(provider: RealtimeProvider) -> None:
    key = _clean_name(provider.key)
    if not key or not key[0].isalnum() or any(
        not (character.islower() or character.isdigit() or character == "-")
        for character in key
    ):
        raise ValueError(f"Invalid realtime provider key: {provider.key}")
    if not str(provider.label or "").strip():
        raise ValueError(f"Realtime provider {key} has no label")
    for attribute in ("input_sample_rate", "output_sample_rate"):
        value = getattr(provider, attribute, 0)
        if not isinstance(value, (int, float)) or value <= 0:
            raise ValueError(f"Realtime provider {key} has invalid {attribute}")


class RealtimeProviderRegistry:
    def __init__(self, providers: Iterable[RealtimeProvider] = ()) -> None:
        self._providers: dict[str, RealtimeProvider] = {}
        self._names: dict[str, str] = {}
        for provider in providers:
            self.register(provider)

    def register(self, provider: RealtimeProvider) -> RealtimeProvider:
        _validate_provider(provider)
        key = _clean_name(provider.key)
        names = [key, *(_clean_name(alias) for alias in provider.aliases)]
        for name in names:
            if not name:
                raise ValueError(f"Realtime provider {key} has an empty alias")
            if name in self._names:
                raise ValueError(f"Realtime provider name already registered: {name}")
        self._providers[key] = provider
        for name in names:
            self._names[name] = key
        return provider

    def resolve(self, requested: str) -> RealtimeProvider:
        name = _clean_name(requested)
        key = self._names.get(name)
        provider = self._providers.get(key or "")
        if provider is None:
            raise ValueError(f"Unsupported realtime provider: {name or requested}")
        return provider

    def list(self, *, configured_only: bool = True) -> builtins.list[RealtimeProvider]:
        return [
            provider
            for provider in self._providers.values()
            if not configured_only or provider.is_configured()
        ]

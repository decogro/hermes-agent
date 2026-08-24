from __future__ import annotations

from dataclasses import dataclass

import pytest

from hermes_cli.realtime_voice.provider import RealtimeProviderRegistry


@dataclass
class FakeProvider:
    key: str
    aliases: tuple[str, ...] = ()
    configured: bool = True
    input_sample_rate: int = 16_000
    output_sample_rate: int = 24_000

    @property
    def label(self) -> str:
        return self.key.upper()

    def is_configured(self) -> bool:
        return self.configured

    async def connect(self, options):
        raise NotImplementedError


def test_registry_resolves_canonical_key_and_alias():
    qwen = FakeProvider("qwen", aliases=("dashscope",))
    registry = RealtimeProviderRegistry([qwen])

    assert registry.resolve("qwen") is qwen
    assert registry.resolve("DASHSCOPE") is qwen


def test_registry_rejects_duplicate_aliases():
    with pytest.raises(ValueError, match="already registered: live"):
        RealtimeProviderRegistry(
            [FakeProvider("one", aliases=("live",)), FakeProvider("two", aliases=("live",))]
        )


def test_registry_lists_only_configured_providers_by_default():
    configured = FakeProvider("configured")
    unavailable = FakeProvider("unavailable", configured=False)
    registry = RealtimeProviderRegistry([configured, unavailable])

    assert [provider.key for provider in registry.list()] == ["configured"]
    assert [provider.key for provider in registry.list(configured_only=False)] == [
        "configured",
        "unavailable",
    ]

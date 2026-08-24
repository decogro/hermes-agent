# Qwen Audio Agent notice

Parts of the realtime voice provider registry and frontend tool contract are
adapted from [Qwen Audio Agent](https://github.com/QwenAudio/qwen-audio-agent)
at commit `c66cde03e9946e3cc8503cb917d9cd0ee7712989`.

Qwen Audio Agent is licensed under the Apache License 2.0. The upstream notice
is reproduced below.

> qwen-audio-agent  
> Copyright 2026 qwen-audio-agent contributors
>
> This product includes software developed by third-party open-source projects.
> See the upstream `THIRD_PARTY_NOTICES.md` for the primary component notices.

Hermes-specific changes include TypeScript interfaces, provider-neutral tool
names, Qwen-compatible aliases, English tool instructions, and replacement of
Qwen memory and task services with injected Hermes ports.

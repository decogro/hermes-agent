# Pipecat vs LiveKit for Hermes realtime voice

Status: researched 2026-08-27. Sources are current official documentation or upstream GitHub source.

## Decision

Use **LiveKit Agents as the disposable realtime voice runtime**, backed by
LiveKit WebRTC transport. Do not add Pipecat initially.

This does not make LiveKit a second durable agent system. Hermes remains the
only application authority. LiveKit's `AgentSession` is used only as the active
media/model session: it moves audio, runs the selected native speech-to-speech
model, handles turns and interruption, exposes the narrow Hermes frontend tool
set, and speaks pushed announcements.

Do not use LiveKit Workflows, agent handoffs, task groups, memory, or any other
feature that would compete with Hermes coordination, Kanban, sessions, or
durable state.

Pipecat is a valid alternative and is somewhat less opinionated as a frame
pipeline. It would be attractive for a desktop-only embedded prototype.
However, the product also requires a real iPhone path. Once LiveKit is already
present for WebRTC, its Agents framework supplies the same required native S2S
adapter, turn, interruption, tool, async-tool, and speech-injection layer.
Adding Pipecat would create another provider/session/event abstraction without
removing LiveKit.

## Target architecture

```text
Hermes desktop or iPhone client
        |
        | LiveKit WebRTC audio and authenticated data
        v
LiveKit Server or LiveKit Cloud
        |
        v
Hermes Realtime Voice Gateway
  - hosts one disposable LiveKit AgentSession while voice is connected
  - owns the canonical voice transcript and recovery
  - owns provider selection and capability checks
  - maps the frontend tools into Hermes authority
        |
        +---- selected native S2S RealtimeModel plugin
        |       OpenAI Realtime, Gemini Live, Grok Voice, Nova Sonic, etc.
        |
        +---- Hermes read-only profile memory
        +---- Hermes Kanban and the one voice-attached Coordinator Session
        +---- Hermes status, permission, cancellation, and completion events
```

The names in LiveKit can be misleading in this architecture:

- `AgentSession` means the temporary realtime media/model session. It is not a
  Hermes coordinator and is not durable.
- The thin LiveKit `Agent` contains only the voice persona and the narrow
  frontend tools. It does not execute durable work.
- Hermes remains the only owner of the one durable Voice Conversation, memory,
  Work, permissions, coordinator, and Layer 3 worker sessions.

## Why LiveKit Agents wins for this product

| Requirement | Pipecat | LiveKit Agents | Decision |
|---|---|---|---|
| Native S2S models | Provider-specific realtime services behind a common frame pipeline | Provider-specific `RealtimeModel` plugins behind `AgentSession` | Both qualify |
| Full duplex and barge-in | Interruption frames and interruptible audio output | Provider/server turn detection, speech interruption, and heard-audio history truncation | Both qualify |
| Hermes tools and async Work | Deferred function results and later context injection | Background tools plus `session.say()` and `generate_reply()` | Both qualify |
| iPhone transport | Pipecat Swift client plus a selected transport; production remote media still needs Daily, LiveKit, or equivalent | First-party Swift SDK and the same LiveKit room used by the agent runtime | LiveKit is one integrated path |
| Provider swapping | Swap Pipecat realtime service, subject to capability differences | Swap `RealtimeModel` plugin, subject to capability differences | Both qualify |
| Framework count with production iPhone | Pipecat plus a production WebRTC system such as LiveKit | LiveKit server/client plus LiveKit Agents | LiveKit avoids the extra runtime |

LiveKit's current realtime-model catalog includes Amazon Nova Sonic, Azure
OpenAI Realtime, Gemini Live, NVIDIA PersonaPlex, OpenAI Realtime, Phonic,
Ultravox, and xAI Grok Voice Agent. Pipecat has comparable native S2S coverage.
Neither framework makes an unsupported provider work automatically; a provider
outside its plugin catalog needs a custom adapter.

Sources:

- [LiveKit realtime models](https://docs.livekit.io/agents/models/realtime/)
- [LiveKit AgentSession](https://docs.livekit.io/agents/logic/sessions/)
- [LiveKit turns and interruptions](https://docs.livekit.io/agents/logic/turns/)
- [LiveKit tools](https://docs.livekit.io/agents/logic/tools/)
- [LiveKit Swift SDK](https://github.com/livekit/client-sdk-swift)
- [Pipecat supported services](https://docs.pipecat.ai/api-reference/server/services/supported-services)
- [Pipecat LiveKit transport](https://docs.pipecat.ai/api-reference/server/services/transport/livekit)
- [Pipecat RTVI](https://docs.pipecat.ai/api-reference/server/rtvi/introduction)

## Exact ownership boundary

### LiveKit owns only ephemeral realtime mechanics

- WebRTC rooms, tracks, and data transport
- the active provider connection
- current-turn audio buffering
- provider-native turn detection
- barge-in and stopping active speech
- temporary provider context
- translating provider function calls into gateway callbacks
- speaking text or provider-generated audio into the active room

### Hermes owns all durable meaning

- the single durable Voice Conversation
- the canonical transcript
- the voice identity and profile memory
- Hermes Work and Kanban IDs
- the one voice-attached Coordinator Session
- permissions and authorization
- status, cancellation, and completion events
- Layer 3 worker and sub-coordinator sessions
- announcement deduplication and delivery policy

The active LiveKit session may hold a temporary context projection, but it is
never the source of truth. Reconnect creates a new `AgentSession` and rehydrates
it from the same Hermes Voice Conversation.

## Hermes tool and completion flow

1. The native S2S model handles conversation directly.
2. If the user requests any action, the model calls a narrow function such as
   `spawn_work`.
3. That function writes Hermes Work and returns an accepted receipt immediately.
4. The Hermes coordinator continues independently while voice stays available.
5. Hermes emits questions, permissions, status, or completion events.
6. The gateway calls `session.say()` or `generate_reply()` to present the event
   through the active native voice session.
7. If voice is disconnected, Hermes retains the event for the next connection.

LiveKit documents background tools specifically for work that should not block
the conversation. This maps directly to Hermes Work acceptance and later
completion delivery.

Sources:

- [LiveKit async and interruptible tools](https://docs.livekit.io/agents/logic/tools/definition/)
- [LiveKit agent speech](https://docs.livekit.io/agents/multimodality/audio/)

## Required custom code

We still need a narrow Hermes integration. No framework knows Hermes semantics.
The custom work should be limited to:

1. A `HermesRealtimeVoiceSession` wrapper around LiveKit `AgentSession`.
2. A provider selector and capability matrix for supported native S2S plugins.
3. The frontend tool bridge: read memory, spawn Work, get status, cancel Work,
   and answer permission requests.
4. Canonical transcript reconciliation and provider rehydration.
5. A Hermes event subscription that injects questions and completions into the
   active voice session.
6. Client playback receipts so Hermes can distinguish audio publication from
   audio actually started, completed, or interrupted on the device.

## What not to build

- Do not add Pipecat unless a measured requirement cannot be met by LiveKit
  Agents.
- Do not use LiveKit Workflows, task groups, agent handoffs, or durable memory.
- Do not build a second coordinator, transcript, Kanban, or permission system.
- Do not build our own WebRTC, SFU, ICE/TURN, or iPhone audio transport.
- Do not anchor the design or first provider on Qwen.
- Do not use the existing turn-based Hermes Voice STT/LLM/TTS loop.
- Do not let provider-native tools bypass Hermes authorization.

## Caveats and acceptance gates

1. `RealtimeModel` is provider-neutral at the gateway boundary, not universally
   compatible. Each provider must pass a capability and behavior test.
2. Qwen Audio Realtime currently needs a custom LiveKit plugin if we decide to
   support it. That is not a reason to make Qwen the foundation.
3. The client must verify microphone behavior, barge-in, stale playback
   cancellation, Wi-Fi/cellular transition, reconnect, and audio-session state.
4. Hermes must commit one canonical transcript and discard unheard generated
   text after interruption.
5. Provider credentials remain server-side. The client receives only short-lived
   room access.
6. A native provider failure is explicit and does not fall back to Legacy
   Hermes Voice.

## Final recommendation

Build the new Hermes realtime voice path on **LiveKit Agents plus LiveKit
WebRTC**, with a deliberately thin `AgentSession` and Hermes behind every tool.

This is the smallest complete architecture for the actual product. Pipecat is
cleaner only when judged as a low-level embedded pipeline in isolation. It is
not cleaner after the production iPhone transport is included, because LiveKit
is required anyway and LiveKit Agents already provides the necessary realtime
model and conversation mechanics.

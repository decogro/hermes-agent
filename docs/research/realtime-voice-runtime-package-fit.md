# Realtime Voice Runtime Package Fit

Status: decided 2026-08-27

## Decision

Use LiveKit Agents and LiveKit WebRTC for the new Hermes Realtime Frontstage.
Do not add Pipecat or make Qwen the implementation foundation.

LiveKit `AgentSession` is the disposable Voice Session runtime. It owns only
live media/model mechanics: WebRTC room I/O, the active native S2S provider
connection, turn detection, barge-in, temporary context, function-call
translation, and speech output.

Hermes remains the sole durable authority for the Voice Conversation,
canonical transcript, read-only profile memory, Work and Kanban, the primary
Coordinator Session, permissions, worker sessions, recovery, and Announcement
delivery.

The detailed package comparison is recorded in
[`pipecat-vs-livekit-decision.md`](./pipecat-vs-livekit-decision.md).

## Deep module and seam

The implementation should expose one small Hermes-facing module:

```text
HermesRealtimeVoiceSession
  start(conversation_id, audio_owner, provider_config)
  announce(work_event)
  interrupt(reason)
  close(reason)
```

Everything else stays inside its implementation:

- LiveKit room and token lifecycle
- `AgentSession` and the thin LiveKit `Agent`
- `RealtimeModel` plugin creation
- provider capability checks
- live transcript and interruption events
- frontend tool registration and translation
- reconnect and context rehydration
- client playback receipt correlation

Callers should not manipulate LiveKit rooms, participants, speech handles, or
provider sessions directly.

## LiveKit features we use

- LiveKit WebRTC rooms and the first-party desktop/mobile client SDKs
- one `AgentSession` per active Voice Session
- one thin `Agent` containing only voice instructions and the Frontstage Tool
  Set
- native S2S `RealtimeModel` plugins
- provider-native or LiveKit turn detection and interruption
- background function tools
- `session.say()` or `generate_reply()` for Hermes Announcements
- session events for transient transcript and lifecycle observation

## LiveKit features we do not use

- Workflows
- task groups
- agent handoffs
- LiveKit-owned durable memory or conversation history
- LiveKit-owned backend coordination
- provider-native tools that bypass Hermes authorization

Those features would compete with existing Hermes capabilities and violate the
single-authority decision.

## Frontstage Tool Set

The native S2S model receives only these Hermes operations:

1. read the existing profile Memory Context;
2. spawn durable Work and immediately return its Work ID;
3. read Work status;
4. request cancellation of Work; and
5. answer an active Hermes permission request.

The thin LiveKit `Agent` never performs substantive Work. It either replies
directly from the live conversation and read-only Memory Context or creates
Hermes Work for the primary Coordinator Session.

## Completion path

```text
Hermes Work Event
  -> Announcement policy and deduplication
  -> active HermesRealtimeVoiceSession.announce(...)
  -> LiveKit AgentSession speech generation
  -> LiveKit room audio
  -> client playback receipt
  -> Hermes delivery acknowledgement
```

If no Voice Session is active, Hermes keeps the Announcement pending. Barge-in
stops speech but does not cancel accepted Work.

## Model decision

The permanent native S2S model is intentionally not selected by this package
decision. The framework can be built against LiveKit's `RealtimeModel` seam and
a controlled test implementation.

One currently supported provider will be selected as an initial integration
fixture before the vertical slice can pass end to end. That choice is not a
product commitment. Permanent selection happens only after the same benchmark
harness measures candidate providers for:

1. first spoken-response latency;
2. audible barge-in latency;
3. immediate Work acceptance while conversation remains available;
4. pushed background questions and completions;
5. reconnect and Hermes context rehydration;
6. transcript and interruption reconciliation;
7. duplicate prevention after recovery; and
8. cost per active audio minute.

## First vertical slice

1. Start an authenticated LiveKit room from Hermes desktop.
2. Host one disposable `AgentSession` in the Hermes Realtime Voice Gateway.
3. Connect one supported native S2S `RealtimeModel` as a test fixture.
4. Complete a direct spoken exchange with working barge-in.
5. Expose only read-only memory, spawn Work, status, cancel, and permission
   response tools.
6. Route one `spawn_work` call into the existing Hermes Kanban and primary
   Coordinator Session.
7. Return the accepted Work receipt immediately.
8. Inject the eventual Hermes completion into the same active Voice Session.
9. Confirm delivery only from a client playback event.

The slice is incomplete until all nine steps work end to end. Unit mocks or a
streaming text response are not proof of realtime voice behavior.

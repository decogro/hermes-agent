# Hermes hosts the realtime voice frontstage

Hermes is the host product and the only durable owner of memory, Work,
permissions, coordination, sessions, and results. Realtime voice is added as a
provider-neutral Hermes module built on LiveKit Agents and LiveKit WebRTC.
LiveKit supplies the disposable realtime media/model session. The permanent
native speech-to-speech model is deliberately deferred until the common
acceptance harness can compare supported providers.

The Hermes Voice Gateway owns the entire realtime control plane: Voice
Conversation identity, authoritative transcript, context compaction, provider
session creation and recovery, Audio Ownership, tool execution, Work routing,
and result delivery. It hosts one disposable LiveKit `AgentSession` for the
active Voice Session. A Realtime Provider owns only native speech-to-speech
inference and its connection-level protocol. LiveKit and provider-native
context, truncation, or resumption may be used as live-session optimizations
but never as durable authority.

This module does not reuse Hermes Voice's existing dictation, STT, TTS,
auto-speak, or voice-conversation loop. Those primitives are turn-based and
cannot keep a native speech session available while durable Hermes Work runs.
Desktop and mobile clients join the same authenticated LiveKit room as audio
and data participants. They do not call the model provider directly.

The realtime path is additional infrastructure inside the Hermes harness. It
does not replace Hermes's general JSON-RPC gateway, existing session and tool
runtime, or Legacy Hermes Voice. The general gateway and legacy audio endpoints
remain available while realtime voice uses LiveKit WebRTC plus a narrow Hermes
control interface.

The Realtime Provider receives only the Frontstage Tool Set: read-only memory,
`spawn_work`, `get_work_status`, `cancel_work`, and
`respond_to_work_permission`. Those operations map to existing Hermes profile
context, Kanban, session, and permission capabilities. Completed Work returns
through pushed Work Events and is spoken as an Announcement. The Voice Session
remains separate from the Coordinator Session.

The system has exactly one durable Voice Conversation and one primary
Coordinator Session paired with it. Realtime provider connections may stop and
resume against that same Voice Conversation. Any additional coordinator-like
or worker sessions are backend Layer 3 sessions, have no voice conversation,
and report through the primary Coordinator Session.

The Voice Conversation and primary Coordinator Session are permanently bound
to one dedicated Coordinator Profile. Other profiles may be selected for
delegated Work without changing the voice identity or replacing the primary
Coordinator.

## Considered options

- A Qwen Audio Agent fork with Hermes behind it was rejected because Hermes is
  the dominant application, interface, and system of record.
- A Qwen-first provider implementation was rejected because the architecture
  does not require Qwen and LiveKit does not currently ship a Qwen realtime
  plugin.
- Pipecat plus LiveKit transport was rejected for the initial implementation
  because LiveKit Agents already supplies the required realtime model session,
  interruption, tool, and speech-injection mechanics. Pipecat would add a
  second session and provider abstraction without removing LiveKit.
- A streaming STT to blocking Hermes turn to streaming TTS pipeline was
  rejected because it makes the conversation unavailable while Hermes works.
- Extending the existing Hermes Voice loop was rejected for the same reason;
  swapping its STT/TTS providers does not create a native duplex Voice Session.
- Keeping Qwen memory or TaskManager state was rejected because it would create
  competing durable authorities.
- Allowing the Realtime Provider to mutate Hermes memory was rejected because
  the frontstage needs profile context, not a second path for curating it.

## Consequences

- LiveKit `AgentSession` is an implementation detail of the temporary Voice
  Session, not a Hermes Coordinator Session or durable transcript.
- LiveKit Workflows, task groups, agent handoffs, and memory are not used.
- Provider-specific behavior stays behind LiveKit's `RealtimeModel` seam plus a
  small Hermes capability check. Unsupported providers require a new LiveKit
  adapter.
- The realtime module is an additional Hermes path; the general gateway and
  Legacy Hermes Voice remain separate and unchanged.
- Any previously copied Qwen source retains required Apache-2.0 attribution and
  change notices but is not the implementation foundation.
- Hermes Kanban and sessions remain authoritative even when voice disconnects.
- Realtime providers must support streaming speech, tool calls, interruption,
  context injection, and background-result presentation.
- Desktop is the first complete client; mobile later joins the same LiveKit
  room and Hermes control interface.
- Screen observation is outside the initial realtime-voice scope.
- A native provider failure is explicit and never falls back to Legacy Hermes
  Voice.
- Whether the Coordinator Session executes Work directly or delegates it is a
  profile prompt and tool-configuration policy, not Voice Gateway logic.
- Layer 3 worker creation, dispatch, execution, and worker-session management
  remain existing Hermes capabilities and are outside this build. The realtime
  module only carries Work requests, questions, status, permissions, and final
  results across the Layer 1 and Layer 2 boundary.
- One supported native S2S model may be used as an initial integration fixture,
  but the permanent model is selected only after the provider benchmark gate.

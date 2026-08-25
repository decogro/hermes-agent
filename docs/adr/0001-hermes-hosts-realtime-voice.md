# Hermes hosts the realtime voice frontstage

Hermes is the host product and the only durable owner of memory, Work,
permissions, coordination, sessions, and results. Realtime voice is added as a
provider-neutral Hermes module, with Qwen Audio Realtime as the first provider
adapter. We will port only the useful Apache-2.0 Qwen Audio Agent modules and
preserve their required notices instead of making a Qwen fork the product.

The Hermes Voice Gateway owns the entire realtime control plane: Voice
Conversation identity, authoritative transcript, context compaction, provider
session creation and recovery, Audio Ownership, tool execution, Work routing,
and result delivery. A Realtime Provider owns only native speech-to-speech
inference and its connection-level protocol. Provider-native context,
truncation, or resumption may be used as an adapter optimization but never as
the durable authority.

This module does not reuse Hermes Voice's existing dictation, STT, TTS,
auto-speak, or voice-conversation loop. Those primitives are turn-based and
cannot keep a native speech session available while durable Hermes Work runs.
The desktop client for this module is only a PCM microphone/playback transport.

The realtime path is additional infrastructure inside the Hermes harness. It
does not replace Hermes's general JSON-RPC gateway, existing session and tool
runtime, or Legacy Hermes Voice. The general gateway and legacy audio endpoints
remain available while realtime voice uses a separate authenticated connection
and client protocol.

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
- A streaming STT to blocking Hermes turn to streaming TTS pipeline was
  rejected because it makes the conversation unavailable while Hermes works.
- Extending the existing Hermes Voice loop was rejected for the same reason;
  swapping its STT/TTS providers does not create a native duplex Voice Session.
- Keeping Qwen memory or TaskManager state was rejected because it would create
  competing durable authorities.
- Allowing the Realtime Provider to mutate Hermes memory was rejected because
  the frontstage needs profile context, not a second path for curating it.

## Consequences

- Qwen-specific protocol behavior stays inside a replaceable provider adapter.
- The realtime module is an additional Hermes path; the general gateway and
  Legacy Hermes Voice remain separate and unchanged.
- Copied Qwen source retains required Apache-2.0 attribution and change notices.
- Hermes Kanban and sessions remain authoritative even when voice disconnects.
- Realtime providers must support streaming speech, tool calls, interruption,
  context injection, and background-result presentation.
- Desktop is the first complete client; mobile adopts the same protocol later.
- Screen observation is outside the initial realtime-voice scope.
- A native provider failure is explicit and never falls back to Legacy Hermes
  Voice.
- Whether the Coordinator Session executes Work directly or delegates it is a
  profile prompt and tool-configuration policy, not Voice Gateway logic.
- Layer 3 worker creation, dispatch, execution, and worker-session management
  remain existing Hermes capabilities and are outside this build. The realtime
  module only carries Work requests, questions, status, permissions, and final
  results across the Layer 1 and Layer 2 boundary.

# Hermes hosts the realtime voice frontstage

Hermes is the host product and the only durable owner of memory, Work,
permissions, coordination, sessions, and results. Realtime voice is added as a
provider-neutral Hermes module, with Qwen Audio Realtime as the first provider
adapter. We will port only the useful Apache-2.0 Qwen Audio Agent modules and
preserve their required notices instead of making a Qwen fork the product.

This module does not reuse Hermes Voice's existing dictation, STT, TTS,
auto-speak, or voice-conversation loop. Those primitives are turn-based and
cannot keep a native speech session available while durable Hermes Work runs.
The desktop client for this module is only a PCM microphone/playback transport.

The Realtime Provider receives only the Frontstage Tool Set: `memory`,
`spawn_work`, `get_work_status`, `cancel_work`, and
`respond_to_work_permission`. Those operations map to existing Hermes memory,
Kanban, session, and permission capabilities. Completed Work returns through
pushed Work Events and is spoken as an Announcement. The Voice Session remains
separate from the Coordinator Session.

## Considered options

- A Qwen Audio Agent fork with Hermes behind it was rejected because Hermes is
  the dominant application, interface, and system of record.
- A streaming STT to blocking Hermes turn to streaming TTS pipeline was
  rejected because it makes the conversation unavailable while Hermes works.
- Extending the existing Hermes Voice loop was rejected for the same reason;
  swapping its STT/TTS providers does not create a native duplex Voice Session.
- Keeping Qwen memory or TaskManager state was rejected because it would create
  competing durable authorities.

## Consequences

- Qwen-specific protocol behavior stays inside a replaceable provider adapter.
- Copied Qwen source retains required Apache-2.0 attribution and change notices.
- Hermes Kanban and sessions remain authoritative even when voice disconnects.
- Realtime providers must support streaming speech, tool calls, interruption,
  context injection, and background-result presentation.

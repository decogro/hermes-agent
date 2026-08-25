# Realtime voice grilling decision ledger

Status: complete, confirmed by the user on 2026-08-24

This file records product decisions from the grilling session. Before asking a
question, check this ledger, `CONTEXT.md`, and the ADRs. Do not reopen a settled
decision unless new evidence creates a real contradiction.

## Settled

### Ownership and sessions

- Hermes is the product and durable system of record.
- The Voice Gateway owns everything except native speech-to-speech inference.
- The Realtime Provider owns its native speech loop: audio inference, acoustic
  turn detection, barge-in detection, and speech generation.
- There is exactly one durable Voice Conversation and one primary Coordinator
  Session attached to it.
- Additional coordinator-like or worker sessions are Layer 3 backend sessions.
  They never own a Voice Conversation and never speak directly.
- Exactly one temporary Realtime Provider session and one Audio Owner may be
  active at a time. Provider or device handoff preserves the Voice Conversation.
- The Realtime Voice Gateway is an additional path inside Hermes. It does not
  replace the general Hermes gateway, and Legacy Hermes Voice remains available
  as a separate turn-based feature.

### Memory, conversation, and work

- Hermes has one canonical durable voice transcript.
- The provider may produce a revisable hypothesis for the current unfinished
  turn. This is temporary input to the one transcript, not a second transcript.
- An interrupted assistant turn commits only the words actually played to the
  user, followed by interruption metadata. Unheard generated output is discarded.
- Memory is the existing read-only Hermes profile memory. Voice does not mutate
  it or create a second memory system.
- The primary Coordinator uses the same Hermes profile memory. A Work handoff
  must not copy that memory into the coordinator request.
- A Work handoff contains the exact finalized request, the existing Hermes Work
  ID, and a reference to the originating voice turn. The Coordinator reads its
  profile memory normally.
- The frontstage may read memory and respond directly. Any requested action is
  accepted as durable Work and routed to the primary Coordinator.
- Hermes Kanban is the authoritative Work ledger. Layer 3 behavior is controlled
  by the Coordinator profile and is not implemented by the realtime module.
- Background questions, permission requests, status, and results return through
  the Gateway as Announcements. Blocking questions and permissions have priority
  at the next silence; routine updates wait for a natural pause.
- Barge-in stops speech but does not cancel accepted Work. Ambiguous cancellation
  requires clarification.

### Provider and failure behavior

- The architecture is provider-neutral for compatible native speech-to-speech
  models.
- Switching or reconnecting a provider does not create a new Voice Conversation.
- Provider history, resumption, and compression are optimizations, not durable
  authority.
- Native provider failure is explicit. The system never silently falls back to
  Legacy Hermes Voice.
- Raw microphone and generated audio are not retained by default.

### Scope and acceptance

- Screen observation is not part of the initial scope. Do not design or ask
  further product questions about it during this build.
- Desktop is completed first. Mobile later uses the same Gateway protocol.
- Streaming acceptance requires actual bidirectional behavior: low latency,
  output audio beginning while the response is still being generated, and
  working barge-in. Numeric thresholds are engineering benchmark gates to be
  established from measurements, not a product question to ask again.

## Technical decisions for Wayfinder

These require code or provider investigation rather than more user grilling:

- the exact Hermes module seams for transcript, Kanban, Coordinator events,
  authentication, and client transport;
- the normalized provider adapter contract;
- direct WebRTC versus Gateway-relayed media by provider;
- transcript event reconciliation and playback acknowledgement mechanics;
- provider rehydration and context-compaction algorithms;
- crash recovery, idempotency, and Announcement deduplication; and
- the benchmark harness and measured numeric release thresholds.

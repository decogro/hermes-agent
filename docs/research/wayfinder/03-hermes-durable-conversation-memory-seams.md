# Hermes durable conversation and profile-memory seams

## Decision

Hermes already has the durable primitives needed for one Voice Conversation, but
the current realtime module is only a live provider transport. The reusable
center is a profile-scoped `SessionDB` row with a stable session ID, its
`messages` rows, the existing resume projections, and in-place compaction.
`AsyncSessionDB` and the gateway's profile-scoped handle make those APIs usable
from an asynchronous gateway.

The current realtime gateway does not use any of those primitives. It has no
database handle, durable conversation ID, profile binding, transcript writer,
reconnect or provider rehydration path, compaction path, Audio Owner state, or
durable announcement state. Its provider contract also has no history or
resume operation. These are lifecycle gaps, not reasons to create a second
conversation or memory system.

The existing built-in `MemoryStore` can provide a sanitized read projection of
the profile's `MEMORY.md` and `USER.md`: load the profile-scoped files and use
the frozen system-prompt projection. It is not currently exposed as a standalone
read-only realtime API. The current realtime `memory` tool is explicitly
write-capable, so it must not be reused unchanged. Voice should receive a
read-only adapter over Hermes profile memory; memory writes must remain on the
existing Hermes memory-tool path.

The authoritative model is therefore:

1. Hermes `SessionDB`, plus any Hermes-owned voice-turn journal needed for
   reconciliation, owns the Voice Conversation identity and canonical transcript.
2. The profile's `MEMORY.md` and `USER.md` remain the memory authority. A voice
   projection is a read view, not a new store.
3. Hermes Work and its durable completion/delivery records remain authoritative
   for accepted work. Realtime announcement objects are delivery projections.
4. The provider owns only native speech inference, audio, VAD, interruption, and
   connection protocol. Provider history, resumption, and compression are
   optimizations.

The required project design says the same boundary: the Voice Session is
temporary, the Voice Conversation is the one durable transcript, and the
provider does not own memory, Work, identity, or recovery
(`CONTEXT.md:13-35`; `docs/adr/0001-hermes-hosts-realtime-voice.md:9-15`).

## Evidence and reusable APIs

All citations below are to this checkout. Line numbers are repository-relative
and refer to the inspected source at report time.

### 1. Durable conversation identity and storage

`SessionDB` is the correct existing storage owner.

- The default database is resolved at call time as
  `get_hermes_home() / "state.db"`, so a profile-scoped Hermes home selects a
  profile-scoped database (`hermes_state.py:392-409`). `SessionDB` is designed
  for multiple readers and a single WAL writer (`hermes_state.py:4045-4051`).
- The schema already stores a durable session ID, source, routing metadata,
  parent lineage, lifecycle fields, and `profile_name`. The `messages` table
  stores ordered role/content rows, timestamps, tool fields, finish reasons,
  API-content sidecars, and display metadata
  (`hermes_state_common.py:369-428`; `hermes_state_common.py:430-454`).
- `create_session()` is an idempotent row-creation seam. Its insertion path
  accepts `source`, `profile_name`, routing fields, and a stable caller-supplied
  session ID, and enriches NULL metadata on conflict
  (`hermes_state.py:5578-5773`). A Voice Conversation can use a stable ID and a
  distinct source such as `realtime_voice` while remaining a normal Hermes
  session row.
- `get_session()` returns the durable row and resolves the stored system prompt
  (`hermes_state.py:9014-9030`). This is enough to verify the conversation's
  profile binding and lifecycle metadata before a reconnect.
- `AsyncSessionDB` forwards synchronous `SessionDB` methods through
  `asyncio.to_thread`, so SQLite calls do not block the event loop
  (`hermes_state.py:14623-14636`). The existing gateway runner already resolves
  one async handle per profile database and exposes it through `_session_db`
  (`gateway/run.py:7269-7333`).

There is no explicit `voice_conversations` table or uniqueness constraint for
one voice conversation per profile. The schema has only the session ID primary
key and source indexes (`hermes_state_common.py:369-428`;
`hermes_state_common.py:531-535`). Therefore the Voice Gateway must own
stable-ID discovery and creation atomically, or Hermes needs a small
voice-binding record. Reusing arbitrary provider session IDs would not solve
that identity problem.

### 2. Durable transcript writes and replay

The existing message APIs can store the canonical finalized transcript.

- `append_message()` writes a row and updates session counters in one write
  transaction. It accepts role, content, timestamp, finish reason, API-content
  sidecar, and display fields, and its transcript write has the long persistence
  patience used for turn-critical writes (`hermes_state.py:10498-10639`).
- `append_messages_batch()` writes a turn atomically, with the same compression
  and session-turn admission guards (`hermes_state.py:10642-10676`). This is the
  right existing primitive for a finalized user/assistant/tool boundary once
  the Voice Gateway has decided which text is durable.
- `get_messages()` is an ordered transcript reader. Active rows are the default;
  `include_compacted=True` adds durable in-place compaction history while
  excluding ordinary rewind rows (`hermes_state.py:11384-11423`).
- `get_messages_as_conversation()` materializes the provider-facing conversation
  in insertion order, and `get_resume_conversations()` returns both the model
  history and a full compression-lineage display history from one read
  (`hermes_state.py:11730-11784`; `hermes_state.py:11984-12039`). These are the
  strongest existing reconnect and UI projection APIs.
- `try_acquire_session_turn_lease()` uses the compression lineage root as the
  durable lease key, preventing concurrent writers from entering the same
  conversation (`hermes_state.py:7609-7660`). A Voice Gateway should use this
  rather than relying on one process-local asyncio task.

The message table is not a voice-turn journal. `platform_message_id` is
documented as an external messaging-platform ID, and `display_metadata` is
explicitly presentation-only and does not change provider replay
(`hermes_state.py:10530-10545`). The existing rows can carry a finalized
assistant message and a finish reason, but there is no provider response/item
identity, playback offset, hypothesis lifecycle, interruption event, or
transactional finalization API. That is the main schema/lifecycle gap.

The durable seam should therefore be split:

- Use `append_message()` or `append_messages_batch()` for finalized canonical
  rows.
- Add a Hermes-owned voice-turn/event reconciliation seam, either as typed
  voice-turn storage or as an explicitly specified extension to the session
  schema. Do not overload `display_metadata` as model-authoritative voice
  state.
- Commit only finalized user speech and assistant text confirmed as played.
  A provider hypothesis remains in memory until finalization. An interruption
  needs durable status and played-text boundaries; the current message API does
  not infer those from audio.

### 3. Same-ID context compaction

Hermes has an unusually good fit for the one-conversation requirement.

- `archive_and_compact()` soft-archives active rows and inserts a compacted set
  atomically under the same durable session ID. Archived rows remain searchable
  and recoverable (`hermes_state.py:11191-11240`).
- The operation accepts a compression-start watermark and clones concurrent
  tail rows byte-exactly after the new compacted set, preventing a live turn
  from disappearing while the summary model runs
  (`hermes_state.py:11218-11235`; `hermes_state.py:11243-11341`).
- The existing compression path explicitly supports in-place mode: it keeps the
  same `session_id`, does not create a child session, and calls
  `archive_and_compact()` after producing the compacted message set
  (`agent/conversation_compression.py:2403-2415`;
  `agent/conversation_compression.py:3512-3554`).
- `ContextCompressor` can bind a session DB and session ID, and its public
  `compress()` API operates on a message list with a model and summary
  configuration (`agent/context_compressor.py:2409-2426`;
  `agent/context_compressor.py:3101-3124`;
  `agent/context_compressor.py:7232-7274`).

This supports a recommendation, not a claim that realtime is already wired:
the Voice Gateway should enforce in-place compaction for the one Voice
Conversation and reuse `archive_and_compact()` plus the existing summarization
algorithm behind a gateway-owned adapter. It must not allow a legacy
compression rotation to create the voice identity's new canonical session.

The native provider compaction module is not the durable seam. It is gated to
the gpt-5.6 family and direct OpenAI routes, sends a provider request payload,
and carries opaque compaction items through an existing reasoning sidecar
(`agent/native_compaction.py:1-33`; `agent/native_compaction.py:119-154`). It
cannot be the Qwen-neutral Voice Conversation transcript or recovery authority.

### 4. Profile scoping

Hermes already has the scope mechanism required to bind both the session DB and
memory projection to one Coordinator Profile.

- `_profile_runtime_scope()` installs a context-local Hermes home for config,
  skills, memory, SOUL, and sessions, while separately scoping credentials
  (`gateway/run.py:2217-2251`).
- `get_hermes_home()` resolves the context-local override before the environment
  and platform default (`hermes_constants.py:114-139`).
- Named profile directories are resolved by `get_profile_dir()`, with the
  default profile represented by the default Hermes home
  (`hermes_cli/profiles.py:271-293`; `hermes_cli/profiles.py:310-379`).

The current realtime constructor accepts only `owner_id`, `voice_session_id`,
and an optional tool-call ID in `VoiceToolContext`; it has no profile name,
profile home, durable session ID, coordinator binding, or database handle
(`hermes_cli/realtime_voice/tools.py:15-34`). The profile mechanism is reusable,
but the Voice Gateway must resolve and pin the dedicated Coordinator Profile
before opening a provider connection. It must not use whichever profile happens
to be active on a reconnect.

### 5. Read-only profile-memory projection

The built-in memory source is profile-scoped file memory.

- `get_memory_dir()` resolves `get_hermes_home() / "memories"`
  (`tools/memory_tool.py:60-66`). `MemoryStore.load_from_disk()` reads
  `MEMORY.md` and `USER.md`, deduplicates entries, sanitizes threat-matching
  entries for the snapshot, and keeps the original live text separate
  (`tools/memory_tool.py:227-264`).
- `format_for_system_prompt()` returns the sanitized frozen block captured at
  load time, and deliberately does not expose mid-session writes
  (`tools/memory_tool.py:706-717`). The renderer's block format is stable and
  target-specific (`tools/memory_tool.py:755-771`).
- The loader's `_read_file()` is explicitly retained for read-only callers and
  does not persist changes (`tools/memory_tool.py:828-837`). `load_from_disk()`
  itself creates the memories directory if absent, so a strict read-only voice
  path should either tolerate that initialization or use a dedicated adapter
  over the safe read and sanitize primitives (`tools/memory_tool.py:241-248`).
- Agent initialization constructs one `MemoryStore` per `AIAgent` and loads it
  from disk; system-prompt assembly consumes only the frozen memory and user
  blocks (`agent/agent_init.py:1825-1866`; `agent/system_prompt.py:820-838`).

The reusable behavior is therefore `MemoryStore`'s load, parse, sanitize, and
projection logic. The missing API is a standalone `read_profile_memory(profile,
targets)` projection that does not hand a realtime provider the mutable store or
the memory-write tool. The projection should return only the selected sanitized
`memory`, `user`, or combined blocks and should carry the profile identity for
diagnostics, not mutation capabilities.

The current realtime tool surface violates this boundary:

- Its schema describes `memory` as “Read or update” and permits `read`,
  `append`, and `replace` actions (`hermes_cli/realtime_voice/tools.py:47-65`).
- The router forwards the action and write fields directly to the Hermes
  `memory` port (`hermes_cli/realtime_voice/tools.py:161-182`).
- The actual built-in memory tool dispatches `add`, `replace`, and `remove` and
  applies the normal write gate (`tools/memory_tool.py:1086-1174`).

The voice-facing port must be read-only. The existing memory tool remains the
authority for approved memory writes. `MemoryManager` is also not a replacement
for this projection: its `prefetch_all()` is query-dependent and its `sync_all()`
performs background provider writes after a completed turn
(`agent/memory_manager.py:525-545`; `agent/memory_manager.py:675-731`). It is a
turn-based provider orchestrator, not a durable read-only profile view.

## What the current realtime implementation actually does

`RealtimeVoiceGateway` is a transport/session skeleton, not a durable
conversation owner.

- Its constructor stores a provider registry, tool router, client, instructions,
  one temporary `RealtimeSession`, an in-memory announcement delivery object,
  a turn counter, and in-memory playback correlation maps. It has no `SessionDB`,
  profile, durable conversation ID, or compactor
  (`hermes_cli/realtime_voice/gateway.py:29-50`).
- `start()` resolves a provider, connects with instructions and frontstage tools,
  creates `AnnouncementDelivery`, and emits `voice.ready`
  (`hermes_cli/realtime_voice/gateway.py:52-72`). It does not create or reopen a
  Hermes session.
- Provider user transcript deltas/finals and assistant transcript deltas are
  forwarded to the client only. `response.done` emits `audio.done` and idle
  state; no transcript row is appended anywhere
  (`hermes_cli/realtime_voice/gateway.py:121-201`).
- `playback.started` only resolves an in-memory announcement waiter. Normal
  `playback.ended` and `playback.cancelled` events are ignored
  (`hermes_cli/realtime_voice/gateway.py:84-110`; `hermes_cli/realtime_voice/gateway.py:203-235`).
- `close()` closes the temporary provider session and clears playback waiters;
  it does not preserve or recover conversation state
  (`hermes_cli/realtime_voice/gateway.py:112-119`).

The provider contract confirms the missing recovery seam. `RealtimeSession`
supports audio append, tool results, announcement injection, interruption,
close, and wait-for-close, while `RealtimeProvider.connect()` accepts an
unstructured options dictionary. There is no history seed, resume token,
rehydration, or compaction capability (`hermes_cli/realtime_voice/provider.py:16-39`).
The Qwen adapter sends only a `session.update` configuration and forwards audio,
tool output, and response control to the socket
(`hermes_cli/realtime_voice/providers/qwen.py:78-100`;
`hermes_cli/realtime_voice/providers/qwen.py:131-145`).

This creates four concrete voice-turn gaps:

1. The provider produces revisable user and assistant text, but the gateway has
   no accumulator or finalization journal.
2. Assistant audio and assistant transcript deltas are separate streams. The
   gateway has no mapping from played audio to the words that may be committed.
3. `playback.started` is an announcement-specific correlation mechanism, not a
   canonical assistant playback acknowledgement. `playback.ended` is ignored.
4. Barge-in calls provider cancellation and clears client playback, but there is
   no durable interruption metadata or accepted-text commit.

The project ledger requires exactly this distinction: a provider hypothesis is
temporary, and an interrupted assistant turn commits only words actually played
(`docs/design/grilling-decision-ledger.md:24-46`). The current code cannot yet
prove that invariant.

## Work and announcement seam

The frontstage tool contract is a useful routing seam, but it is not a durable
Work implementation in this module. The tool context contains owner and
temporary voice-session identifiers, and the protocol exposes memory, Work
creation/status/cancellation, and permission responses
(`hermes_cli/realtime_voice/tools.py:15-34`). `spawn_work` is explicitly
non-blocking and accepted work is tracked only by adding its returned ID to the
in-memory announcement delivery object (`hermes_cli/realtime_voice/tools.py:68-87`;
`hermes_cli/realtime_voice/gateway.py:176-189`). The handoff has no explicit
originating durable voice-turn reference.

Hermes already has a durable async-delegation completion rail that is a better
source for pending Work results than a voice-local queue:

- Completion persistence stores the event/result and resets delivery to pending
  (`tools/async_delegation.py:315-324`).
- Startup restores pending completions, and claims are scoped across competing
  consumers (`tools/async_delegation.py:392-444`; `tools/async_delegation.py:459-487`).
- Completion delivery can be acknowledged, released for retry, or terminally
  dropped with the result still queryable (`tools/async_delegation.py:490-560`).

That rail is reusable as the durable Work-event source if the Work path uses
async delegations. It is not a complete Voice Announcement implementation: the
current `AnnouncementDelivery` keeps owned work IDs, delivered event IDs, and
in-flight event IDs only in process memory, and marks delivery only after
provider playback starts (`hermes_cli/realtime_voice/announcements.py:54-92`).
The Gateway must bridge durable Hermes Work Events to a profile-bound Voice
Conversation, claim/deduplicate them, and retain pending announcements across
provider disconnects. It must not make `_delivered` the authority.

## Required authority boundaries

| Concern | Authoritative owner | Existing evidence | Do not promote |
| --- | --- | --- | --- |
| Voice Conversation identity and canonical transcript | Hermes profile-scoped `SessionDB`, extended by a Hermes-owned voice-turn journal if needed | `hermes_state_common.py:369-454`; `hermes_state.py:10498-10676` | Qwen conversation items or a provider connection |
| Resume and durable context | Hermes active message rows plus `get_resume_conversations()` and in-place `archive_and_compact()` | `hermes_state.py:11191-11240`; `hermes_state.py:11984-12039` | Provider history, native truncation, or opaque provider compaction |
| Profile memory | Profile `MEMORY.md` and `USER.md`, projected through sanitized Hermes read logic | `tools/memory_tool.py:60-66`; `tools/memory_tool.py:227-264` | Voice-local memory, Qwen memory, or external provider sync |
| Memory mutation | Existing Hermes memory tool and its write/approval path | `tools/memory_tool.py:1086-1174` | Realtime `memory` actions `append` and `replace` |
| Accepted Work lifecycle | Hermes Kanban/Work implementation and durable delegation records where applicable | `tools/async_delegation.py:315-324`; `tools/async_delegation.py:392-444` | In-memory work ID sets or model recollection |
| Voice connection state | Voice Gateway | `hermes_cli/realtime_voice/gateway.py:29-72` | Provider session as durable state |
| Native speech behavior | Realtime Provider | `hermes_cli/realtime_voice/provider.py:16-39` | Hermes transcript or memory authority |

The project design also requires the Voice Conversation and primary Coordinator
Session to remain bound to one dedicated Coordinator Profile, while worker
sessions remain backend sessions without a Voice Conversation
(`CONTEXT.md:72-86`; `docs/adr/0001-hermes-hosts-realtime-voice.md:29-38`).
The profile-scoped session handle must enforce that binding rather than treating
`owner_id` or a provider session ID as the durable owner.

## Minimal implementation seam for the next ticket

This report does not change production code. The smallest coherent follow-up
should add the following gateway-owned seams:

1. A durable Voice Conversation handle containing the pinned Coordinator Profile,
   profile home, stable Hermes session ID, `AsyncSessionDB`, primary Coordinator
   binding, current turn state, and Audio Owner.
2. A create-or-reopen path that enters the profile runtime scope, creates or
   verifies the one `realtime_voice` session row, acquires the session-turn lease,
   and loads `get_resume_conversations()` before provider connect.
3. A normalized provider lifecycle for history seeding, reconnect, transcript
   hypotheses/finals, response identity, played-text acknowledgement, and
   interruption. The current provider protocol lacks these operations.
4. A transactional voice-turn commit that uses existing message append APIs for
   finalized rows and persists enough typed event data to make replay,
   interruption, idempotency, and crash recovery deterministic.
5. An in-place compaction adapter using the existing watermark and
   `archive_and_compact()` path. The one Voice Conversation must not rotate into
   a new canonical session ID.
6. A read-only profile-memory projection port backed by Hermes's sanitized
   `MemoryStore` read path. Remove mutation fields from the provider-facing
   memory schema; retain the normal Hermes memory tool as the only write path.
7. A durable Work-event bridge that claims pending results from the existing
   Hermes delivery rail, maps them to the stable Voice Conversation and origin
   voice turn, and acknowledges delivery only according to the chosen playback
   policy.

The current implementation is therefore sufficient as a provider/media seam,
and Hermes persistence is sufficient as a durable storage seam, but the durable
Voice Conversation is not implemented until those gateway-owned lifecycle seams
exist.

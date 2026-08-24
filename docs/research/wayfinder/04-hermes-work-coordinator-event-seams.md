# Hermes Work and Coordinator event seams

## Finding

The existing Hermes Kanban database is the authoritative durable Work ledger. A
small adapter can use the Kanban task ID as `work_id`, create the task with an
idempotency key, read task/run/event data for status, and feed completed or
blocked events into the realtime announcement path. The source already has
atomic claims, retry history, event cursors, summaries, artifacts, and ordinary
gateway delivery.

The issue is not missing storage. The missing seams are:

1. There is no concrete `HermesFrontstagePort` implementation connecting the
   five realtime tools to Hermes capabilities. The realtime router receives an
   injected protocol implementation only (`hermes_cli/realtime_voice/tools.py:22-33`,
   `hermes_cli/realtime_voice/tools.py:161-221`).
2. Hermes has a `RelaySessionCoordinator`, but it owns Relay conversation and
   turn scopes, not a durable Work coordinator or Work event stream
   (`agent/relay_runtime.py:1321-1414`). The inspected code does not bind a
   realtime voice session, a Kanban task, and a long-lived primary Coordinator
   Session into one control-plane object.
3. Existing worker cancellation is reclaim and requeue, not terminal user
   cancellation (`hermes_cli/kanban_db.py:5114-5182`).
4. Existing permission and clarify systems are session-scoped prompt queues.
   They have useful request IDs and replay behavior, but no Work-scoped
   authorization or blocker-answer adapter (`tools/approval.py:2779-2902`,
   `tui_gateway/server.py:4019-4098`).
5. Kanban event cursors are durable, while realtime announcement ownership and
   delivery state are only in memory (`hermes_cli/kanban_db.py:11766-11860`,
   `hermes_cli/realtime_voice/announcements.py:54-91`). There is no source
   path that subscribes the realtime gateway to Kanban events.

## Existing authoritative Work lifecycle

The Work ID should be the Kanban `tasks.id`. The task row carries the durable
status, originating session, result, idempotency key, active run pointer, and
typed block state (`hermes_cli/kanban_db.py:1052-1143`). The database defines
the task event log and historical attempt table separately, with each event
linked to a task and optionally a run (`hermes_cli/kanban_db.py:1442-1478`).

The lifecycle that exists today is:

1. **Accepted:** create a task with `create_task`. It accepts a title/body,
   assignee, idempotency key, origin `session_id`, and execution settings; it
   returns the stable task ID and avoids duplicating a non-archived task with
   the same idempotency key (`hermes_cli/kanban_db.py:3158-3202`,
   `hermes_cli/kanban_db.py:3396-3409`, `hermes_cli/kanban_db.py:3491-3557`).
2. **Ready and dispatched:** a ready task is atomically changed to running,
   one `task_runs` row is created, `current_run_id` is set, and a `claimed`
   event is appended (`hermes_cli/kanban_db.py:4617-4736`). The default
   dispatcher starts `hermes -p <profile> --cli chat -q "work kanban task
   <id>"` and observes completion through Kanban mutations rather than the
   child process's stdout (`hermes_cli/kanban_db.py:10709-10725`,
   `hermes_cli/kanban_db.py:10841-10921`).
3. **Progress and liveness:** a worker can update the task/run heartbeat and
   append a `heartbeat` event with an optional free-text note
   (`hermes_cli/kanban_db.py:8372-8420`). The dashboard's only structured
   progress rollup is child tasks done over child tasks total
   (`plugins/kanban/dashboard/plugin_api.py:432-474`). There is no canonical
   percentage, phase-progress payload, or realtime progress event contract.
4. **Blocked:** `block_task` distinguishes dependency waits from human-facing
   `needs_input` and `capability` blockers, closes the active run, and appends
   a typed event with the reason (`hermes_cli/kanban_db.py:6246-6279`,
   `hermes_cli/kanban_db.py:6327-6344`, `hermes_cli/kanban_db.py:6450-6471`).
5. **Completed:** `complete_task` sets the task to done, stores the explicit
   result on the task, stores summary and metadata on the closing run, and
   appends a `completed` event carrying a short summary and artifact paths
   (`hermes_cli/kanban_db.py:5352-5378`, `hermes_cli/kanban_db.py:5443-5551`).
6. **Retry or failure:** crash, timeout, spawn failure, and reclaim are run
   outcomes with attempt history. Reclaim explicitly closes the run as
   `reclaimed`, emits a `reclaimed` event, and restores the task to its retry
   phase (`hermes_cli/kanban_db.py:1241-1267`,
   `hermes_cli/kanban_db.py:5114-5182`).
7. **Unblocked:** `unblock_task` restores `ready`, `todo`, or `review` based
   on parent and prior-event state and appends `unblocked`; it accepts no
   answer or response payload (`hermes_cli/kanban_db.py:6890-6948`).

This is the authoritative state machine for a Kanban-backed Work. The
realtime layer should not invent a second Work status store.

## Capability map

| Frontstage operation | Existing Hermes capability | Adapter gap or semantic warning |
| --- | --- | --- |
| `spawn_work` | `create_task` supports idempotency, origin session, parent links, profile/model settings, and a durable creation event (`hermes_cli/kanban_db.py:3158-3202`, `hermes_cli/kanban_db.py:3491-3557`). The existing tool wrapper captures the originating session and creates a notification subscription when a normal gateway or TUI context exists (`tools/kanban_tools.py:1343-1474`, `tools/kanban_tools.py:1484-1603`). | The voice schema supplies only `objective` and `input_refs` (`hermes_cli/realtime_voice/tools.py:68-86`), while the existing `kanban_create` tool requires a title and assignee and is documented as orchestrator fan-out (`tools/kanban_tools.py:1343-1360`, `tools/kanban_tools.py:2132-2163`). The adapter must resolve the Coordinator/worker profile, derive a title/body, bind owner and voice session, and choose a retry-safe idempotency key. |
| status | `get_task`, `list_tasks(session_id=...)`, `list_runs`, `latest_run`, `latest_summary`, `list_events`, parent results, comments, and attachments provide the needed data (`hermes_cli/kanban_db.py:3631-3699`, `hermes_cli/kanban_db.py:3963-4047`, `hermes_cli/kanban_db.py:4276-4297`, `hermes_cli/kanban_db.py:12032-12103`). | `get_task` is a raw task-ID lookup with no owner check (`hermes_cli/kanban_db.py:3631-3633`). The adapter must authorize by the voice owner and durable origin mapping before returning status or allowing `list_all`; the existing `VoiceToolContext` only carries `owner_id`, `voice_session_id`, and optional tool-call ID (`hermes_cli/realtime_voice/tools.py:15-20`). |
| cancellation | The dashboard `terminate` endpoint reaches the same `reclaim_task` path as manual reclaim and can signal the worker (`plugins/kanban/dashboard/plugin_api.py:1707-1752`). Realtime barge-in only interrupts provider speech and explicitly does not call the Work port (`hermes_cli/realtime_voice/gateway.py:84-110`, `tests/hermes_cli/test_realtime_voice_gateway.py:75-90`). | `reclaim_task` only acts on a running claim, kills the worker, records `reclaimed`, and restores a retryable status (`hermes_cli/kanban_db.py:5114-5175`). It cannot cancel a queued ready task with no claim, and it is not a terminal `cancelled` state. `cancel_work` therefore needs a distinct cancellation path and event that prevents later dispatch or accidental requeue. |
| spoken permission | The core approval queue has per-session entries, unique request IDs, FIFO or request-ID resolution, reconnect-safe snapshots, and `once`, `session`, `always`, and `deny` outcomes (`tools/approval.py:2779-2902`). The gateway path blocks the agent thread, times out, maps interruption to deny, and persists session/permanent choices when selected (`tools/approval.py:3754-3818`, `tools/approval.py:4382-4544`). | The realtime tool contract exposes only `authorization_id` plus `always` or `reject` (`hermes_cli/realtime_voice/tools.py:113-124`). There is no Work ID in the approval queue contract, and no adapter maps a pending dangerous action to a delegated Work or a voice session. A Work permission event must preserve one-time semantics where required, correlate the response to the worker/run, and fail closed on timeout or lost voice transport. |
| blocking question | `block_task(kind="needs_input", reason=...)` gives Kanban a typed human blocker and durable reason event (`hermes_cli/kanban_db.py:6246-6279`, `hermes_cli/kanban_db.py:6450-6471`). Comments are durable and `list_comments_after` already supports a live worker bridge (`hermes_cli/kanban_db.py:3982-4047`). The TUI clarify bridge has request IDs, timeout, replay, and late-answer handling (`tui_gateway/server.py:4019-4098`, `tui_gateway/methods_prompt.py:1515-1521`). | `unblock_task` has no answer argument or answer event (`hermes_cli/kanban_db.py:6890-6948`). TUI clarify is keyed to an in-memory session prompt, not a Kanban task. The adapter needs a Work-scoped question ID, a durable question/answer correlation, an owner check, and an explicit answer-to-comment or answer-to-worker transition before unblocking. |
| final result | Kanban completion stores task result, run summary/metadata, and artifact references in durable rows/events (`hermes_cli/kanban_db.py:5352-5551`). The existing gateway notifier consumes terminal task events, formats a human handoff, wakes the originating session when configured, and uploads completion artifacts (`gateway/kanban_watchers.py:201-223`, `gateway/kanban_watchers.py:549-648`, `gateway/kanban_watchers.py:767-887`, `gateway/kanban_watchers.py:1095-1202`). | Realtime `announce_work` can inject a caller-supplied `WorkEvent` and waits for `playback.started` before acknowledging delivery (`hermes_cli/realtime_voice/gateway.py:74-82`, `hermes_cli/realtime_voice/announcements.py:17-50`, `hermes_cli/realtime_voice/announcements.py:70-91`). No source path connects `task_events` or the Kanban watcher to `announce_work`; a Work-event bridge is missing. |

## Coordinator and backend-session seams

### Core Relay coordinator

`RelaySessionCoordinator` is real existing infrastructure. Its contract is to
acquire a profile-scoped Relay conversation, create either a root session or a
registered subagent session, and begin/end a turn with a `task_id`
(`agent/relay_runtime.py:1252-1274`, `agent/relay_runtime.py:1321-1414`).
`run_agent.py` invokes it around every AIAgent turn, passes the effective task
ID and parent session for subagents, and maps interrupted, failed, or successful
turns to Relay outcomes (`run_agent.py:8581-8600`, `run_agent.py:8876-8957`).

This is useful for the adapter, but it is not the issue's primary Coordinator
Session implementation. It manages Relay scope lifetime and metrics; it does
not create Kanban tasks, subscribe to `task_events`, route frontstage tools, or
deliver Work results to realtime voice. The adapter must decide whether the
voice conversation's durable Hermes session is the parent session for Work, and
must keep that identity separate from the worker attempt.

### Normal gateway session creation

`SessionStore.get_or_create_session` is a single-flight lookup/create keyed by a
`SessionSource` routing key (`gateway/session.py:2598-2651`). On creation it
allocates a durable session ID, records the source/origin, and writes the row
through `SessionDB.create_session` (`gateway/session.py:2891-3004`). The state
database supports parent session lineage and source/profile/cwd metadata
(`hermes_state.py:5578-5773`). This is the reusable session-creation seam for a
voice adapter, but it is keyed around messaging/session routing, not a named
Coordinator Work role.

### Kanban worker session

The default Kanban dispatcher launches a detached, one-shot `chat -q` worker,
clears inherited gateway routing variables, stamps `HERMES_SESSION_SOURCE=kanban`,
and carries the task, run, claim, board, and workspace through environment
variables (`hermes_cli/kanban_db.py:10709-10725`,
`hermes_cli/kanban_db.py:10737-10773`, `hermes_cli/kanban_db.py:10790-10831`).
`tasks.session_id` is documented as the originating chat or agent session and
is null for CLI/dashboard-created tasks, not as the worker session ID
(`hermes_cli/kanban_db.py:1131-1136`, `hermes_cli/kanban_db.py:1407-1412`).
The worker's session is therefore not the primary voice/Coordinator session.

The session context explicitly says dispatcher-spawned Kanban workers are
one-shot subprocesses whose parent process disappears and therefore cannot
receive later async completion delivery (`gateway/session_context.py:496-521`).
This rules out using the current worker process as the realtime result
consumer.

### In-process delegated backend session

`delegate_task` creates a child `AIAgent` with a dedicated `SessionDB` handle
pointing at the parent's database, `platform="subagent"`, and
`parent_session_id` lineage (`tools/delegate_tool.py:1928-2005`). It can relay
child text and completion progress and supports a direct stop action
(`tools/delegate_tool.py:2805-2823`, `tools/delegate_tool.py:3625-3658`).

The separate async delegation registry already persists origin session IDs,
parent session ID, status, result, delivery state, delivery claims, retry
attempts, and restart recovery (`tools/async_delegation.py:142-180`,
`tools/async_delegation.py:392-456`, `tools/async_delegation.py:753-809`,
`tools/async_delegation.py:900-1006`). This is a useful event/delivery pattern,
but it is not a Kanban task ledger: it has a `delegation_id`, not a Kanban
`work_id`, and its runner is the in-process child-agent path. A coordinator
adapter must choose one execution rail per Work item instead of silently
creating both a Kanban task and an async delegation.

## Event streaming and result delivery

There are three existing event rails:

1. **Durable Kanban events:** `_append_event` writes arbitrary typed payloads
   inside the task transaction, and `list_events` reads them in order
   (`hermes_cli/kanban_db.py:4276-4321`).
2. **Gateway notification subscriptions:** a subscription stores platform/chat/
   thread routing and `last_event_id`; `claim_unseen_events_for_sub` advances
   that cursor atomically and `rewind_notify_cursor` supports retry after
   delivery failure (`hermes_cli/kanban_db.py:1497-1515`,
   `hermes_cli/kanban_db.py:11385-11426`,
   `hermes_cli/kanban_db.py:11766-11860`). The gateway watcher uses that cursor
   to deliver terminal events and retains subscriptions until archive
   (`gateway/kanban_watchers.py:201-223`, `gateway/kanban_watchers.py:990-1027`).
3. **Dashboard WebSocket:** the dashboard exposes an authenticated board-wide
   `task_events` stream with a client-supplied numeric cursor and batches of up
   to 200 events (`plugins/kanban/dashboard/plugin_api.py:2893-2990`). This is
   an operator stream, not an owner-scoped voice delivery channel.

The realtime event rail is different. `RealtimeVoiceGateway` accepts a
provider-neutral session and an injected frontstage router, tracks Work IDs in
memory, and exposes `announce_work` as a direct method
(`hermes_cli/realtime_voice/gateway.py:29-82`). `AnnouncementDelivery` filters
to a small terminal set, de-duplicates only in memory, and marks an event
delivered only after playback starts (`hermes_cli/realtime_voice/announcements.py:17-25`,
`hermes_cli/realtime_voice/announcements.py:54-91`). The provider protocol
contains audio, tool-result, announcement, interrupt, wait, and close methods,
but no Work-event subscription or durable transcript/session method
(`hermes_cli/realtime_voice/provider.py:16-39`).

The missing adapter should consume the durable Kanban event rail and translate
events into `WorkEvent`. It must retain enough durable ownership and cursor
state to replay an event after voice disconnect, and it must not advance a
Kanban cursor permanently before the voice delivery has been accepted. The
existing in-memory `_delivered` set cannot provide that guarantee across
gateway reconnect or process restart.

## Recommended minimal adapter boundary

The smallest coherent implementation would be one Hermes-owned adapter behind
`HermesFrontstagePort` with these responsibilities:

1. **Owner and Coordinator binding:** resolve or create the durable voice
   session through the existing session/Relay seams, retain a Coordinator
   session identifier, and bind it to `owner_id` plus `voice_session_id`. Do
   not treat `tasks.session_id` as the worker session without an explicit
   mapping, because the field currently records the origin session.
2. **Work creation:** create exactly one Kanban task per accepted Work request,
   attach a stable idempotency key, record the origin session, select the
   execution profile, and register a durable voice delivery subscription. The
   return value should contain `work_id` and the authoritative Kanban status.
3. **Status authorization:** read the task, current/latest run, summary/result,
   typed blocker, recent events, and child progress only after checking that
   the caller owns the Work. `list_all` must be an owner-scoped query, not a
   board-wide `get_task` loop.
4. **Event bridge:** consume `task_events` using an owner-scoped durable cursor;
   map completed, blocked, crash, timeout, and triage events to a normalized
   `WorkEvent`; preserve run ID and payload for status queries; and translate
   summary/artifact references without exposing internal IDs in speech.
5. **Voice delivery acknowledgement:** call `announce_work`, keep the event
   pending until playback starts, and persist/replay pending delivery state.
   Barge-in should cancel speech only, as the current gateway already does;
   it must leave accepted Work and undelivered announcements owned by the
   session (`hermes_cli/realtime_voice/gateway.py:97-103`,
   `tests/hermes_cli/test_realtime_voice_announcements.py:58-66`).
6. **Permission bridge:** create a Work/run-scoped authorization record that
   points to the existing approval request ID, exposes a one-time decision
   explicitly, rejects stale or foreign responses, and maps timeout, deny, or
   interrupted approval to a durable blocked/failure event.
7. **Question bridge:** when a worker blocks with `needs_input`, emit a
   Work-scoped question event with a durable question ID. Store the spoken
   answer as a comment or dedicated response record, then unblock only the
   matching Work/run. Do not use a bare `unblock_task` call as the answer.
8. **Cancellation bridge:** add a true terminal cancellation semantic for
   `cancel_work`, covering queued and running tasks and recording who cancelled
   and why. Keep `reclaim_task` available for operator recovery and retry, but
   do not present reclaim as user cancellation.
9. **Progress policy:** initially expose heartbeat/liveness and child-task
   done/total only. Add a normalized progress event only if voice needs
   percentage or phase updates; the current heartbeat note is not a stable
   machine-readable progress contract.

This boundary reuses the existing Kanban ledger, worker dispatcher, session
creation, approval, and playback code. It adds the missing identity,
authorization, Work-event, question-response, cancellation, and durable voice
delivery adapters without creating a second Work store.

## Source audit conclusion

The current realtime tests prove the transport shell only: they inject an
`AsyncMock` port, assert tool routing, and supply synthetic `WorkEvent` objects
(`tests/hermes_cli/test_realtime_voice_frontstage_tools.py:14-24`,
`tests/hermes_cli/test_realtime_voice_gateway.py:34-48`,
`tests/hermes_cli/test_realtime_voice_gateway.py:136-163`). The source tree has
no concrete implementation beyond the protocol and its router. Issue #4 is
therefore resolved at the research level as an adapter-and-event-seam problem:
Kanban can remain the authoritative Work lifecycle, but the realtime voice
frontstage still needs the ownership, Coordinator binding, cancellation,
permission, question, progress, and durable delivery seams listed above.

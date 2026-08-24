# Hermes realtime gateway and client seams

Issue: #2, “Map the Hermes realtime gateway and client seams”

Audit scope: the Hermes source in this worktree, with the required project
documents used only to state the declared architecture constraints. No
secondary implementation write-up or external source is used below. This is a
source audit, not a claim that the unmounted realtime path has been exercised
end to end.

## Executive answer

Hermes already contains the beginnings of the right provider-neutral backend
seam in hermes_cli/realtime_voice/: a provider registry, a native realtime
session contract, a gateway that translates provider events to client events,
frontstage tool routing, and Work-result announcement delivery
[hermes_cli/realtime_voice/provider.py:L16-L95,
hermes_cli/realtime_voice/gateway.py:L25-L72,
hermes_cli/realtime_voice/tools.py:L22-L33,
hermes_cli/realtime_voice/announcements.py:L20-L92].

That module is not mounted into the production FastAPI web server and has no
desktop client. The web server's final route-mount sequence contains plugin
routes, dashboard auth routes, and the SPA, but no realtime voice route
[hermes_cli/web_server.py:L18947-L19071]. The separate public API also
advertises realtime_voice: false
[gateway/platforms/api_server.py:L3342-L3367].

The implementation-spec seam should therefore be a new authenticated,
provider-session WebSocket endpoint and a separate desktop realtime client.
Reuse Hermes' existing WebSocket host/origin/peer checks, WS credential
validation, profile-scoped connection resolver, reconnect policy, Work port,
and desktop audio state. Keep the existing /api/ws JSON-RPC transport,
/api/audio/speak-stream legacy TTS transport, and turn-based Hermes Voice
loop as separate surfaces. This recommendation follows the protocol and
ownership boundaries in the code and the required ADR, which explicitly says
the Voice Gateway owns realtime control except native inference and that the
desktop client should carry PCM mic/playback transport rather than reuse the
legacy STT/TTS loop
[docs/adr/0001-hermes-hosts-realtime-voice.md:L9-L20].

## Reusable seams

### 1. Provider-neutral realtime control plane

RealtimeSession is already the narrow provider contract: append audio, submit
tool results, inject announcements, interrupt speech, observe closure, and
close
[hermes_cli/realtime_voice/provider.py:L16-L27]. RealtimeProvider adds
provider identity, aliases, sample rates, configuration, and connect
[hermes_cli/realtime_voice/provider.py:L30-L40]. The registry validates names
and sample rates, resolves aliases, and can list configured providers
[hermes_cli/realtime_voice/provider.py:L46-L95].

RealtimeVoiceGateway injects that registry, a frontstage tool router, a client,
voice context, and instructions. start() connects one provider with the Hermes
frontstage tool schema and event callbacks, then emits voice.ready with
provider and sample-rate metadata
[hermes_cli/realtime_voice/gateway.py:L29-L72]. The client-facing seam is
send_json; inbound client events are base64 audio append, interrupt,
playback-start acknowledgement, or no-op playback completion
[hermes_cli/realtime_voice/gateway.py:L25-L27,
hermes_cli/realtime_voice/gateway.py:L84-L110].

Provider events are normalized at the gateway boundary. Speech state and user
transcript events are forwarded, assistant transcript deltas and audio deltas
are tagged with a response ID, tool calls go through Hermes, and response
completion emits audio.done and idle state
[hermes_cli/realtime_voice/gateway.py:L121-L201]. The Qwen adapter is a
concrete first provider, not the gateway: it connects to its own provider
WebSocket, sends JSON events with base64 PCM, configures text/audio modalities
and smart turn detection, and maps provider events into normalized event names
[hermes_cli/realtime_voice/providers/qwen.py:L59-L144,
hermes_cli/realtime_voice/providers/qwen.py:L153-L226,
hermes_cli/realtime_voice/providers/qwen.py:L229-L278].

Reusable seam: instantiate RealtimeVoiceGateway behind a Hermes-owned
transport and inject a provider. Do not let the provider own Hermes session
identity, durable transcript state, Work state, or authentication.

### 2. Hermes frontstage tools, Work, and announcements

The tool router is already dependency-injected through HermesFrontstagePort for
memory, Work creation/status/cancellation, and permission responses
[hermes_cli/realtime_voice/tools.py:L22-L33]. FRONTSTAGE_TOOLS describes these
functions to the provider, including the important non-blocking semantics that
accepting Work does not mean that it is complete
[hermes_cli/realtime_voice/tools.py:L47-L127]. FrontstageToolRouter normalizes
aliases and arguments and delegates with a VoiceToolContext containing the
owner, voice-session, and tool-call IDs
[hermes_cli/realtime_voice/tools.py:L15-L20,
hermes_cli/realtime_voice/tools.py:L161-L221].

Work announcements are also isolated. WorkEvent carries an event ID, status,
payload, and Work ID; AnnouncementDelivery filters to terminal statuses,
requires ownership by the active voice session, suppresses duplicate or
in-flight events, injects a provider announcement, and only marks an event
delivered when the provider reports playback started
[hermes_cli/realtime_voice/announcements.py:L17-L25,
hermes_cli/realtime_voice/announcements.py:L54-L92].

Reusable seam: connect these ports to the existing Work authority and event
source. The current delivery sets are in-memory and local to one gateway
instance, so they are a protocol seam, not yet durable pending-announcement
storage.

### 3. Web server lifecycle and WebSocket security

The FastAPI lifespan initializes event and PTY state, reconciles the profile
database, warms the gateway import, starts desktop-specific orphan cleanup and
cron work, starts reapers/self-tests/auto-archive, then cancels tasks, closes
PTYs, and terminates the desktop-managed gateway on shutdown
[hermes_cli/web_server.py:L382-L478]. The server owns a per-process session
token that is either injected by the desktop or freshly generated
[hermes_cli/web_server.py:L529-L544].

The HTTP auth middleware does not protect WebSocket upgrades. Existing WS
routes call _ws_auth_reason and _ws_request_is_allowed themselves before
accepting. _ws_request_is_allowed combines Host/Origin and peer checks, and
the code explicitly repeats the HTTP DNS-rebinding guard because HTTP
middleware does not run for WebSockets
[hermes_cli/web_server.py:L16261-L16280]. _ws_auth_reason supports loopback
session tokens, gated single-use tickets, and server-internal credentials;
gated tickets stamp server-minted identity onto the WebSocket
[hermes_cli/web_server.py:L16313-L16428].

The existing /api/ws route demonstrates the admission order and identity
handoff: reject disabled chat, authenticate, apply request-boundary checks,
then pass the authenticated identity into tui_gateway.ws.handle_ws
[hermes_cli/web_server.py:L17535-L17559]. A new realtime route should reuse
these guards and identity rules, while owning a different handler and session
registry.

### 4. Existing JSON-RPC WebSocket seam

/api/ws is a JSON-RPC transport for the TUI gateway. Its documented wire
format is newline-delimited JSON in both directions, with gateway.ready after
accept [tui_gateway/ws.py:L1-L22]. The server receives text frames, parses
JSON, handles gateway.ping, and dispatches all other messages through the
existing tui_gateway.server.dispatch function
[tui_gateway/ws.py:L319-L404, tui_gateway/ws.py:L406-L476]. The dispatcher
binds the transport for inline and worker-thread handlers, and routes replies
and events through the same transport
[tui_gateway/server.py:L1990-L2019, tui_gateway/server.py:L2463-L2501].

The desktop client mirrors that contract. JsonRpcGatewayClient sends a JSON
RPC object as text, parses JSON responses/events, maintains pending request
timeouts, and runs heartbeat state
[apps/shared/src/json-rpc-gateway.ts:L99-L125,
apps/shared/src/json-rpc-gateway.ts:L132-L254,
apps/shared/src/json-rpc-gateway.ts:L316-L485].

Reusable seam: the server's connection admission, heartbeat, reconnect
patterns, and profile routing. Boundary: /api/ws is not a raw audio
transport and its handler is coupled to tui_gateway.server.dispatch. The
realtime module's own audio contract is base64 JSON, while WSTransport also
serializes dicts as JSON text and has token-event coalescing
[hermes_cli/realtime_voice/gateway.py:L84-L95,
hermes_cli/realtime_voice/gateway.py:L164-L174,
tui_gateway/ws.py:L140-L189]. Putting both protocols into one handler would
couple independent session lifecycles and make audio compete with chat
RPC/event traffic.

### 5. One-way event and SSE transports

/api/pub accepts text from a PTY-side publisher and broadcasts it; /api/events
only holds a subscriber open and receives no client speech
[hermes_cli/web_server.py:L17562-L17645]. The PTY publisher is explicitly
best effort, bounded, and one-way, with no JSON-RPC envelope
[tui_gateway/event_publisher.py:L1-L17, tui_gateway/event_publisher.py:L90-L126].
These are useful event-relay precedents, not a full-duplex voice session.

SSE exists in the separate aiohttp public API for one-way agent output. The
session chat stream and chat-completion writer emit text/event-stream and
interrupt the agent if the stream disconnects
[gateway/platforms/api_server.py:L4718-L4729,
gateway/platforms/api_server.py:L5402-L5417]. Run lifecycle events use a
queued SSE stream that closes when the run finishes
[gateway/platforms/api_server.py:L8015-L8064]. There is no SSE audio or
realtime voice session in the FastAPI desktop gateway. SSE therefore does not
satisfy the bidirectional audio and interruption requirement.

### 6. Desktop connection and authentication seam

The shared URL helper already encodes the correct credential lifecycle: OAuth
connections must mint a fresh URL immediately before opening because their
ticket is single-use; local/token connections can reuse the connection URL
[apps/shared/src/websocket-url.ts:L9-L21,
apps/shared/src/websocket-url.ts:L39-L94]. The URL builder can target an
arbitrary gateway path and merge profile/auth query parameters
[apps/shared/src/websocket-url.ts:L96-L150].

The desktop gateway store resolves either the active profile or an explicit
connectionId and profile, resolves a fresh WS URL, opens the JSON-RPC client,
and schedules reconnects on close/error
[apps/desktop/src/store/gateway.ts:L326-L374,
apps/desktop/src/store/gateway.ts:L481-L518]. The boot reconnect path re-mints
OAuth tickets and refreshes profile/session state after a successful reconnect
[apps/desktop/src/app/gateway/hooks/use-gateway-boot.ts:L296-L334].
Electron exposes getConnection, getConnectionFor, and their WS URL
counterparts as the renderer's connection-routing bridge
[apps/desktop/src/global.d.ts:L17-L49].

Reusable seam: a realtime desktop client should resolve the active
connectionId and profile through this same bridge and use
resolveGatewayWsUrl, rather than deriving a URL from the primary backend.
The existing voice playback resolver is a concrete precedent for doing this
and for swapping an authenticated /api/ws URL to a voice-specific endpoint
[apps/desktop/src/lib/voice-playback.ts:L105-L158].

### 7. Current voice and audio path, which must remain separate

The current mic hook requests a browser MediaStream, creates a
MediaRecorder, buffers encoded chunks, and returns one Blob only when the
recorder stops
[apps/desktop/src/app/chat/composer/hooks/use-mic-recorder.ts:L169-L259]. The
current voice conversation stops that recorder, posts the complete blob for
transcription, and submits the resulting text to the normal chat path
[apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts:L138-L203].
Its barge monitor can interrupt an in-flight chat turn, but the captured
interruption is still transcribed and submitted as another text turn
[apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts:L303-L364,
apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts:L367-L375].

The corresponding server routes are complete-recording STT and complete-text
TTS. /api/audio/transcribe accepts a base64 data URL, writes a temporary file,
and calls transcribe_recording; /api/audio/speak calls the existing TTS
provider chain and returns a base64 data URL
[hermes_cli/web_server.py:L5175-L5265,
hermes_cli/web_server.py:L5418-L5493]. /api/audio/voice-config is a
client-direct STT/TTS optimization, not a native provider session
[hermes_cli/web_server.py:L5269-L5302].

/api/audio/speak-stream is the existing streaming TTS seam: text JSON frames
enter, sentence chunks are synthesized, and raw int16 PCM binary frames leave
the server
[hermes_cli/web_server.py:L5522-L5541,
hermes_cli/web_server.py:L5583-L5673]. The desktop opens that socket, creates
an AudioContext, schedules binary PCM, and closes it for stop or barge-in
[apps/desktop/src/lib/voice-playback.ts:L325-L383,
apps/desktop/src/lib/voice-playback.ts:L385-L495]. The voice loop feeds
assistant text into this session while chat generation continues
[apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts:L483-L570].

This is a useful playback-state and profile-routing seam, but it is still
legacy text-to-speech relay. It does not provide provider-native full-duplex
mic audio, provider turn detection, native tool calls, or a durable Voice
Conversation.

### 8. Backend and chat-session lifecycle

The desktop launches a headless hermes serve backend on loopback with an
ephemeral port, with a legacy dashboard fallback for older runtimes
[apps/desktop/electron/backend-command.ts:L1-L38]. It keeps generation-guarded
process and connection state so stale start attempts cannot publish a dead
backend
[apps/desktop/electron/backend-connection-state.ts:L11-L86,
apps/desktop/electron/main.ts:L10737-L10824]. Backend readiness tests the actual
authenticated /api/ws connection, not just HTTP reachability
[apps/desktop/electron/main.ts:L10606-L10627,
apps/desktop/electron/main.ts:L11047-L11064].

Primary and pooled backend shutdown is coordinated, waits for process exit, and
is invoked from Electron quit teardown
[apps/desktop/electron/main.ts:L10642-L10678,
apps/desktop/electron/main.ts:L15576-L15664]. The server also reaps orphaned
desktop backends at startup and terminates its desktop-managed gateway at
lifespan shutdown
[hermes_cli/web_server.py:L429-L478]. A realtime provider session must close
or recover across both the renderer socket and this backend process lifecycle.

The existing JSON-RPC session model is a different ownership domain.
session.create creates an in-memory runtime session, binds its transport, and
deliberately defers the durable database row until the first prompt
[tui_gateway/methods_session.py:L14-L25,
tui_gateway/methods_session.py:L73-L125]. prompt.submit rebinds a chat
session to the current transport, and WS disconnect either closes sessions
configured for that behavior or parks others for resume/reap
[tui_gateway/methods_prompt.py:L358-L364,
tui_gateway/server.py:L1363-L1430]. Those are reusable transport-lifecycle
patterns, but they do not make a chat session the durable Voice Conversation.

## Constraints the implementation must respect

The required project constraints say:

- Hermes is the durable host and system of record; the provider owns native
  inference only
  [docs/adr/0001-hermes-hosts-realtime-voice.md:L3-L15].
- The realtime gateway owns the control plane, while the desktop sends PCM
  transport; the legacy dictation/STT/TTS/auto-speak loop is not the new
  primitive
  [docs/adr/0001-hermes-hosts-realtime-voice.md:L17-L20].
- A Voice Session is temporary, while one durable Voice Conversation and its
  primary Coordinator Session are Hermes-owned; Work and announcements remain
  Hermes-owned
  [CONTEXT.md:L8-L15, CONTEXT.md:L30-L45,
  docs/adr/0001-hermes-hosts-realtime-voice.md:L22-L38].
- The transcript, compaction, provider switching, interruption semantics,
  audio ownership, recovery, and Work delivery are Hermes responsibilities,
  not provider memory
  [docs/design/grilling-decision-ledger.md:L11-L57].
- Acceptance requires actual bidirectional low-latency behavior, audio beginning
  while response generation continues, and working barge-in. A mic UI or one
  completed TTS reply is insufficient
  [docs/design/grilling-decision-ledger.md:L59-L80].

## Coupling, gaps, and open facts

### Confirmed gaps in the current source

1. **No production integration.** The realtime module has no FastAPI route,
   auth admission, profile resolution, or desktop caller. The final FastAPI
   mount block and the production-source search support this conclusion
   [hermes_cli/web_server.py:L18947-L19071].
2. **No realtime desktop client.** The only desktop gateway client is the
   JSON-RPC HermesGateway; the voice UI still uses MediaRecorder blobs, STT
   POST, normal prompt.submit, and legacy TTS relay
   [apps/shared/src/json-rpc-gateway.ts:L316-L447,
   apps/desktop/src/app/chat/composer/hooks/use-mic-recorder.ts:L208-L259,
   apps/desktop/src/app/chat/composer/hooks/use-voice-conversation.ts:L148-L188].
3. **No durable conversation or transcript write in the realtime core.** The
   gateway stores only one in-memory provider session, client, turn counter,
   playback waiters, and response/announcement pairing maps; provider transcript
   and response events are forwarded to the client
   [hermes_cli/realtime_voice/gateway.py:L29-L50,
   hermes_cli/realtime_voice/gateway.py:L138-L201].
4. **Provider failure supervision is incomplete.** The session protocol exposes
   wait_closed, but the gateway's close() only closes the current session and
   clears playback waiters; no code in this module supervises provider closure,
   reconnect, resume, or deduplication after a drop
   [hermes_cli/realtime_voice/provider.py:L16-L27,
   hermes_cli/realtime_voice/gateway.py:L112-L119].
5. **Playback acknowledgement is narrow.** Only playback.started is paired;
   playback.cancelled and playback.ended are ignored. Announcement and response
   IDs are paired FIFO, which is an unverified assumption if provider responses
   overlap
   [hermes_cli/realtime_voice/gateway.py:L104-L110,
   hermes_cli/realtime_voice/gateway.py:L203-L234].
6. **Announcement durability is absent.** Delivery deduplication and pending
   state are sets inside one AnnouncementDelivery instance, and only terminal
   Work events are accepted
   [hermes_cli/realtime_voice/announcements.py:L17-L18,
   hermes_cli/realtime_voice/announcements.py:L54-L91].
7. **Tool semantics conflict with the design ledger.** The code exposes
   memory actions read, append, and replace, while the ledger declares realtime
   memory context read-only
   [hermes_cli/realtime_voice/tools.py:L47-L65,
   docs/design/grilling-decision-ledger.md:L24-L31].
8. **No audio-owner or multi-client policy exists.** The gateway has one client
   and one provider session per instance, but no lease, takeover, or
   single-capture enforcement beyond whatever route creates the instance
   [hermes_cli/realtime_voice/gateway.py:L29-L50].

### Open facts the implementation spec must decide

- Whether the new endpoint is a separate path such as /api/realtime or an
  extension of /api/ws. The source favors a separate handler because /api/ws
  is hard-wired to JSON-RPC dispatch, while the realtime core has a different
  event protocol.
- Whether the client sends base64 PCM JSON, binary PCM, or a negotiated codec.
  The current realtime core uses base64 JSON, the legacy TTS path uses binary
  PCM, and the current mic path produces encoded blobs. No shared full-duplex
  media contract exists
  [hermes_cli/realtime_voice/gateway.py:L87-L95,
  hermes_cli/web_server.py:L5533-L5540,
  apps/desktop/src/app/chat/composer/hooks/use-mic-recorder.ts:L194-L245].
- Where the durable Voice Conversation and primary Coordinator Session are
  created, rehydrated, compacted, and reconciled with partial/interrupted
  assistant output. The current VoiceToolContext carries IDs but does not
  create those durable records
  [hermes_cli/realtime_voice/tools.py:L15-L20].
- How playback acknowledgements identify the exact played audio, including
  interruption, queued audio, late frames, and response concurrency. The
  current FIFO pairing is not a durable reconciliation protocol
  [hermes_cli/realtime_voice/gateway.py:L203-L234].
- How provider socket loss, backend restart, desktop sleep/wake, and OAuth
  ticket renewal affect the temporary Voice Session. Existing desktop
  reconnect code can provide the outer pattern, but it intentionally resets
  stale runtime IDs and refreshes chat state
  [apps/desktop/src/app/gateway/hooks/use-gateway-boot.ts:L296-L334].
- How Work completion events are subscribed to and retained while the voice
  client is offline, and how event IDs remain idempotent across gateway
  restarts. The current announcement object has no durable queue
  [hermes_cli/realtime_voice/announcements.py:L54-L92].
- Whether Qwen is only the first replaceable adapter or also supplies required
  capabilities such as native turn detection, interruption, and audio format
  guarantees. The registry supports replacement, but only Qwen currently
  implements the concrete provider in this path
  [hermes_cli/realtime_voice/provider.py:L61-L95,
  hermes_cli/realtime_voice/providers/qwen.py:L229-L278].

## Recommended implementation boundary

1. Add a new FastAPI WebSocket handler beside the existing WS routes. Apply
   _ws_auth_reason, _ws_request_is_allowed, and profile validation before
   accepting; pass only server-verified identity into the Hermes-owned voice
   context. Instantiate RealtimeVoiceGateway with an injected Hermes
   frontstage port and a transport adapter.
2. Add a desktop realtime client beside HermesGateway, not inside the
   JSON-RPC dispatcher. Resolve the active connection/profile through
   getConnectionFor and getGatewayWsUrlFor when present, mint fresh OAuth
   credentials per dial, and own reconnect/close state separately from chat
   RPC.
3. Define the audio protocol and acknowledgements before wiring the current
   voice UI. The existing AudioContext playback and stop sequence are useful
   client primitives, but MediaRecorder blob capture and /api/audio/* are the
   legacy turn path.
4. Bind the new session to Hermes durable Voice Conversation, Coordinator,
   Work, transcript, compaction, and announcement authorities before claiming
   full-duplex completion. Keep provider-native inference and provider socket
   state behind RealtimeProvider.

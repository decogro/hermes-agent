# Realtime voice long-session architecture

Status: concise research draft, 2026-08-24

## Decision

Hermes Gateway should be the sole authority for the application lifecycle:

- one durable Hermes Voice Conversation owns the canonical transcript;
- Hermes owns compaction checkpoints, recovery, memory access, tool semantics,
  coordination, Kanban work, and announcement delivery;
- one primary Hermes Coordinator Session is attached to that Voice Conversation;
- one ephemeral native speech-to-speech connection is active at a time, with a
  replacement connection created after disconnect or provider expiry;
- one disposable LiveKit `AgentSession` owns the active media/model mechanics;
- LiveKit `RealtimeModel` plugins expose normalized provider behavior, with a
  small Hermes capability layer for differences that affect recovery or tools.

Provider resumption, provider history, and provider compression are useful
adapter optimizations. They are not the source of truth. This gives the user
one conversation even when the provider connection changes, and it prevents a
provider's context policy from becoming Hermes memory or task state.

## Comparison

| System | Long-session behavior | Tool and deep-work behavior | Ownership and limitation |
| --- | --- | --- | --- |
| ChatGPT GPT-Live and OpenAI Realtime | GPT-Live keeps stateful voice inference running continuously. When context compaction or instance replacement is needed, ChatGPT warms a replacement instance beside the current one, prefills the replacement with the current or compacted context, runs both briefly, and cuts over without interrupting media. The public Realtime API separately exposes configurable oldest-first truncation, but does not document this managed warm-handoff control plane. ([GPT-Live engineering](https://openai.com/index/continuous-voice-interaction-with-gpt-live/), [Realtime truncation](https://developers.openai.com/api/reference/python/resources/realtime/subresources/calls/methods/accept)) | GPT-Live explicitly separates continuous talking from deeper thinking. The application server creates and prefills a frontier-model inference session when voice begins, keeps it available with stable affinity, and delegates reasoning and tools over an asynchronous boundary while voice remains available. ChatGPT also maintains speculative live turns and a separate authoritative finalized transcript. ([GPT-Live engineering](https://openai.com/index/continuous-voice-interaction-with-gpt-live/), [GPT-Live launch](https://openai.com/index/introducing-gpt-live/)) | This is the strongest architectural reference and directly matches the Hermes target. GPT-Live-1 is not yet publicly available through the API, so Hermes must implement the control-plane pattern around an available S2S model rather than depend on ChatGPT's private runtime. ChatGPT currently limits one Live call to two hours even though the underlying chat remains durable. ([ChatGPT Voice](https://help.openai.com/en/articles/20001274/)) |
| Gemini Live API | A WebSocket normally ends after about ten minutes. Session resumption supplies a handle valid for two hours. Context-window compression uses a sliding window and can extend a session to effectively unlimited duration. Without compression, audio-only and audio-video limits are documented as 15 minutes and 2 minutes. ([session management](https://ai.google.dev/gemini-api/docs/live-api/session-management), [best practices](https://ai.google.dev/gemini-api/docs/live-api/best-practices)) | Custom functions are executed by the application. Gemini 2.5 Flash Live supports non-blocking function calling; Gemini 3.1 Flash Live documents sequential function calling and does not support the non-blocking behavior. ([capabilities](https://ai.google.dev/gemini-api/docs/live-api/capabilities), [WebSocket guide](https://ai.google.dev/gemini-api/docs/live-api/get-started-websocket)) | The application maintains the WebSocket and must preserve any durable history. Provider compression and resumption do not define Hermes durability. Async tools are model-specific. |
| Qwen Audio Realtime | One WebSocket is one session. The documented maximum is 50 audio turns and 300 seconds of audio for the 3.0 realtime models; older history is automatically dropped. `max_history_turns` defaults to 20 and may be set from 1 to 50. The API supports creating, querying, deleting, and injecting conversation items. ([overview](https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime), [client events](https://help.aliyun.com/en/model-studio/fun-audiochat-client-events)) | Function calls are returned to the client, which executes the function and sends a result followed by `response.create`. The API docs do not establish that a long-running function is non-blocking, so Hermes must return a fast work-accepted receipt rather than wait for completion. ([function calling section](https://help.aliyun.com/zh/model-studio/fun-audiochat-realtime)) | The provider has bounded context and no verified provider-native durable reconnect mechanism in the cited API docs. Hermes must persist the transcript and replay a compact projection after reconnect. |
| qwen-audio-agent | Its reference architecture separates realtime speech from a persistent backend Agent session. `spawn_thinking` returns immediately, allowing multiple Work items while the user continues speaking; completion is later presented into the realtime conversation. ([architecture](https://github.com/QwenAudio/qwen-audio-agent/blob/main/docs/architecture.md)) | The repository's gateway owns work records, task status, cancellation, and pending announcements. The current source keeps a bounded in-memory conversation projection and restores recent context into a newly created provider connection. ([conversation sync](https://github.com/QwenAudio/qwen-audio-agent/blob/main/server/src/conversation/conversation-sync.mjs), [context projection](https://github.com/QwenAudio/qwen-audio-agent/blob/main/server/src/conversation/frontend-agent-context.mjs), [provider restore](https://github.com/QwenAudio/qwen-audio-agent/blob/main/server/src/voice/realtime-provider.mjs)) | This is the closest reference architecture, but its default memory and task ownership are Qwen-side. We should copy the separation and announcement pattern while replacing Qwen persistence and task authority with Hermes. |
| xAI Voice Agent API | With resumption disabled, a closed WebSocket loses conversation history. With `resumption.enabled` and a `conversation_id`, xAI caches turns for reconnection; the documented expiry is 30 minutes of inactivity. No public voice documentation reviewed here establishes context compression or a longer durable-session limit. ([speech-to-speech](https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech)) | Server-side web, X, file-search, and remote MCP tools can be executed by xAI. Custom functions require the application to execute the call, send `function_call_output`, and request another response. Its `force_message` event can inject an interruptible spoken announcement with a normal response lifecycle, making xAI a strong fit for pushed Hermes results. Long Work still needs an immediate Hermes acceptance receipt. ([speech-to-speech](https://docs.x.ai/developers/model-capabilities/audio/speech-to-speech)) | xAI resumption is a cache, not Hermes history. Compression behavior and exact long-conversation limits are unknown from the reviewed official voice docs. Hermes should not rely on xAI server tools because they bypass Hermes tool semantics. |
| AWS Nova Sonic | Current Nova documentation lists a maximum connection duration of 8 minutes and a 300K input context. Recovery is application-managed: store chat history, end the connection, open a new one, and replay history after the system prompt and before new audio. ([Nova model information](https://docs.aws.amazon.com/nova/latest/userguide/what-is-nova.html), [input events](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-input-events.html), [error recovery](https://docs.aws.amazon.com/nova/latest/userguide/speech-errors.html)) | Nova 2 Sonic explicitly supports asynchronous tool calling: the model can continue the conversation while the tool runs, and the application later returns a `toolResult`. The application must always return a result for a tool call. ([tool configuration](https://docs.aws.amazon.com/nova/latest/nova2-userguide/sonic-tool-configuration.html)) | This is a strong fit for the execution boundary, but the 8-minute provider connection must be treated as disposable. AWS documents replay, not a provider resume token. |
| Hume EVI | EVI documents a maximum session duration of 30 minutes. A chat can be resumed with its `chat_group_id`, provided data retention is enabled. `custom_session_id` can correlate application state across EVI sessions. ([overview](https://dev.hume.ai/docs/speech-to-speech-evi/overview), [resume chats](https://dev.hume.ai/docs/speech-to-speech-evi/features/resume-chats), [session settings](https://dev.hume.ai/docs/speech-to-speech-evi/configuration/session-settings), [timeouts](https://dev.hume.ai/docs/speech-to-speech-evi/configuration/timeouts)) | Custom tools are executed by the application. Hume documents no parallel function calling, so only one custom function runs at a time. Pausing stops generation while continuing listening and transcription, but tool use is disabled while paused. ([tool use](https://dev.hume.ai/docs/speech-to-speech-evi/features/tool-use), [pause responses](https://dev.hume.ai/docs/speech-to-speech-evi/features/pause-responses)) | Resume depends on Hume retention settings and provider chat state. Hume does not document a Hermes-compatible compaction strategy or durable task ledger. |

## What the long-session designs have in common

### 1. The live model is not the durable conversation

Provider sessions contain the context needed for current inference. They are
bounded, expiring, or reconnectable caches. ChatGPT uses the same separation:
its application server persists the conversation off the live media path, and
its voice infrastructure treats model instances as replaceable while keeping
the user-visible conversation continuous. ([GPT-Live engineering](https://openai.com/index/continuous-voice-interaction-with-gpt-live/))

Hermes should therefore write finalized user and assistant turns to the one
Voice Conversation independently of provider events. Audio is transport data;
the canonical durable record is the transcript plus metadata such as turn IDs,
interruptions, tool receipts, and announcement delivery state.

Hermes has one canonical transcript. While someone is speaking, the Gateway
may hold a temporary, revisable hypothesis for the current unfinished turn.
That hypothesis is not a second transcript and is never durable. Once speaker
attribution and wording are stable, the Gateway commits that turn exactly once
to the canonical transcript and uses committed turns for context compaction.

### 2. Reconnect is a projection operation

On every provider connection:

1. Hermes loads the current compaction checkpoint and recent canonical turns.
2. The provider adapter applies those items using the provider's supported
   history-injection mechanism before live audio begins.
3. Hermes adds read-only memory context and the current coordinator identity.
4. The provider connection receives new audio and emits normalized events.

If a provider resume handle is valid, the adapter may use it first and verify
that the provider's replayed context matches the Hermes conversation. If the
handle is missing, expired, or invalid, Hermes opens a new provider session and
rehydrates from its own checkpoint. A provider-specific synthetic user message
must not be copied blindly: the adapter must use the provider's history item
semantics and preserve Hermes's message-role and prompt-caching invariants.

The checkpoint should contain a compact conversation summary, unresolved
references, current user preferences needed for the voice interaction, active
work IDs, and undelivered announcements. It should not contain the complete
transcript in every provider request.

### 3. Deep work must be a receipt, not a blocking tool call

The live provider should have a small normalized semantic surface:

- `read_memory`, read-only Hermes context;
- `spawn_work`, which creates or updates a Hermes Kanban item and immediately
  returns a Work ID and accepted status;
- `get_work_status`;
- `cancel_work`;
- permission response, when required by Hermes.

The primary Hermes Coordinator Session owns the work decision and can delegate
to Hermes worker or additional coordinator sessions. Those sessions never own a
voice conversation and never speak directly. This is the same separation that
qwen-audio-agent calls realtime frontend versus backend Agent session, but the
durable owner here is Hermes.

When work completes, Hermes records the result in Kanban and creates a pending
announcement. The next active provider connection receives a short announcement
through an adapter operation. The announcement is acknowledged only after the
provider has accepted it and playback has completed. If the provider is
disconnected, the announcement remains in Hermes and is delivered after
reconnect. This prevents a provider disconnect from losing completed work.

Provider function calling is not a portable async contract. Gemini's
non-blocking mode is model-dependent, Nova 2 documents asynchronous tools, and
Qwen, xAI, and Hume document application execution but do not establish the
same non-blocking behavior for arbitrary long-running functions. The Hermes
adapter must make `spawn_work` fast even when the provider's function protocol
waits for a result.

## Media and session ownership

The selected topology uses one media path for desktop and mobile. Clients join
an authenticated LiveKit room, while the Hermes Realtime Voice Gateway hosts
the disposable `AgentSession` and all durable meaning remains in Hermes:

```text
Desktop or phone
   |
   | LiveKit WebRTC audio + authenticated data
   v
LiveKit room
   |
   v
Hermes Realtime Voice Gateway
   |
   +-- disposable LiveKit AgentSession --> Realtime S2S Provider
   +-- durable Voice Conversation
   +-- authoritative transcript + compaction
   +-- provider lifecycle + recovery
   +-- primary Coordinator Session
   +-- Kanban + announcement ledger
```

The provider owns native S2S inference, VAD, interruption behavior, and audio
generation. The Gateway creates and authorizes the provider session, owns its
control channel and lifecycle, commits transcripts, projects context, executes
tools, and delivers announcements. LiveKit moves audio and temporary session
events but does not own conversation identity, Work, memory, or recovery.

## Infrastructure patterns worth copying

LiveKit Agents separates an `AgentSession` from room media, supports provider
pipelines, background tools, and explicit history handling during handoffs. Its
documentation also says applications should persist history and that realtime
transcripts can be delayed or incomplete, so LiveKit is transport and session
infrastructure, not durable memory. ([sessions](https://docs.livekit.io/agents/logic/sessions/), [tools](https://docs.livekit.io/agents/logic/tools/), [handoffs](https://docs.livekit.io/agents/logic/agents-handoffs/), [logging](https://docs.livekit.io/agents/ops/logging/))

Pipecat provides useful provider-neutral patterns: context aggregators keep STT
and TTS text in the LLM context, optional summarization compresses older turns
outside the main pipeline, and `cancel_on_interruption=False` allows a function
to continue while conversation proceeds. These are patterns to reproduce at
the Hermes adapter boundary, not a reason to add another gateway or durable
store. ([context management](https://docs.pipecat.ai/pipecat/learn/context-management), [summarization](https://docs.pipecat.ai/pipecat/fundamentals/context-summarization), [function calling](https://docs.pipecat.ai/pipecat/learn/function-calling))

## Recommendation

1. Copy the GPT-Live control-plane architecture: keep the media path dedicated,
   keep persistence and application logic off that path, and delegate deeper
   work to the already-warm primary Hermes Coordinator Session asynchronously.
2. Use LiveKit's `RealtimeModel` seam and add only Hermes-relevant capability
   flags: interruption, server push, history seeding, provider resumption,
   provider compression, asynchronous tool receipt, and transcript quality.
3. Make Hermes transcript and compaction the authority. Treat Gemini handles,
   xAI conversation IDs, Qwen history, Nova replay, and Hume chat groups as
   disposable provider metadata.
4. Preserve the realtime/backend split and announcement queue, a fast
   asynchronous Work receipt, and explicit reconnect and compression capability
   detection.
5. Require `server_push_announcement` or an equivalent provider adapter path for
   a provider to claim immediate background completion announcements. Otherwise
   queue the result until the next user turn or reconnect.
6. Benchmark providers separately from the architecture. The strongest
   documented long-session properties are Gemini's resumption plus compression;
   the strongest documented async-work property is Nova 2 Sonic. Qwen is the
   closest existing reference implementation for the desired three-layer
   delegation shape. xAI has the clearest documented pushed-speech primitive
   for background announcements. Hume is viable, but its public docs leave
   compaction and tool-parallelism limitations that Hermes must handle.

## Provider benchmark gate

Do not choose the permanent S2S model from feature tables alone. Build the
LiveKit-to-Hermes seam first, use one supported provider only as an integration
fixture, then run the same acceptance harness against the strongest supported
native S2S candidates. A provider passes only if it can:

1. begin a direct spoken reply within the target latency;
2. stop audible playback within the barge-in target;
3. accept `spawn_work` immediately and sustain unrelated conversation while
   Hermes Work remains active;
4. speak a pushed completion without requiring another user turn;
5. survive a forced reconnect using a Hermes context projection;
6. reconcile interrupted and overlapping transcripts without corrupting the
   authoritative Voice Conversation;
7. avoid duplicate Work or duplicate announcements after recovery; and
8. meet the acceptable cost per active audio minute.

Provider-native resumption and compression should be tested twice: enabled as
an optimization, and disabled with a cold Hermes-managed rehydrate. Passing the
cold path is what proves provider independence.

### Deliberately unknown

- Whether the upcoming GPT-Live API will expose ChatGPT's warm handoff,
  asynchronous frontier delegation, and authoritative transcript controls.
- xAI voice context compression and maximum retained context beyond its
  documented 30-minute resumption cache.
- Qwen provider-native reconnect/resumption beyond replaying conversation items.
- Hume's internal compaction and the exact context retained on chat resume.
- Whether any provider's server-side tools can be made to honor Hermes's
  permission, audit, and Kanban semantics without bypassing the Gateway.

Those unknowns do not block the design because Hermes remains authoritative and
the adapter can fail closed when a provider lacks a required capability.

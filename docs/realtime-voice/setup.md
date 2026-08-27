# Native realtime voice setup

This is the launch path for Hermes's native speech-to-speech mode. It is not
the legacy Hermes Voice loop. The desktop conversation button joins a LiveKit
room and sends microphone audio directly to one temporary native realtime
model session. Hermes remains the durable owner of the transcript, memory,
Work, Coordinator Session, permissions, and results.

## What is already wired

- The desktop conversation button uses LiveKit WebRTC microphone and speaker
  tracks. It never routes through batch STT, normal chat submission, or TTS.
- Hermes mints short-lived room tokens through the authenticated dashboard
  route `POST /api/realtime-voice/token`. LiveKit secrets never reach the
  renderer.
- The realtime model receives only five Hermes tools: read-only memory,
  `spawn_work`, `get_work_status`, `cancel_work`, and
  `respond_to_work_permission`.
- Accepted Work is written to Hermes Kanban and delivered to one stable primary
  Coordinator Session through Hermes's Runs API.
- Permission prompts, failures, blocked Work, and final results return through
  durable Work events and are injected into the still-active voice session.
- Final user speech and actually played assistant speech are appended to one
  durable Voice Conversation. Interrupted unheard output is not recorded as if
  the user heard it.
- Native startup failures are explicit. Hermes does not silently fall back to
  its legacy turn-based voice loop.

## Remaining provider decision

The transport and Hermes integration are provider-neutral. A permanent native
speech-to-speech model has intentionally not been selected. The worker loads a
zero-argument model factory from `HERMES_REALTIME_MODEL_FACTORY`. That factory
must return a LiveKit-compatible native realtime model with streaming audio,
tool calls, interruption, and injected-reply support.

Provider-specific packages and credentials stay outside the Hermes core extra.
Picking a provider should require only installing its LiveKit plugin, adding a
small factory module, and setting the provider's credentials. It must not alter
the Hermes Work, memory, transcript, or desktop code.

## Host configuration

Install the realtime runtime and desktop dependencies:

```bash
uv sync --extra realtime-voice --extra dev
npm install
```

Set these host-only environment variables:

```bash
LIVEKIT_URL=wss://your-project.livekit.cloud
LIVEKIT_API_KEY=...
LIVEKIT_API_SECRET=...
HERMES_REALTIME_MODEL_FACTORY=python.module:function_name
API_SERVER_KEY=use-a-strong-existing-hermes-api-key
```

Stable defaults are already supplied for the single durable records:

```text
Voice Conversation: realtime-voice-main
Primary Coordinator Session: realtime-voice-coordinator
Coordinator Profile: default
Owner: local-owner
```

Override them only to bind existing Hermes records:

```bash
HERMES_VOICE_CONVERSATION_ID=...
HERMES_COORDINATOR_SESSION_ID=...
HERMES_COORDINATOR_PROFILE=...
HERMES_REALTIME_OWNER_ID=...
```

Start the normal Hermes gateway first. A configured `API_SERVER_KEY` enables
the loopback API server that the realtime worker uses for the primary
Coordinator Session:

```bash
hermes gateway run
```

Then start the realtime worker:

```bash
hermes-realtime-voice dev
```

Start the desktop app from this fork and click **Start voice conversation**.
The separate dictation microphone and read-aloud controls retain their legacy
behavior; they are not the native realtime path.

## Acceptance check

Do not accept text streaming as proof. A valid end-to-end test must show all of
these behaviors:

1. The model begins speaking before a long response has been fully generated.
2. Speaking over it stops current playback quickly without cancelling accepted
   background Work.
3. An action request creates a Hermes Kanban Work card while conversation stays
   available.
4. The same primary Coordinator Session receives every voice-created Work card.
5. A permission request is spoken, the user's answer resolves the matching
   Hermes run, and Work continues.
6. A final or blocked Work event is spoken without the user polling.
7. Reconnecting creates a new temporary provider session but continues the same
   `realtime-voice-main` durable Voice Conversation.

The final provider benchmark should measure time to first audible response,
barge-in latency, semantic turn accuracy, tool-call reliability, long-session
recovery, voice quality, and cost using this same acceptance path.

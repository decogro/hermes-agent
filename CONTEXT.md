# Hermes Realtime Voice

This context defines a continuously available speech frontstage whose durable
memory, work, coordination, and execution remain owned by Hermes.

## Language

**Realtime Frontstage**:
The continuously available speech experience that listens, speaks, answers
simple questions, and hands substantive requests to Hermes.
_Avoid_: Voice backend, main agent, coordinator

**Voice Session**:
A temporary live connection between the sole Voice Conversation and a Realtime
Provider. It does not own durable memory or execute Work.
_Avoid_: Coordinator Session, Worker Session, orchestration session

**Voice Conversation**:
The system's single durable direct-speech conversation and transcript. Every
Voice Session reconnects to it; no backend session owns another one.
_Avoid_: Voice chat, provider session, worker voice conversation

**Realtime Provider**:
A native speech-to-speech model endpoint capable of streaming audio, tool use,
interruption, and receiving background results. Qwen is one possible provider.
It owns inference only, not transcript, memory, Work, conversation identity, or
session recovery policy.
_Avoid_: Qwen when referring to the provider-neutral role

**Voice Gateway**:
The provider-neutral Hermes authority for Voice Conversation state, transcript,
context compaction, Realtime Provider lifecycle and recovery, Audio Ownership,
Frontstage Tool execution, Work routing, and Announcements. Provider-native
session state may optimize a live connection but is never authoritative.
_Avoid_: TaskManager, orchestrator, memory owner

**Legacy Hermes Voice**:
The existing turn-based dictation and read-aloud path. It is not a component of
the Realtime Frontstage and must not be used as its audio, session, or routing
primitive.
_Avoid_: Realtime Frontstage, native speech-to-speech

**Frontstage Tool Set**:
The operations available to a Realtime Provider: read Memory Context, spawn
Work, read Work status, cancel Work, and respond to a Work permission request.
_Avoid_: Hermes toolset, worker tools, backend tools

**Memory Context**:
The read-only Hermes profile knowledge made available to a Voice Session.
_Avoid_: Voice memory, editable voice memory, Qwen memory

**Direct Reply**:
A response produced entirely from the live conversation and Memory Context,
without performing any action or using any other source.
_Avoid_: Work, backend turn

**Work**:
A durable user request accepted for asynchronous execution by Hermes and
identified by a stable Work ID.
_Avoid_: Voice task, prompt, background message

**Root Work**:
The authoritative Kanban item created for one delegated user request and sent
to the paired Coordinator Session.
_Avoid_: Voice task, coordinator prompt, worker card

**Work Ledger**:
Hermes Kanban state that authoritatively records Work lifecycle, ownership,
progress, results, permissions, and cancellation.
_Avoid_: Qwen TaskManager, voice task store

**Coordinator Session**:
The single long-lived primary Hermes orchestration session paired with the
Voice Conversation. It receives all accepted Work and may create backend sessions.
_Avoid_: Voice Session, speech transcript, TaskManager

**Coordinator Profile**:
The dedicated Hermes profile that permanently owns the Voice Conversation and
primary Coordinator Session. Other profiles may perform delegated Work, but
they do not replace the voice identity or primary Coordinator.
_Avoid_: active worker profile, selectable voice profile

**Worker Session**:
An independent Hermes backend session created or resumed to complete or
coordinate all or part of a Work item. It has no Voice Conversation.
_Avoid_: Voice worker, frontend worker

**Work Event**:
An authoritative Hermes update that reports a Work status, permission request,
blocker, failure, or completion to interested clients.
_Avoid_: Model recollection, polling guess

**Announcement**:
A user-safe Work Event delivered to the Realtime Frontstage for natural speech.
_Avoid_: Worker output, raw event, notification when referring to speech

**Pending Announcement**:
An Announcement retained by Hermes until it is presented in the normal Hermes
interface and spoken by a relevant active Voice Session.
_Avoid_: Missed result, voice queue

**Spoken Permission**:
A one-time approval or rejection communicated through the Realtime Frontstage.
It never creates a permanent authorization rule.
_Avoid_: Always allow, permanent voice approval

**Audio Owner**:
The single connected client allowed to capture and play audio for a Voice
Session. Ownership may be handed to another connected client.
_Avoid_: Primary device, active microphone when referring to session authority

**Barge-in**:
User speech that interrupts current playback while preserving accepted Work
unless the user explicitly asks to cancel it.
_Avoid_: Work cancellation, stop task

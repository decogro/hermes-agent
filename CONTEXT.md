# Hermes Realtime Voice

This context defines a continuously available speech frontstage whose durable
memory, work, coordination, and execution remain owned by Hermes.

## Language

**Realtime Frontstage**:
The continuously available speech experience that listens, speaks, answers
simple questions, and hands substantive requests to Hermes.
_Avoid_: Voice backend, main agent, coordinator

**Voice Session**:
An ephemeral live conversation between a client and a Realtime Provider. It
does not own durable memory or execute Work.
_Avoid_: Coordinator Session, Worker Session, orchestration session

**Realtime Provider**:
A native speech-to-speech model endpoint capable of streaming audio, tool use,
interruption, and receiving background results. Qwen is one possible provider.
_Avoid_: Qwen when referring to the provider-neutral role

**Voice Gateway**:
The provider-neutral connection between a Voice Session and Hermes memory,
Work, permissions, and result events. It owns no durable user state.
_Avoid_: TaskManager, orchestrator, memory owner

**Legacy Hermes Voice**:
The existing turn-based dictation and read-aloud path. It is not a component of
the Realtime Frontstage and must not be used as its audio, session, or routing
primitive.
_Avoid_: Realtime Frontstage, native speech-to-speech

**Frontstage Tool Set**:
The five operations available to a Realtime Provider: memory, spawn Work, read
Work status, cancel Work, and respond to a Work permission request.
_Avoid_: Hermes toolset, worker tools, backend tools

**Direct Reply**:
A short answer produced inside the Voice Session without external tools,
current-information lookup, files, applications, code, or sustained reasoning.
_Avoid_: Work, backend turn

**Work**:
A durable user request accepted for asynchronous execution by Hermes and
identified by a stable Work ID.
_Avoid_: Voice task, prompt, background message

**Work Ledger**:
Hermes Kanban state that authoritatively records Work lifecycle, ownership,
progress, results, permissions, and cancellation.
_Avoid_: Qwen TaskManager, voice task store

**Coordinator Session**:
The Hermes session that receives accepted Work and decides whether to execute
it directly or create Worker Sessions. It is not the spoken conversation.
_Avoid_: Voice Session, speech transcript, TaskManager

**Worker Session**:
An independent Hermes execution session created or resumed to complete all or
part of a Work item.
_Avoid_: Voice worker, frontend worker

**Work Event**:
An authoritative Hermes update that reports a Work status, permission request,
blocker, failure, or completion to interested clients.
_Avoid_: Model recollection, polling guess

**Announcement**:
A user-safe Work Event delivered to the Realtime Frontstage for natural speech.
_Avoid_: Worker output, raw event, notification when referring to speech

**Barge-in**:
User speech that interrupts current playback while preserving accepted Work
unless the user explicitly asks to cancel it.
_Avoid_: Work cancellation, stop task

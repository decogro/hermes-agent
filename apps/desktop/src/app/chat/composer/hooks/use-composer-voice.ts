import { useStore } from '@nanostores/react'
import { useCallback, useEffect, useRef } from 'react'

import { useI18n } from '@/i18n'
import { chatMessageText } from '@/lib/chat-messages'
import { markAssistantIdSpoken, resolveSpokenReply } from '@/lib/spoken-reply'
import { clearWakeIndicator, syncWakeIndicatorWithVoice } from '@/lib/wake-indicator'
import { $voiceConversationStartRequest, takeVoiceConversationStart } from '@/store/composer'
import { $gateway } from '@/store/gateway'
import { notifyError } from '@/store/notifications'
import { $autoSpeakReplies, setAutoSpeakReplies } from '@/store/voice-prefs'
import { resumeWakeAfterVoice } from '@/store/wake-word'

import type { ComposerTarget } from '../focus'
import { onComposerVoiceToggleRequest } from '../focus'
import { useComposerScope } from '../scope'
import type { ChatBarProps } from '../types'

import { useAutoSpeakReplies } from './use-auto-speak-replies'
import { useNativeRealtimeVoice } from './use-native-realtime-voice'
import { useVoiceRecorder } from './use-voice-recorder'

interface UseComposerVoiceArgs {
  busy: boolean
  clearDraft: () => void
  disabled: boolean
  focusInput: () => void
  insertText: (text: string) => void
  maxRecordingSeconds: number
  onInterrupt?: () => Promise<void> | void
  onSubmit: ChatBarProps['onSubmit']
  onTranscribeAudio: ChatBarProps['onTranscribeAudio']
  sessionId: string | null | undefined
  target: ComposerTarget
}

/**
 * Voice controls for a composer.
 *
 * Dictation and read-aloud keep their existing turn-based implementations.
 * The conversation button is a separate native speech-to-speech path through
 * LiveKit and never submits transcript text through the normal chat composer.
 */
export function useComposerVoice({
  busy,
  disabled,
  focusInput,
  insertText,
  maxRecordingSeconds,
  onTranscribeAudio,
  sessionId,
  target
}: UseComposerVoiceArgs) {
  const { t } = useI18n()
  const { $messages } = useComposerScope()
  const ownsWakeIndicatorRef = useRef(false)
  const voiceStartRequest = useStore($voiceConversationStartRequest)

  const { dictate, voiceActivityState, voiceStatus } = useVoiceRecorder({
    focusInput,
    maxRecordingSeconds,
    onTranscript: insertText,
    onTranscribeAudio
  })

  const pendingResponse = () => {
    const messages = $messages.get()
    const last = messages.findLast(message => message.role === 'assistant' && !message.hidden)
    const spoken = resolveSpokenReply(sessionId, messages)

    if (!last || last.id === spoken?.id) {
      return null
    }

    const text = chatMessageText(last).trim()

    return text ? { id: last.id, pending: Boolean(last.pending), text } : null
  }

  const consumePendingResponse = () => {
    const messages = $messages.get()
    const last = messages.findLast(message => message.role === 'assistant' && !message.hidden)

    if (last) {
      markAssistantIdSpoken(sessionId, messages, last.id)
    }
  }

  const wakePausedRef = useRef(false)
  const wakePauseBarrierRef = useRef<Promise<void> | null>(null)

  const resumeWakeIfPaused = useCallback(() => {
    if (!wakePausedRef.current) {
      return
    }

    wakePausedRef.current = false
    wakePauseBarrierRef.current = null
    void resumeWakeAfterVoice()
  }, [])

  const pauseWakeForVoice = useCallback(() => {
    if (wakePauseBarrierRef.current) {
      return wakePauseBarrierRef.current
    }

    wakePausedRef.current = true

    const barrier = (async () => {
      try {
        await $gateway.get()?.request('wake.pause', {})
      } catch {
        // No wake listener or an older backend means no competing mic owner.
      }
    })()

    wakePauseBarrierRef.current = barrier

    return barrier
  }, [])

  const conversation = useNativeRealtimeVoice({
    beforeConnect: pauseWakeForVoice,
    onDisconnected: resumeWakeIfPaused
  })

  const voiceConversationActive = conversation.active

  // eslint-disable-next-line no-restricted-syntax -- ownership token used only by unmount cleanup
  useEffect(() => {
    if (target !== 'main') {
      return
    }

    if (syncWakeIndicatorWithVoice(voiceConversationActive, conversation.status)) {
      ownsWakeIndicatorRef.current = voiceConversationActive
    }
  }, [conversation.status, target, voiceConversationActive])

  useEffect(
    () => () => {
      if (ownsWakeIndicatorRef.current) {
        clearWakeIndicator()
      }

      resumeWakeIfPaused()
    },
    [resumeWakeIfPaused]
  )

  const startConversation = useCallback(() => {
    if (disabled || conversation.active) {
      return
    }

    void conversation.start().catch(() => resumeWakeIfPaused())
  }, [conversation, disabled, resumeWakeIfPaused])

  const endConversation = useCallback(() => {
    void conversation.end().finally(resumeWakeIfPaused)
  }, [conversation, resumeWakeIfPaused])

  const toggleVoiceConversation = useCallback(() => {
    if (voiceConversationActive) {
      endConversation()
    } else {
      startConversation()
    }
  }, [endConversation, startConversation, voiceConversationActive])

  useEffect(
    () => onComposerVoiceToggleRequest(toggled => toggled === target && toggleVoiceConversation()),
    [target, toggleVoiceConversation]
  )

  useEffect(() => {
    if (target === 'main' && !disabled && takeVoiceConversationStart(voiceStartRequest) && !voiceConversationActive) {
      startConversation()
    }
  }, [disabled, startConversation, target, voiceConversationActive, voiceStartRequest])

  const handleToggleAutoSpeak = useCallback(() => {
    void setAutoSpeakReplies(!$autoSpeakReplies.get()).catch(error =>
      notifyError(error, t.settings.config.autosaveFailed)
    )
  }, [t])

  useAutoSpeakReplies({
    conversationActive: voiceConversationActive,
    failureLabel: t.assistant.thread.readAloudFailed,
    markSpoken: consumePendingResponse,
    pendingReply: pendingResponse,
    sessionId
  })

  return {
    conversation,
    dictate,
    endConversation,
    handleToggleAutoSpeak,
    startConversation,
    voiceActivityState,
    voiceConversationActive,
    voiceStatus
  }
}

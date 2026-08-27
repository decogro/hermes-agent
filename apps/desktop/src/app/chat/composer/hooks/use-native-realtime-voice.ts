import { type RemoteTrack, Room, RoomEvent, Track } from 'livekit-client'
import { useCallback, useEffect, useRef, useState } from 'react'

import { createRealtimeVoiceConnection } from '@/api/realtime-voice'
import { notifyError } from '@/store/notifications'

import type { ConversationStatus } from './use-voice-conversation'

interface NativeRealtimeVoiceOptions {
  beforeConnect?: () => Promise<void> | void
  onDisconnected?: () => void
}

export interface NativeRealtimeVoiceConversation {
  active: boolean
  canStopTurn: false
  end: () => Promise<void>
  level: number
  muted: boolean
  start: () => Promise<void>
  status: ConversationStatus
  stopTurn: () => void
  toggleMute: () => Promise<void>
}

/**
 * Hermes-native realtime voice transport.
 *
 * LiveKit owns microphone and speaker transport. The speech-to-speech model
 * owns turn detection and barge-in. This hook never submits transcript text to
 * the normal chat composer and never falls back to the legacy STT/LLM/TTS loop.
 */
export function useNativeRealtimeVoice({
  beforeConnect,
  onDisconnected
}: NativeRealtimeVoiceOptions = {}): NativeRealtimeVoiceConversation {
  const [active, setActive] = useState(false)
  const [level, setLevel] = useState(0)
  const [muted, setMuted] = useState(false)
  const [status, setStatus] = useState<ConversationStatus>('idle')
  const roomRef = useRef<Room | null>(null)
  const attachedAudioRef = useRef(new Map<RemoteTrack, HTMLMediaElement>())
  const levelTimerRef = useRef<number | null>(null)
  const endingRef = useRef(false)

  const clearLevelTimer = useCallback(() => {
    if (levelTimerRef.current !== null) {
      window.clearInterval(levelTimerRef.current)
      levelTimerRef.current = null
    }
  }, [])

  const detachAudio = useCallback(() => {
    for (const [track, element] of attachedAudioRef.current) {
      track.detach(element)
      element.remove()
    }

    attachedAudioRef.current.clear()
  }, [])

  const reset = useCallback(() => {
    clearLevelTimer()
    detachAudio()
    roomRef.current = null
    setActive(false)
    setLevel(0)
    setMuted(false)
    setStatus('idle')
  }, [clearLevelTimer, detachAudio])

  const end = useCallback(async () => {
    const room = roomRef.current

    if (!room) {
      reset()

      return
    }

    endingRef.current = true

    try {
      await room.localParticipant.setMicrophoneEnabled(false)
      room.disconnect()
    } finally {
      reset()
      endingRef.current = false
    }
  }, [reset])

  const start = useCallback(async () => {
    if (roomRef.current) {
      return
    }

    setStatus('thinking')
    setActive(true)

    try {
      await beforeConnect?.()
      const connection = await createRealtimeVoiceConnection()
      const room = new Room({ adaptiveStream: true, dynacast: true })

      roomRef.current = room

      room.on(RoomEvent.TrackSubscribed, track => {
        if (track.kind !== Track.Kind.Audio) {
          return
        }

        const element = track.attach()

        element.autoplay = true
        element.style.display = 'none'
        document.body.appendChild(element)
        attachedAudioRef.current.set(track, element)
      })

      room.on(RoomEvent.TrackUnsubscribed, track => {
        const element = attachedAudioRef.current.get(track)

        if (element) {
          track.detach(element)
          element.remove()
          attachedAudioRef.current.delete(track)
        }
      })

      room.on(RoomEvent.ActiveSpeakersChanged, speakers => {
        const remoteSpeaking = speakers.some(participant => participant !== room.localParticipant)

        setStatus(remoteSpeaking ? 'speaking' : 'listening')
      })

      room.on(RoomEvent.Disconnected, () => {
        const notify = !endingRef.current

        reset()

        if (notify) {
          onDisconnected?.()
        }
      })

      await room.connect(connection.url, connection.token)
      await room.startAudio()
      await room.localParticipant.setMicrophoneEnabled(true)

      setActive(true)
      setMuted(false)
      setStatus('listening')
      clearLevelTimer()
      levelTimerRef.current = window.setInterval(() => {
        setLevel(room.localParticipant.audioLevel)
      }, 100)
    } catch (error) {
      const room = roomRef.current

      roomRef.current = null
      room?.disconnect()
      reset()
      notifyError(error, 'Could not start native realtime voice')
      throw error
    }
  }, [beforeConnect, clearLevelTimer, onDisconnected, reset])

  const toggleMute = useCallback(async () => {
    const room = roomRef.current

    if (!room) {
      return
    }

    const nextMuted = !muted

    await room.localParticipant.setMicrophoneEnabled(!nextMuted)
    setMuted(nextMuted)
  }, [muted])

  useEffect(
    () => () => {
      const room = roomRef.current

      clearLevelTimer()
      detachAudio()
      room?.disconnect()
      roomRef.current = null
    },
    [clearLevelTimer, detachAudio]
  )

  return {
    active,
    canStopTurn: false,
    end,
    level,
    muted,
    start,
    status,
    // Native speech-to-speech endpointing is provider-owned. Barge-in happens
    // by speaking; there is no buffered utterance for Hermes to force-close.
    stopTurn: () => {},
    toggleMute
  }
}

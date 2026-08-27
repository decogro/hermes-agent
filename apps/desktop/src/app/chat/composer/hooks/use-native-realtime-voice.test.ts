import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const mocks = vi.hoisted(() => ({
  connect: vi.fn(),
  createConnection: vi.fn(),
  disconnect: vi.fn(),
  notifyError: vi.fn(),
  setMicrophoneEnabled: vi.fn(),
  startAudio: vi.fn()
}))

vi.mock('@/api/realtime-voice', () => ({
  createRealtimeVoiceConnection: mocks.createConnection
}))

vi.mock('@/store/notifications', () => ({ notifyError: mocks.notifyError }))

vi.mock('livekit-client', () => {
  class Room {
    localParticipant = {
      audioLevel: 0.25,
      setMicrophoneEnabled: mocks.setMicrophoneEnabled
    }

    connect = mocks.connect
    disconnect = mocks.disconnect
    on = vi.fn()
    startAudio = mocks.startAudio
  }

  return {
    Room,
    RoomEvent: {
      ActiveSpeakersChanged: 'active-speakers-changed',
      Disconnected: 'disconnected',
      TrackSubscribed: 'track-subscribed',
      TrackUnsubscribed: 'track-unsubscribed'
    },
    Track: { Kind: { Audio: 'audio' } }
  }
})

import { useNativeRealtimeVoice } from './use-native-realtime-voice'

describe('useNativeRealtimeVoice', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mocks.createConnection.mockResolvedValue({
      conversation_id: 'realtime-voice-main',
      expires_in: 600,
      object: 'hermes.realtime_voice.connection',
      participant_identity: 'desktop-1',
      room: 'hermes-realtime-voice',
      token: 'room-token',
      transport: 'livekit-webrtc',
      url: 'wss://voice.example.test'
    })
    mocks.connect.mockResolvedValue(undefined)
    mocks.startAudio.mockResolvedValue(undefined)
    mocks.setMicrophoneEnabled.mockResolvedValue(undefined)
  })

  it('opens WebRTC microphone and speaker transport without submitting chat text', async () => {
    const beforeConnect = vi.fn()
    const { result } = renderHook(() => useNativeRealtimeVoice({ beforeConnect }))

    await act(async () => result.current.start())

    expect(beforeConnect).toHaveBeenCalledOnce()
    expect(mocks.createConnection).toHaveBeenCalledOnce()
    expect(mocks.connect).toHaveBeenCalledWith('wss://voice.example.test', 'room-token')
    expect(mocks.startAudio).toHaveBeenCalledOnce()
    expect(mocks.setMicrophoneEnabled).toHaveBeenCalledWith(true)
    expect(result.current.active).toBe(true)
    expect(result.current.status).toBe('listening')

    await act(async () => result.current.end())

    expect(mocks.setMicrophoneEnabled).toHaveBeenLastCalledWith(false)
    expect(mocks.disconnect).toHaveBeenCalledOnce()
    expect(result.current.active).toBe(false)
  })

  it('surfaces connection failure instead of falling back to legacy voice', async () => {
    mocks.connect.mockRejectedValueOnce(new Error('offline'))
    const { result } = renderHook(() => useNativeRealtimeVoice())

    await expect(act(async () => result.current.start())).rejects.toThrow('offline')

    expect(mocks.notifyError).toHaveBeenCalledWith(
      expect.any(Error),
      'Could not start native realtime voice'
    )
    expect(result.current.active).toBe(false)
    expect(result.current.status).toBe('idle')
  })
})

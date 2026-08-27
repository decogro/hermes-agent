import { hermesApi, profileScoped } from './client'

export interface RealtimeVoiceConnection {
  object: 'hermes.realtime_voice.connection'
  transport: 'livekit-webrtc'
  url: string
  room: string
  token: string
  participant_identity: string
  conversation_id: string
  expires_in: number
}

export function createRealtimeVoiceConnection(): Promise<RealtimeVoiceConnection> {
  return hermesApi<RealtimeVoiceConnection>({
    ...profileScoped(),
    path: '/api/realtime-voice/token',
    method: 'POST',
    body: {}
  })
}

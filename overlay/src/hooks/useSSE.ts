/**
 * Hook for connecting to the backend SSE stream.
 *
 * Handles all event types: transcript, question_detected,
 * ai_answer_start/chunk/end, status. Auto-reconnects on failure.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

interface TranscriptLine {
  source: string
  speaker: number
  text: string
}

interface SSEState {
  transcripts: TranscriptLine[]
  currentAnswer: string
  lastQuestion: string
  isAnswering: boolean
  isRecording: boolean
  isConnected: boolean
  error: string | null
  answerHistory: string[]
}

const BACKEND_URL = 'http://127.0.0.1:8765'
const MAX_TRANSCRIPTS = 50

export function useSSE() {
  const [state, setState] = useState<SSEState>({
    transcripts: [],
    currentAnswer: '',
    lastQuestion: '',
    isAnswering: false,
    isRecording: false,
    isConnected: false,
    error: null,
    answerHistory: [],
  })

  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>()
  const reconnectDelay = useRef(1000)

  const connect = useCallback(() => {
    const es = new EventSource(`${BACKEND_URL}/stream`)

    es.onopen = () => {
      setState((s) => ({ ...s, isConnected: true, error: null }))
      reconnectDelay.current = 1000 // Reset backoff
    }

    es.addEventListener('transcript', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({
        ...s,
        transcripts: [...s.transcripts.slice(-MAX_TRANSCRIPTS), data],
      }))
    })

    es.addEventListener('question_detected', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({ ...s, lastQuestion: data.text }))
    })

    es.addEventListener('ai_answer_start', () => {
      setState((s) => ({ ...s, currentAnswer: '', isAnswering: true }))
    })

    es.addEventListener('ai_answer_chunk', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({
        ...s,
        currentAnswer: s.currentAnswer + data.text,
      }))
    })

    es.addEventListener('ai_answer_end', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({
        ...s,
        isAnswering: false,
        answerHistory: [...s.answerHistory, data.full_answer],
      }))
    })

    es.addEventListener('status', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({
        ...s,
        isRecording: data.type === 'recording',
        error: data.type === 'error' ? data.message : s.error,
      }))
    })

    es.onerror = () => {
      es.close()
      setState((s) => ({ ...s, isConnected: false }))

      // Exponential backoff reconnect
      reconnectTimeout.current = setTimeout(() => {
        reconnectDelay.current = Math.min(reconnectDelay.current * 2, 10000)
        connect()
      }, reconnectDelay.current)
    }

    return es
  }, [])

  useEffect(() => {
    const es = connect()
    return () => {
      es.close()
      if (reconnectTimeout.current) clearTimeout(reconnectTimeout.current)
    }
  }, [connect])

  return state
}

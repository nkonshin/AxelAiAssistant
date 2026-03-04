/**
 * Hook for connecting to the backend SSE stream.
 *
 * Handles all event types: transcript, question_detected,
 * ai_answer_start/chunk/end, status. Auto-reconnects on failure.
 * Provides answer history with navigation.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

export interface TranscriptLine {
  source: string
  speaker: number
  text: string
}

export interface AnswerEntry {
  id: string
  question: string
  answer: string
  isComplete: boolean
}

interface SSEState {
  transcripts: TranscriptLine[]
  answers: AnswerEntry[]
  pendingQuestion: string | null
  isRecording: boolean
  isConnected: boolean
  error: string | null
  statusMessage: string | null
}

const BACKEND_URL = 'http://127.0.0.1:8765'
const MAX_TRANSCRIPTS = 50

function safeParse(raw: string): unknown | null {
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function useSSE() {
  const [state, setState] = useState<SSEState>({
    transcripts: [],
    answers: [],
    pendingQuestion: null,
    isRecording: false,
    isConnected: false,
    error: null,
    statusMessage: null,
  })

  const reconnectTimeout = useRef<ReturnType<typeof setTimeout>>()
  const reconnectDelay = useRef(1000)

  const connect = useCallback(() => {
    const es = new EventSource(`${BACKEND_URL}/stream`)

    es.onopen = () => {
      setState((s) => ({ ...s, isConnected: true, error: null }))
      reconnectDelay.current = 1000
    }

    es.addEventListener('transcript', (e) => {
      const data = safeParse(e.data) as TranscriptLine | null
      if (!data) return
      setState((s) => ({
        ...s,
        transcripts: [...s.transcripts.slice(-MAX_TRANSCRIPTS), data],
      }))
    })

    es.addEventListener('question_detected', (e) => {
      const data = safeParse(e.data) as { text: string } | null
      if (!data) return
      setState((s) => ({ ...s, pendingQuestion: data.text }))
    })

    es.addEventListener('ai_answer_start', (e) => {
      const data = safeParse(e.data) as { question?: string; id?: string } | null
      if (!data) return
      setState((s) => {
        const newEntry: AnswerEntry = {
          id: data.id || String(Date.now()),
          question: data.question || s.pendingQuestion || '',
          answer: '',
          isComplete: false,
        }
        return {
          ...s,
          answers: [...s.answers, newEntry],
          pendingQuestion: null,
        }
      })
    })

    es.addEventListener('ai_answer_chunk', (e) => {
      const data = safeParse(e.data) as { text: string } | null
      if (!data) return
      setState((s) => {
        if (s.answers.length === 0) return s
        const updated = [...s.answers]
        const last = updated[updated.length - 1]
        updated[updated.length - 1] = { ...last, answer: last.answer + data.text }
        return { ...s, answers: updated }
      })
    })

    es.addEventListener('ai_answer_end', () => {
      setState((s) => {
        if (s.answers.length === 0) return s
        const updated = [...s.answers]
        const last = updated[updated.length - 1]
        updated[updated.length - 1] = { ...last, isComplete: true }
        return { ...s, answers: updated }
      })
    })

    es.addEventListener('status', (e) => {
      const data = safeParse(e.data) as { type: string; message?: string } | null
      if (!data) return
      setState((s) => {
        const updates: Partial<SSEState> = {}
        if (data.type === 'recording') {
          updates.isRecording = true
          updates.statusMessage = null
          updates.error = null
        }
        if (data.type === 'stopped') {
          updates.isRecording = false
          updates.statusMessage = null
          updates.error = null
        }
        if (data.type === 'loading') {
          updates.statusMessage = data.message ?? null
        }
        if (data.type === 'model_ready') {
          updates.statusMessage = null
        }
        if (data.type === 'error') {
          updates.error = data.message ?? null
          updates.statusMessage = null
        }
        return { ...s, ...updates }
      })
    })

    es.onerror = () => {
      es.close()
      setState((s) => ({ ...s, isConnected: false }))

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

  const clearError = useCallback(() => {
    setState((s) => ({ ...s, error: null }))
  }, [])

  return {
    ...state,
    clearError,
  }
}

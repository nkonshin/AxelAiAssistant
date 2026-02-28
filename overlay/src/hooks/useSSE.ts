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
  question: string
  answer: string
  isComplete: boolean
}

interface SSEState {
  transcripts: TranscriptLine[]
  answers: AnswerEntry[]
  viewIndex: number
  pendingQuestion: string | null
  isRecording: boolean
  isConnected: boolean
  error: string | null
}

const BACKEND_URL = 'http://127.0.0.1:8765'
const MAX_TRANSCRIPTS = 50

export function useSSE() {
  const [state, setState] = useState<SSEState>({
    transcripts: [],
    answers: [],
    viewIndex: 0,
    pendingQuestion: null,
    isRecording: false,
    isConnected: false,
    error: null,
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
      const data = JSON.parse(e.data)
      setState((s) => ({
        ...s,
        transcripts: [...s.transcripts.slice(-MAX_TRANSCRIPTS), data],
      }))
    })

    es.addEventListener('question_detected', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => ({ ...s, pendingQuestion: data.text }))
    })

    es.addEventListener('ai_answer_start', (e) => {
      const data = JSON.parse(e.data)
      setState((s) => {
        const newEntry: AnswerEntry = {
          question: data.question || s.pendingQuestion || '',
          answer: '',
          isComplete: false,
        }
        const newAnswers = [...s.answers, newEntry]
        return {
          ...s,
          answers: newAnswers,
          viewIndex: newAnswers.length - 1,
          pendingQuestion: null,
        }
      })
    })

    es.addEventListener('ai_answer_chunk', (e) => {
      const data = JSON.parse(e.data)
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

  // Navigation
  const goNext = useCallback(() => {
    setState((s) => ({
      ...s,
      viewIndex: Math.min(s.viewIndex + 1, s.answers.length - 1),
    }))
  }, [])

  const goPrev = useCallback(() => {
    setState((s) => ({
      ...s,
      viewIndex: Math.max(s.viewIndex - 1, 0),
    }))
  }, [])

  const goToLatest = useCallback(() => {
    setState((s) => ({
      ...s,
      viewIndex: Math.max(s.answers.length - 1, 0),
    }))
  }, [])

  const currentEntry = state.answers[state.viewIndex] || null

  return {
    ...state,
    currentEntry,
    totalAnswers: state.answers.length,
    currentPage: state.answers.length > 0 ? state.viewIndex + 1 : 0,
    goNext,
    goPrev,
    goToLatest,
  }
}

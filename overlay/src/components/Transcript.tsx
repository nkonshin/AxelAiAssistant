/**
 * Live transcript panel in dialog format.
 * Shows real-time speech recognition results as a chat:
 * - INT (system audio) = interviewer
 * - YOU (mic) = user
 *
 * Always visible when there are transcripts. Auto-scrolls to latest.
 */

import { useRef, useEffect } from 'react'
import { Interactable } from './Interactable'

interface TranscriptLine {
  source: string
  speaker: number
  text: string
}

interface Props {
  transcripts: TranscriptLine[]
  isRecording: boolean
}

export function Transcript({ transcripts, isRecording }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [transcripts])

  // Show recording state even with no transcripts
  if (transcripts.length === 0) {
    if (!isRecording) return null
    return (
      <div className="transcript-panel">
        <div className="transcript-empty">
          <span className="cursor-blink" />
          <span>Слушаю...</span>
        </div>
      </div>
    )
  }

  // Group consecutive lines from the same source
  const grouped: { source: string; lines: string[] }[] = []
  for (const t of transcripts) {
    const last = grouped[grouped.length - 1]
    if (last && last.source === t.source) {
      last.lines.push(t.text)
    } else {
      grouped.push({ source: t.source, lines: [t.text] })
    }
  }

  return (
    <Interactable className="transcript-panel">
      <div ref={scrollRef} className="transcript-scroll">
        {grouped.map((group, i) => (
          <div key={i} className={`transcript-msg ${group.source === 'system' ? 'int' : 'you'}`}>
            <span className="transcript-label">
              {group.source === 'system' ? 'INT' : 'YOU'}
            </span>
            <span className="transcript-text">
              {group.lines.join(' ')}
            </span>
          </div>
        ))}
      </div>
    </Interactable>
  )
}

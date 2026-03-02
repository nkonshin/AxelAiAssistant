/**
 * Compact transcript indicator: shows only the last line from each source.
 * - INT (system audio) = interviewer → amber
 * - YOU (mic) = user → green
 *
 * Fixed height (2 lines max), text truncated with ellipsis.
 */

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

  // Find last line from each source
  let lastInt: string | null = null
  let lastYou: string | null = null
  for (let i = transcripts.length - 1; i >= 0; i--) {
    const t = transcripts[i]
    if (!lastInt && t.source === 'system') lastInt = t.text
    if (!lastYou && t.source === 'mic') lastYou = t.text
    if (lastInt && lastYou) break
  }

  if (!lastInt && !lastYou) {
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

  return (
    <Interactable className="transcript-panel">
      <div className="transcript-compact">
        {lastInt && (
          <div className="transcript-line int">
            <span className="transcript-dot int" />
            <span className="transcript-text-truncate">{lastInt}</span>
          </div>
        )}
        {lastYou && (
          <div className="transcript-line you">
            <span className="transcript-dot you" />
            <span className="transcript-text-truncate">{lastYou}</span>
          </div>
        )}
      </div>
    </Interactable>
  )
}

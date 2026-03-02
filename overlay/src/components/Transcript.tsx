/**
 * Compact transcript indicator: shows recent speech from each source.
 * - INT (system audio) = interviewer → amber dot
 * - YOU (mic) = user → green dot
 *
 * Concatenates all recent consecutive phrases from the same source.
 * Overflow is clipped from the LEFT (beginning) via direction: rtl trick,
 * so you always see the most recent words.
 * Fixed height (2 lines max).
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

/** Collect all recent consecutive lines from a source, walking backwards. */
function collectRecent(transcripts: TranscriptLine[], targetSource: string): string {
  const parts: string[] = []
  // Walk backwards, collect all consecutive lines from targetSource
  // Stop when we hit the other source (to get only the latest "block")
  let foundTarget = false
  for (let i = transcripts.length - 1; i >= 0; i--) {
    const t = transcripts[i]
    if (t.source === targetSource) {
      foundTarget = true
      parts.unshift(t.text)
    } else if (foundTarget) {
      // Hit a different source after collecting some — stop
      break
    }
    // Skip other source lines before finding target
  }
  return parts.join(' ')
}

export function Transcript({ transcripts, isRecording }: Props) {
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

  const intText = collectRecent(transcripts, 'system')
  const youText = collectRecent(transcripts, 'mic')

  if (!intText && !youText) {
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
        {intText && (
          <div className="transcript-line int">
            <span className="transcript-dot int" />
            <span className="transcript-text-clip">{intText}</span>
          </div>
        )}
        {youText && (
          <div className="transcript-line you">
            <span className="transcript-dot you" />
            <span className="transcript-text-clip">{youText}</span>
          </div>
        )}
      </div>
    </Interactable>
  )
}

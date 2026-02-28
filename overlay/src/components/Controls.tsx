/**
 * Bottom control bar: screenshot, record toggle, force answer.
 */

import { Interactable } from './Interactable'

interface Props {
  isRecording: boolean
}

const BACKEND_URL = 'http://127.0.0.1:8765'

export function Controls({ isRecording }: Props) {
  const handleScreenshot = () => {
    fetch(`${BACKEND_URL}/screenshot`, { method: 'POST' }).catch(() => {})
  }

  const handleToggleRecording = () => {
    const endpoint = isRecording ? '/stop' : '/start'
    fetch(`${BACKEND_URL}${endpoint}`, { method: 'POST' }).catch(() => {})
  }

  const handleForceAnswer = () => {
    fetch(`${BACKEND_URL}/force-answer`, { method: 'POST' }).catch(() => {})
  }

  return (
    <Interactable className="flex items-center justify-center gap-3 px-3 py-2 border-t border-white/10">
      <button
        onClick={handleScreenshot}
        className="text-xs text-white/40 hover:text-white/70 transition-colors px-2 py-1 rounded hover:bg-white/5"
        title="Screenshot (Cmd+Shift+S)"
      >
        Screenshot
      </button>

      <button
        onClick={handleToggleRecording}
        className={`text-xs px-2 py-1 rounded transition-colors ${
          isRecording
            ? 'text-red-300 hover:text-red-200 hover:bg-red-500/10'
            : 'text-green-300 hover:text-green-200 hover:bg-green-500/10'
        }`}
        title="Toggle recording (Cmd+Shift+M)"
      >
        {isRecording ? 'Stop' : 'Record'}
      </button>

      <button
        onClick={handleForceAnswer}
        className="text-xs text-white/40 hover:text-white/70 transition-colors px-2 py-1 rounded hover:bg-white/5"
        title="Force answer (Cmd+Shift+A)"
      >
        Answer
      </button>
    </Interactable>
  )
}

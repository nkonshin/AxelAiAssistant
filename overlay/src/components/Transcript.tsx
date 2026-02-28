/**
 * Collapsible transcript panel showing recent speech recognition results.
 */

import { useState, useRef, useEffect } from 'react'
import { Interactable } from './Interactable'

interface TranscriptLine {
  source: string
  speaker: number
  text: string
}

interface Props {
  transcripts: TranscriptLine[]
}

export function Transcript({ transcripts }: Props) {
  const [collapsed, setCollapsed] = useState(true)
  const scrollRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [transcripts])

  if (transcripts.length === 0) return null

  return (
    <Interactable className="border-b border-white/10">
      <button
        onClick={() => setCollapsed(!collapsed)}
        className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-white/50 hover:text-white/70"
      >
        <span className={`transition-transform ${collapsed ? '' : 'rotate-90'}`}>
          &#9654;
        </span>
        Transcript ({transcripts.length})
      </button>

      {!collapsed && (
        <div
          ref={scrollRef}
          className="max-h-32 overflow-y-auto px-3 pb-2 space-y-1"
        >
          {transcripts.slice(-20).map((t, i) => (
            <div key={i} className="text-xs">
              <span className={`font-medium ${
                t.source === 'system' ? 'text-orange-300' : 'text-green-300'
              }`}>
                {t.source === 'system' ? 'INT' : 'YOU'}:
              </span>{' '}
              <span className="text-white/80">{t.text}</span>
            </div>
          ))}
        </div>
      )}
    </Interactable>
  )
}

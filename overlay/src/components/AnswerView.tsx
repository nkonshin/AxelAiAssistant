/**
 * Main content area: displays question + AI answer with markdown rendering,
 * auto-scroll, streaming cursor, and empty state.
 */

import { useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'

interface AnswerEntry {
  question: string
  answer: string
  isComplete: boolean
}

interface Props {
  entry: AnswerEntry | null
  pendingQuestion: string | null
}

export function AnswerView({ entry, pendingQuestion }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll as answer streams in
  useEffect(() => {
    if (scrollRef.current && entry && !entry.isComplete) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [entry?.answer, entry?.isComplete])

  // Empty state
  if (!entry && !pendingQuestion) {
    return (
      <div className="empty-state">
        <svg width="48" height="48" viewBox="0 0 48 48" fill="none">
          <rect x="6" y="18" width="5" height="12" rx="2.5" fill="currentColor" />
          <rect x="14" y="10" width="5" height="28" rx="2.5" fill="currentColor" />
          <rect x="22" y="14" width="5" height="20" rx="2.5" fill="currentColor" />
          <rect x="30" y="6" width="5" height="36" rx="2.5" fill="currentColor" />
          <rect x="38" y="16" width="5" height="16" rx="2.5" fill="currentColor" />
        </svg>
        <p>
          Нажми <span className="kbd">&#8984;&#8679;M</span> чтобы начать сессию и лови подсказки
        </p>
      </div>
    )
  }

  // Pending question (waiting for AI to start)
  if (!entry && pendingQuestion) {
    return (
      <div className="flex-1 flex flex-col min-h-0">
        <div className="px-4 py-2.5" style={{ borderBottom: '1px solid var(--border)' }}>
          <p className="text-[13px] text-[var(--accent)] font-medium">{pendingQuestion}</p>
        </div>
        <div className="flex-1 flex items-center justify-center">
          <div className="flex items-center gap-2 text-[var(--text-tertiary)] text-[13px]">
            <span className="cursor-blink" />
            Генерирую ответ...
          </div>
        </div>
      </div>
    )
  }

  if (!entry) return null

  return (
    <div className="flex-1 flex flex-col min-h-0">
      {/* Question header */}
      {entry.question && (
        <div className="px-4 py-2.5 flex-shrink-0" style={{ borderBottom: '1px solid var(--border)' }}>
          <p className="text-[13px] text-[var(--accent)] font-medium leading-snug">
            {entry.question}
          </p>
        </div>
      )}

      {/* Answer body */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-3"
      >
        {entry.answer ? (
          <div className="answer-markdown">
            <ReactMarkdown
              remarkPlugins={[remarkGfm]}
              components={{
                code({ className, children, ...props }) {
                  const match = /language-(\w+)/.exec(className || '')
                  const codeString = String(children).replace(/\n$/, '')

                  if (match) {
                    return (
                      <SyntaxHighlighter
                        style={oneDark}
                        language={match[1]}
                        PreTag="div"
                        customStyle={{
                          margin: '10px 0',
                          borderRadius: '8px',
                          fontSize: '12px',
                          border: '1px solid var(--border)',
                        }}
                      >
                        {codeString}
                      </SyntaxHighlighter>
                    )
                  }

                  return (
                    <code {...props}>{children}</code>
                  )
                },
              }}
            >
              {entry.answer}
            </ReactMarkdown>

            {/* Streaming cursor */}
            {!entry.isComplete && <span className="cursor-blink" />}
          </div>
        ) : (
          <div className="flex items-center gap-2 text-[var(--text-tertiary)] text-[13px] pt-2">
            <span className="cursor-blink" />
            Генерирую ответ...
          </div>
        )}
      </div>
    </div>
  )
}

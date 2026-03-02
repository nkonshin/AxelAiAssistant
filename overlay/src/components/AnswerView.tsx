/**
 * Main content area: displays question + AI answer with markdown rendering,
 * auto-scroll, streaming cursor, and empty state.
 */

import { useRef, useEffect, useState, useCallback } from 'react'
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
  onElaborate?: (selectedText: string) => void
}

export function AnswerView({ entry, pendingQuestion, onElaborate }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; text: string } | null>(null)

  // Auto-scroll as answer streams in
  useEffect(() => {
    if (scrollRef.current && entry && !entry.isComplete) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [entry?.answer, entry?.isComplete])

  // Close context menu on click anywhere or scroll
  useEffect(() => {
    if (!contextMenu) return
    const close = () => setContextMenu(null)
    document.addEventListener('click', close)
    document.addEventListener('scroll', close, true)
    return () => {
      document.removeEventListener('click', close)
      document.removeEventListener('scroll', close, true)
    }
  }, [contextMenu])

  const handleContextMenu = useCallback((e: React.MouseEvent) => {
    const selected = window.getSelection()?.toString().trim()
    if (!selected) return
    e.preventDefault()
    setContextMenu({ x: e.clientX, y: e.clientY, text: selected })
  }, [])

  const handleElaborate = useCallback(() => {
    if (contextMenu?.text && onElaborate) {
      onElaborate(contextMenu.text)
      setContextMenu(null)
      window.getSelection()?.removeAllRanges()
    }
  }, [contextMenu, onElaborate])

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
        onContextMenu={handleContextMenu}
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

      {/* Context menu */}
      {contextMenu && (
        <div
          className="context-menu"
          style={{ left: contextMenu.x, top: contextMenu.y }}
          onClick={(e) => e.stopPropagation()}
        >
          <button className="context-menu-item" onClick={handleElaborate}>
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
              <circle cx="11" cy="11" r="8" />
              <line x1="21" y1="21" x2="16.65" y2="16.65" />
              <line x1="11" y1="8" x2="11" y2="14" />
              <line x1="8" y1="11" x2="14" y2="11" />
            </svg>
            Расскажи подробнее
          </button>
        </div>
      )}
    </div>
  )
}

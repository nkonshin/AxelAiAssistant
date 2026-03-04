/**
 * Scrollable chat-style view: renders all answers in a single feed.
 * Auto-scrolls to the bottom as new answers stream in.
 */

import { useRef, useEffect, useState, useCallback } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import type { AnswerEntry } from '../hooks/useSSE'

interface Props {
  answers: AnswerEntry[]
  pendingQuestion: string | null
  onElaborate?: (selectedText: string) => void
}

/** Parse question text into lines with source info. Strips [Интервьюер]/[Кандидат] labels. */
function parseQuestionLines(text: string): { source: 'int' | 'you'; text: string }[] {
  return text.split('\n').filter(Boolean).map((line) => {
    const intMatch = line.match(/^\[Интервьюер\]:\s*(.+)/)
    if (intMatch) return { source: 'int' as const, text: intMatch[1] }
    const youMatch = line.match(/^\[Кандидат\]:\s*(.+)/)
    if (youMatch) return { source: 'you' as const, text: youMatch[1] }
    return { source: 'int' as const, text: line }
  })
}

const mdComponents = {
  code({ className, children, ...props }: any) {
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

    return <code {...props}>{children}</code>
  },
}

export function AnswerView({ answers, pendingQuestion, onElaborate }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const bottomRef = useRef<HTMLDivElement>(null)
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; text: string } | null>(null)

  // Auto-scroll when last answer is streaming or a new answer appears
  const lastAnswer = answers[answers.length - 1]
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [lastAnswer?.answer, lastAnswer?.isComplete, answers.length, pendingQuestion])

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
  if (answers.length === 0 && !pendingQuestion) {
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

  return (
    <div
      ref={scrollRef}
      className="flex-1 overflow-y-auto min-h-0"
      onContextMenu={handleContextMenu}
    >
      {answers.map((entry) => (
        <div key={entry.id} className="chat-entry">
          {/* Question lines with colored left borders */}
          {entry.question && (
            <div className="chat-question">
              {parseQuestionLines(entry.question).map((line, j) => (
                <div key={j} className={`chat-q-line ${line.source}`}>
                  {line.text}
                </div>
              ))}
            </div>
          )}

          {/* Answer */}
          <div className="chat-answer">
            {entry.answer ? (
              <div className="answer-markdown">
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
                  {entry.answer}
                </ReactMarkdown>
                {!entry.isComplete && <span className="cursor-blink" />}
              </div>
            ) : (
              <div className="flex items-center gap-2 text-[var(--text-tertiary)] text-[13px]">
                <span className="cursor-blink" />
                Генерирую ответ...
              </div>
            )}
          </div>
        </div>
      ))}

      {/* Pending question (before AI starts) */}
      {pendingQuestion && (
        <div className="chat-entry">
          <div className="chat-question">
            {parseQuestionLines(pendingQuestion).map((line, j) => (
              <div key={j} className={`chat-q-line ${line.source}`}>
                {line.text}
              </div>
            ))}
          </div>
          <div className="chat-answer">
            <div className="flex items-center gap-2 text-[var(--text-tertiary)] text-[13px]">
              <span className="cursor-blink" />
              Генерирую ответ...
            </div>
          </div>
        </div>
      )}

      {/* Scroll anchor */}
      <div ref={bottomRef} />

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

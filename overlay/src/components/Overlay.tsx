/**
 * Main content area: displays AI answer with markdown rendering,
 * auto-scroll, and copy button.
 */

import { useRef, useEffect } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Prism as SyntaxHighlighter } from 'react-syntax-highlighter'
import { oneDark } from 'react-syntax-highlighter/dist/esm/styles/prism'
import { Interactable } from './Interactable'

interface Props {
  question: string
  answer: string
  isAnswering: boolean
}

export function Overlay({ question, answer, isAnswering }: Props) {
  const scrollRef = useRef<HTMLDivElement>(null)

  // Auto-scroll as answer streams in
  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [answer])

  const handleCopy = () => {
    if (answer) {
      window.electronAPI?.copyToClipboard(answer)
    }
  }

  if (!question && !answer) {
    return (
      <div className="flex-1 flex items-center justify-center">
        <p className="text-white/30 text-sm">
          Waiting for question...
        </p>
      </div>
    )
  }

  return (
    <Interactable className="flex-1 flex flex-col min-h-0">
      {/* Question */}
      {question && (
        <div className="px-3 py-2 border-b border-white/10">
          <p className="text-xs text-orange-300/80 truncate">{question}</p>
        </div>
      )}

      {/* Answer with markdown */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-3 py-2 text-sm text-white/90 leading-relaxed"
      >
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
                      margin: '8px 0',
                      borderRadius: '6px',
                      fontSize: '12px',
                    }}
                  >
                    {codeString}
                  </SyntaxHighlighter>
                )
              }

              return (
                <code
                  className="bg-white/10 rounded px-1 py-0.5 text-xs font-mono"
                  {...props}
                >
                  {children}
                </code>
              )
            },
            p({ children }) {
              return <p className="mb-2">{children}</p>
            },
            ul({ children }) {
              return <ul className="list-disc list-inside mb-2 space-y-1">{children}</ul>
            },
            ol({ children }) {
              return <ol className="list-decimal list-inside mb-2 space-y-1">{children}</ol>
            },
          }}
        >
          {answer}
        </ReactMarkdown>

        {isAnswering && (
          <span className="inline-block w-2 h-4 bg-blue-400 animate-pulse ml-1" />
        )}
      </div>

      {/* Copy button */}
      {answer && !isAnswering && (
        <div className="px-3 py-1.5 border-t border-white/10 flex justify-end">
          <button
            onClick={handleCopy}
            className="text-xs text-white/40 hover:text-white/70 transition-colors"
          >
            Copy
          </button>
        </div>
      )}
    </Interactable>
  )
}

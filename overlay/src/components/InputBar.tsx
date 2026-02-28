/**
 * Manual question input field with submit button.
 */

import { useState, useRef, KeyboardEvent } from 'react'

interface Props {
  onSubmit: (question: string) => void
  disabled?: boolean
}

export function InputBar({ onSubmit, disabled }: Props) {
  const [text, setText] = useState('')
  const inputRef = useRef<HTMLInputElement>(null)

  const handleSubmit = () => {
    const q = text.trim()
    if (!q || disabled) return
    onSubmit(q)
    setText('')
  }

  const handleKeyDown = (e: KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSubmit()
    }
  }

  return (
    <div className="flex items-center gap-2 px-4 py-2.5" style={{ borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)' }}>
      <input
        ref={inputRef}
        type="text"
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={handleKeyDown}
        placeholder="Введите запрос вручную..."
        disabled={disabled}
        className="flex-1 bg-transparent text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-tertiary)] outline-none"
      />
      <button
        onClick={handleSubmit}
        disabled={!text.trim() || disabled}
        className="text-[12px] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:text-[var(--text-tertiary)] disabled:cursor-default cursor-pointer transition-colors whitespace-nowrap"
      >
        Получить ответ
      </button>
    </div>
  )
}

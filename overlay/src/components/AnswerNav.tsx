/**
 * Bottom navigation bar for browsing answer history.
 * Shows prev/next arrows and page counter.
 */

interface Props {
  current: number
  total: number
  onPrev: () => void
  onNext: () => void
  onCopy: () => void
}

export function AnswerNav({ current, total, onPrev, onNext, onCopy }: Props) {
  if (total === 0) return null

  return (
    <div
      className="flex items-center justify-between px-4 py-2.5 flex-shrink-0"
      style={{ borderTop: '1px solid var(--border)' }}
    >
      {/* Prev */}
      <button
        onClick={onPrev}
        disabled={current <= 1}
        className="flex items-center gap-1.5 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:text-[var(--text-tertiary)] disabled:cursor-default cursor-pointer transition-colors"
      >
        <span className="kbd">&#8984;</span>
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="15 18 9 12 15 6" />
        </svg>
      </button>

      {/* Counter + Copy */}
      <div className="flex items-center gap-3">
        <button
          onClick={onCopy}
          className="text-[11px] text-[var(--text-tertiary)] hover:text-[var(--text-secondary)] transition-colors cursor-pointer"
          title="Скопировать ответ (&#8984;&#8679;C)"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <rect x="9" y="9" width="13" height="13" rx="2" />
            <path d="M5 15H4a2 2 0 01-2-2V4a2 2 0 012-2h9a2 2 0 012 2v1" />
          </svg>
        </button>
        <span className="text-[12px] text-[var(--text-secondary)] font-medium tabular-nums min-w-[32px] text-center">
          {current}/{total}
        </span>
      </div>

      {/* Next */}
      <button
        onClick={onNext}
        disabled={current >= total}
        className="flex items-center gap-1.5 text-[12px] text-[var(--text-secondary)] hover:text-[var(--text-primary)] disabled:text-[var(--text-tertiary)] disabled:cursor-default cursor-pointer transition-colors"
      >
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
          <polyline points="9 18 15 12 9 6" />
        </svg>
        <span className="kbd">&#8984;</span>
      </button>
    </div>
  )
}

/**
 * Top bar: drag zone, logo, recording indicator, action buttons, menu.
 */

interface Props {
  isRecording: boolean
  isConnected: boolean
  onMenuClick: () => void
}

export function TopBar({ isRecording, isConnected, onMenuClick }: Props) {
  const handleForceAnswer = () => {
    fetch('http://127.0.0.1:8765/force-answer', { method: 'POST' }).catch(() => {})
  }

  const handleScreenshot = () => {
    fetch('http://127.0.0.1:8765/screenshot', { method: 'POST' }).catch(() => {})
  }

  return (
    <div className="drag-region flex items-center gap-3 px-4 py-3">
      {/* Logo + status */}
      <div className="flex items-center gap-2.5 no-drag">
        {/* Waveform icon */}
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
          <rect x="2" y="9" width="3" height="6" rx="1.5" fill={isConnected ? '#0a84ff' : '#48484a'} opacity={isConnected ? 1 : 0.5} />
          <rect x="7" y="5" width="3" height="14" rx="1.5" fill={isConnected ? '#0a84ff' : '#48484a'} opacity={isConnected ? 0.8 : 0.5} />
          <rect x="12" y="7" width="3" height="10" rx="1.5" fill={isConnected ? '#0a84ff' : '#48484a'} opacity={isConnected ? 0.9 : 0.5} />
          <rect x="17" y="3" width="3" height="18" rx="1.5" fill={isConnected ? '#0a84ff' : '#48484a'} opacity={isConnected ? 0.7 : 0.5} />
        </svg>

        {/* Recording dots */}
        <div className="flex items-center gap-[3px]">
          {Array.from({ length: 6 }).map((_, i) => (
            <span
              key={i}
              className={`rec-dot ${isRecording ? 'active' : ''}`}
              style={{ animationDelay: `${i * 0.12}s` }}
            />
          ))}
        </div>
      </div>

      {/* Spacer */}
      <div className="flex-1" />

      {/* Action buttons */}
      <div className="flex items-center gap-2 no-drag">
        <button className="action-btn" onClick={handleForceAnswer}>
          Спросить
          <span className="shortcut">&#8984;&#8679;A</span>
        </button>

        <button className="action-btn" onClick={handleScreenshot}>
          Скриншот
          <span className="shortcut">&#8984;&#8679;S</span>
        </button>
      </div>

      {/* Menu button */}
      <button
        className="no-drag w-8 h-8 rounded-lg flex items-center justify-center hover:bg-[rgba(255,255,255,0.08)] transition-colors cursor-pointer"
        onClick={onMenuClick}
      >
        <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
          <line x1="4" y1="6" x2="20" y2="6" />
          <line x1="4" y1="12" x2="20" y2="12" />
          <line x1="4" y1="18" x2="20" y2="18" />
        </svg>
      </button>
    </div>
  )
}

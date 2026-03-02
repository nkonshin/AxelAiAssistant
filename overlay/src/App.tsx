import { useState, useCallback, useEffect } from 'react'
import { useSSE } from './hooks/useSSE'
import { useHotkeys } from './hooks/useHotkeys'
import { TopBar } from './components/TopBar'
import { InputBar } from './components/InputBar'
import { Transcript } from './components/Transcript'
import { AnswerView } from './components/AnswerView'
import { SettingsPanel } from './components/SettingsPanel'

function App() {
  const {
    answers,
    pendingQuestion,
    isRecording,
    isConnected,
    transcripts,
    error,
    statusMessage,
    clearError,
  } = useSSE()

  // UI state
  // Two-phase mount: settingsMounted controls DOM presence,
  // settingsOpen controls the CSS open/close animation.
  // This ensures the drag-region inside SettingsPanel is completely
  // removed from the DOM when closed, avoiding Chromium's compositor
  // caching bug where -webkit-app-region: drag persists after class removal.
  const [settingsMounted, setSettingsMounted] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [opacity, setOpacity] = useState(0.85)
  const [clickThrough, setClickThrough] = useState(false)
  const [autoAnswer, setAutoAnswer] = useState(true)

  const handleOpenSettings = useCallback(() => {
    setSettingsMounted(true)
    // Next frame: trigger CSS transition after DOM is ready
    requestAnimationFrame(() => setSettingsOpen(true))
  }, [])

  const handleCloseSettings = useCallback(() => {
    setSettingsOpen(false)
    // Unmount after CSS transition completes (200ms + buffer)
    setTimeout(() => setSettingsMounted(false), 250)
  }, [])

  // Copy last answer to clipboard
  const handleCopy = useCallback(() => {
    const last = [...answers].reverse().find((a) => a.isComplete)
    if (last?.answer) {
      window.electronAPI?.copyToClipboard(last.answer)
    }
  }, [answers])

  // Submit manual question
  const handleManualQuestion = useCallback(async (question: string) => {
    try {
      await fetch('http://127.0.0.1:8765/ask', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question }),
      })
    } catch {
      // ignore
    }
  }, [])

  // Elaborate on selected text from AI answer
  const handleElaborate = useCallback((selectedText: string) => {
    const prompt = `Расскажи подробнее об этом из предыдущего ответа: «${selectedText}»`
    handleManualQuestion(prompt)
  }, [handleManualQuestion])

  // Opacity change -> IPC
  const handleOpacityChange = useCallback((value: number) => {
    setOpacity(value)
    window.electronAPI?.setOpacity(value)
  }, [])

  // Click-through toggle
  const handleClickThroughChange = useCallback((value: boolean) => {
    setClickThrough(value)
    if (!settingsOpen) {
      window.electronAPI?.setClickThrough(value)
    }
  }, [settingsOpen])

  // When settings open/close, manage click-through override
  useEffect(() => {
    if (settingsOpen) {
      window.electronAPI?.setClickThrough(false)
    } else if (clickThrough) {
      window.electronAPI?.setClickThrough(true)
    }
  }, [settingsOpen, clickThrough])

  // Hotkey handlers
  useHotkeys({
    'copy-last-answer': handleCopy,
  })

  return (
    <div className="app-shell">
      <TopBar
        isRecording={isRecording}
        isConnected={isConnected}
        onMenuClick={handleOpenSettings}
      />

      {/* Status/loading toast */}
      {statusMessage && (
        <div className="status-toast">
          <span className="status-toast-text">{statusMessage}</span>
        </div>
      )}

      {/* Error toast */}
      {error && (
        <div className="error-toast">
          <span className="error-toast-text">{error}</span>
          <button className="error-toast-close" onClick={clearError}>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>
      )}

      <InputBar
        onSubmit={handleManualQuestion}
        disabled={!isConnected}
      />

      <Transcript
        transcripts={transcripts}
        isRecording={isRecording}
      />

      <AnswerView
        answers={answers}
        pendingQuestion={pendingQuestion}
        onElaborate={handleElaborate}
      />

      {settingsMounted && (
        <SettingsPanel
          isOpen={settingsOpen}
          onClose={handleCloseSettings}
          opacity={opacity}
          onOpacityChange={handleOpacityChange}
          clickThrough={clickThrough}
          onClickThroughChange={handleClickThroughChange}
          autoAnswer={autoAnswer}
          onAutoAnswerChange={setAutoAnswer}
        />
      )}
    </div>
  )
}

export default App

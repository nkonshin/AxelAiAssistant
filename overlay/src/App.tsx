import { useState, useCallback, useEffect } from 'react'
import { useSSE } from './hooks/useSSE'
import { useHotkeys } from './hooks/useHotkeys'
import { TopBar } from './components/TopBar'
import { InputBar } from './components/InputBar'
import { AnswerView } from './components/AnswerView'
import { AnswerNav } from './components/AnswerNav'
import { SettingsPanel } from './components/SettingsPanel'

function App() {
  const {
    currentEntry,
    pendingQuestion,
    totalAnswers,
    currentPage,
    isRecording,
    isConnected,
    goNext,
    goPrev,
  } = useSSE()

  // UI state
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [opacity, setOpacity] = useState(0.85)
  const [clickThrough, setClickThrough] = useState(false)
  const [autoAnswer, setAutoAnswer] = useState(true)

  // Copy current answer to clipboard
  const handleCopy = useCallback(() => {
    const text = currentEntry?.answer
    if (text) {
      window.electronAPI?.copyToClipboard(text)
    }
  }, [currentEntry])

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
    'prev-answer': goPrev,
    'next-answer': goNext,
  })

  return (
    <div className="app-shell">
      <TopBar
        isRecording={isRecording}
        isConnected={isConnected}
        onMenuClick={() => setSettingsOpen(true)}
      />

      <InputBar
        onSubmit={handleManualQuestion}
        disabled={!isConnected}
      />

      <AnswerView
        entry={currentEntry}
        pendingQuestion={pendingQuestion}
      />

      <AnswerNav
        current={currentPage}
        total={totalAnswers}
        onPrev={goPrev}
        onNext={goNext}
        onCopy={handleCopy}
      />

      <SettingsPanel
        isOpen={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        opacity={opacity}
        onOpacityChange={handleOpacityChange}
        clickThrough={clickThrough}
        onClickThroughChange={handleClickThroughChange}
        autoAnswer={autoAnswer}
        onAutoAnswerChange={setAutoAnswer}
        isRecording={isRecording}
      />
    </div>
  )
}

export default App

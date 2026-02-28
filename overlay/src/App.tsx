import { useCallback } from 'react'
import { useSSE } from './hooks/useSSE'
import { useHotkeys } from './hooks/useHotkeys'
import { StatusBar } from './components/StatusBar'
import { Transcript } from './components/Transcript'
import { Overlay } from './components/Overlay'
import { Controls } from './components/Controls'

function App() {
  const {
    transcripts,
    currentAnswer,
    lastQuestion,
    isAnswering,
    isRecording,
    isConnected,
    answerHistory,
  } = useSSE()

  const handleCopyLastAnswer = useCallback(() => {
    const lastAnswer = currentAnswer || answerHistory[answerHistory.length - 1] || ''
    if (lastAnswer) {
      window.electronAPI?.copyToClipboard(lastAnswer)
    }
  }, [currentAnswer, answerHistory])

  useHotkeys(handleCopyLastAnswer)

  return (
    <div className="overlay-container w-full h-screen flex flex-col">
      <StatusBar
        isRecording={isRecording}
        isConnected={isConnected}
        isAnswering={isAnswering}
      />
      <Transcript transcripts={transcripts} />
      <Overlay
        question={lastQuestion}
        answer={currentAnswer}
        isAnswering={isAnswering}
      />
      <Controls isRecording={isRecording} />
    </div>
  )
}

export default App

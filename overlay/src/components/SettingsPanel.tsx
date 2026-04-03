/**
 * Full-window settings overlay with LLM provider/model selector,
 * profile/job editor, transparency slider, feature toggles,
 * hotkeys reference, and quit button.
 */

import { useState, useEffect, useCallback, useRef } from 'react'

export interface LLMSettings {
  provider: string
  model: string
}

interface LLMOptions {
  provider: string
  model: string
  available: {
    openai: string[]
    claude: string[]
  }
  claude_labels: Record<string, string>
}

interface Props {
  isOpen: boolean
  onClose: () => void
  opacity: number
  onOpacityChange: (value: number) => void
  clickThrough: boolean
  onClickThroughChange: (value: boolean) => void
  autoAnswer: boolean
  onAutoAnswerChange: (value: boolean) => void
  activeLab: { index: number; name: string } | null
}

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return (
    <div className={`toggle-track ${value ? 'on' : ''}`} onClick={() => onChange(!value)}>
      <div className="toggle-thumb" />
    </div>
  )
}

const HOTKEYS = [
  { keys: '&#8984;&#8679;\\', desc: 'Показать / скрыть' },
  { keys: '&#8984;&#8679;M', desc: 'Начать / стоп запись' },
  { keys: '&#8984;&#8679;A', desc: 'Принудительный ответ' },
  { keys: '&#8984;&#8679;S', desc: 'Скриншот + анализ' },
  { keys: '&#8984;&#8679;C', desc: 'Скопировать ответ' },
  { keys: '&#8984;&#8679;&#8593;&#8595;', desc: 'Прозрачность +/-' },
  { keys: '&#8984;&#8592;&#8594;', desc: 'Предыдущий / следующий ответ' },
]

const BACKEND_URL = 'http://127.0.0.1:8765'

function getModelLabel(model: string, claudeLabels: Record<string, string>): string {
  if (claudeLabels[model]) return claudeLabels[model]
  return model
}

/** Chevron icon for collapsible sections */
function ChevronIcon({ expanded }: { expanded: boolean }) {
  return (
    <svg
      width="14"
      height="14"
      viewBox="0 0 24 24"
      fill="none"
      stroke="var(--text-tertiary)"
      strokeWidth="2"
      strokeLinecap="round"
      style={{
        transform: expanded ? 'rotate(180deg)' : 'rotate(0deg)',
        transition: 'transform 0.2s ease',
      }}
    >
      <polyline points="6 9 12 15 18 9" />
    </svg>
  )
}

/** Editable markdown section with load/save, file upload, and reset */
function EditableSection({
  title,
  subtitle,
  endpoint,
  uploadEndpoint,
  resetEndpoint,
  processEndpoint,
  placeholder,
  isOpen,
}: {
  title: string
  subtitle: string
  endpoint: string
  uploadEndpoint: string
  resetEndpoint: string
  processEndpoint?: string
  placeholder: string
  isOpen: boolean
}) {
  const [expanded, setExpanded] = useState(false)
  const [content, setContent] = useState('')
  const [loaded, setLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [resetting, setResetting] = useState(false)
  const [saveStatus, setSaveStatus] = useState<'idle' | 'saved' | 'error' | 'uploaded' | 'reset'>('idle')
  const fileInputRef = useRef<HTMLInputElement>(null)

  const loadContent = useCallback(() => {
    if (loaded) return
    fetch(`${BACKEND_URL}/settings/${endpoint}`)
      .then((r) => r.json())
      .then((data) => {
        setContent(data.content || '')
        setLoaded(true)
      })
      .catch(() => {})
  }, [endpoint, loaded])

  // Reset loaded state when panel closes
  useEffect(() => {
    if (!isOpen) {
      setLoaded(false)
      setExpanded(false)
      setSaveStatus('idle')
    }
  }, [isOpen])

  // Load content when section expands
  useEffect(() => {
    if (expanded && isOpen) loadContent()
  }, [expanded, isOpen, loadContent])

  const handleSave = async () => {
    setSaving(true)
    setSaveStatus('idle')
    try {
      if (processEndpoint && content.trim()) {
        // Process through LLM first, then save
        const res = await fetch(`${BACKEND_URL}/settings/${processEndpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        })
        const data = await res.json()
        if (data.status === 'ok' && data.content) {
          setContent(data.content)
          setSaveStatus('saved')
          setTimeout(() => setSaveStatus('idle'), 2000)
        } else {
          setSaveStatus('error')
        }
      } else {
        // Save as-is
        const res = await fetch(`${BACKEND_URL}/settings/${endpoint}`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ content }),
        })
        if (res.ok) {
          setSaveStatus('saved')
          setTimeout(() => setSaveStatus('idle'), 2000)
        } else {
          setSaveStatus('error')
        }
      }
    } catch {
      setSaveStatus('error')
    }
    setSaving(false)
  }

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return
    setUploading(true)
    setSaveStatus('idle')
    try {
      const formData = new FormData()
      formData.append('file', file)
      const res = await fetch(`${BACKEND_URL}/settings/${uploadEndpoint}`, {
        method: 'POST',
        body: formData,
      })
      const data = await res.json()
      if (data.status === 'ok' && data.content) {
        setContent(data.content)
        setSaveStatus('uploaded')
        setTimeout(() => setSaveStatus('idle'), 3000)
      } else {
        setSaveStatus('error')
      }
    } catch {
      setSaveStatus('error')
    }
    setUploading(false)
    // Reset input so the same file can be re-uploaded
    if (fileInputRef.current) fileInputRef.current.value = ''
  }

  const handleReset = async () => {
    if (!confirm('Сбросить на шаблон? Текущее содержимое будет потеряно.')) return
    setResetting(true)
    setSaveStatus('idle')
    try {
      const res = await fetch(`${BACKEND_URL}/settings/${resetEndpoint}`, { method: 'POST' })
      const data = await res.json()
      if (data.status === 'ok') {
        setContent(data.content || '')
        setSaveStatus('reset')
        setTimeout(() => setSaveStatus('idle'), 2000)
      } else {
        setSaveStatus('error')
      }
    } catch {
      setSaveStatus('error')
    }
    setResetting(false)
  }

  return (
    <div style={{ borderTop: '1px solid var(--border)' }}>
      <button
        className="w-full flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-[rgba(255,255,255,0.03)] transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        <div className="text-left">
          <span className="text-[13px] font-medium text-[var(--text-primary)]">{title}</span>
          <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5">{subtitle}</div>
        </div>
        <ChevronIcon expanded={expanded} />
      </button>

      {expanded && (
        <div className="px-4 pb-3">
          <textarea
            className="settings-textarea"
            value={content}
            onChange={(e) => {
              setContent(e.target.value)
              setSaveStatus('idle')
            }}
            placeholder={placeholder}
            rows={8}
          />
          <div className="flex items-center gap-2 mt-2">
            <button
              className="save-btn"
              onClick={handleSave}
              disabled={saving || uploading}
            >
              {saving ? (processEndpoint ? 'AI обрабатывает...' : 'Сохранение...') : 'Сохранить'}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,.doc,.docx"
              onChange={handleUpload}
              className="hidden"
            />
            <button
              className="upload-btn"
              onClick={() => fileInputRef.current?.click()}
              disabled={uploading}
            >
              <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4" />
                <polyline points="17 8 12 3 7 8" />
                <line x1="12" y1="3" x2="12" y2="15" />
              </svg>
              {uploading ? 'AI обрабатывает...' : 'Загрузить файл'}
            </button>
            {saveStatus === 'saved' && (
              <span className="text-[11px] text-[var(--accent-green)]">Сохранено</span>
            )}
            {saveStatus === 'uploaded' && (
              <span className="text-[11px] text-[var(--accent-green)]">Загружено и обработано</span>
            )}
            {saveStatus === 'reset' && (
              <span className="text-[11px] text-[var(--text-secondary)]">Шаблон восстановлен</span>
            )}
            {saveStatus === 'error' && (
              <span className="text-[11px] text-[var(--accent-red)]">Ошибка</span>
            )}
            <button
              className="reset-btn ml-auto"
              onClick={handleReset}
              disabled={resetting || uploading || saving}
              title="Сбросить на шаблон"
            >
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                <polyline points="1 4 1 10 7 10" />
                <path d="M3.51 15a9 9 0 105.17-12.36L1 10" />
              </svg>
              {resetting ? 'Сброс...' : 'Сбросить'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export function SettingsPanel({
  isOpen,
  onClose,
  opacity,
  onOpacityChange,
  clickThrough,
  onClickThroughChange,
  autoAnswer,
  onAutoAnswerChange,
  activeLab,
}: Props) {
  const [hotkeysExpanded, setHotkeysExpanded] = useState(false)
  const [llmOptions, setLlmOptions] = useState<LLMOptions | null>(null)
  const [selectedProvider, setSelectedProvider] = useState('openai')
  const [selectedModel, setSelectedModel] = useState('gpt-4o-mini')
  const [transProvider, setTransProvider] = useState('deepgram')
  const [transModel, setTransModel] = useState('base')
  const [transModels, setTransModels] = useState<string[]>([])
  const [modelStatus, setModelStatus] = useState('n/a')

  const [mode, setMode] = useState<'interview' | 'study'>('study')
  const [studyFolder, setStudyFolder] = useState('')
  const [labs, setLabs] = useState<{ name: string; index: number }[]>([])
  const [activeLabIndex, setActiveLabIndex] = useState(-1)
  const [audioTesting, setAudioTesting] = useState(false)
  const [micLevel, setMicLevel] = useState(0)
  const [systemLevel, setSystemLevel] = useState(0)
  const [systemAvailable, setSystemAvailable] = useState(true)

  // Load LLM + transcription settings when panel opens
  useEffect(() => {
    if (!isOpen) return
    fetch(`${BACKEND_URL}/settings/llm`)
      .then((r) => r.json())
      .then((data: LLMOptions) => {
        setLlmOptions(data)
        setSelectedProvider(data.provider)
        setSelectedModel(data.model)
      })
      .catch(() => {})
    fetch(`${BACKEND_URL}/settings/transcription`)
      .then((r) => r.json())
      .then((data) => {
        setTransProvider(data.provider)
        setTransModel(data.model)
        setTransModels(data.available_models || [])
        setModelStatus(data.model_status || 'n/a')
      })
      .catch(() => {})
    fetch(`${BACKEND_URL}/settings/mode`)
      .then((r) => r.json())
      .then((data) => setMode(data.mode))
      .catch(() => {})
    fetch(`${BACKEND_URL}/settings/study/labs`)
      .then((r) => r.json())
      .then((data) => {
        setStudyFolder(data.folder || '')
        setLabs(data.labs || [])
        setActiveLabIndex(data.active_index ?? -1)
      })
      .catch(() => {})
  }, [isOpen])

  // Poll model status while loading
  useEffect(() => {
    if (!isOpen || transProvider !== 'whisper' || modelStatus !== 'loading') return
    const interval = setInterval(() => {
      fetch(`${BACKEND_URL}/settings/transcription`)
        .then((r) => r.json())
        .then((data) => setModelStatus(data.model_status || 'n/a'))
        .catch(() => {})
    }, 2000)
    return () => clearInterval(interval)
  }, [isOpen, transProvider, modelStatus])

  const handleProviderChange = async (provider: string) => {
    if (!llmOptions) return
    const models = provider === 'claude' ? llmOptions.available.claude : llmOptions.available.openai
    const model = models[0]
    setSelectedProvider(provider)
    setSelectedModel(model)
    try {
      await fetch(`${BACKEND_URL}/settings/llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, model }),
      })
    } catch {}
  }

  const handleModelChange = async (model: string) => {
    setSelectedModel(model)
    try {
      await fetch(`${BACKEND_URL}/settings/llm`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: selectedProvider, model }),
      })
    } catch {}
  }

  const handleTransProviderChange = async (provider: string) => {
    setTransProvider(provider)
    const model = provider === 'whisper' ? transModel : 'base'
    if (provider === 'whisper') setModelStatus('loading')
    try {
      const res = await fetch(`${BACKEND_URL}/settings/transcription`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider, model }),
      })
      if (provider === 'whisper') {
        const status = await fetch(`${BACKEND_URL}/settings/transcription`).then(r => r.json())
        setModelStatus(status.model_status || 'loading')
      }
    } catch {}
  }

  const handleTransModelChange = async (model: string) => {
    setTransModel(model)
    setModelStatus('loading')
    try {
      await fetch(`${BACKEND_URL}/settings/transcription`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ provider: transProvider, model }),
      })
      const status = await fetch(`${BACKEND_URL}/settings/transcription`).then(r => r.json())
      setModelStatus(status.model_status || 'loading')
    } catch {}
  }

  const handleModeChange = async (newMode: 'interview' | 'study') => {
    setMode(newMode)
    try {
      await fetch(`${BACKEND_URL}/settings/mode`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ mode: newMode }),
      })
    } catch {}
  }

  const handleSelectFolder = async () => {
    const folder = prompt('Путь к папке предмета:', studyFolder || '/Users/user/Documents/PSU/3.2/Распознование образов')
    if (!folder) return
    try {
      const res = await fetch(`${BACKEND_URL}/settings/study/folder`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ folder }),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setStudyFolder(data.folder)
        setLabs(data.labs || [])
        setActiveLabIndex(data.active_index ?? -1)
      }
    } catch {}
  }

  const handleLabSwitch = async (index: number) => {
    try {
      const res = await fetch(`${BACKEND_URL}/settings/study/active-lab`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ index }),
      })
      const data = await res.json()
      if (data.status === 'ok') {
        setActiveLabIndex(index)
      }
    } catch {}
  }

  useEffect(() => {
    if (!audioTesting) return
    const handleLevel = (e: Event) => {
      const { mic, system } = (e as CustomEvent).detail
      setMicLevel(mic)
      if (system === -1) {
        setSystemAvailable(false)
        setSystemLevel(0)
      } else {
        setSystemAvailable(true)
        setSystemLevel(system)
      }
    }
    const handleDone = () => setAudioTesting(false)
    window.addEventListener('audio-level', handleLevel)
    window.addEventListener('audio-test-done', handleDone)
    return () => {
      window.removeEventListener('audio-level', handleLevel)
      window.removeEventListener('audio-test-done', handleDone)
    }
  }, [audioTesting])

  const handleStartAudioTest = async () => {
    setAudioTesting(true)
    setMicLevel(0)
    setSystemLevel(0)
    setSystemAvailable(true)
    try {
      await fetch(`${BACKEND_URL}/audio-test/start`, { method: 'POST' })
    } catch {
      setAudioTesting(false)
    }
  }

  const handleStopAudioTest = async () => {
    try {
      await fetch(`${BACKEND_URL}/audio-test/stop`, { method: 'POST' })
    } catch {}
    setAudioTesting(false)
  }

  useEffect(() => {
    if (activeLab) {
      setActiveLabIndex(activeLab.index)
    }
  }, [activeLab])

  const handleQuit = () => {
    window.electronAPI?.quitApp()
  }

  const currentModels = llmOptions
    ? selectedProvider === 'claude'
      ? llmOptions.available.claude
      : llmOptions.available.openai
    : []

  return (
    <div className={`settings-overlay ${isOpen ? 'open' : ''}`}>
      <div className="settings-body">
        {/* Header */}
        <div className="drag-region flex items-center justify-between px-4 py-3" style={{ borderBottom: '1px solid var(--border)' }}>
          <div className="flex items-center gap-2">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="var(--text-secondary)" strokeWidth="2" strokeLinecap="round">
              <circle cx="12" cy="12" r="3" />
              <path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 010 2.83 2 2 0 01-2.83 0l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-2 2 2 2 0 01-2-2v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83 0 2 2 0 010-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 01-2-2 2 2 0 012-2h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 010-2.83 2 2 0 012.83 0l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 012-2 2 2 0 012 2v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 0 2 2 0 010 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 012 2 2 2 0 01-2 2h-.09a1.65 1.65 0 00-1.51 1z" />
            </svg>
            <span className="text-[14px] font-semibold text-[var(--text-primary)]">Настройки</span>
          </div>
          <button
            className="no-drag w-7 h-7 rounded-md flex items-center justify-center hover:bg-[rgba(255,255,255,0.08)] transition-colors cursor-pointer"
            onClick={onClose}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
          </button>
        </div>

        {/* Mode Toggle */}
        <div className="px-4 pt-4 pb-2">
          <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2.5">Режим</div>
          <div className="flex gap-2">
            <button
              className={`setting-chip ${mode === 'interview' ? 'active' : ''}`}
              onClick={() => handleModeChange('interview')}
            >
              Собеседование
            </button>
            <button
              className={`setting-chip ${mode === 'study' ? 'active' : ''}`}
              onClick={() => handleModeChange('study')}
            >
              Учёба
            </button>
          </div>
        </div>

        {mode === 'study' && (
          <div className="px-4 pb-3">
            <div style={{ height: 1, background: 'var(--border)', margin: '4px -16px 12px', width: 'calc(100% + 32px)' }} />
            <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2">Предмет</div>
            <div className="flex items-center gap-2 mb-3">
              <div className="flex-1 text-[11px] text-[var(--text-secondary)] truncate">
                {studyFolder || 'Папка не выбрана'}
              </div>
              <button className="setting-chip" onClick={handleSelectFolder}>
                Выбрать папку
              </button>
            </div>

            {labs.length > 0 && (
              <>
                <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2">
                  Лабораторные ({labs.length})
                </div>
                <div className="space-y-1">
                  {labs.map((lab) => (
                    <button
                      key={lab.index}
                      className={`w-full text-left px-3 py-2 rounded-lg text-[12px] transition-colors cursor-pointer ${
                        activeLabIndex === lab.index
                          ? 'bg-[rgba(110,123,242,0.15)] text-[var(--accent)]'
                          : 'text-[var(--text-secondary)] hover:bg-[rgba(255,255,255,0.04)]'
                      }`}
                      onClick={() => handleLabSwitch(lab.index)}
                    >
                      <span className="font-medium text-[var(--text-tertiary)] mr-2">
                        {lab.index + 1}.
                      </span>
                      {lab.name}
                    </button>
                  ))}
                </div>
                <div className="text-[10px] text-[var(--text-tertiary)] mt-2">
                  Переключение: Cmd+Shift+1..{Math.min(labs.length, 9)}
                </div>
              </>
            )}
          </div>
        )}

        {/* Settings content */}
        <div className="flex-1 overflow-y-auto">
          <div className="px-4 py-4 space-y-5">

            {/* LLM Provider */}
            <div>
              <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2.5">AI-провайдер</div>
              <div className="flex gap-2">
                <button
                  className={`setting-chip ${selectedProvider === 'openai' ? 'active' : ''}`}
                  onClick={() => handleProviderChange('openai')}
                >
                  OpenAI
                </button>
                <button
                  className={`setting-chip ${selectedProvider === 'claude' ? 'active' : ''}`}
                  onClick={() => handleProviderChange('claude')}
                >
                  Claude (Max)
                </button>
              </div>
              {selectedProvider === 'claude' && (
                <div className="text-[10px] text-[var(--text-tertiary)] mt-1.5">
                  Через CLIProxyAPI на localhost:8317
                </div>
              )}
            </div>

            {/* Model selector */}
            <div>
              <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2.5">Модель</div>
              <div className="flex flex-wrap gap-2">
                {currentModels.map((m) => (
                  <button
                    key={m}
                    className={`setting-chip ${selectedModel === m ? 'active' : ''}`}
                    onClick={() => handleModelChange(m)}
                  >
                    {getModelLabel(m, llmOptions?.claude_labels || {})}
                  </button>
                ))}
              </div>
            </div>

            {/* Divider */}
            <div style={{ height: 1, background: 'var(--border)', margin: '4px -16px', width: 'calc(100% + 32px)' }} />

            {/* Transcription Provider */}
            <div>
              <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2.5">Транскрибация</div>
              <div className="flex gap-2">
                <button
                  className={`setting-chip ${transProvider === 'deepgram' ? 'active' : ''}`}
                  onClick={() => handleTransProviderChange('deepgram')}
                >
                  Deepgram
                </button>
                <button
                  className={`setting-chip ${transProvider === 'whisper' ? 'active' : ''}`}
                  onClick={() => handleTransProviderChange('whisper')}
                >
                  Whisper (local)
                </button>
              </div>
              {transProvider === 'deepgram' && (
                <div className="text-[10px] text-[var(--text-tertiary)] mt-1.5">
                  Облако, Nova-3, низкая задержка
                </div>
              )}
            </div>

            {/* Whisper model selector */}
            {transProvider === 'whisper' && transModels.length > 0 && (
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)] mb-2.5">Whisper модель</div>
                <div className="flex flex-wrap gap-2">
                  {transModels.map((m) => (
                    <button
                      key={m}
                      className={`setting-chip ${transModel === m ? 'active' : ''}`}
                      onClick={() => handleTransModelChange(m)}
                    >
                      {m}
                    </button>
                  ))}
                </div>
                <div className="text-[10px] mt-1.5" style={{
                  color: modelStatus === 'ready' ? 'var(--accent-green)'
                    : modelStatus === 'available' ? 'var(--accent-green)'
                    : modelStatus === 'loading' ? 'var(--accent-blue)'
                    : modelStatus.startsWith('error') ? 'var(--accent-red)'
                    : 'var(--text-tertiary)'
                }}>
                  {modelStatus === 'ready' && 'Модель готова'}
                  {modelStatus === 'available' && 'Модель скачана, готова к запуску'}
                  {modelStatus === 'loading' && 'Загрузка модели...'}
                  {modelStatus.startsWith('error') && `Ошибка: ${modelStatus.slice(7)}`}
                  {modelStatus === 'not_downloaded' && (transModel.startsWith('large') ? '~1.6 ГБ, скачается при первом запуске' : 'Будет загружена автоматически')}
                </div>
              </div>
            )}

            {/* Divider */}
            <div style={{ height: 1, background: 'var(--border)', margin: '4px -16px', width: 'calc(100% + 32px)' }} />

            {/* Transparency */}
            <div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-[13px] font-medium text-[var(--text-primary)]">Прозрачность</span>
                <span className="text-[11px] text-[var(--text-tertiary)] tabular-nums">{Math.round(opacity * 100)}%</span>
              </div>
              <input
                type="range"
                min="0.2"
                max="1"
                step="0.05"
                value={opacity}
                onChange={(e) => onOpacityChange(parseFloat(e.target.value))}
              />
            </div>

            {/* Auto-answer */}
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">Автоответы</div>
                <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5">Отвечать при обнаружении вопроса</div>
              </div>
              <Toggle value={autoAnswer} onChange={onAutoAnswerChange} />
            </div>

            {/* Click-through */}
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">Клики сквозь окно</div>
                <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5">Мышь проходит сквозь оверлей</div>
              </div>
              <Toggle value={clickThrough} onChange={onClickThroughChange} />
            </div>
          </div>

          {mode === 'interview' && (
            <>
              {/* Profile section */}
              <EditableSection
                title="Профиль кандидата"
                subtitle="Резюме для системного промпта AI"
                endpoint="profile"
                uploadEndpoint="profile/upload"
                resetEndpoint="profile/reset"
                placeholder={"# Профиль кандидата\n\n## Имя\n[Ваше имя]\n\n## Роль\nAI Engineer\n\n## Опыт\n- Python, Docker, LLM\n\n## Ключевые проекты\n..."}
                isOpen={isOpen}
              />

              {/* Job description section */}
              <EditableSection
                title="Вакансия"
                subtitle="Описание позиции для контекста AI"
                endpoint="job"
                uploadEndpoint="job/upload"
                resetEndpoint="job/reset"
                processEndpoint="job/process"
                placeholder={"# Описание вакансии\n\n## Компания\n[Название]\n\n## Позиция\n[Роль]\n\n## Требования\n- ...\n\n## Стек\n- ..."}
                isOpen={isOpen}
              />
            </>
          )}

          {/* Audio Test */}
          <div style={{ borderTop: '1px solid var(--border)' }}>
            <div className="px-4 py-3">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[13px] font-medium text-[var(--text-primary)]">Тест аудио</span>
                <button
                  className="setting-chip"
                  onClick={audioTesting ? handleStopAudioTest : handleStartAudioTest}
                >
                  {audioTesting ? 'Остановить' : 'Проверить'}
                </button>
              </div>
              {audioTesting && (
                <div className="space-y-2">
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] text-[var(--text-secondary)]">Микрофон</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">
                        {micLevel > 0.05 ? 'Работает' : 'Говорите в микрофон'}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-100"
                        style={{
                          width: `${Math.min(100, micLevel * 100)}%`,
                          backgroundColor: 'var(--accent-green)',
                        }}
                      />
                    </div>
                  </div>
                  <div>
                    <div className="flex items-center justify-between mb-1">
                      <span className="text-[11px] text-[var(--text-secondary)]">Системный звук</span>
                      <span className="text-[10px] text-[var(--text-tertiary)]">
                        {!systemAvailable
                          ? 'BlackHole не найден'
                          : systemLevel > 0.05
                            ? 'Захватывается'
                            : 'Включите звук на компьютере'}
                      </span>
                    </div>
                    <div className="h-2 rounded-full bg-[rgba(255,255,255,0.06)] overflow-hidden">
                      <div
                        className="h-full rounded-full transition-all duration-100"
                        style={{
                          width: `${Math.min(100, systemLevel * 100)}%`,
                          backgroundColor: systemAvailable ? 'var(--accent)' : 'var(--accent-red)',
                        }}
                      />
                    </div>
                  </div>
                </div>
              )}
            </div>
          </div>

          {/* Hotkeys section */}
          <div style={{ borderTop: '1px solid var(--border)' }}>
            <button
              className="w-full flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-[rgba(255,255,255,0.03)] transition-colors"
              onClick={() => setHotkeysExpanded(!hotkeysExpanded)}
            >
              <span className="text-[13px] font-medium text-[var(--text-primary)]">Горячие клавиши</span>
              <ChevronIcon expanded={hotkeysExpanded} />
            </button>

            {hotkeysExpanded && (
              <div className="px-4 pb-3 space-y-2">
                {HOTKEYS.map((hk) => (
                  <div key={hk.desc} className="flex items-center justify-between">
                    <span className="text-[12px] text-[var(--text-secondary)]">{hk.desc}</span>
                    <span
                      className="kbd"
                      dangerouslySetInnerHTML={{ __html: hk.keys }}
                    />
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* Quit button */}
        <div className="px-4 py-3 mt-auto" style={{ borderTop: '1px solid var(--border)' }}>
          <button
            onClick={handleQuit}
            className="w-full flex items-center justify-center gap-2 py-2.5 rounded-lg text-[13px] font-medium text-[var(--accent-red)] hover:bg-[rgba(255,69,58,0.1)] transition-colors cursor-pointer"
          >
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
              <line x1="18" y1="6" x2="6" y2="18" />
              <line x1="6" y1="6" x2="18" y2="18" />
            </svg>
            Закрыть приложение
          </button>
        </div>
      </div>
    </div>
  )
}

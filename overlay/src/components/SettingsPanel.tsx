/**
 * Full-window settings overlay with LLM provider/model selector,
 * transparency slider, feature toggles, hotkeys reference, and quit button.
 */

import { useState, useEffect } from 'react'

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
  isRecording: boolean
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

export function SettingsPanel({
  isOpen,
  onClose,
  opacity,
  onOpacityChange,
  clickThrough,
  onClickThroughChange,
  autoAnswer,
  onAutoAnswerChange,
  isRecording,
}: Props) {
  const [hotkeysExpanded, setHotkeysExpanded] = useState(false)
  const [llmOptions, setLlmOptions] = useState<LLMOptions | null>(null)
  const [selectedProvider, setSelectedProvider] = useState('openai')
  const [selectedModel, setSelectedModel] = useState('gpt-4o-mini')

  // Load LLM settings when panel opens
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
  }, [isOpen])

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

  const handleQuit = () => {
    window.electronAPI?.quitApp()
  }

  const handleToggleRecording = async () => {
    const endpoint = isRecording ? '/stop' : '/start'
    try {
      await fetch(`${BACKEND_URL}${endpoint}`, { method: 'POST' })
    } catch {}
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

            {/* Recording toggle */}
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[13px] font-medium text-[var(--text-primary)]">Запись</div>
                <div className="text-[11px] text-[var(--text-tertiary)] mt-0.5">Микрофон + системное аудио</div>
              </div>
              <Toggle value={isRecording} onChange={handleToggleRecording} />
            </div>

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

          {/* Hotkeys section */}
          <div style={{ borderTop: '1px solid var(--border)' }}>
            <button
              className="w-full flex items-center justify-between px-4 py-3 cursor-pointer hover:bg-[rgba(255,255,255,0.03)] transition-colors"
              onClick={() => setHotkeysExpanded(!hotkeysExpanded)}
            >
              <span className="text-[13px] font-medium text-[var(--text-primary)]">Горячие клавиши</span>
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                stroke="var(--text-tertiary)"
                strokeWidth="2"
                strokeLinecap="round"
                style={{
                  transform: hotkeysExpanded ? 'rotate(180deg)' : 'rotate(0deg)',
                  transition: 'transform 0.2s ease',
                }}
              >
                <polyline points="6 9 12 15 18 9" />
              </svg>
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

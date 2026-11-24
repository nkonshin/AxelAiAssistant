/**
 * Python backend lifecycle management.
 *
 * Spawns the Python FastAPI server, monitors its health,
 * and restarts on crash.
 *
 * Where the backend comes from:
 * - Dev (`npx electron .`): ../backend рядом с overlay.
 * - Собранное .app: живая папка проекта (бэкенд + его .venv), чтобы правки кода
 *   и ui.html работали без пересборки приложения. Путь берётся из
 *   ~/.axel-assistant/project_dir, иначе — тот, откуда собирали (__AXEL_PROJECT_DIR__).
 * - Если папки проекта нет — бэкенд, вшитый в Contents/Resources/backend,
 *   и venv в ~/.axel-assistant/venv/ (старый режим v1 для чужого Mac).
 *
 * Приложение, запущенное из Finder, не получает окружение Терминала (PATH, HTTPS_PROXY…),
 * поэтому в собранном режиме окружение берётся из `zsh -ilc env` — как при запуске из .command.
 */

import { spawn, execFile, execSync, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'
import os from 'os'
import { app } from 'electron'

declare const __AXEL_PROJECT_DIR__: string

let pythonProcess: ChildProcess | null = null
let shouldRestart = true
let restarts = 0

const AXEL_HOME = path.join(os.homedir(), '.axel-assistant')
const BACKEND_LOG = path.join(AXEL_HOME, 'backend.out')

function isPackaged(): boolean {
  return app.isPackaged
}

function hasBackend(dir: string | null | undefined): dir is string {
  return !!dir && fs.existsSync(path.join(dir, 'backend', 'app.py'))
}

/** Папка проекта с живым бэкендом или null (тогда — вшитый бэкенд). */
export function projectDir(): string | null {
  if (!isPackaged()) return path.resolve(app.getAppPath(), '..')
  try {
    const p = fs.readFileSync(path.join(AXEL_HOME, 'project_dir'), 'utf-8').trim()
    if (hasBackend(p)) return p
  } catch {}
  const baked = typeof __AXEL_PROJECT_DIR__ === 'string' ? __AXEL_PROJECT_DIR__ : ''
  return hasBackend(baked) ? baked : null
}

function getBackendDir(): string {
  const p = projectDir()
  return p ? path.join(p, 'backend') : path.join(process.resourcesPath, 'backend')
}

function findPython(): string {
  const p = projectDir()
  if (p) {
    const venvPython = path.join(p, 'backend', '.venv', 'bin', 'python3')
    if (fs.existsSync(venvPython)) return venvPython
  }
  const homeVenv = path.join(AXEL_HOME, 'venv', 'bin', 'python3')
  return fs.existsSync(homeVenv) ? homeVenv : 'python3'
}

/** Окружение интерактивного zsh: PATH (claude, homebrew, pyenv), прокси, язык. */
let shellEnvCache: Record<string, string> | null = null
function readShellOutput(): Promise<string> {
  const shell = process.env.SHELL || '/bin/zsh'
  return new Promise((resolve) => {
    const child = execFile(shell, ['-ilc', 'printf "__AXEL_ENV__"; env -0'],
      { encoding: 'utf-8', timeout: 8000, maxBuffer: 16 * 1024 * 1024 },
      (_err, stdout) => resolve(stdout || ''))
    child.stdin?.end()
  })
}

async function shellEnv(): Promise<Record<string, string>> {
  if (shellEnvCache) return shellEnvCache
  const env: Record<string, string> = {}
  try {
    const out = await readShellOutput()
    const i = out.indexOf('__AXEL_ENV__')
    if (i >= 0) {
      for (const kv of out.slice(i + '__AXEL_ENV__'.length).split('\0')) {
        const eq = kv.indexOf('=')
        if (eq > 0) env[kv.slice(0, eq)] = kv.slice(eq + 1)
      }
    }
  } catch {}
  for (const k of ['PWD', 'OLDPWD', 'SHLVL', '_', 'TERM_SESSION_ID', 'TERM_PROGRAM', 'TERM_PROGRAM_VERSION']) delete env[k]
  const home = os.homedir()
  const extra = [`${home}/.local/bin`, '/opt/homebrew/bin', '/usr/local/bin', '/usr/bin', '/bin', '/usr/sbin', '/sbin']
  const parts = (env.PATH || process.env.PATH || '').split(':').filter(Boolean)
  for (const d of extra) if (!parts.includes(d)) parts.push(d)
  env.PATH = parts.join(':')
  shellEnvCache = env
  return env
}

function ensurePackagedVenv(): void {
  /**
   * Только для вшитого бэкенда (нет папки проекта): на первом запуске
   * создать venv в ~/.axel-assistant/venv/ и поставить зависимости.
   */
  if (!isPackaged() || projectDir()) return

  const venvDir = path.join(AXEL_HOME, 'venv')
  const venvPython = path.join(venvDir, 'bin', 'python3')
  const requirementsPath = path.join(getBackendDir(), 'requirements.txt')

  if (!fs.existsSync(AXEL_HOME)) fs.mkdirSync(AXEL_HOME, { recursive: true })

  if (fs.existsSync(venvPython)) {
    const stampFile = path.join(AXEL_HOME, '.deps-installed')
    const reqMtime = fs.existsSync(requirementsPath) ? fs.statSync(requirementsPath).mtimeMs : 0
    const stampMtime = fs.existsSync(stampFile) ? parseFloat(fs.readFileSync(stampFile, 'utf-8') || '0') : 0
    if (reqMtime <= stampMtime) return
    try {
      execSync(`"${venvPython}" -m pip install -q -r "${requirementsPath}"`, { stdio: 'ignore', timeout: 120000 })
      fs.writeFileSync(stampFile, String(reqMtime))
    } catch (e) {
      logLine(`[Backend] Failed to update deps: ${e}`)
    }
    return
  }

  try {
    execSync(`python3 -m venv "${venvDir}"`, { stdio: 'ignore', timeout: 30000 })
  } catch {
    throw new Error('Cannot create Python venv. Is python3 installed?')
  }
  try {
    execSync(`"${venvPython}" -m pip install --upgrade pip`, { stdio: 'ignore', timeout: 60000 })
  } catch {}
  if (fs.existsSync(requirementsPath)) {
    execSync(`"${venvPython}" -m pip install -q -r "${requirementsPath}"`, { stdio: 'ignore', timeout: 300000 })
    fs.writeFileSync(path.join(AXEL_HOME, '.deps-installed'), String(fs.statSync(requirementsPath).mtimeMs))
  }
}

function logLine(msg: string): void {
  try {
    if (!fs.existsSync(AXEL_HOME)) fs.mkdirSync(AXEL_HOME, { recursive: true })
    fs.appendFileSync(BACKEND_LOG, msg.endsWith('\n') ? msg : msg + '\n')
  } catch {}
}

let externalBackend = false

async function isBackendAlreadyUp(): Promise<boolean> {
  try {
    const res = await fetch('http://127.0.0.1:8765/health')
    return res.ok
  } catch {
    return false
  }
}

export async function startBackend(): Promise<void> {
  // Бэкенд уже запущен (например, из «Ассистент защиты.command») — подключаемся к нему
  if (await isBackendAlreadyUp()) {
    logLine('[Backend] Already running on port 8765, skipping spawn')
    externalBackend = true
    return
  }

  ensurePackagedVenv()

  const backendDir = getBackendDir()
  const backendPath = path.join(backendDir, 'app.py')
  const pythonPath = findPython()

  const env: Record<string, string | undefined> = isPackaged() ? { ...process.env, ...(await shellEnv()) } : { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE
  env.PYTHONUNBUFFERED = '1'
  if (isPackaged()) env.AXEL_HOST_APP = app.getName()

  logLine(`\n[${new Date().toISOString()}] [Backend] Starting: ${pythonPath} ${backendPath}`)

  pythonProcess = spawn(pythonPath, [backendPath], {
    env: env as NodeJS.ProcessEnv,
    cwd: backendDir,
    stdio: ['ignore', 'pipe', 'pipe'],
  })
  const started = Date.now()

  pythonProcess.stdout?.on('data', (d) => logLine(d.toString()))
  pythonProcess.stderr?.on('data', (d) => logLine(d.toString()))
  pythonProcess.on('error', (e) => logLine(`[Backend] spawn error: ${e.message}`))

  pythonProcess.on('exit', (code) => {
    logLine(`[Backend] Exited with code ${code}`)
    pythonProcess = null
    // проработал минуту — считаем, что падение случайное, счётчик сбрасываем
    if (Date.now() - started > 60000) restarts = 0
    if (shouldRestart && code !== 0 && restarts < 5) {
      restarts++
      setTimeout(() => startBackend(), 2000)
    }
  })
}

export function stopBackend(): void {
  shouldRestart = false
  if (pythonProcess) {
    pythonProcess.kill('SIGTERM')
    pythonProcess = null
  }
}

export async function waitForBackend(maxAttempts = 50): Promise<boolean> {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const res = await fetch('http://127.0.0.1:8765/health')
      if (res.ok) return true
    } catch {
      // Backend not ready yet
    }
    await new Promise((r) => setTimeout(r, 200))
  }
  return false
}

export function isBackendRunning(): boolean {
  return pythonProcess !== null && !pythonProcess.killed
}

export function usesExternalBackend(): boolean {
  return externalBackend
}

export const backendLogPath = BACKEND_LOG

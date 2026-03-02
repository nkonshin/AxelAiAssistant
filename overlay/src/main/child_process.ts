/**
 * Python backend lifecycle management.
 *
 * Spawns the Python FastAPI server, monitors its health,
 * and restarts on crash.
 *
 * Supports two modes:
 * - Dev: backend at ../../backend relative to overlay
 * - Packaged (.app): backend bundled in Contents/Resources/backend,
 *   venv auto-created in ~/.axel-assistant/venv/
 */

import { spawn, execSync, ChildProcess } from 'child_process'
import path from 'path'
import fs from 'fs'
import os from 'os'
import { app } from 'electron'

let pythonProcess: ChildProcess | null = null
let shouldRestart = true

const AXEL_HOME = path.join(os.homedir(), '.axel-assistant')

function isPackaged(): boolean {
  return app.isPackaged
}

function getBackendDir(): string {
  if (isPackaged()) {
    return path.join(process.resourcesPath, 'backend')
  }
  const appPath = app.getAppPath()
  return path.resolve(appPath, '..', 'backend')
}

function getBackendPath(): string {
  return path.join(getBackendDir(), 'main.py')
}

function findPython(): string {
  if (isPackaged()) {
    // In packaged mode, use venv from ~/.axel-assistant/venv/
    const venvPython = path.join(AXEL_HOME, 'venv', 'bin', 'python3')
    if (fs.existsSync(venvPython)) {
      return venvPython
    }
    // Fallback to system python3
    return 'python3'
  }
  // Dev mode: use local .venv
  const appPath = app.getAppPath()
  const venvPython = path.resolve(appPath, '..', 'backend', '.venv', 'bin', 'python3')
  return venvPython
}

function ensurePackagedVenv(): void {
  /**
   * On first launch of packaged .app, create a Python venv
   * in ~/.axel-assistant/venv/ and install dependencies.
   */
  if (!isPackaged()) return

  const venvDir = path.join(AXEL_HOME, 'venv')
  const venvPython = path.join(venvDir, 'bin', 'python3')
  const requirementsPath = path.join(getBackendDir(), 'requirements.txt')

  // Create ~/.axel-assistant/ if needed
  if (!fs.existsSync(AXEL_HOME)) {
    fs.mkdirSync(AXEL_HOME, { recursive: true })
  }

  // If venv already exists and has python3 binary, check if requirements are up to date
  if (fs.existsSync(venvPython)) {
    // Quick check: compare requirements.txt mtime with a stamp file
    const stampFile = path.join(AXEL_HOME, '.deps-installed')
    const reqMtime = fs.existsSync(requirementsPath)
      ? fs.statSync(requirementsPath).mtimeMs
      : 0
    const stampMtime = fs.existsSync(stampFile)
      ? parseFloat(fs.readFileSync(stampFile, 'utf-8') || '0')
      : 0

    if (reqMtime <= stampMtime) {
      console.log('[Backend] Venv is up to date')
      return
    }

    // Requirements changed — upgrade pip and install new deps
    console.log('[Backend] Requirements changed, updating deps...')
    try {
      execSync(`"${venvPython}" -m pip install --upgrade pip`, {
        stdio: 'inherit',
        timeout: 60000,
      })
    } catch {}
    try {
      execSync(`"${venvPython}" -m pip install -q -r "${requirementsPath}"`, {
        stdio: 'inherit',
        timeout: 120000,
      })
      fs.writeFileSync(stampFile, String(reqMtime))
      console.log('[Backend] Dependencies updated')
    } catch (e) {
      console.error('[Backend] Failed to update deps:', e)
    }
    return
  }

  // Create venv from scratch
  console.log('[Backend] Creating Python venv in', venvDir)
  try {
    execSync(`python3 -m venv "${venvDir}"`, { stdio: 'inherit', timeout: 30000 })
  } catch (e) {
    console.error('[Backend] Failed to create venv:', e)
    throw new Error('Cannot create Python venv. Is python3 installed?')
  }

  // Upgrade pip first (old pip can't install binary wheels)
  try {
    execSync(`"${venvPython}" -m pip install --upgrade pip`, {
      stdio: 'inherit',
      timeout: 60000,
    })
  } catch {
    console.error('[Backend] pip upgrade failed, continuing anyway')
  }

  // Install dependencies
  if (fs.existsSync(requirementsPath)) {
    console.log('[Backend] Installing dependencies...')
    try {
      execSync(`"${venvPython}" -m pip install -q -r "${requirementsPath}"`, {
        stdio: 'inherit',
        timeout: 300000,
      })
      const reqMtime = fs.statSync(requirementsPath).mtimeMs
      fs.writeFileSync(path.join(AXEL_HOME, '.deps-installed'), String(reqMtime))
      console.log('[Backend] Dependencies installed')
    } catch (e) {
      console.error('[Backend] Failed to install deps:', e)
      throw new Error('Failed to install Python dependencies')
    }
  }
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
  // Check if backend is already running (e.g. started by dev.sh)
  if (await isBackendAlreadyUp()) {
    console.log('[Backend] Already running on port 8765, skipping spawn')
    externalBackend = true
    return
  }

  // In packaged mode, ensure venv exists with all dependencies
  ensurePackagedVenv()

  const backendPath = getBackendPath()
  const pythonPath = findPython()
  const backendDir = getBackendDir()

  console.log(`[Backend] Starting: ${pythonPath} ${backendPath}`)
  console.log(`[Backend] Working dir: ${backendDir}`)

  const env = { ...process.env }
  delete env.ELECTRON_RUN_AS_NODE

  pythonProcess = spawn(pythonPath, [backendPath], {
    env,
    cwd: backendDir,
    stdio: ['pipe', 'pipe', 'pipe'],
  })

  pythonProcess.stdout?.on('data', (data) => {
    console.log(`[Backend] ${data.toString().trim()}`)
  })

  pythonProcess.stderr?.on('data', (data) => {
    console.error(`[Backend] ${data.toString().trim()}`)
  })

  pythonProcess.on('exit', (code) => {
    console.log(`[Backend] Exited with code ${code}`)
    pythonProcess = null
    if (shouldRestart && code !== 0) {
      console.log('[Backend] Restarting in 2s...')
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

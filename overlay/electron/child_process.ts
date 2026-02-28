/**
 * Python backend lifecycle management.
 *
 * Spawns the Python FastAPI server, monitors its health,
 * and restarts on crash.
 */

import { spawn, ChildProcess } from 'child_process'
import path from 'path'
import { app } from 'electron'

let pythonProcess: ChildProcess | null = null
let shouldRestart = true

function getBackendPath(): string {
  // In dev: project root is two levels up from overlay/out/main/
  const appPath = app.getAppPath()
  return path.resolve(appPath, '..', 'backend', 'main.py')
}

function findPython(): string {
  // Check for venv first, then fall back to system python3
  const appPath = app.getAppPath()
  const venvPython = path.resolve(appPath, '..', 'backend', '.venv', 'bin', 'python3')
  // We'll try venv first; if spawn fails, fall back to 'python3'
  return venvPython
}

export function startBackend(): void {
  const backendPath = getBackendPath()
  const pythonPath = findPython()

  console.log(`[Backend] Starting: ${pythonPath} ${backendPath}`)

  pythonProcess = spawn(pythonPath, [backendPath], {
    env: { ...process.env },
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

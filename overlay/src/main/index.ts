/**
 * Electron main process: stealth overlay window with hotkeys and Python backend management.
 *
 * Stealth features:
 * - setContentProtection(true): hidden from screen share
 * - setAlwaysOnTop("screen-saver"): above all windows including fullscreen
 * - app.dock.hide(): no Dock icon
 * - transparent, frameless window
 *
 * Window is interactive by default. Click-through is opt-in via settings.
 */

import { app, BrowserWindow, globalShortcut, ipcMain, clipboard } from 'electron'
import { join } from 'path'
import { writeFileSync, appendFileSync, mkdirSync, existsSync } from 'fs'
import { homedir } from 'os'
import { startBackend, stopBackend, waitForBackend } from './child_process.js'

// File-based logging for packaged app debugging
const LOG_DIR = join(homedir(), '.axel-assistant')
const LOG_FILE = join(LOG_DIR, 'app.log')
function log(msg: string): void {
  const line = `[${new Date().toISOString()}] ${msg}\n`
  try {
    if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true })
    appendFileSync(LOG_FILE, line)
  } catch {}
  console.log(msg)
}

let mainWindow: BrowserWindow | null = null
let isRecording = false
let currentOpacity = 0.85
let isClickThrough = false

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 500,
    height: 700,
    x: 50,
    y: 100,
    transparent: true,
    frame: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    hasShadow: false,
    resizable: true,
    opacity: currentOpacity,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  })

  // Stealth: hide from screen capture
  mainWindow.setContentProtection(true)

  // Above ALL windows including fullscreen
  mainWindow.setAlwaysOnTop(true, 'screen-saver')

  // Window is interactive by default (NOT click-through)
  // Click-through can be toggled via settings panel

  // Visible on all workspaces and fullscreen spaces
  mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })

  // Load the renderer
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../renderer/index.html'))
  }
}

function registerHotkeys(): void {
  // Toggle overlay visibility
  globalShortcut.register('CommandOrControl+Shift+\\', () => {
    if (mainWindow?.isVisible()) {
      mainWindow.hide()
    } else {
      mainWindow?.show()
    }
  })

  // Toggle recording
  globalShortcut.register('CommandOrControl+Shift+M', async () => {
    const endpoint = isRecording ? '/stop' : '/start'
    try {
      const res = await fetch(`http://127.0.0.1:8765${endpoint}`, { method: 'POST' })
      if (res.ok) isRecording = !isRecording
    } catch (e) {
      console.error('[Hotkey] Recording toggle failed:', e)
    }
    // Ensure window stays interactive after hotkey (fixes macOS transparent window focus loss)
    if (!isClickThrough) {
      mainWindow?.setIgnoreMouseEvents(false)
    }
  })

  // Toggle click-through (Cmd+Shift+T)
  globalShortcut.register('CommandOrControl+Shift+T', () => {
    isClickThrough = !isClickThrough
    if (isClickThrough) {
      mainWindow?.setIgnoreMouseEvents(true, { forward: true })
    } else {
      mainWindow?.setIgnoreMouseEvents(false)
    }
    log(`[Hotkey] Click-through: ${isClickThrough}`)
  })

  // Force answer (all buffers)
  globalShortcut.register('CommandOrControl+Shift+A', () => {
    fetch('http://127.0.0.1:8765/force-answer', { method: 'POST' }).catch(() => {})
  })

  // Mic trigger: send candidate's speech to LLM (F5)
  globalShortcut.register('F5', () => {
    fetch('http://127.0.0.1:8765/trigger-mic', { method: 'POST' }).catch(() => {})
  })

  // Screenshot
  globalShortcut.register('CommandOrControl+Shift+S', () => {
    fetch('http://127.0.0.1:8765/screenshot', { method: 'POST' }).catch(() => {})
  })

  // Copy last answer
  globalShortcut.register('CommandOrControl+Shift+C', () => {
    mainWindow?.webContents.send('hotkey-action', 'copy-last-answer')
  })

  // Increase opacity
  globalShortcut.register('CommandOrControl+Shift+Up', () => {
    currentOpacity = Math.min(1.0, currentOpacity + 0.1)
    mainWindow?.setOpacity(currentOpacity)
  })

  // Decrease opacity
  globalShortcut.register('CommandOrControl+Shift+Down', () => {
    currentOpacity = Math.max(0.2, currentOpacity - 0.1)
    mainWindow?.setOpacity(currentOpacity)
  })

}

log(`[App] Starting (packaged=${app.isPackaged})`)

app.whenReady().then(async () => {
  // Hide from Dock on macOS
  if (process.platform === 'darwin') {
    app.dock.hide()
  }

  // Obscure process name
  app.setName('System Helper')

  try {
    // Start Python backend (skips if already running, e.g. from dev.sh)
    log('[App] Starting backend...')
    await startBackend()

    const backendReady = await waitForBackend()
    if (!backendReady) {
      log('[App] WARNING: Python backend failed to start')
    }
  } catch (e: any) {
    log(`[App] Backend error: ${e.message}`)
  }

  createWindow()
  registerHotkeys()
  log('[App] Startup complete')
}).catch((e: any) => {
  log(`[App] FATAL: ${e.message}\n${e.stack}`)
})

// IPC handlers
ipcMain.on('set-ignore-mouse', (_event, ignore: boolean) => {
  // Only toggle mouse events when click-through mode is active.
  // Without this guard, Interactable components in the renderer
  // (e.g. Transcript) would accidentally put the window into
  // click-through mode on mouseleave even when the user hasn't
  // enabled click-through, making TopBar buttons unresponsive.
  if (!isClickThrough) return
  mainWindow?.setIgnoreMouseEvents(ignore, { forward: true })
})

ipcMain.on('copy-to-clipboard', (_event, text: string) => {
  clipboard.writeText(text)
})

ipcMain.on('quit-app', () => {
  app.quit()
})

ipcMain.on('set-opacity', (_event, opacity: number) => {
  currentOpacity = Math.max(0.2, Math.min(1.0, opacity))
  mainWindow?.setOpacity(currentOpacity)
})

ipcMain.on('set-click-through', (_event, enabled: boolean) => {
  isClickThrough = enabled
  if (enabled) {
    mainWindow?.setIgnoreMouseEvents(true, { forward: true })
  } else {
    mainWindow?.setIgnoreMouseEvents(false)
  }
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  stopBackend()
})

app.on('window-all-closed', () => {
  app.quit()
})

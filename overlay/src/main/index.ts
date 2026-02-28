/**
 * Electron main process: stealth overlay window with hotkeys and Python backend management.
 *
 * Stealth features:
 * - setContentProtection(true): hidden from screen share
 * - setAlwaysOnTop("screen-saver"): above all windows including fullscreen
 * - setIgnoreMouseEvents(true, { forward: true }): click-through with event forwarding
 * - app.dock.hide(): no Dock icon
 * - transparent, frameless window
 */

import { app, BrowserWindow, globalShortcut, ipcMain, clipboard } from 'electron'
import { join } from 'path'
import { startBackend, stopBackend, waitForBackend } from './child_process.js'

let mainWindow: BrowserWindow | null = null
let isRecording = false
let currentOpacity = 0.85

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

  // Click-through by default
  mainWindow.setIgnoreMouseEvents(true, { forward: true })

  // Visible on all workspaces and fullscreen spaces
  mainWindow.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true })

  // Load the renderer
  if (process.env.ELECTRON_RENDERER_URL) {
    mainWindow.loadURL(process.env.ELECTRON_RENDERER_URL)
  } else {
    mainWindow.loadFile(join(__dirname, '../../src/index.html'))
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
  })

  // Force answer
  globalShortcut.register('CommandOrControl+Shift+A', () => {
    fetch('http://127.0.0.1:8765/force-answer', { method: 'POST' }).catch(() => {})
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

app.whenReady().then(async () => {
  // Hide from Dock on macOS
  if (process.platform === 'darwin') {
    app.dock.hide()
  }

  // Obscure process name
  app.setName('System Helper')

  // Start Python backend
  startBackend()

  const backendReady = await waitForBackend()
  if (!backendReady) {
    console.error('[App] Python backend failed to start')
  }

  createWindow()
  registerHotkeys()
})

// IPC handlers
ipcMain.on('set-ignore-mouse', (_event, ignore: boolean) => {
  mainWindow?.setIgnoreMouseEvents(ignore, { forward: true })
})

ipcMain.on('copy-to-clipboard', (_event, text: string) => {
  clipboard.writeText(text)
})

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  stopBackend()
})

app.on('window-all-closed', () => {
  app.quit()
})

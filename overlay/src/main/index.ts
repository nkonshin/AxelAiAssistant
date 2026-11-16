/**
 * Electron main process v2: окно-суфлёр для второго монитора.
 *
 * Окно грузит интерфейс бэкенда (http://127.0.0.1:8765/ui), поэтому всё можно открыть и в браузере.
 * - Ставится на НЕ основной монитор (основной обычно показывают в Zoom).
 * - setContentProtection — переключаемо. На macOS 15+ Zoom всё равно видит окно,
 *   надёжный способ — демонстрировать в Zoom только один экран.
 * - Глобальные хоткеи работают, даже когда в фокусе Zoom.
 */

import { app, BrowserWindow, globalShortcut, ipcMain, clipboard, screen, dialog } from 'electron'
import { join } from 'path'
import { appendFileSync, mkdirSync, existsSync } from 'fs'
import { homedir } from 'os'
import { startBackend, stopBackend, waitForBackend } from './child_process.js'

const API = 'http://127.0.0.1:8765'
const LOG_DIR = join(homedir(), '.axel-assistant')
const LOG_FILE = join(LOG_DIR, 'app.log')
function log(msg: string): void {
  try {
    if (!existsSync(LOG_DIR)) mkdirSync(LOG_DIR, { recursive: true })
    appendFileSync(LOG_FILE, `[${new Date().toISOString()}] ${msg}\n`)
  } catch {}
  console.log(msg)
}

let win: BrowserWindow | null = null
let stealth = true
let onTop = false

function post(path: string, body: object = {}): void {
  fetch(API + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  }).catch((e) => log(`[POST ${path}] ${e}`))
}

function pickDisplay(): Electron.Display {
  const primary = screen.getPrimaryDisplay()
  const others = screen.getAllDisplays().filter((d) => d.id !== primary.id)
  // самый большой не основной монитор; если его нет — основной
  return others.sort((a, b) => b.workArea.width * b.workArea.height - a.workArea.width * a.workArea.height)[0] || primary
}

function placeOn(d: Electron.Display): void {
  if (!win) return
  const wa = d.workArea
  const w = Math.min(1250, Math.round(wa.width * 0.9))
  const h = Math.min(950, Math.round(wa.height * 0.9))
  win.setBounds({ x: wa.x + Math.round((wa.width - w) / 2), y: wa.y + Math.round((wa.height - h) / 2), width: w, height: h })
}

function createWindow(): void {
  win = new BrowserWindow({
    width: 1200,
    height: 900,
    title: 'Заметки',
    backgroundColor: '#111315',
    show: false,
    webPreferences: {
      preload: join(__dirname, '../preload/index.js'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  })
  placeOn(pickDisplay())
  win.setContentProtection(stealth)
  win.loadURL(`${API}/ui`)
  win.once('ready-to-show', () => win?.showInactive())
  // если бэкенд перезапускался — перезагрузить страницу
  win.webContents.on('did-fail-load', () => setTimeout(() => win?.loadURL(`${API}/ui`), 1500))
  win.on('page-title-updated', (e) => e.preventDefault())
  // macOS иногда сбрасывает флаг при активации — выставляем заново
  win.on('focus', () => win?.setContentProtection(stealth))
  win.on('show', () => win?.setContentProtection(stealth))
}

function registerHotkeys(): void {
  const reg = (acc: string, fn: () => void) => {
    if (!globalShortcut.register(acc, fn)) log(`[Hotkey] не удалось занять ${acc}`)
  }
  reg('CommandOrControl+Shift+\\', () => {
    if (win?.isVisible()) win.hide()
    else win?.showInactive()
  })
  reg('CommandOrControl+Shift+A', () => post('/ask'))
  reg('F5', () => post('/ask'))
  reg('CommandOrControl+Shift+M', () => post('/listen/toggle'))
  reg('CommandOrControl+Shift+S', () => post('/screenshot', { mode: 'ask' }))
  reg('CommandOrControl+Shift+D', () => moveToNextDisplay())
  reg('CommandOrControl+Shift+X', () => post('/cancel'))
  // ⌘⇧3/4/5 заняты скриншотами macOS — работы переключаем через Ctrl+Shift+цифра
  for (let i = 1; i <= 9; i++) reg(`Control+Shift+${i}`, () => post('/lab', { index: i - 1 }))
}

function moveToNextDisplay(): void {
  if (!win) return
  const all = screen.getAllDisplays()
  const cur = screen.getDisplayMatching(win.getBounds())
  const idx = all.findIndex((d) => d.id === cur.id)
  placeOn(all[(idx + 1) % all.length])
}

log(`[App v2] Starting (packaged=${app.isPackaged})`)

app.whenReady().then(async () => {
  if (process.platform === 'darwin') app.dock.hide()
  app.setName('Notes Helper')
  try {
    await startBackend()
    if (!(await waitForBackend(100))) log('[App] WARNING: backend не ответил за 20 с')
  } catch (e: any) {
    log(`[App] Backend error: ${e.message}`)
  }
  createWindow()
  registerHotkeys()
  log('[App v2] Startup complete')
}).catch((e: any) => log(`[App] FATAL: ${e.message}\n${e.stack}`))

ipcMain.on('set-stealth', (_e, on: boolean) => {
  stealth = !!on
  win?.setContentProtection(stealth)
  log(`[App] stealth=${stealth}`)
})
ipcMain.on('set-always-on-top', (_e, on: boolean) => {
  onTop = !!on
  win?.setAlwaysOnTop(onTop, 'floating')
})
ipcMain.on('move-to-next-display', () => moveToNextDisplay())
ipcMain.handle('get-window-state', () => ({ stealth, onTop }))
ipcMain.on('copy-to-clipboard', (_e, text: string) => clipboard.writeText(text))
ipcMain.handle('select-folder', async (_e, defaultPath?: string) => {
  if (!win) return null
  const r = await dialog.showOpenDialog(win, { title: 'Папка с материалами', defaultPath, properties: ['openDirectory'] })
  return r.canceled || !r.filePaths.length ? null : r.filePaths[0]
})
ipcMain.on('quit-app', () => app.quit())

app.on('will-quit', () => {
  globalShortcut.unregisterAll()
  stopBackend()
})
app.on('window-all-closed', () => app.quit())

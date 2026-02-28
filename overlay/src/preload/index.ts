/**
 * Preload script: secure IPC bridge between Electron main and React renderer.
 *
 * Exposes a limited API via contextBridge so the renderer can:
 * - Toggle click-through mode
 * - Copy text to clipboard
 * - Receive hotkey actions from main process
 */

import { contextBridge, ipcRenderer } from 'electron'

contextBridge.exposeInMainWorld('electronAPI', {
  setIgnoreMouseEvents: (ignore: boolean) => {
    ipcRenderer.send('set-ignore-mouse', ignore)
  },

  copyToClipboard: (text: string) => {
    ipcRenderer.send('copy-to-clipboard', text)
  },

  onHotkeyAction: (callback: (action: string) => void) => {
    ipcRenderer.on('hotkey-action', (_event, action: string) => callback(action))
  },
})

/**
 * Preload script: secure IPC bridge between Electron main and React renderer.
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
    ipcRenderer.removeAllListeners('hotkey-action')
    ipcRenderer.on('hotkey-action', (_event, action: string) => callback(action))
  },

  quitApp: () => {
    ipcRenderer.send('quit-app')
  },

  setOpacity: (opacity: number) => {
    ipcRenderer.send('set-opacity', opacity)
  },

  setClickThrough: (enabled: boolean) => {
    ipcRenderer.send('set-click-through', enabled)
  },
})

interface ElectronAPI {
  setIgnoreMouseEvents: (ignore: boolean) => void
  copyToClipboard: (text: string) => void
  onHotkeyAction: (callback: (action: string) => void) => void
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}

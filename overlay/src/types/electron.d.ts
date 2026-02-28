interface ElectronAPI {
  setIgnoreMouseEvents: (ignore: boolean) => void
  copyToClipboard: (text: string) => void
  onHotkeyAction: (callback: (action: string) => void) => void
  quitApp: () => void
  setOpacity: (opacity: number) => void
  setClickThrough: (enabled: boolean) => void
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}

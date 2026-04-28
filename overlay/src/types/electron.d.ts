interface ElectronAPI {
  setIgnoreMouseEvents: (ignore: boolean) => void
  copyToClipboard: (text: string) => void
  onHotkeyAction: (callback: (action: string) => void) => void
  quitApp: () => void
  setOpacity: (opacity: number) => void
  setClickThrough: (enabled: boolean) => void
  selectFolder: (defaultPath?: string) => Promise<string | null>
}

declare global {
  interface Window {
    electronAPI: ElectronAPI
  }
}

export {}

/**
 * Hook for handling hotkey actions forwarded from Electron main process via IPC.
 */

import { useEffect } from 'react'

export function useHotkeys(onCopyLastAnswer: () => void) {
  useEffect(() => {
    const api = window.electronAPI
    if (!api) return

    api.onHotkeyAction((action: string) => {
      if (action === 'copy-last-answer') {
        onCopyLastAnswer()
      }
    })
  }, [onCopyLastAnswer])
}

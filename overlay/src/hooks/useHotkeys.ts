/**
 * Hook for handling hotkey actions forwarded from Electron main process via IPC.
 * Accepts a map of action name to handler function.
 */

import { useEffect, useRef } from 'react'

export function useHotkeys(handlers: Record<string, () => void>) {
  const handlersRef = useRef(handlers)
  handlersRef.current = handlers

  useEffect(() => {
    const api = window.electronAPI
    if (!api?.onHotkeyAction) return

    api.onHotkeyAction((action: string) => {
      handlersRef.current[action]?.()
    })
  }, [])
}

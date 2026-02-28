/**
 * Wrapper that toggles click-through when mouse enters/leaves.
 *
 * By default the overlay is click-through. When hovering over
 * interactive elements (buttons, scroll areas), we disable
 * click-through so the user can interact.
 */

import { ReactNode } from 'react'

interface Props {
  children: ReactNode
  className?: string
}

export function Interactable({ children, className = '' }: Props) {
  return (
    <div
      className={className}
      onMouseEnter={() => window.electronAPI?.setIgnoreMouseEvents(false)}
      onMouseLeave={() => window.electronAPI?.setIgnoreMouseEvents(true)}
    >
      {children}
    </div>
  )
}

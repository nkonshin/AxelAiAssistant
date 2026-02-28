/**
 * Top status bar: recording indicator, connection status, drag zone.
 */

import { Interactable } from './Interactable'

interface Props {
  isRecording: boolean
  isConnected: boolean
  isAnswering: boolean
}

export function StatusBar({ isRecording, isConnected, isAnswering }: Props) {
  return (
    <Interactable className="drag-region flex items-center justify-between px-3 py-2 border-b border-white/10">
      <div className="flex items-center gap-2">
        {/* Recording indicator */}
        <div
          className={`w-2 h-2 rounded-full ${
            isRecording ? 'bg-green-400 animate-pulse' : 'bg-red-400'
          }`}
        />
        <span className="text-xs text-white/60">
          {isRecording ? 'REC' : 'OFF'}
        </span>

        {/* Connection status */}
        <div
          className={`w-1.5 h-1.5 rounded-full ml-2 ${
            isConnected ? 'bg-blue-400' : 'bg-yellow-400'
          }`}
        />

        {/* AI thinking indicator */}
        {isAnswering && (
          <span className="text-xs text-blue-300 animate-pulse ml-2">
            AI...
          </span>
        )}
      </div>

      <span className="text-[10px] text-white/30 no-drag select-none">
        Axel
      </span>
    </Interactable>
  )
}

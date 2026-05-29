'use client'

import { useEffect, useRef, useState } from 'react'

interface TimerBarProps {
  examStartMs: number
  examDurationMs: number
  onExpire: () => void
  onWarning?: () => void
}

export default function TimerBar({ examStartMs, examDurationMs, onExpire, onWarning }: TimerBarProps) {
  const [msRemaining, setMsRemaining] = useState(() =>
    Math.max(0, examDurationMs - (Date.now() - examStartMs))
  )
  const warningFiredRef = useRef(false)

  useEffect(() => {
    if (examStartMs === 0) return
    const interval = setInterval(() => {
      const remaining = Math.max(0, examDurationMs - (Date.now() - examStartMs))
      setMsRemaining(remaining)

      if (remaining <= 3 * 60 * 1000 && remaining > 0 && !warningFiredRef.current) {
        warningFiredRef.current = true
        onWarning?.()
      }

      if (remaining === 0) {
        clearInterval(interval)
        onExpire()
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [examStartMs, examDurationMs, onExpire, onWarning])

  const totalSeconds = Math.ceil(msRemaining / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  const formatted = `${minutes}:${seconds.toString().padStart(2, '0')}`
  const isWarning = msRemaining < 5 * 60 * 1000 && msRemaining > 0
  const isCritical = msRemaining < 60 * 1000 && msRemaining > 0

  return (
    <div className="flex items-center gap-1.5">
      <span className={`text-xs ${isWarning ? 'text-rose-400' : 'text-slate-400'}`}>⏱</span>
      <span className={`font-mono text-sm tabular-nums ${
        isCritical ? 'text-rose-500 font-bold animate-pulse' :
        isWarning  ? 'text-rose-500 font-bold' :
                     'text-slate-500 font-semibold'
      }`}>
        {formatted}
      </span>
      <span className={`text-xs ${isWarning ? 'text-rose-400' : 'text-slate-400'}`}>remaining</span>
    </div>
  )
}

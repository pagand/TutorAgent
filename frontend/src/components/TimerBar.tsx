'use client'

import { useEffect, useState } from 'react'

interface TimerBarProps {
  examStartMs: number
  examDurationMs: number
  onExpire: () => void
}

export default function TimerBar({ examStartMs, examDurationMs, onExpire }: TimerBarProps) {
  const [msRemaining, setMsRemaining] = useState(() =>
    Math.max(0, examDurationMs - (Date.now() - examStartMs))
  )

  useEffect(() => {
    if (examStartMs === 0) return
    const interval = setInterval(() => {
      const remaining = Math.max(0, examDurationMs - (Date.now() - examStartMs))
      setMsRemaining(remaining)
      if (remaining === 0) {
        clearInterval(interval)
        onExpire()
      }
    }, 1000)
    return () => clearInterval(interval)
  }, [examStartMs, examDurationMs, onExpire])

  const totalSeconds = Math.ceil(msRemaining / 1000)
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  const formatted = `${minutes}:${seconds.toString().padStart(2, '0')}`
  const isWarning = msRemaining < 5 * 60 * 1000 && msRemaining > 0

  return (
    <span className={`font-mono text-sm font-semibold tabular-nums ${isWarning ? 'text-rose-500 font-bold' : 'text-slate-500'}`}>
      {formatted}
    </span>
  )
}

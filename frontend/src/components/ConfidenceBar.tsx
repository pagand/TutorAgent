'use client'

import { useEffect, useState } from 'react'

const LEVELS = Array.from({ length: 10 }, (_, i) => i + 1)

export default function ConfidenceBar({
  value,
  onSelect,
  showError,
}: {
  value: number | null
  onSelect: (level: number) => void
  showError: boolean
}) {
  const [hoverLevel, setHoverLevel] = useState(0)
  const displayLevel = hoverLevel || value || 0

  // A click that never produces a mouseleave (keyboard, or a submit without
  // moving the pointer off the bar) would otherwise leave the old fill on
  // screen after the parent resets the value for the next attempt.
  useEffect(() => {
    if (value === null) setHoverLevel(0)
  }, [value])

  return (
    <div
      className={[
        'mt-4 p-3 rounded-lg border transition-colors',
        showError ? 'border-rose-500 bg-rose-50 confidence-bar-shake' : 'border-slate-200',
      ].join(' ')}
    >
      <div className="flex items-center justify-between mb-2">
        <p className={`text-xs font-medium ${showError ? 'text-rose-600' : 'text-slate-600'}`}>How confident are you?</p>
        {value !== null && <span className="text-xs text-slate-400">{value}/10</span>}
      </div>
      <div className="flex items-center gap-2">
        <span className="hidden sm:block text-[10px] text-slate-400 shrink-0">guessing</span>
        <div className="flex gap-1 flex-1" onMouseLeave={() => setHoverLevel(0)}>
          {LEVELS.map((level) => (
            <button
              key={level}
              type="button"
              onClick={() => onSelect(level)}
              onMouseEnter={() => setHoverLevel(level)}
              aria-label={`Confidence ${level} of 10`}
              className={[
                'h-7 sm:h-5 flex-1 rounded-sm transition-colors',
                level <= displayLevel ? 'bg-indigo-600' : 'bg-slate-200',
              ].join(' ')}
            />
          ))}
        </div>
        <span className="hidden sm:block text-[10px] text-slate-400 shrink-0">certain</span>
      </div>
      <div className="flex justify-between mt-1 sm:hidden">
        <span className="text-[10px] text-slate-400">guessing</span>
        <span className="text-[10px] text-slate-400">certain</span>
      </div>
    </div>
  )
}

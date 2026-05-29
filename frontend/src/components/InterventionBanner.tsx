'use client'

interface InterventionBannerProps {
  onAccept: () => void
  onDismiss: () => void
  reason?: string | null
}

const REASON_MESSAGES: Record<string, string> = {
  time_spent: "You've been on this question for a while. A hint might help you move forward.",
  low_mastery: "This topic seems challenging. A hint could help you get started.",
  consecutive_errors: "A few incorrect attempts so far. Want some guidance on the right approach?",
  consecutive_skips: "You've skipped a few questions on this topic. A hint could help you tackle this one.",
}

export default function InterventionBanner({ onAccept, onDismiss, reason }: InterventionBannerProps) {
  const message = (reason && REASON_MESSAGES[reason]) || "Need some help? A hint is available for this question."

  return (
    <div className="p-4 bg-amber-50 border border-amber-300 rounded-lg">
      <p className="text-sm text-amber-800 mb-3">{message}</p>
      <div className="flex gap-2">
        <button
          onClick={onAccept}
          className="px-3 py-1.5 text-xs font-semibold text-white bg-indigo-600 rounded hover:bg-indigo-700"
        >
          Get hint
        </button>
        <button
          onClick={onDismiss}
          className="px-3 py-1.5 text-xs font-semibold text-slate-600 bg-white border border-slate-300 rounded hover:bg-slate-50"
        >
          No thanks
        </button>
      </div>
    </div>
  )
}

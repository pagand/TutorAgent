'use client'

interface InterventionBannerProps {
  onAccept: () => void
  onDismiss: () => void
}

export default function InterventionBanner({ onAccept, onDismiss }: InterventionBannerProps) {
  return (
    <div className="mt-4 p-4 bg-amber-50 border border-amber-300 rounded-lg flex items-center justify-between gap-4">
      <p className="text-sm text-amber-800">
        Looks like you&apos;ve been on this a while. Want a hint?
      </p>
      <div className="flex gap-2 shrink-0">
        <button
          onClick={onAccept}
          className="px-3 py-1.5 text-xs font-semibold text-white bg-indigo-600 rounded hover:bg-indigo-700"
        >
          Yes
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

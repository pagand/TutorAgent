'use client'

import { useQuiz } from '@/context/QuizContext'

interface HintPanelProps {
  isLoading: boolean
  onRequestHint: () => void
  disabled?: boolean
}

export default function HintPanel({ isLoading, onRequestHint, disabled }: HintPanelProps) {
  const { state } = useQuiz()
  const { hints, questions, currentQuestionIndex } = state
  const currentQNum = questions[currentQuestionIndex]?.question_number
  const activeHint = currentQNum !== undefined ? (hints[currentQNum] ?? null) : null

  return (
    <div className="mt-3">
      {!activeHint && (
        <button
          onClick={onRequestHint}
          disabled={isLoading || disabled}
          className="text-sm text-indigo-600 hover:text-indigo-800 disabled:text-slate-400 disabled:cursor-not-allowed font-medium"
        >
          {isLoading ? 'Getting hint…' : 'Get Hint'}
        </button>
      )}

      {activeHint && (
        <div className="p-4 border-l-4 border-indigo-400 bg-indigo-50 rounded-r-lg">
          <div className="flex items-center gap-2 mb-1">
            <span className="text-xs font-semibold text-indigo-700 uppercase tracking-wide">Hint</span>
            <span className="text-xs text-indigo-500 bg-indigo-100 px-2 py-0.5 rounded-full">
              {activeHint.hint_style}
            </span>
          </div>
          <p className="text-sm text-indigo-900 leading-relaxed">{activeHint.hint}</p>
        </div>
      )}
    </div>
  )
}

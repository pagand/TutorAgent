'use client'

import { useQuiz } from '@/context/QuizContext'

interface ResultBannerProps {
  questionNumber: number
  onNext?: () => void
}

export default function ResultBanner({ questionNumber, onNext }: ResultBannerProps) {
  const { state } = useQuiz()
  const status = state.questionStates[questionNumber]

  if (!status || status === 'unanswered') return null

  let message: string
  let style: string

  switch (status) {
    case 'correct':
      message = '✓ Correct!'
      style = 'bg-emerald-50 border-emerald-300 text-emerald-800'
      break
    case 'wrong_1':
      message = '✗ Incorrect — 1 attempt remaining'
      style = 'bg-amber-50 border-amber-300 text-amber-800'
      break
    case 'wrong_2':
      message = '✗ Locked — Move on to the next question'
      style = 'bg-rose-50 border-rose-300 text-rose-800'
      break
    case 'skipped':
      message = 'Question skipped — you can return to it later'
      style = 'bg-slate-100 border-slate-300 text-slate-700'
      break
    default:
      return null
  }

  return (
    <div className={`mt-4 p-3 border rounded-lg ${style}`}>
      <p className="text-sm font-medium">{message}</p>
      {onNext && (
        <button
          onClick={onNext}
          className="mt-1 text-xs font-semibold text-indigo-600 hover:text-indigo-800"
        >
          Next question →
        </button>
      )}
    </div>
  )
}

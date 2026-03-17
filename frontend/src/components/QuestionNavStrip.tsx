'use client'

import { useQuiz } from '@/context/QuizContext'
import type { QuestionStatus } from '@/types'

const statusStyle: Record<QuestionStatus, string> = {
  unanswered: 'bg-slate-200 text-slate-400',
  skipped: 'bg-amber-400 text-white hover:bg-amber-500',
  wrong_1: 'bg-orange-400 text-white hover:bg-orange-500',
  correct: 'bg-emerald-500 text-white hover:bg-emerald-600',
  wrong_2: 'bg-rose-500 text-white hover:bg-rose-600',
}

interface QuestionNavStripProps {
  onNavigate?: (index: number) => void
}

export default function QuestionNavStrip({ onNavigate }: QuestionNavStripProps) {
  const { state, dispatch } = useQuiz()
  const { questions, questionStates, currentQuestionIndex, highestReachedIndex } = state

  const handleClick = (index: number) => {
    if (onNavigate) {
      onNavigate(index)
    } else {
      dispatch({ type: 'NAVIGATE_TO', index })
    }
  }

  return (
    <div className="flex flex-wrap gap-1 px-4 py-2 bg-white border-b border-slate-200">
      {questions.map((q, index) => {
        const status = questionStates[q.question_number] || 'unanswered'
        const isAccessible = index <= highestReachedIndex
        const isCurrent = index === currentQuestionIndex

        return (
          <button
            key={q.question_number}
            disabled={!isAccessible}
            onClick={() => isAccessible && handleClick(index)}
            title={`Q${q.question_number}: ${status}`}
            className={[
              'w-8 h-8 rounded text-xs font-semibold flex items-center justify-center transition-colors',
              isAccessible ? statusStyle[status] : 'bg-slate-200 text-slate-300 cursor-not-allowed',
              isCurrent ? 'ring-2 ring-indigo-600 ring-offset-1' : '',
            ].join(' ')}
          >
            {q.question_number}
          </button>
        )
      })}
    </div>
  )
}

'use client'

import { useState } from 'react'
import { useQuiz } from '@/context/QuizContext'

export default function FeedbackBar() {
  const { state, dispatch } = useQuiz()
  const { hints, pendingRatings, questions, currentQuestionIndex } = state
  const currentQNum = questions[currentQuestionIndex]?.question_number
  const activeHint = currentQNum !== undefined ? (hints[currentQNum] ?? null) : null
  const pendingRating = currentQNum !== undefined ? (pendingRatings[currentQNum] ?? null) : null
  const [hoverRating, setHoverRating] = useState(0)

  if (!activeHint) return null

  const displayRating = hoverRating || pendingRating || 0

  return (
    <div className="mt-3 p-3 bg-slate-50 border border-slate-200 rounded-lg">
      <p className="text-xs text-slate-500 mb-2">Was this hint helpful? (optional)</p>
      <div className="flex gap-1 items-center">
        {[1, 2, 3, 4, 5].map((star) => (
          <button
            key={star}
            onClick={() => currentQNum !== undefined && dispatch({ type: 'SET_RATING', questionNumber: currentQNum, rating: star })}
            onMouseEnter={() => setHoverRating(star)}
            onMouseLeave={() => setHoverRating(0)}
            className={`text-2xl transition-colors leading-none ${
              star <= displayRating ? 'text-amber-400' : 'text-slate-300'
            }`}
          >
            ★
          </button>
        ))}
        {pendingRating !== null && (
          <span className="ml-1 text-xs text-slate-400">{pendingRating}/5</span>
        )}
      </div>
    </div>
  )
}

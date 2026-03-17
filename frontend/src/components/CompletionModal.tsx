'use client'

import { useQuiz } from '@/context/QuizContext'

interface CompletionModalProps {
  triggeredByTimer?: boolean
}

export default function CompletionModal({ triggeredByTimer }: CompletionModalProps) {
  const { state } = useQuiz()
  const { questions, questionStates, correctAnswers, userAnswers } = state

  // Classify each question for scoring
  const totalQuestions = questions.length
  const totalCorrect = questions.filter(q => questionStates[q.question_number] === 'correct').length
  // Attempted = user submitted at least one answer (correct, wrong_1, wrong_2)
  const totalAttempted = questions.filter(q => {
    const s = questionStates[q.question_number]
    return s === 'correct' || s === 'wrong_1' || s === 'wrong_2'
  }).length
  const engagementRate = totalQuestions > 0 ? totalAttempted / totalQuestions : 0
  const accuracy = totalAttempted > 0 ? totalCorrect / totalAttempted : 0

  // Skill scores (wrong_1 counts as wrong — not correct)
  const skillScores: Record<string, { correct: number; total: number }> = {}
  for (const q of questions) {
    const skill = q.skill
    if (!skillScores[skill]) skillScores[skill] = { correct: 0, total: 0 }
    skillScores[skill].total++
    if (questionStates[q.question_number] === 'correct') {
      skillScores[skill].correct++
    }
  }

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50 p-4">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-2xl max-h-[90vh] overflow-y-auto">
        <div className="p-6">
          <h2 className="text-2xl font-bold text-slate-900 mb-1">
            {triggeredByTimer ? '⏱ Time\'s up!' : '✓ Quiz Complete!'}
          </h2>
          <p className="text-slate-500 text-sm mb-6">
            You answered {totalCorrect} of {totalQuestions} questions correctly.
          </p>

          {/* Summary metrics */}
          <div className="grid grid-cols-3 gap-3 mb-6">
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-indigo-600">
                {totalQuestions > 0 ? Math.round((totalCorrect / totalQuestions) * 100) : 0}%
              </p>
              <p className="text-xs text-slate-500 mt-1">Final Score</p>
              <p className="text-xs text-slate-400">{totalCorrect}/{totalQuestions} correct</p>
            </div>
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-emerald-600">
                {Math.round(engagementRate * 100)}%
              </p>
              <p className="text-xs text-slate-500 mt-1">Engagement</p>
              <p className="text-xs text-slate-400">{totalAttempted}/{totalQuestions} attempted</p>
            </div>
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-amber-600">
                {Math.round(accuracy * 100)}%
              </p>
              <p className="text-xs text-slate-500 mt-1">Accuracy</p>
              <p className="text-xs text-slate-400">of attempted Qs</p>
            </div>
          </div>

          {/* Score by skill */}
          <div className="mb-6">
            <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
              Score by Skill
            </h3>
            <div className="space-y-2">
              {Object.entries(skillScores).map(([skill, score]) => (
                <div key={skill} className="flex items-center gap-3">
                  <span className="text-sm text-slate-700 w-48 truncate">{skill}</span>
                  <div className="flex-1 h-2 bg-slate-200 rounded-full overflow-hidden">
                    <div
                      className="h-full bg-indigo-500 rounded-full"
                      style={{ width: `${score.total ? (score.correct / score.total) * 100 : 0}%` }}
                    />
                  </div>
                  <span className="text-xs text-slate-500 w-12 text-right">
                    {score.correct}/{score.total}
                  </span>
                </div>
              ))}
            </div>
          </div>

          {/* Answer review */}
          <div>
            <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">
              Answer Review
            </h3>
            <div className="space-y-3">
              {questions.map((q) => {
                const status = questionStates[q.question_number]
                const correct = correctAnswers[q.question_number]
                const userAns = userAnswers[q.question_number]

                let statusBadge: string
                let badgeStyle: string
                if (status === 'correct') {
                  statusBadge = 'Correct'
                  badgeStyle = 'bg-emerald-100 text-emerald-700'
                } else if (status === 'wrong_2' || status === 'wrong_1') {
                  statusBadge = 'Incorrect'
                  badgeStyle = 'bg-rose-100 text-rose-700'
                } else if (status === 'skipped') {
                  statusBadge = 'Skipped'
                  badgeStyle = 'bg-amber-100 text-amber-700'
                } else {
                  statusBadge = 'Not attempted'
                  badgeStyle = 'bg-slate-100 text-slate-500'
                }

                return (
                  <div key={q.question_number} className="p-3 border border-slate-200 rounded-lg">
                    <div className="flex items-start justify-between gap-2 mb-1">
                      <span className="text-sm font-medium text-slate-800">
                        Q{q.question_number}. {q.question}
                      </span>
                      <span className={`text-xs font-semibold px-2 py-0.5 rounded-full shrink-0 ${badgeStyle}`}>
                        {statusBadge}
                      </span>
                    </div>
                    {userAns && status !== 'correct' && (
                      <p className="text-xs text-slate-500">Your answer: {userAns}</p>
                    )}
                    {correct && status !== 'correct' && (
                      <p className="text-xs text-emerald-700 font-medium">Correct answer: {correct}</p>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

'use client'

import { useQuiz } from '@/context/QuizContext'

interface CompletionModalProps {
  triggeredByTimer?: boolean
}

export default function CompletionModal({ triggeredByTimer }: CompletionModalProps) {
  const { state } = useQuiz()
  const { questions, questionStates, correctAnswers, userAnswers, retryCount } = state

  const totalQuestions = questions.length

  // Unique questions answered correctly (each question counted once)
  const totalCorrect = questions.filter(q => questionStates[q.question_number] === 'correct').length

  // Total answer submission events across all questions (each submit = 1 event, skips excluded)
  // retryCount[q] tracks how many times the user submitted an answer for question q
  const totalSubmissions = questions.reduce((sum, q) => sum + (retryCount[q.question_number] || 0), 0)

  // Total skipped questions (active decision to defer — a distinct effort event)
  const totalSkipped = questions.filter(q => questionStates[q.question_number] === 'skipped').length

  // Questions the student actually saw (non-unanswered = reached in the exam flow)
  const totalExposed = questions.filter(q => {
    const s = questionStates[q.question_number]
    return s !== undefined && s !== 'unanswered'
  }).length

  /**
   * Grade = unique questions correct / total questions (official exam score)
   * Counts every question — penalizes both wrong answers and unreached questions.
   */
  const grade = totalQuestions > 0 ? totalCorrect / totalQuestions : 0

  /**
   * Accuracy = correct answers / total submission events (skips excluded)
   * Measures answer quality: a student who answered wrong twice before getting it right
   * scores lower than one who answered correctly on the first try.
   * Formula from spec: Correct Answers / Total Answer Events
   */
  const accuracy = totalSubmissions > 0 ? totalCorrect / totalSubmissions : 0

  /**
   * Efficiency = correct answers / total effort events (submissions + skips)
   * Penalizes wasted effort — skips count as an effort unit alongside wrong answers.
   * A system that guides students to correct answers with less wasted effort scores higher.
   * Formula from spec: Total Correct / Total Attempt Events (ANSWER + SKIP)
   */
  const totalEffortEvents = totalSubmissions + totalSkipped
  const efficiency = totalEffortEvents > 0 ? totalCorrect / totalEffortEvents : 0

  /**
   * Coverage = questions reached / total questions
   * Measures exam progress — separates time-limited students from low performers.
   * A student who ran out of time at Q15 may have high accuracy on Q1–Q15.
   */
  const coverage = totalQuestions > 0 ? totalExposed / totalQuestions : 0

  // Skill scores (correct per skill out of total questions in that skill)
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
            {totalCorrect}/{totalQuestions} correct · {totalSubmissions} answer events · {totalSkipped} skipped · {totalExposed}/{totalQuestions} reached
          </p>

          {/* 4 core metrics */}
          <div className="grid grid-cols-2 gap-3 mb-6">
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-indigo-600">
                {Math.round(grade * 100)}%
              </p>
              <p className="text-xs font-semibold text-slate-600 mt-1">Grade</p>
              <p className="text-xs text-slate-400">{totalCorrect}/{totalQuestions} correct</p>
            </div>
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-emerald-600">
                {Math.round(accuracy * 100)}%
              </p>
              <p className="text-xs font-semibold text-slate-600 mt-1">Accuracy</p>
              <p className="text-xs text-slate-400">{totalCorrect}/{totalSubmissions} answer events</p>
            </div>
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-amber-600">
                {Math.round(efficiency * 100)}%
              </p>
              <p className="text-xs font-semibold text-slate-600 mt-1">Efficiency</p>
              <p className="text-xs text-slate-400">{totalCorrect}/{totalEffortEvents} effort events</p>
            </div>
            <div className="bg-slate-50 rounded-lg p-3 text-center">
              <p className="text-2xl font-bold text-slate-600">
                {Math.round(coverage * 100)}%
              </p>
              <p className="text-xs font-semibold text-slate-600 mt-1">Coverage</p>
              <p className="text-xs text-slate-400">{totalExposed}/{totalQuestions} questions reached</p>
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
                const attempts = retryCount[q.question_number] || 0

                let statusBadge: string
                let badgeStyle: string
                if (status === 'correct') {
                  statusBadge = attempts > 1 ? `Correct (${attempts} tries)` : 'Correct'
                  badgeStyle = 'bg-emerald-100 text-emerald-700'
                } else if (status === 'wrong_2' || status === 'wrong_1') {
                  statusBadge = 'Incorrect'
                  badgeStyle = 'bg-rose-100 text-rose-700'
                } else if (status === 'skipped') {
                  statusBadge = 'Skipped'
                  badgeStyle = 'bg-amber-100 text-amber-700'
                } else {
                  statusBadge = 'Not reached'
                  badgeStyle = 'bg-slate-100 text-slate-400'
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

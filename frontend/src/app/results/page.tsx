'use client'

import { useEffect, useState } from 'react'
import { useRouter } from 'next/navigation'
import { getUserProfile, getQuestions } from '@/services/apiClient'
import type { Question, QuestionStatus } from '@/types'

interface ExamResults {
  questions: Question[]
  questionStates: Record<number, QuestionStatus>
  correctAnswers: Record<number, string>
  userAnswers: Record<number, string>
  retryCount: Record<number, number>
  triggeredByTimer: boolean
}

async function fetchCorrectAnswers(userId: string, sessionId?: string): Promise<Record<number, string>> {
  const profile = await getUserProfile(userId, sessionId)
  const correctAnswers: Record<number, string> = {}
  for (const [k, v] of Object.entries(profile.completed_answers)) correctAnswers[Number(k)] = v
  return correctAnswers
}

async function fetchResultsFromBackend(userId: string, sessionId?: string): Promise<ExamResults | null> {
  try {
    const [qs, profile] = await Promise.all([getQuestions(userId), getUserProfile(userId, sessionId)])
    const questionStates: Record<number, QuestionStatus> = {}
    const retryCount: Record<number, number> = {}
    const userAnswers: Record<number, string> = {}

    for (const q of qs) questionStates[q.question_number] = 'unanswered'

    const logsByQ: Record<number, typeof profile.interaction_history> = {}
    for (const log of profile.interaction_history) {
      if (!logsByQ[log.question_id]) logsByQ[log.question_id] = []
      logsByQ[log.question_id].push(log)
    }
    for (const [qidStr, logs] of Object.entries(logsByQ)) {
      const qid = Number(qidStr)
      const real = logs.filter(l => l.user_answer !== null)
      const anyCorrect = real.some(l => l.is_correct)
      if (anyCorrect) {
        questionStates[qid] = 'correct'
        retryCount[qid] = real.length
        const c = real.find(l => l.is_correct)
        if (c?.user_answer) userAnswers[qid] = c.user_answer
      } else if (real.length >= 2) {
        questionStates[qid] = 'wrong_2'; retryCount[qid] = 2
        const last = real[real.length - 1]
        if (last.user_answer) userAnswers[qid] = last.user_answer
      } else if (real.length === 1) {
        questionStates[qid] = 'wrong_1'; retryCount[qid] = 1
        if (real[0].user_answer) userAnswers[qid] = real[0].user_answer
      } else {
        questionStates[qid] = 'skipped'; retryCount[qid] = 0
      }
    }
    const correctAnswers: Record<number, string> = {}
    for (const [k, v] of Object.entries(profile.completed_answers)) correctAnswers[Number(k)] = v
    return { questions: qs, questionStates, correctAnswers, userAnswers, retryCount, triggeredByTimer: false }
  } catch {
    return null
  }
}

export default function ResultsPage() {
  const router = useRouter()
  const [results, setResults] = useState<ExamResults | null>(null)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    async function load() {
      // Fast path: fresh from quiz session
      try {
        const raw = localStorage.getItem('examResults')
        if (raw) {
          const parsed: ExamResults = JSON.parse(raw)
          setResults(parsed)

          // correctAnswers is never populated by the quiz session itself
          // (POST /answer/ deliberately never returns it) — backfill it here
          // from GET /users/{id}/profile without blocking the initial render.
          const hasGraded = Object.values(parsed.questionStates).some(
            (s) => s === 'correct' || s === 'wrong_2'
          )
          if (hasGraded && Object.keys(parsed.correctAnswers).length === 0) {
            const userId = localStorage.getItem('userId')
            if (userId) {
              try {
                const correctAnswers = await fetchCorrectAnswers(userId, localStorage.getItem('sessionId') || undefined)
                setResults((prev) => (prev ? { ...prev, correctAnswers } : prev))
              } catch { /* leave the answer key blank rather than block the page */ }
            }
          }
          return
        }
      } catch { /* ignore parse error, fall through */ }

      // Slow path: arriving from login with a completed token
      const userId = localStorage.getItem('userId')
      if (!userId) { router.replace('/login'); return }
      const fetched = await fetchResultsFromBackend(userId, localStorage.getItem('sessionId') || undefined)
      if (fetched) {
        setResults(fetched)
      } else {
        setLoadError(true)
      }
    }
    load()
  }, [router])

  if (loadError) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-3">
        <p className="text-rose-600 text-sm">Could not load results. Please try again.</p>
        <button onClick={() => router.replace('/login')} className="text-sm text-indigo-600 hover:text-indigo-800">← Back to login</button>
      </div>
    )
  }

  if (!results) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4">
        <div className="w-10 h-10 rounded-full border-4 border-slate-200 border-t-indigo-600 animate-spin" />
        <p className="text-slate-500 text-sm">Loading results…</p>
      </div>
    )
  }

  const { questions, questionStates, correctAnswers, userAnswers, retryCount, triggeredByTimer } = results

  const totalQuestions = questions.length
  const totalCorrect = questions.filter(q => questionStates[q.question_number] === 'correct').length
  const totalSubmissions = questions.reduce((sum, q) => sum + (retryCount[q.question_number] || 0), 0)
  const totalSkipped = questions.filter(q => questionStates[q.question_number] === 'skipped').length
  const totalExposed = questions.filter(q => {
    const s = questionStates[q.question_number]
    return s !== undefined && s !== 'unanswered'
  }).length
  const totalEffortEvents = totalSubmissions + totalSkipped

  const grade = totalQuestions > 0 ? totalCorrect / totalQuestions : 0
  const accuracy = totalSubmissions > 0 ? totalCorrect / totalSubmissions : 0
  const efficiency = totalEffortEvents > 0 ? totalCorrect / totalEffortEvents : 0
  const coverage = totalQuestions > 0 ? totalExposed / totalQuestions : 0

  const skillScores: Record<string, { correct: number; total: number }> = {}
  for (const q of questions) {
    if (!skillScores[q.skill]) skillScores[q.skill] = { correct: 0, total: 0 }
    skillScores[q.skill].total++
    if (questionStates[q.question_number] === 'correct') skillScores[q.skill].correct++
  }

  return (
    <div className="min-h-screen bg-slate-50 py-8 px-4">
      <div className="max-w-2xl mx-auto">
        <div className="bg-white rounded-xl shadow-sm border border-slate-200">
          <div className="p-6">
            <h1 className="text-2xl font-bold text-slate-900 mb-1">
              {triggeredByTimer ? '⏱ Time\'s up!' : '✓ Exam Complete!'}
            </h1>
            <p className="text-slate-500 text-sm mb-6">
              {totalCorrect}/{totalQuestions} correct · {totalSubmissions} answer events · {totalSkipped} skipped · {totalExposed}/{totalQuestions} reached
            </p>

            <div className="grid grid-cols-2 gap-3 mb-6">
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-indigo-600">{Math.round(grade * 100)}%</p>
                <p className="text-xs font-semibold text-slate-600 mt-1">Grade</p>
                <p className="text-xs text-slate-400">{totalCorrect}/{totalQuestions} correct</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-emerald-600">{Math.round(accuracy * 100)}%</p>
                <p className="text-xs font-semibold text-slate-600 mt-1">Accuracy</p>
                <p className="text-xs text-slate-400">{totalCorrect}/{totalSubmissions} answer events</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-amber-600">{Math.round(efficiency * 100)}%</p>
                <p className="text-xs font-semibold text-slate-600 mt-1">Efficiency</p>
                <p className="text-xs text-slate-400">{totalCorrect}/{totalEffortEvents} effort events</p>
              </div>
              <div className="bg-slate-50 rounded-lg p-3 text-center">
                <p className="text-2xl font-bold text-slate-600">{Math.round(coverage * 100)}%</p>
                <p className="text-xs font-semibold text-slate-600 mt-1">Coverage</p>
                <p className="text-xs text-slate-400">{totalExposed}/{totalQuestions} questions reached</p>
              </div>
            </div>

            <div className="mb-6">
              <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">Score by Skill</h3>
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
                    <span className="text-xs text-slate-500 w-12 text-right">{score.correct}/{score.total}</span>
                  </div>
                ))}
              </div>
            </div>

            <div className="mb-8">
              <h3 className="text-sm font-semibold text-slate-700 uppercase tracking-wide mb-3">Answer Review</h3>
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
                        <span className="text-sm font-medium text-slate-800">Q{q.question_number}. {q.question}</span>
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

            <div className="text-center">
              <button
                onClick={() => router.replace('/login')}
                className="text-sm text-indigo-600 hover:text-indigo-800 font-medium"
              >
                ← Return to login
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

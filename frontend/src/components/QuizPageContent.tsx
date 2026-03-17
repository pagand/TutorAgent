'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useQuiz } from '@/context/QuizContext'
import {
  getQuestions, startSession, getHint, submitAnswer,
  checkIntervention, logAction, logIntervention,
} from '@/services/apiClient'
import TimerBar from './TimerBar'
import QuestionNavStrip from './QuestionNavStrip'
import AnswerInput from './AnswerInput'
import HintDisplay from './HintDisplay'
import FeedbackBar from './FeedbackBar'
import ResultBanner from './ResultBanner'
import InterventionBanner from './InterventionBanner'
import ChatPanel from './ChatPanel'
import CompletionModal from './CompletionModal'

function generateSessionId(): string {
  return `sess_${Date.now()}_${Math.random().toString(36).slice(2, 9)}`
}

export default function QuizPageContent() {
  const router = useRouter()
  const { state, dispatch } = useQuiz()
  const {
    userId, sessionId, questions, questionStates, currentQuestionIndex,
    examStartMs, examDurationMs, hints, pendingRatings,
    isComplete, draftAnswers, userAnswers,
  } = state

  const currentQNum = questions[currentQuestionIndex]?.question_number
  const activeHint = currentQNum !== undefined ? (hints[currentQNum] ?? null) : null
  const pendingRating = currentQNum !== undefined ? (pendingRatings[currentQNum] ?? null) : null

  const [loadError, setLoadError] = useState<string | null>(null)
  const [initializing, setInitializing] = useState(true)

  const [userAnswer, setUserAnswerLocal] = useState('')
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [isSkipping, setIsSkipping] = useState(false)
  const [isHintLoading, setIsHintLoading] = useState(false)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [timerExpired, setTimerExpired] = useState(false)

  const [showIntervention, setShowIntervention] = useState(false)
  const [interventionDismissed, setInterventionDismissed] = useState(false)
  const [showSubmitConfirm, setShowSubmitConfirm] = useState(false)
  const questionStartTimeRef = useRef<Record<number, number>>({})
  const interventionIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const setUserAnswer = useCallback((val: string) => {
    setUserAnswerLocal(val)
    if (questions.length && currentQuestionIndex < questions.length) {
      const qNum = questions[currentQuestionIndex].question_number
      dispatch({ type: 'SET_DRAFT', questionNumber: qNum, answer: val })
    }
  }, [questions, currentQuestionIndex, dispatch])

  // Initialize
  useEffect(() => {
    const storedUserId = localStorage.getItem('userId')
    if (!storedUserId) { router.replace('/login'); return }

    if (state.userId === storedUserId && state.questions.length > 0) {
      setInitializing(false)
      return
    }

    const storedSessionId = localStorage.getItem('sessionId') || generateSessionId()
    localStorage.setItem('sessionId', storedSessionId)

    async function init() {
      try {
        const sessionData = await startSession(storedUserId!, storedSessionId)
        localStorage.setItem('examStartMs', String(sessionData.exam_start_ms))
        const qs = await getQuestions(storedUserId!)
        dispatch({
          type: 'LOAD_QUIZ',
          userId: storedUserId!,
          sessionId: storedSessionId,
          questions: qs,
          examStartMs: sessionData.exam_start_ms,
          examDurationMs: sessionData.exam_duration_ms,
        })
        logAction({ user_id: storedUserId!, session_id: storedSessionId, action_type: 'session_start' })
      } catch (err) {
        setLoadError('Failed to load quiz. Please refresh.')
        console.error(err)
      } finally {
        setInitializing(false)
      }
    }
    init()
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  // Log question_view + restore draft on navigation
  useEffect(() => {
    if (!questions.length) return
    const currentQ = questions[currentQuestionIndex]
    const draft = draftAnswers[currentQ.question_number] ?? ''
    setUserAnswerLocal(draft)
    setSubmitError(null)
    setShowIntervention(false)
    setInterventionDismissed(false)

    if (!questionStartTimeRef.current[currentQ.question_number]) {
      questionStartTimeRef.current[currentQ.question_number] = Date.now()
    }
    if (userId && sessionId) {
      logAction({
        user_id: userId, session_id: sessionId,
        action_type: 'question_view', question_number: currentQ.question_number,
        action_data: { status: questionStates[currentQ.question_number] || 'unanswered' },
      })
    }
  }, [currentQuestionIndex, questions]) // eslint-disable-line react-hooks/exhaustive-deps

  // Intervention polling
  useEffect(() => {
    if (!userId || !questions.length) return
    const currentQ = questions[currentQuestionIndex]
    if (!currentQ) return
    const status = questionStates[currentQ.question_number]
    if (status === 'correct' || status === 'wrong_2' || status === 'skipped') return
    if (activeHint) return

    if (interventionIntervalRef.current) clearInterval(interventionIntervalRef.current)

    interventionIntervalRef.current = setInterval(async () => {
      if (showIntervention || interventionDismissed || activeHint) return
      const startTime = questionStartTimeRef.current[currentQ.question_number] || Date.now()
      const timeSpentMs = Date.now() - startTime
      try {
        const result = await checkIntervention(userId, currentQ.question_number, timeSpentMs)
        if (result.intervention_needed) {
          setShowIntervention(true)
          logIntervention({
            user_id: userId, session_id: sessionId,
            question_number: currentQ.question_number,
            time_on_question_ms: timeSpentMs,
            accepted: undefined,
          })
        }
      } catch { /* non-critical */ }
    }, 15000)

    return () => { if (interventionIntervalRef.current) clearInterval(interventionIntervalRef.current) }
  }, [currentQuestionIndex, userId, questions, questionStates, activeHint, interventionDismissed, showIntervention]) // eslint-disable-line react-hooks/exhaustive-deps

  const handleRequestHint = useCallback(async () => {
    if (!userId || !questions.length) return
    const currentQ = questions[currentQuestionIndex]
    setIsHintLoading(true)
    setShowIntervention(false)
    logAction({
      user_id: userId, session_id: sessionId, action_type: 'hint_request',
      question_number: currentQ.question_number,
      action_data: { current_answer: userAnswer || null },
    })
    try {
      const hint = await getHint(userId, currentQ.question_number, userAnswer || undefined)
      dispatch({ type: 'SET_HINT', questionNumber: currentQ.question_number, hint: { hint: hint.hint, hint_style: hint.hint_style, pre_hint_mastery: hint.pre_hint_mastery } })
      logAction({
        user_id: userId, session_id: sessionId, action_type: 'hint_display',
        question_number: currentQ.question_number,
        action_data: { hint_style: hint.hint_style, pre_hint_mastery: hint.pre_hint_mastery },
      })
    } catch { /* non-fatal */ }
    finally { setIsHintLoading(false) }
  }, [userId, sessionId, questions, currentQuestionIndex, userAnswer, dispatch])

  const handleSubmit = async () => {
    if (!userId || !questions.length || !userAnswer) return
    const currentQ = questions[currentQuestionIndex]
    const startTime = questionStartTimeRef.current[currentQ.question_number] || Date.now()
    const timeTakenMs = Date.now() - startTime
    setIsSubmitting(true)
    setSubmitError(null)

    try {
      const payload: Parameters<typeof submitAnswer>[0] = {
        user_id: userId, question_number: currentQ.question_number,
        user_answer: userAnswer, time_taken_ms: timeTakenMs,
      }
      if (activeHint) {
        payload.hint_shown = true
        payload.hint_style_used = activeHint.hint_style
        payload.hint_text = activeHint.hint
        payload.pre_hint_mastery = activeHint.pre_hint_mastery
        if (pendingRating !== null) payload.feedback_rating = pendingRating
      }

      const result = await submitAnswer(payload)
      dispatch({
        type: 'SUBMIT_RESULT',
        questionNumber: currentQ.question_number,
        isCorrect: result.correct,
        correctAnswer: result.correct_answer,
        userAnswer,
      })
      setUserAnswerLocal('')
    } catch {
      setSubmitError('Failed to submit. Please try again.')
    } finally {
      setIsSubmitting(false)
    }
  }

  const handleSkip = async () => {
    if (!userId || !questions.length) return
    const currentQ = questions[currentQuestionIndex]
    const startTime = questionStartTimeRef.current[currentQ.question_number] || Date.now()
    const timeTakenMs = Date.now() - startTime
    setIsSkipping(true)
    try {
      const payload: Parameters<typeof submitAnswer>[0] = {
        user_id: userId, question_number: currentQ.question_number,
        skipped: true, time_taken_ms: timeTakenMs,
      }
      if (activeHint) {
        payload.hint_shown = true
        payload.hint_style_used = activeHint.hint_style
        payload.hint_text = activeHint.hint
        payload.pre_hint_mastery = activeHint.pre_hint_mastery
        if (pendingRating !== null) payload.feedback_rating = pendingRating
      }
      await submitAnswer(payload)
      dispatch({ type: 'SKIP_QUESTION' })
    } catch {
      setSubmitError('Failed to skip. Please try again.')
    } finally {
      setIsSkipping(false)
    }
  }

  const handleNavigateNext = useCallback(() => {
    let nextIndex = currentQuestionIndex + 1
    while (nextIndex < questions.length) {
      const s = questionStates[questions[nextIndex].question_number] || 'unanswered'
      if (s === 'unanswered' || s === 'wrong_1' || s === 'skipped') break
      nextIndex++
    }
    if (nextIndex < questions.length) {
      logAction({
        user_id: userId, session_id: sessionId, action_type: 'question_navigate',
        question_number: questions[nextIndex].question_number,
      })
      dispatch({ type: 'NAVIGATE_TO', index: nextIndex })
    }
  }, [currentQuestionIndex, questions, questionStates, userId, sessionId, dispatch])

  const handleNavStripNavigate = useCallback((index: number) => {
    if (!questions[index]) return
    logAction({
      user_id: userId, session_id: sessionId, action_type: 'question_navigate',
      question_number: questions[index].question_number,
      action_data: { from: questions[currentQuestionIndex]?.question_number },
    })
    dispatch({ type: 'NAVIGATE_TO', index })
  }, [userId, sessionId, questions, currentQuestionIndex, dispatch])

  const handleTimerExpire = useCallback(() => {
    setTimerExpired(true)
    dispatch({ type: 'COMPLETE' })
    if (userId && sessionId) {
      logAction({ user_id: userId, session_id: sessionId, action_type: 'timer_expired' })
    }
  }, [dispatch, userId, sessionId])

  const handleInterventionAccept = useCallback(() => {
    const currentQ = questions[currentQuestionIndex]
    const startTime = questionStartTimeRef.current[currentQ.question_number] || Date.now()
    logIntervention({
      user_id: userId, session_id: sessionId,
      question_number: currentQ.question_number,
      time_on_question_ms: Date.now() - startTime,
      accepted: true,
    })
    setShowIntervention(false)
    handleRequestHint()
  }, [userId, sessionId, questions, currentQuestionIndex, handleRequestHint])

  const handleEarlySubmit = useCallback(() => {
    dispatch({ type: 'COMPLETE' })
    setShowSubmitConfirm(false)
    if (userId && sessionId) {
      logAction({ user_id: userId, session_id: sessionId, action_type: 'session_complete',
        action_data: { triggered_by: 'early_submit' } })
    }
  }, [dispatch, userId, sessionId])

  const handleInterventionDismiss = useCallback(() => {
    const currentQ = questions[currentQuestionIndex]
    const startTime = questionStartTimeRef.current[currentQ.question_number] || Date.now()
    logIntervention({
      user_id: userId, session_id: sessionId,
      question_number: currentQ.question_number,
      time_on_question_ms: Date.now() - startTime,
      accepted: false,
    })
    setShowIntervention(false)
    setInterventionDismissed(true)
  }, [userId, sessionId, questions, currentQuestionIndex])

  if (initializing) {
    return <div className="min-h-screen bg-slate-50 flex items-center justify-center"><p className="text-slate-500 text-sm">Loading quiz…</p></div>
  }
  if (loadError) {
    return <div className="min-h-screen bg-slate-50 flex items-center justify-center"><p className="text-rose-600 text-sm">{loadError}</p></div>
  }
  if (!questions.length) return null

  const currentQ = questions[currentQuestionIndex]
  const currentStatus = questionStates[currentQ.question_number] || 'unanswered'
  const isReadOnly = currentStatus === 'correct' || currentStatus === 'wrong_2'
  const canSubmit = !isSubmitting && userAnswer.trim() !== ''
  const prevWrongAnswer = currentStatus === 'wrong_1' ? userAnswers[currentQ.question_number] : undefined
  const showBanner = currentStatus !== 'unanswered'
  const showNextBtn = (currentStatus === 'correct' || currentStatus === 'wrong_2') && currentQuestionIndex < questions.length - 1

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200 sticky top-0 z-10">
        <div className="max-w-3xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-sm font-semibold text-slate-800">AI Tutor</span>
            {examStartMs > 0 && (
              <TimerBar examStartMs={examStartMs} examDurationMs={examDurationMs} onExpire={handleTimerExpire} />
            )}
          </div>
          <div className="flex items-center gap-3">
            {!isComplete && !timerExpired && (
              <button
                onClick={() => setShowSubmitConfirm(true)}
                className="text-xs font-medium text-rose-600 hover:text-rose-800 border border-rose-200 hover:border-rose-400 px-3 py-1.5 rounded-lg transition-colors"
              >
                End Session
              </button>
            )}
            <Link href="/profile" className="text-xs text-indigo-600 hover:text-indigo-800 font-medium">Profile →</Link>
          </div>
        </div>
        <QuestionNavStrip onNavigate={handleNavStripNavigate} />
      </header>

      {showSubmitConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">End your session?</h3>
            <p className="text-sm text-slate-500 mb-6">
              You won&apos;t be able to continue. Your current answers will be recorded and results shown immediately.
            </p>
            <div className="flex gap-3 justify-end">
              <button
                onClick={() => setShowSubmitConfirm(false)}
                className="px-4 py-2 text-sm text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-50"
              >
                Cancel
              </button>
              <button
                onClick={handleEarlySubmit}
                className="px-4 py-2 text-sm font-medium text-white bg-rose-600 rounded-lg hover:bg-rose-700"
              >
                Yes, end session
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="max-w-3xl mx-auto px-4 py-6">
        <div className="bg-white rounded-xl border border-slate-200 p-6">
          <div className="flex items-center justify-between mb-4">
            <span className="text-xs font-semibold text-indigo-600 bg-indigo-50 px-2 py-1 rounded-full">{currentQ.skill}</span>
            <span className="text-xs text-slate-400">Q{currentQ.question_number} of {questions.length}</span>
          </div>

          <p className="text-slate-800 leading-relaxed mb-2">{currentQ.question}</p>

          {isReadOnly && (
            <p className="text-xs text-slate-400 mb-3 italic">
              {currentStatus === 'correct' ? 'Answered correctly — read only.' : 'This question is locked — read only.'}
            </p>
          )}

          <AnswerInput
            questionType={currentQ.question_type}
            options={currentQ.options}
            value={isReadOnly ? (userAnswers[currentQ.question_number] || '') : userAnswer}
            onChange={setUserAnswer}
            disabled={isReadOnly}
            wrongAnswer={prevWrongAnswer}
          />

          {!isReadOnly && (
            <div className="flex gap-3 mt-2">
              <button onClick={handleSkip} disabled={isSkipping || isSubmitting}
                className="px-4 py-2 text-sm text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-50 disabled:opacity-50 disabled:cursor-not-allowed">
                {isSkipping ? 'Skipping…' : 'Skip'}
              </button>
              <button onClick={handleSubmit} disabled={!canSubmit}
                className="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed">
                {isSubmitting ? 'Submitting…' : 'Submit Answer'}
              </button>
            </div>
          )}

          {submitError && <p className="mt-2 text-xs text-rose-600">{submitError}</p>}

          {!isReadOnly && (
            <>
              <HintDisplay isLoading={isHintLoading} onRequestHint={handleRequestHint} disabled={isSubmitting} />
              <FeedbackBar />
            </>
          )}

          {showBanner && (
            <ResultBanner questionNumber={currentQ.question_number} onNext={showNextBtn ? handleNavigateNext : undefined} />
          )}
        </div>

        {showIntervention && !isReadOnly && !activeHint && (
          <InterventionBanner onAccept={handleInterventionAccept} onDismiss={handleInterventionDismiss} />
        )}

        <ChatPanel />
      </main>

      {(isComplete || timerExpired) && <CompletionModal triggeredByTimer={timerExpired} />}
    </div>
  )
}

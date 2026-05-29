'use client'

import { useEffect, useState, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { useQuiz } from '@/context/QuizContext'
import {
  getQuestions, startSession, getHint, submitAnswer,
  checkIntervention, logAction, logIntervention, getUserProfile,
  sessionHeartbeat, submitSession,
} from '@/services/apiClient'
import type { QuestionStatus, HintData, ChatMessage } from '@/types'
import TimerBar from './TimerBar'
import QuestionNavStrip from './QuestionNavStrip'
import AnswerInput from './AnswerInput'
import HintDisplay from './HintDisplay'
import FeedbackBar from './FeedbackBar'
import ResultBanner from './ResultBanner'
import InterventionBanner from './InterventionBanner'
import ChatPanel from './ChatPanel'
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
  const [interventionReason, setInterventionReason] = useState<string | null>(null)
  const [showSubmitConfirm, setShowSubmitConfirm] = useState(false)
  const [showTimerWarning, setShowTimerWarning] = useState(false)
  const [showProfileBanner, setShowProfileBanner] = useState(false)
  const [takenOver, setTakenOver] = useState(false)
  const questionStartTimeRef = useRef<Record<number, number>>({})
  const interventionIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const heartbeatIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
  const initCalledRef = useRef(false)
  const hasRedirectedRef = useRef(false)
  const stateRef = useRef(state)
  const timerExpiredRef = useRef(false)
  useEffect(() => { stateRef.current = state }, [state])

  const saveAndRedirect = useCallback((byTimer: boolean) => {
    if (hasRedirectedRef.current) return
    hasRedirectedRef.current = true
    const s = stateRef.current
    const results = {
      questions: s.questions,
      questionStates: s.questionStates,
      correctAnswers: s.correctAnswers,
      userAnswers: s.userAnswers,
      retryCount: s.retryCount,
      triggeredByTimer: byTimer,
    }
    try { localStorage.setItem('examResults', JSON.stringify(results)) } catch { /* ignore */ }
    router.replace('/results')
  }, [router])

  // When all questions reach a final state, redirect to results page
  useEffect(() => {
    if (isComplete && !initializing) {
      saveAndRedirect(timerExpiredRef.current)
    }
  }, [isComplete, initializing, saveAndRedirect])

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

    if (initCalledRef.current) return
    initCalledRef.current = true

    const storedSessionId = localStorage.getItem('sessionId') || generateSessionId()
    localStorage.setItem('sessionId', storedSessionId)

    let isMounted = true

    async function init() {
      try {
        // 30-second timeout so a hanging API call surfaces as a retryable error
        const timeout = new Promise<never>((_, reject) =>
          setTimeout(() => reject(new Error('timeout')), 30000)
        )
        const [sessionData, qs, profile] = await Promise.race([
          Promise.all([
            startSession(storedUserId!, storedSessionId),
            getQuestions(storedUserId!),
            getUserProfile(storedUserId!),
          ]),
          timeout,
        ])
        if (!isMounted) return
        localStorage.setItem('examStartMs', String(sessionData.exam_start_ms))

        // Reconstruct question states from interaction history (needed for both active and expired paths)
        const logsByQuestion: Record<number, typeof profile.interaction_history> = {}
        for (const log of profile.interaction_history) {
          if (!logsByQuestion[log.question_id]) logsByQuestion[log.question_id] = []
          logsByQuestion[log.question_id].push(log)
        }

        const questionStates: Record<number, QuestionStatus> = {}
        const retryCount: Record<number, number> = {}
        const userAnswers: Record<number, string> = {}

        for (const [qidStr, logs] of Object.entries(logsByQuestion)) {
          const qid = Number(qidStr)
          const realAttempts = logs.filter(l => l.user_answer !== null)
          const anyCorrect = realAttempts.some(l => l.is_correct)

          if (anyCorrect) {
            questionStates[qid] = 'correct'
            retryCount[qid] = realAttempts.length
            const correctLog = realAttempts.find(l => l.is_correct)
            if (correctLog?.user_answer) userAnswers[qid] = correctLog.user_answer
          } else if (realAttempts.length >= 2) {
            questionStates[qid] = 'wrong_2'
            retryCount[qid] = 2
            const last = realAttempts[realAttempts.length - 1]
            if (last.user_answer) userAnswers[qid] = last.user_answer
          } else if (realAttempts.length === 1) {
            questionStates[qid] = 'wrong_1'
            retryCount[qid] = 1
            if (realAttempts[0].user_answer) userAnswers[qid] = realAttempts[0].user_answer
          } else {
            questionStates[qid] = 'skipped'
            retryCount[qid] = 0
          }
        }

        const correctAnswers: Record<number, string> = {}
        for (const [qidStr, ans] of Object.entries(profile.completed_answers)) {
          correctAnswers[Number(qidStr)] = ans
        }

        // If expired or already submitted on another device, redirect to /results immediately
        // — no quiz UI is shown at all, eliminating the brief-access window
        const isExpired = sessionData.ms_remaining === 0
        let isAlreadySubmitted = false
        if (!isExpired) {
          try {
            const hb = await sessionHeartbeat(storedUserId!, storedSessionId)
            if (isMounted && hb.submitted) isAlreadySubmitted = true
          } catch { /* non-fatal */ }
        }

        if ((isExpired || isAlreadySubmitted) && isMounted) {
          const allQStates: Record<number, QuestionStatus> = {}
          for (const q of qs) allQStates[q.question_number] = questionStates[q.question_number] ?? 'unanswered'
          const results = {
            questions: qs, questionStates: allQStates,
            correctAnswers, userAnswers, retryCount,
            triggeredByTimer: isExpired,
          }
          try { localStorage.setItem('examResults', JSON.stringify(results)) } catch { /* ignore */ }
          router.replace('/results')
          return
        }

        // Read cached hints/chat from localStorage to survive refresh
        let cachedHints: Record<number, HintData> = {}
        let cachedChat: ChatMessage[] = []
        try {
          const cached = localStorage.getItem(`quizCache_${storedUserId}`)
          if (cached) { const d = JSON.parse(cached); cachedHints = d.hints || {}; cachedChat = d.chatHistory || [] }
        } catch { /* ignore */ }

        dispatch({
          type: 'LOAD_QUIZ',
          userId: storedUserId!, sessionId: storedSessionId, questions: qs,
          examStartMs: sessionData.exam_start_ms, examDurationMs: sessionData.exam_duration_ms,
          cachedHints, cachedChat,
        })

        if (Object.keys(questionStates).length > 0) {
          dispatch({ type: 'RESTORE_STATE', questionStates, retryCount, userAnswers, correctAnswers })
        }

        // Periodic heartbeat: update lock, detect expiry/submission/takeover
        heartbeatIntervalRef.current = setInterval(async () => {
          const uid = localStorage.getItem('userId')
          const sid = localStorage.getItem('sessionId')
          if (!uid || !sid) return
          try {
            const hb = await sessionHeartbeat(uid, sid)
            if (!isMounted) return
            if (hb.submitted) { saveAndRedirect(false) }
            if (hb.expired) { timerExpiredRef.current = true; saveAndRedirect(true) }
            if (!hb.active) { setTakenOver(true) }
          } catch { /* ignore heartbeat errors silently */ }
        }, 25000)

        // Show profile banner for free_choice users who haven't customized their hint style
        const prefs = profile.preferences || {}
        if (prefs.ab_group === 'free_choice' && (!prefs.hint_style_preference || prefs.hint_style_preference === 'adaptive')) {
          setShowProfileBanner(true)
        }

        logAction({ user_id: storedUserId!, session_id: storedSessionId, action_type: 'session_start' })
      } catch (err) {
        if (!isMounted) return
        const msg = err instanceof Error && err.message === 'timeout'
          ? 'Loading timed out. Please check your connection and try again.'
          : 'Failed to load quiz. Please try again.'
        setLoadError(msg)
      } finally {
        if (isMounted) setInitializing(false)
      }
    }
    init()
    return () => {
      isMounted = false
      initCalledRef.current = false
      if (heartbeatIntervalRef.current) clearInterval(heartbeatIntervalRef.current)
    }
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
    setInterventionReason(null)

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
    if (status === 'correct' || status === 'wrong_2') return
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
          setInterventionReason(result.reason)
          logIntervention({
            user_id: userId, session_id: sessionId,
            question_number: currentQ.question_number,
            time_on_question_ms: timeSpentMs,
            reason: result.reason,
            accepted: undefined,
          })
          logAction({
            user_id: userId, session_id: sessionId, action_type: 'intervention_offer',
            question_number: currentQ.question_number,
            action_data: { reason: result.reason },
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
      logAction({
        user_id: userId, session_id: sessionId, action_type: 'answer_submit',
        question_number: currentQ.question_number,
        action_data: { is_correct: result.correct },
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
      logAction({
        user_id: userId, session_id: sessionId, action_type: 'answer_skip',
        question_number: currentQ.question_number,
      })
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
    timerExpiredRef.current = true
    if (userId) {
      submitSession(userId).catch(() => {})
      if (sessionId) logAction({ user_id: userId, session_id: sessionId, action_type: 'session_expire' })
    }
    saveAndRedirect(true)
  }, [userId, sessionId, saveAndRedirect])

  const handleTimerWarning = useCallback(() => {
    setShowTimerWarning(true)
    setTimeout(() => setShowTimerWarning(false), 5000)
    if (userId && sessionId) {
      logAction({ user_id: userId, session_id: sessionId, action_type: 'timer_warning' })
    }
  }, [userId, sessionId])

  const handleInterventionAccept = useCallback(() => {
    const currentQ = questions[currentQuestionIndex]
    const startTime = questionStartTimeRef.current[currentQ.question_number] || Date.now()
    logIntervention({
      user_id: userId, session_id: sessionId,
      question_number: currentQ.question_number,
      time_on_question_ms: Date.now() - startTime,
      accepted: true,
    })
    logAction({
      user_id: userId, session_id: sessionId, action_type: 'intervention_accept',
      question_number: currentQ.question_number,
    })
    setShowIntervention(false)
    handleRequestHint()
  }, [userId, sessionId, questions, currentQuestionIndex, handleRequestHint])

  const handleEarlySubmit = useCallback(() => {
    setShowSubmitConfirm(false)
    if (userId) {
      submitSession(userId).catch(() => {})
      if (sessionId) logAction({ user_id: userId, session_id: sessionId, action_type: 'session_submit' })
    }
    saveAndRedirect(false)
  }, [userId, sessionId, saveAndRedirect])

  const handleInterventionDismiss = useCallback(() => {
    const currentQ = questions[currentQuestionIndex]
    const startTime = questionStartTimeRef.current[currentQ.question_number] || Date.now()
    logIntervention({
      user_id: userId, session_id: sessionId,
      question_number: currentQ.question_number,
      time_on_question_ms: Date.now() - startTime,
      accepted: false,
    })
    logAction({
      user_id: userId, session_id: sessionId, action_type: 'intervention_reject',
      question_number: currentQ.question_number,
    })
    setShowIntervention(false)
    setInterventionDismissed(true)
  }, [userId, sessionId, questions, currentQuestionIndex])

  if (initializing) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-4">
        <div className="w-10 h-10 rounded-full border-4 border-slate-200 border-t-indigo-600 animate-spin" />
        <p className="text-slate-500 text-sm">Loading exam…</p>
      </div>
    )
  }
  if (loadError) {
    return (
      <div className="min-h-screen bg-slate-50 flex flex-col items-center justify-center gap-3">
        <p className="text-rose-600 text-sm font-medium">{loadError}</p>
        <button
          onClick={() => { initCalledRef.current = false; window.location.reload() }}
          className="px-4 py-2 text-sm bg-indigo-600 text-white rounded hover:bg-indigo-700"
        >
          Retry
        </button>
      </div>
    )
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
        <div className="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="text-sm font-bold text-slate-900">DaTu AIR</span>
            {examStartMs > 0 && !isComplete && !timerExpired && (
              <TimerBar examStartMs={examStartMs} examDurationMs={examDurationMs} onExpire={handleTimerExpire} onWarning={handleTimerWarning} />
            )}
          </div>
          <div className="flex items-center gap-2">
            {!isComplete && !timerExpired && (
              <button
                onClick={() => setShowSubmitConfirm(true)}
                className="text-xs font-semibold text-white bg-rose-600 hover:bg-rose-700 px-3 py-1.5 rounded-lg transition-colors"
              >
                Submit Exam
              </button>
            )}
            <Link href="/profile" className="text-xs font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 hover:bg-indigo-100 px-3 py-1.5 rounded-lg transition-colors">
              Profile
            </Link>
          </div>
        </div>
        <QuestionNavStrip onNavigate={handleNavStripNavigate} />
      </header>

      {showTimerWarning && (
        <div className="fixed top-24 left-1/2 -translate-x-1/2 z-40">
          <div className="bg-amber-500 text-white text-sm font-semibold px-5 py-2.5 rounded-lg shadow-lg whitespace-nowrap">
            ⏱ 3 minutes remaining — wrap up your answers!
          </div>
        </div>
      )}

      {showSubmitConfirm && (
        <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50 p-4">
          <div className="bg-white rounded-xl shadow-xl p-6 w-full max-w-sm">
            <h3 className="text-lg font-semibold text-slate-900 mb-2">Submit your exam?</h3>
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
                className="px-4 py-2 text-sm font-semibold text-white bg-rose-600 rounded-lg hover:bg-rose-700"
              >
                Yes, submit exam
              </button>
            </div>
          </div>
        </div>
      )}

      <main className="max-w-7xl mx-auto px-4 py-6">
        <div className="flex flex-col lg:flex-row gap-6">

          {/* Left panel: question */}
          <div className="w-full lg:w-3/5">
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
                onChoiceSelect={(val) => logAction({
                  user_id: userId, session_id: sessionId,
                  action_type: 'choice_select',
                  question_number: currentQ.question_number,
                  action_data: { selected_option: val },
                })}
                onInputFocus={() => logAction({
                  user_id: userId, session_id: sessionId,
                  action_type: 'answer_focus',
                  question_number: currentQ.question_number,
                })}
              />

              {!isReadOnly && (
                <div className="flex gap-3 mt-4">
                  <button onClick={handleSkip} disabled={isSkipping || isSubmitting}
                    className="flex items-center gap-1.5 px-4 py-2 text-sm font-medium text-amber-700 border-2 border-amber-400 rounded-lg hover:bg-amber-50 disabled:opacity-50 disabled:cursor-not-allowed">
                    {isSkipping ? 'Skipping…' : '↷ Skip'}
                  </button>
                  <button onClick={handleSubmit} disabled={!canSubmit}
                    className="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed">
                    {isSubmitting ? 'Submitting…' : 'Submit Answer'}
                  </button>
                </div>
              )}

              {submitError && <p className="mt-2 text-xs text-rose-600">{submitError}</p>}

              {showBanner && (
                <ResultBanner
                  questionNumber={currentQ.question_number}
                  onNext={showNextBtn ? handleNavigateNext : undefined}
                  previousAnswer={currentStatus === 'wrong_1' && currentQ.question_type === 'fill_in_the_blank' ? userAnswers[currentQ.question_number] : undefined}
                />
              )}
            </div>

            {/* Intervention banner — mobile only (stacks below question card) */}
            {showIntervention && !isReadOnly && !activeHint && (
              <div className="lg:hidden mt-4">
                <InterventionBanner reason={interventionReason} onAccept={handleInterventionAccept} onDismiss={handleInterventionDismiss} />
              </div>
            )}
          </div>

          {/* Right panel: hints + chat */}
          <div className="w-full lg:w-2/5 lg:sticky lg:top-20 lg:self-start lg:max-h-[calc(100vh-6rem)] lg:overflow-y-auto space-y-4">
            {/* Intervention banner — desktop only */}
            {showIntervention && !isReadOnly && !activeHint && (
              <div className="hidden lg:block">
                <InterventionBanner reason={interventionReason} onAccept={handleInterventionAccept} onDismiss={handleInterventionDismiss} />
              </div>
            )}

            {/* Profile reminder for free_choice users who haven't set a hint style */}
            {showProfileBanner && (
              <div className="flex items-start gap-3 bg-indigo-50 border border-indigo-200 rounded-xl p-3 text-sm text-indigo-800">
                <span className="shrink-0">💡</span>
                <span className="flex-1">You can customize your hint style in your <a href="/profile" className="font-semibold underline hover:text-indigo-600">Profile</a>.</span>
                <button onClick={() => setShowProfileBanner(false)} className="shrink-0 text-indigo-400 hover:text-indigo-600 font-bold">×</button>
              </div>
            )}

            {/* Hint section */}
            <div className="bg-white rounded-xl border border-slate-200 p-4">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">Hint</h3>
              {!isReadOnly ? (
                <>
                  <HintDisplay isLoading={isHintLoading} onRequestHint={handleRequestHint} disabled={isSubmitting} />
                  <FeedbackBar />
                </>
              ) : (
                <p className="text-xs text-slate-400 italic">Hints are not available for completed questions.</p>
              )}
            </div>

            {/* Chat */}
            <ChatPanel defaultOpen />
          </div>
        </div>
      </main>

      {takenOver && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60">
          <div className="bg-white rounded-xl border border-slate-200 p-8 max-w-sm text-center shadow-xl">
            <p className="text-base font-semibold text-rose-600 mb-2">Session ended</p>
            <p className="text-sm text-slate-600">
              This exam token is now active on another device. Your progress has been saved.
              Contact your instructor if you believe this is an error.
            </p>
          </div>
        </div>
      )}
    </div>
  )
}

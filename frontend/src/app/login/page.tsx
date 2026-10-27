'use client'

import { useState, useEffect, useCallback } from 'react'
import Image from 'next/image'
import { useRouter } from 'next/navigation'
import { participantLogin, createUser, logoutSession, apiHealth } from '@/services/apiClient'
import { clearLocalSession, claimLocalSession } from '@/services/localSession'
import { useQuiz } from '@/context/QuizContext'

const examRules = [
  'The exam lasts 1 hour. The timer starts the moment you begin and cannot be paused.',
  'Closing the browser, losing your connection, or reloading the page does not stop the timer.',
  'There are 25 questions, 18 multiple choice and 7 fill in the blank, 5 for each of the five topics.',
  'You have at most 2 attempts per question. A second wrong answer locks it, no answer is shown, you simply move on. A wrong multiple-choice option is grayed out so you do not retry it.',
  'You may skip a question and return to it later, as long as time remains.',
  'You can always go back to any question you have already reached, but you cannot jump ahead past one you have not yet answered or skipped.',
  'After a correct answer, nothing advances automatically. You choose when to move on.',
]

const statusLegend = [
  { label: 'Unanswered', swatch: 'bg-slate-200' },
  { label: 'Skipped', swatch: 'bg-amber-400' },
  { label: '1 wrong, retry left', swatch: 'bg-orange-400' },
  { label: 'Correct, locked', swatch: 'bg-emerald-500' },
  { label: '2 wrong, locked', swatch: 'bg-rose-500' },
]

type LoginState = 'idle' | 'not_started' | 'resumable' | 'active_elsewhere' | 'completed' | 'invalid'
type ProbeStatus = 'checking' | 'open' | 'closed'

function generateSessionId(): string {
  return crypto.randomUUID ? crypto.randomUUID() : Math.random().toString(36).slice(2)
}

export default function LoginPage() {
  const router = useRouter()
  const { dispatch } = useQuiz()
  const [token, setToken] = useState('')
  const [loading, setLoading] = useState(false)
  const [loginState, setLoginState] = useState<LoginState>('idle')
  const [participantName, setParticipantName] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [savedUserId, setSavedUserId] = useState<string | null>(null)
  const [showNewToken, setShowNewToken] = useState(false)
  const [probeStatus, setProbeStatus] = useState<ProbeStatus>('checking')

  // Check if there's a saved session in localStorage
  useEffect(() => {
    const stored = localStorage.getItem('userId')
    if (stored) setSavedUserId(stored)
  }, [])

  // Backend up/down probe (Stage 4.5): the exam server only runs during exam
  // windows, but the static frontend is up 24/7. A failed probe IS the
  // closed-exam state — no build flag or separate status file to keep in
  // sync, the backend being unreachable is exactly what "closed" means.
  const runHealthProbe = useCallback(async () => {
    setProbeStatus('checking')
    const ok = await apiHealth()
    setProbeStatus(ok ? 'open' : 'closed')
  }, [])

  useEffect(() => {
    runHealthProbe()
  }, [runHealthProbe])

  const handleContinueSaved = async () => {
    if (!savedUserId) return
    setLoading(true)
    setError(null)
    try {
      const currentSessionId = localStorage.getItem('sessionId') ?? undefined
      const data = await participantLogin(savedUserId, currentSessionId)
      if (data.state === 'completed') {
        router.replace('/results')
        return
      }
      if (data.state === 'resumable' || data.state === 'active_elsewhere') {
        // active_elsewhere — show the warning screen; resumable — go straight to quiz
        if (data.state === 'resumable') {
          router.replace('/quiz')
          return
        }
        setParticipantName(data.name)
        setLoginState(data.state as LoginState)
      } else if (data.state === 'not_started') {
        // Admin reset the session but localStorage still has the userId — show start screen
        setToken(savedUserId)
        setParticipantName(data.name)
        setLoginState('not_started')
      }
    } catch {
      setError('Could not reach the server. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  const handleCheck = async (e: React.FormEvent) => {
    e.preventDefault()
    const t = token.trim().toUpperCase()
    if (!t) { setError('Please enter your exam token.'); return }
    setLoading(true)
    setError(null)
    try {
      const currentSessionId = localStorage.getItem('sessionId') ?? undefined
      const data = await participantLogin(t, currentSessionId)
      setParticipantName(data.name)
      setLoginState(data.state as LoginState)
    } catch (err: unknown) {
      const status = (err as { response?: { status?: number } })?.response?.status
      if (status === 404) {
        setLoginState('invalid')
      } else {
        setError('Could not reach the server. Please try again.')
      }
    } finally {
      setLoading(false)
    }
  }

  const handleProceed = async () => {
    const t = token.trim().toUpperCase()
    setLoading(true)
    setError(null)
    try {
      await createUser(t)
      const sessionId = generateSessionId()
      // Drop any other student's cached results, hints and chat before this
      // student's session begins. Done here rather than at logout because
      // this is the first point where the incoming identity is known.
      claimLocalSession(t)
      localStorage.setItem('userId', t)
      localStorage.setItem('sessionId', sessionId)
      router.replace('/quiz')
    } catch {
      setError('Could not start session. Please try again.')
      setLoading(false)
    }
  }

  const handleReset = () => {
    setLoginState('idle')
    setToken('')
    setParticipantName(null)
    setError(null)
  }

  const handleUseNewToken = () => {
    // Clear saved session and show token input
    if (savedUserId) {
      logoutSession(savedUserId, localStorage.getItem('sessionId') || undefined)
    }
    clearLocalSession()
    dispatch({ type: 'RESET' })
    setSavedUserId(null)
    setShowNewToken(true)
    setLoginState('idle')
    setToken('')
    setError(null)
  }

  // Redirect to /results when a manually-entered token comes back as completed
  useEffect(() => {
    if (loginState === 'completed') {
      const t = token.trim().toUpperCase() || savedUserId || ''
      if (t) localStorage.setItem('userId', t)
      router.replace('/results')
    }
  }, [loginState, router, token, savedUserId])

  return (
    <div className="min-h-screen bg-slate-50 px-4 py-12 sm:py-16">
      <div className="w-full max-w-2xl mx-auto">
        <h1 className="flex justify-center mb-2">
          <Image src="/brand/logo-wordmark.png" alt="DaTu AIR" width={240} height={46} priority unoptimized />
        </h1>
        <p className="text-sm text-slate-500 text-center mb-8">Adaptive exam preparation</p>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm space-y-8 mb-6">
          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              What this is
            </h2>
            <p className="text-sm text-slate-700 leading-relaxed">
              A 1-hour adaptive exam on deep learning training and optimization. As you work
              through it, the system tracks what you have shown mastery of and adjusts the
              guidance it offers you. Your answers, hints, and chat messages are all recorded for
              later review.
            </p>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              How the exam works
            </h2>
            <ul className="space-y-2">
              {examRules.map((rule) => (
                <li key={rule} className="flex gap-3 text-sm text-slate-700 leading-relaxed">
                  <span aria-hidden className="text-slate-300 select-none">&bull;</span>
                  <span>{rule}</span>
                </li>
              ))}
            </ul>

            <div className="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-lg">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Question status colors
              </p>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                {statusLegend.map((s) => (
                  <span key={s.label} className="flex items-center gap-1.5 text-xs text-slate-600">
                    <span aria-hidden className={`w-3 h-3 rounded-sm ${s.swatch}`} />
                    {s.label}
                  </span>
                ))}
              </div>
            </div>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Getting help while you work
            </h2>
            <dl className="space-y-4">
              <div>
                <dt className="text-sm font-medium text-slate-900 mb-1">Get Hint</dt>
                <dd className="text-sm text-slate-700 leading-relaxed">
                  Requests one guided hint for the question you are on, never the answer itself.
                  After reading it, you can rate how helpful it was, this is optional. Hints are
                  not available once a question is locked. If you spend a while stuck on a
                  question, the tutor may proactively offer you a hint, you can accept or decline.
                </dd>
              </div>
            </dl>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Your profile
            </h2>
            <p className="text-sm text-slate-700 leading-relaxed">
              Open your profile anytime from the header link. It shows your student ID and lets
              you log out, which releases your device lock but does not pause the timer.
              Depending on your assigned group, you may also be able to choose your preferred
              hint style: Conceptual, Analogy, Socratic Question, or Worked Example. If your
              group has the system manage this for you, the choice is shown but disabled, with a
              note that it is managed for the session.
            </p>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Before you start
            </h2>
            <p className="text-sm text-slate-700 leading-relaxed">
              You can only be logged in from one device at a time. Treat this like the proctored
              exam it is: stay on this tab for the full 1 hour, and do not open other tabs,
              windows, or outside material while your timer is running.
              Switching to another tab or app is recorded, and a notice appears when you return.
            </p>
          </section>
        </div>

        <div className="w-full max-w-sm mx-auto bg-white rounded-xl border border-slate-200 p-6 shadow-sm">

          {probeStatus === 'checking' && (
            <div className="text-center py-4">
              <p className="text-sm text-slate-400">Checking exam status…</p>
            </div>
          )}

          {probeStatus === 'closed' && (
            <div className="text-center">
              <p className="text-base font-medium text-slate-800 mb-2">The exam is not currently open</p>
              <p className="text-sm text-slate-500 mb-5">
                This page is working correctly, but the exam server is offline outside exam windows.
                Contact your instructor if you believe the exam should be running right now.
              </p>
              <button
                onClick={runHealthProbe}
                className="w-full py-2 px-4 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700"
              >
                Check again
              </button>
            </div>
          )}

          {probeStatus === 'open' && (<>

          {/* Saved session found — show continue option (only when no active state and not showing new token form) */}
          {savedUserId && loginState === 'idle' && !showNewToken && (
            <div>
              <p className="text-sm text-slate-500 mb-1">Previous session found:</p>
              <p className="font-mono text-slate-900 text-base font-semibold mb-4">{savedUserId}</p>
              <button
                onClick={handleContinueSaved}
                disabled={loading}
                className="w-full py-2 px-4 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed mb-3"
              >
                {loading ? 'Checking…' : 'Continue Session'}
              </button>
              <button
                onClick={handleUseNewToken}
                className="w-full py-2 px-4 text-sm font-medium text-slate-600 border border-slate-300 rounded-lg hover:bg-slate-50"
              >
                Use a different token
              </button>
              {error && <p className="mt-3 text-xs text-rose-600 text-center">{error}</p>}
            </div>
          )}

          {/* Token entry — shown when no saved session, or user chose to enter a new token */}
          {(!savedUserId || showNewToken) && (loginState === 'idle' || loginState === 'invalid') && (
            <form onSubmit={handleCheck}>
              <label htmlFor="token" className="block text-sm font-medium text-slate-700 mb-1">
                Exam Token
              </label>
              <input
                id="token"
                type="text"
                value={token}
                onChange={(e) => { setToken(e.target.value); setLoginState('idle') }}
                placeholder="e.g., Z7XN5Z4H"
                autoFocus
                autoCapitalize="characters"
                className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm font-mono tracking-widest focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent mb-4"
              />
              {loginState === 'invalid' && (
                <p className="text-xs text-rose-600 mb-3">Invalid token. Check your token and try again.</p>
              )}
              <button
                type="submit"
                disabled={loading}
                className="w-full py-2 px-4 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed"
              >
                {loading ? 'Checking…' : 'Continue'}
              </button>
              {error && <p className="mt-3 text-xs text-rose-600 text-center">{error}</p>}
            </form>
          )}

          {/* Not started */}
          {loginState === 'not_started' && (
            <div className="text-center">
              {participantName && (
                <p className="text-sm text-slate-500 mb-1">Welcome, <span className="font-medium text-slate-700">{participantName}</span></p>
              )}
              <p className="text-base font-medium text-slate-800 mb-1">Ready to begin?</p>
              <p className="text-xs text-slate-500 mb-5">
                Your timer starts immediately and cannot be paused. Closing your browser or losing internet connection will not stop the timer.
              </p>
              <button
                onClick={handleProceed}
                disabled={loading}
                className="w-full py-2 px-4 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed mb-3"
              >
                {loading ? 'Starting…' : 'Start Exam'}
              </button>
              <button onClick={handleReset} className="text-xs text-slate-400 hover:text-slate-600">
                Use a different token
              </button>
            </div>
          )}

          {/* Resumable */}
          {loginState === 'resumable' && (
            <div className="text-center">
              {participantName && (
                <p className="text-sm text-slate-500 mb-1">Welcome back, <span className="font-medium text-slate-700">{participantName}</span></p>
              )}
              <p className="text-base font-medium text-slate-800 mb-1">Resume your exam?</p>
              <p className="text-xs text-slate-500 mb-5">
                Your timer has been running. Your previous progress is saved.
              </p>
              <button
                onClick={handleProceed}
                disabled={loading}
                className="w-full py-2 px-4 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed mb-3"
              >
                {loading ? 'Resuming…' : 'Resume Exam'}
              </button>
              <button onClick={handleReset} className="text-xs text-slate-400 hover:text-slate-600">
                Use a different token
              </button>
            </div>
          )}

          {/* Already active on another device */}
          {loginState === 'active_elsewhere' && (
            <div className="text-center">
              <p className="text-base font-medium text-rose-600 mb-2">Token already in use</p>
              <p className="text-sm text-slate-600 mb-5">
                This token is currently active on another device. If that was you and the session
                was interrupted, please wait 60 seconds and try again.
              </p>
              <button onClick={handleReset} className="text-xs text-slate-400 hover:text-slate-600">
                Try a different token
              </button>
            </div>
          )}

          </>)}
        </div>
      </div>
    </div>
  )
}

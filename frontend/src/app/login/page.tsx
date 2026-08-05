'use client'

import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { participantLogin, createUser, logoutSession, apiHealth } from '@/services/apiClient'
import { clearLocalSession } from '@/services/localSession'
import { useQuiz } from '@/context/QuizContext'

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
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-bold text-slate-900 text-center mb-1">DaTu AIR</h1>
        <p className="text-sm text-slate-500 text-center mb-8">Adaptive exam preparation</p>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">

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

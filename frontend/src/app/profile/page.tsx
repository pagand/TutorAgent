'use client'

import { useState, useEffect } from 'react'
import { useRouter } from 'next/navigation'
import Link from 'next/link'
import { getUserProfile, setUserPreference } from '@/services/apiClient'

// Values must match backend HintStyle enum exactly
const HINT_STYLES = [
  { value: 'Conceptual', label: 'Conceptual' },
  { value: 'Analogy', label: 'Analogy' },
  { value: 'Socratic Question', label: 'Socratic Question' },
  { value: 'Worked Example', label: 'Worked Example' },
]

export default function ProfilePage() {
  const router = useRouter()
  const [userId, setUserId] = useState<string | null>(null)
  const [abGroup, setAbGroup] = useState<string | null>(null)
  const [hintStyle, setHintStyle] = useState<string>('Conceptual')
  const [interventionPref, setInterventionPref] = useState<string>('proactive')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const id = localStorage.getItem('userId')
    if (!id) { router.replace('/login'); return }
    setUserId(id)

    getUserProfile(id)
      .then((profile) => {
        const prefs = profile.preferences || {}
        setAbGroup(prefs.ab_group || null)
        setHintStyle(prefs.hint_style_preference || 'Conceptual')
        setInterventionPref(prefs.intervention_preference || 'proactive')
      })
      .catch(() => setError('Failed to load profile.'))
      .finally(() => setLoading(false))
  }, [router])

  const handleSave = async () => {
    if (!userId || abGroup === 'adaptive') return
    setSaving(true)
    setSaved(false)
    setError(null)
    try {
      await setUserPreference(userId, hintStyle, interventionPref)
      setSaved(true)
      setTimeout(() => setSaved(false), 2000)
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : 'Failed to save preference.'
      setError(msg)
    } finally {
      setSaving(false)
    }
  }

  const handleLogout = () => {
    localStorage.removeItem('userId')
    localStorage.removeItem('sessionId')
    localStorage.removeItem('examStartMs')
    router.replace('/login')
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-slate-50 flex items-center justify-center">
        <p className="text-slate-400 text-sm">Loading…</p>
      </div>
    )
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="bg-white border-b border-slate-200">
        <div className="max-w-2xl mx-auto px-4 py-4 flex items-center justify-between">
          <h1 className="text-lg font-bold text-slate-900">Profile</h1>
          <Link href="/quiz" className="text-sm text-indigo-600 hover:text-indigo-800 font-medium">
            ← Back to Quiz
          </Link>
        </div>
      </header>

      <main className="max-w-2xl mx-auto px-4 py-8 space-y-4">
        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <p className="text-sm text-slate-500 mb-1">
            Student ID: <span className="font-semibold text-slate-800">{userId}</span>
          </p>
          {abGroup && (
            <p className="text-xs text-slate-400">
              Group: <span className="font-medium">{abGroup}</span>
            </p>
          )}
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Hint Style Preference</h2>

          {abGroup === 'adaptive' && (
            <p className="text-xs text-slate-500 italic mb-3">
              Your hint style is managed for this session.
            </p>
          )}

          <div className="space-y-2">
            {HINT_STYLES.map(({ value, label }) => (
              <label
                key={value}
                className={[
                  'flex items-center p-3 border rounded-lg transition-colors',
                  abGroup === 'adaptive'
                    ? 'opacity-50 cursor-not-allowed'
                    : 'cursor-pointer hover:bg-slate-50',
                  hintStyle === value ? 'border-indigo-400 bg-indigo-50' : 'border-slate-200',
                ].join(' ')}
              >
                <input
                  type="radio"
                  name="hintStyle"
                  value={value}
                  checked={hintStyle === value}
                  onChange={() => abGroup !== 'adaptive' && setHintStyle(value)}
                  disabled={abGroup === 'adaptive'}
                  className="h-4 w-4 text-indigo-600 border-slate-300"
                />
                <span className="ml-3 text-sm text-slate-800">{label}</span>
              </label>
            ))}
          </div>

          {abGroup !== 'adaptive' && (
            <button
              onClick={handleSave}
              disabled={saving}
              className="mt-4 px-5 py-2 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300"
            >
              {saving ? 'Saving…' : saved ? 'Saved ✓' : 'Save Preference'}
            </button>
          )}

          {error && <p className="mt-2 text-xs text-rose-600">{error}</p>}
        </div>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <h2 className="text-sm font-semibold text-slate-700 mb-3">Session</h2>
          <button
            onClick={handleLogout}
            className="px-4 py-2 text-sm font-medium text-rose-600 border border-rose-200 rounded-lg hover:bg-rose-50"
          >
            Log out
          </button>
        </div>
      </main>
    </div>
  )
}

'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { createUser } from '@/services/apiClient'

export default function LoginPage() {
  const router = useRouter()
  const [userId, setUserId] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const handleStart = async (e: React.FormEvent) => {
    e.preventDefault()
    const id = userId.trim()
    if (!id) { setError('Please enter your student ID.'); return }
    setLoading(true)
    setError(null)
    try {
      await createUser(id)
      localStorage.setItem('userId', id)
      router.replace('/quiz')
    } catch {
      setError('Could not start session. Please try again.')
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        <h1 className="text-3xl font-bold text-slate-900 text-center mb-1">AI Tutor</h1>
        <p className="text-sm text-slate-500 text-center mb-8">Adaptive exam preparation</p>

        <form onSubmit={handleStart} className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm">
          <label htmlFor="userId" className="block text-sm font-medium text-slate-700 mb-1">
            Student ID
          </label>
          <input
            id="userId"
            type="text"
            value={userId}
            onChange={(e) => setUserId(e.target.value)}
            placeholder="e.g., student_42"
            autoFocus
            className="w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent mb-4"
          />
          <button
            type="submit"
            disabled={loading}
            className="w-full py-2 px-4 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed"
          >
            {loading ? 'Starting…' : 'Start Exam'}
          </button>
          {error && <p className="mt-3 text-xs text-rose-600 text-center">{error}</p>}
        </form>
      </div>
    </div>
  )
}

'use client'

import { useState, useRef, useEffect } from 'react'
import { useQuiz } from '@/context/QuizContext'
import { sendChat } from '@/services/apiClient'

export default function ChatPanel() {
  const { state, dispatch } = useQuiz()
  const { userId, sessionId, chatHistory, currentQuestionIndex, questions, userAnswers } = state
  const [open, setOpen] = useState(false)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const bottomRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (open) bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [chatHistory, open])

  const currentQuestion = questions[currentQuestionIndex]
  const currentAnswer = currentQuestion ? userAnswers[currentQuestion.question_number] : undefined

  const handleSend = async () => {
    if (!input.trim() || !currentQuestion) return
    const message = input.trim()
    setInput('')
    setSending(true)
    setError(null)
    try {
      const result = await sendChat({
        user_id: userId,
        session_id: sessionId,
        question_number: currentQuestion.question_number,
        message,
        chat_history: chatHistory,
        current_answer: currentAnswer,
      })
      dispatch({ type: 'APPEND_CHAT', userMessage: message, tutorResponse: result.response })
    } catch {
      setError('Failed to send message. Try again.')
    } finally {
      setSending(false)
    }
  }

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className="mt-4 border border-slate-200 rounded-lg bg-white overflow-hidden">
      <button
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center justify-between px-4 py-3 text-sm font-medium text-slate-700 hover:bg-slate-50"
      >
        <span>Chat with Tutor</span>
        <span className="text-slate-400">{open ? '▲' : '▼'}</span>
      </button>

      {open && (
        <div className="border-t border-slate-200">
          {/* Messages */}
          <div className="h-56 overflow-y-auto p-3 space-y-3 bg-slate-50">
            {chatHistory.length === 0 && (
              <p className="text-xs text-slate-400 text-center mt-4">
                Ask the tutor anything about this question.
              </p>
            )}
            {chatHistory.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div
                  className={[
                    'max-w-[80%] px-3 py-2 rounded-lg text-sm leading-relaxed',
                    msg.role === 'user'
                      ? 'bg-indigo-600 text-white rounded-br-none'
                      : 'bg-white border border-slate-200 text-slate-800 rounded-bl-none',
                  ].join(' ')}
                >
                  {msg.content}
                </div>
              </div>
            ))}
            {sending && (
              <div className="flex justify-start">
                <div className="bg-white border border-slate-200 text-slate-400 px-3 py-2 rounded-lg text-sm rounded-bl-none">
                  …
                </div>
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {error && <p className="px-3 py-1 text-xs text-rose-600 bg-rose-50">{error}</p>}

          {/* Input */}
          <div className="flex gap-2 p-2 border-t border-slate-200">
            <input
              type="text"
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask a question…"
              disabled={sending}
              className="flex-1 px-3 py-2 text-sm border border-slate-300 rounded-lg focus:outline-none focus:ring-2 focus:ring-indigo-500 disabled:bg-slate-100"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim() || sending}
              className="px-4 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 disabled:bg-indigo-300 disabled:cursor-not-allowed"
            >
              Send
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

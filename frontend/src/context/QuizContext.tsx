'use client'

import React, { createContext, useContext, useReducer, ReactNode } from 'react'
import type { QuizState, QuestionStatus, Question, ChatMessage, HintData } from '@/types'

type QuizAction =
  | { type: 'LOAD_QUIZ'; userId: string; sessionId: string; questions: Question[]; examStartMs: number; examDurationMs: number; cachedHints?: Record<number, HintData>; cachedChat?: ChatMessage[] }
  | { type: 'NAVIGATE_TO'; index: number }
  | { type: 'SUBMIT_RESULT'; questionNumber: number; isCorrect: boolean; correctAnswer: string; userAnswer: string }
  | { type: 'SKIP_QUESTION' }
  | { type: 'SET_HINT'; questionNumber: number; hint: HintData }
  | { type: 'SET_RATING'; questionNumber: number; rating: number }
  | { type: 'SET_DRAFT'; questionNumber: number; answer: string }
  | { type: 'APPEND_CHAT'; userMessage: string; tutorResponse: string }
  | { type: 'COMPLETE' }
  | { type: 'RESTORE_STATE'; questionStates: Record<number, QuestionStatus>; retryCount: Record<number, number>; userAnswers: Record<number, string>; correctAnswers: Record<number, string> }

const initialState: QuizState = {
  userId: '',
  sessionId: '',
  questions: [],
  questionStates: {},
  retryCount: {},
  userAnswers: {},
  correctAnswers: {},
  draftAnswers: {},
  currentQuestionIndex: 0,
  highestReachedIndex: 0,
  examStartMs: 0,
  examDurationMs: 25 * 60 * 1000,
  chatHistory: [],
  hints: {},
  pendingRatings: {},
  isComplete: false,
}

function quizReducer(state: QuizState, action: QuizAction): QuizState {
  switch (action.type) {
    case 'LOAD_QUIZ': {
      const questionStates: Record<number, QuestionStatus> = {}
      for (const q of action.questions) {
        questionStates[q.question_number] = 'unanswered'
      }
      return {
        ...state,
        userId: action.userId,
        sessionId: action.sessionId,
        questions: action.questions,
        questionStates,
        retryCount: {},
        userAnswers: {},
        correctAnswers: {},
        draftAnswers: {},
        currentQuestionIndex: 0,
        highestReachedIndex: 0,
        examStartMs: action.examStartMs,
        examDurationMs: action.examDurationMs,
        chatHistory: action.cachedChat ?? [],
        hints: action.cachedHints ?? {},
        pendingRatings: {},
        isComplete: false,
      }
    }

    case 'NAVIGATE_TO': {
      return { ...state, currentQuestionIndex: action.index }
    }

    case 'SUBMIT_RESULT': {
      const { questionNumber, isCorrect, correctAnswer, userAnswer } = action
      const currentStatus = state.questionStates[questionNumber] || 'unanswered'

      let newStatus: QuestionStatus
      if (isCorrect) {
        newStatus = 'correct'
      } else {
        newStatus = currentStatus === 'wrong_1' ? 'wrong_2' : 'wrong_1'
      }

      const newStates = { ...state.questionStates, [questionNumber]: newStatus }
      const newRetryCount = { ...state.retryCount, [questionNumber]: (state.retryCount[questionNumber] || 0) + 1 }
      const newCorrectAnswers = { ...state.correctAnswers, [questionNumber]: correctAnswer }
      const newUserAnswers = { ...state.userAnswers, [questionNumber]: userAnswer }
      // Clear draft for this question after submission
      const newDrafts = { ...state.draftAnswers, [questionNumber]: '' }

      const newHighest = Math.min(
        Math.max(state.highestReachedIndex, state.currentQuestionIndex + 1),
        state.questions.length - 1
      )

      const allFinal = state.questions.every(q => {
        const s = newStates[q.question_number]
        return s === 'correct' || s === 'wrong_2' || s === 'skipped'
      })

      return {
        ...state,
        questionStates: newStates,
        retryCount: newRetryCount,
        correctAnswers: newCorrectAnswers,
        userAnswers: newUserAnswers,
        draftAnswers: newDrafts,
        highestReachedIndex: newHighest,
        isComplete: allFinal,
      }
    }

    case 'SKIP_QUESTION': {
      const currentQ = state.questions[state.currentQuestionIndex]
      const currentStatus = state.questionStates[currentQ.question_number] || 'unanswered'
      const newStatus: QuestionStatus = currentStatus === 'unanswered' ? 'skipped' : currentStatus
      const newStates = { ...state.questionStates, [currentQ.question_number]: newStatus }
      const newDrafts = { ...state.draftAnswers, [currentQ.question_number]: '' }

      let nextIndex = state.currentQuestionIndex + 1
      while (nextIndex < state.questions.length) {
        const q = state.questions[nextIndex]
        const s = newStates[q.question_number] || 'unanswered'
        if (s === 'unanswered' || s === 'skipped' || s === 'wrong_1') break
        nextIndex++
      }
      if (nextIndex >= state.questions.length) {
        nextIndex = state.currentQuestionIndex
      }

      const newHighest = Math.min(
        Math.max(state.highestReachedIndex, nextIndex),
        state.questions.length - 1
      )

      const allFinal = state.questions.every(q => {
        const s = newStates[q.question_number] || 'unanswered'
        return s === 'correct' || s === 'wrong_2' || s === 'skipped'
      })

      return {
        ...state,
        questionStates: newStates,
        draftAnswers: newDrafts,
        currentQuestionIndex: nextIndex,
        highestReachedIndex: newHighest,
        isComplete: allFinal,
      }
    }

    case 'SET_DRAFT': {
      return { ...state, draftAnswers: { ...state.draftAnswers, [action.questionNumber]: action.answer } }
    }

    case 'SET_HINT': {
      return { ...state, hints: { ...state.hints, [action.questionNumber]: action.hint } }
    }

    case 'SET_RATING': {
      return { ...state, pendingRatings: { ...state.pendingRatings, [action.questionNumber]: action.rating } }
    }

    case 'APPEND_CHAT': {
      const newMessages: ChatMessage[] = [
        ...state.chatHistory,
        { role: 'user', content: action.userMessage },
        { role: 'tutor', content: action.tutorResponse },
      ]
      return { ...state, chatHistory: newMessages }
    }

    case 'COMPLETE': {
      return { ...state, isComplete: true }
    }

    case 'RESTORE_STATE': {
      const { questionStates, retryCount, userAnswers, correctAnswers } = action
      const allFinal = state.questions.every(q => {
        const s = questionStates[q.question_number] ?? 'unanswered'
        return s === 'correct' || s === 'wrong_2' || s === 'skipped'
      })
      const firstResumable = state.questions.findIndex(q => {
        const s = questionStates[q.question_number] ?? 'unanswered'
        return s === 'unanswered' || s === 'wrong_1' || s === 'skipped'
      })
      const resumeIndex = firstResumable === -1 ? state.questions.length - 1 : firstResumable

      // highestReachedIndex = highest index with any non-unanswered state + 1 (to unlock next)
      // This ensures all previously visited questions stay accessible after refresh
      let highestVisited = 0
      for (let i = 0; i < state.questions.length; i++) {
        const s = questionStates[state.questions[i].question_number] ?? 'unanswered'
        if (s !== 'unanswered') highestVisited = i
      }
      const highestReachedIndex = Math.min(highestVisited + 1, state.questions.length - 1)

      return {
        ...state,
        questionStates,
        retryCount,
        userAnswers,
        correctAnswers,
        currentQuestionIndex: allFinal ? state.currentQuestionIndex : resumeIndex,
        highestReachedIndex,
        isComplete: allFinal,
      }
    }

    default:
      return state
  }
}

interface QuizContextValue {
  state: QuizState
  dispatch: React.Dispatch<QuizAction>
}

const QuizContext = createContext<QuizContextValue | null>(null)

export function QuizProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(quizReducer, initialState)

  // Persist hints and chat to localStorage so they survive page refresh
  React.useEffect(() => {
    if (!state.userId) return
    try {
      localStorage.setItem(`quizCache_${state.userId}`, JSON.stringify({
        hints: state.hints,
        chatHistory: state.chatHistory,
      }))
    } catch { /* storage quota — non-fatal */ }
  }, [state.hints, state.chatHistory, state.userId])

  return (
    <QuizContext.Provider value={{ state, dispatch }}>
      {children}
    </QuizContext.Provider>
  )
}

export function useQuiz() {
  const ctx = useContext(QuizContext)
  if (!ctx) throw new Error('useQuiz must be used within QuizProvider')
  return ctx
}

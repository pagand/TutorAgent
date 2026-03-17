import axios from 'axios'
import type { ChatMessage } from '@/types'

const apiClient = axios.create({
  baseURL: process.env.NEXT_PUBLIC_API_URL || 'http://127.0.0.1:8000',
  headers: { 'Content-Type': 'application/json' },
})

export default apiClient

export const createUser = async (userId: string) => {
  const res = await apiClient.post('/users/', { user_id: userId })
  return res.data
}

export const getUserProfile = async (userId: string) => {
  const res = await apiClient.get(`/users/${userId}/profile`)
  return res.data
}

export const setUserPreference = async (userId: string, hintStyle: string, interventionPreference = 'proactive') => {
  const res = await apiClient.put(`/users/${userId}/preferences/`, {
    hint_style_preference: hintStyle,
    intervention_preference: interventionPreference,
  })
  return res.data
}

export const getQuestions = async (userId: string) => {
  const res = await apiClient.get(`/questions/?user_id=${userId}`)
  return res.data
}

export const submitAnswer = async (payload: {
  user_id: string
  question_number: number
  user_answer?: string
  skipped?: boolean
  time_taken_ms?: number
  hint_shown?: boolean
  hint_style_used?: string
  hint_text?: string
  pre_hint_mastery?: number
  feedback_rating?: number
}) => {
  const res = await apiClient.post('/answer/', payload)
  return res.data
}

export const getHint = async (userId: string, questionNumber: number, userAnswer?: string) => {
  const res = await apiClient.post('/hints/', {
    user_id: userId,
    question_number: questionNumber,
    user_answer: userAnswer,
  })
  return res.data
}

export const startSession = async (userId: string, sessionId: string) => {
  const res = await apiClient.post('/session/start', { user_id: userId, session_id: sessionId })
  return res.data as { user_id: string; session_id: string; exam_start_ms: number; exam_duration_ms: number; ms_remaining: number }
}

export const getSessionRemaining = async (userId: string) => {
  const res = await apiClient.get(`/session/${userId}/remaining`)
  return res.data as { exam_start_ms: number; exam_duration_ms: number; ms_remaining: number; expired: boolean }
}

export const sendChat = async (payload: {
  user_id: string
  session_id: string
  question_number: number
  message: string
  chat_history: ChatMessage[]
  current_answer?: string
}) => {
  const res = await apiClient.post('/chat/', payload)
  return res.data as { response: string; question_number: number }
}

export const checkIntervention = async (userId: string, questionNumber: number, timeSpentMs: number) => {
  const res = await apiClient.post('/intervention-check', {
    user_id: userId,
    question_number: questionNumber,
    time_spent_ms: timeSpentMs,
  })
  return res.data as { intervention_needed: boolean }
}

export const logAction = async (payload: {
  user_id: string
  session_id: string
  action_type: string
  question_number?: number
  action_data?: Record<string, unknown>
}) => {
  // Fire-and-forget — never await in critical paths
  apiClient.post('/log/action', payload).catch(() => {})
}

export const logIntervention = async (payload: {
  user_id: string
  session_id: string
  question_number: number
  time_on_question_ms: number
  mastery_at_trigger?: number
  accepted?: boolean
}) => {
  apiClient.post('/log/intervention', payload).catch(() => {})
}

export type QuestionStatus = 'unanswered' | 'skipped' | 'wrong_1' | 'correct' | 'wrong_2'

export interface Question {
  question_number: number
  question: string
  question_type: 'multiple_choice' | 'fill_in_the_blank'
  options?: string[]
  skill: string
}

export interface ChatMessage {
  role: 'user' | 'tutor'
  content: string
}

export interface HintData {
  hint: string
  hint_style: string
  pre_hint_mastery: number
}

export interface QuizState {
  userId: string
  sessionId: string
  questions: Question[]
  questionStates: Record<number, QuestionStatus>  // keyed by question_number
  retryCount: Record<number, number>              // keyed by question_number
  userAnswers: Record<number, string>             // last submitted answer per question_number
  correctAnswers: Record<number, string>          // revealed in CompletionModal only
  draftAnswers: Record<number, string>            // in-progress answer per question (persists navigation)
  currentQuestionIndex: number
  highestReachedIndex: number                     // max index user can navigate to
  examStartMs: number
  examDurationMs: number
  chatHistory: ChatMessage[]
  hints: Record<number, HintData>         // per question_number, persists across navigation
  pendingRatings: Record<number, number>  // per question_number
  isComplete: boolean
}

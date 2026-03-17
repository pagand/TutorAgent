'use client'

import { QuizProvider } from '@/context/QuizContext'

export default function Providers({ children }: { children: React.ReactNode }) {
  return <QuizProvider>{children}</QuizProvider>
}

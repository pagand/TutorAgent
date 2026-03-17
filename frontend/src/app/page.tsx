'use client'

import { useEffect } from 'react'
import { useRouter } from 'next/navigation'

export default function Home() {
  const router = useRouter()

  useEffect(() => {
    const userId = localStorage.getItem('userId')
    router.replace(userId ? '/quiz' : '/login')
  }, [router])

  return null
}

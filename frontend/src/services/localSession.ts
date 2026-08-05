/**
 * localStorage lifecycle for a student's exam session.
 *
 * Exam data is keyed per student because a proctored exam hall reuses the same
 * browser for different students. An unscoped key let the next student read the
 * previous one's results, including the revealed answer key, and let a stale
 * snapshot overwrite a real one.
 */

export function examResultsKey(userId: string): string {
  return `examResults_${userId}`
}

/**
 * Clears every trace of the departing student. Called when the browser is
 * handed to a different token, so it sweeps all per-student keys rather than
 * just the current one, and drops the legacy unscoped `examResults` key that
 * earlier builds wrote.
 */
export function clearLocalSession(): void {
  const stale: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)
    if (k && (k.startsWith('examResults_') || k.startsWith('quizCache_'))) stale.push(k)
  }
  for (const k of stale) localStorage.removeItem(k)

  localStorage.removeItem('examResults')
  localStorage.removeItem('userId')
  localStorage.removeItem('sessionId')
  localStorage.removeItem('examStartMs')
}

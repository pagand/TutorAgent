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
 * Ends the current session's identity. Deliberately leaves the per-student
 * caches alone: at logout we do not yet know who logs in next, and a student
 * who logs out and back in must keep their own hints and chat history, which
 * is what `quizCache_<userId>` exists for.
 *
 * Other students' data is removed by claimLocalSession on the way IN, where
 * the incoming identity is actually known.
 */
export function clearLocalSession(): void {
  localStorage.removeItem('examResults')
  localStorage.removeItem('userId')
  localStorage.removeItem('sessionId')
  localStorage.removeItem('examStartMs')
}

/**
 * Claims the browser for one student, dropping every other student's cached
 * hints, chat and results first. A proctored hall reuses machines, so the
 * handover has to be airtight: an unscoped or leftover key previously let the
 * next student read the previous one's results and revealed answer key.
 *
 * Keeping only the incoming student's own keys is what lets a genuine
 * logout-and-resume survive.
 */
export function claimLocalSession(userId: string): void {
  const mine = new Set([examResultsKey(userId), `quizCache_${userId}`])
  const foreign: string[] = []
  for (let i = 0; i < localStorage.length; i++) {
    const k = localStorage.key(i)
    if (!k) continue
    const isScoped = k.startsWith('examResults_') || k.startsWith('quizCache_')
    if (isScoped && !mine.has(k)) foreign.push(k)
  }
  for (const k of foreign) localStorage.removeItem(k)

  // Legacy unscoped key from earlier builds, never attributable to a student.
  localStorage.removeItem('examResults')
}

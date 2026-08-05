import Link from 'next/link'

const topics = [
  { code: 'SGD-M', name: 'SGD with momentum' },
  { code: 'ADAM', name: 'Adam' },
  { code: 'REG', name: 'Regularization' },
  { code: 'INIT', name: 'Weight initialization' },
  { code: 'BN', name: 'Batch normalization' },
]

const examRules = [
  'The exam lasts 25 minutes. The timer starts the moment you begin and cannot be paused.',
  'Closing the browser, losing your connection, or reloading the page does not stop the timer.',
  'The timer turns red once under 5 minutes remain, and you get a one-time reminder banner at the 3-minute mark. At 0:00 you are moved straight to your results, whatever state you are in.',
  'There are 25 questions, 18 multiple choice and 7 fill in the blank, 5 for each topic above.',
  'You have at most 2 attempts per question. A second wrong answer locks it, no answer is shown, you simply move on. A wrong multiple-choice option is grayed out so you do not retry it.',
  'You may skip a question and return to it later, as long as time remains.',
  'You can always go back to any question you have already reached, but you cannot jump ahead past one you have not yet answered or skipped.',
  'After a correct answer, nothing advances automatically. You choose when to move on.',
  'Correct answers are never shown during the exam, right or wrong. They are revealed only on the results page once you finish.',
  'If you want to end early, the "Submit Exam" button in the header lets you finish and see your results right away, after a confirmation.',
]

const statusLegend = [
  { label: 'Unanswered', swatch: 'bg-slate-200' },
  { label: 'Skipped', swatch: 'bg-amber-400' },
  { label: '1 wrong, retry left', swatch: 'bg-orange-400' },
  { label: 'Correct, locked', swatch: 'bg-emerald-500' },
  { label: '2 wrong, locked', swatch: 'bg-rose-500' },
]

const scoringMetrics = [
  { name: 'Grade', detail: 'the share of all 25 questions you answered correctly. This is your headline score.' },
  { name: 'Accuracy', detail: 'of every answer you submitted, right or wrong, the share that were correct. Needing a second attempt on a question lowers this even if you get it right in the end.' },
  { name: 'Efficiency', detail: 'the same idea as Accuracy, but a skipped question counts against you too. It reflects how often an attempt or a skip actually paid off.' },
  { name: 'Coverage', detail: 'the share of the 25 questions you reached at all, answered or skipped, rather than never seeing them because time ran out.' },
]

export default function Home() {
  return (
    <div className="min-h-screen bg-slate-50 px-4 py-12 sm:py-16">
      <div className="w-full max-w-2xl mx-auto">
        <h1 className="text-3xl font-bold text-slate-900 text-center mb-1">DaTu AIR</h1>
        <p className="text-sm text-slate-500 text-center mb-8">Adaptive exam preparation</p>

        <div className="bg-white rounded-xl border border-slate-200 p-6 shadow-sm space-y-8">
          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              What this is
            </h2>
            <p className="text-sm text-slate-700 leading-relaxed mb-3">
              A 25-minute adaptive exam on deep learning training and optimization. As you work
              through it, the system tracks what you have shown mastery of and adjusts the
              guidance it offers you. Your answers, hints, and chat messages are all recorded for
              later review.
            </p>
            <p className="text-sm text-slate-700 leading-relaxed mb-2">
              Each question is tagged with one of five topics, shown as a small badge above the
              question text:
            </p>
            <ul className="grid grid-cols-1 sm:grid-cols-2 gap-x-4 gap-y-1.5">
              {topics.map((t) => (
                <li key={t.code} className="flex items-center gap-2 text-sm text-slate-700">
                  <span className="text-xs font-semibold text-indigo-600 bg-indigo-50 px-1.5 py-0.5 rounded-full shrink-0">
                    {t.code}
                  </span>
                  <span>{t.name}</span>
                </li>
              ))}
            </ul>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              How the exam works
            </h2>
            <ul className="space-y-2">
              {examRules.map((rule) => (
                <li key={rule} className="flex gap-3 text-sm text-slate-700 leading-relaxed">
                  <span aria-hidden className="text-slate-300 select-none">&bull;</span>
                  <span>{rule}</span>
                </li>
              ))}
            </ul>

            <div className="mt-4 p-3 bg-slate-50 border border-slate-200 rounded-lg">
              <p className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">
                Question status colors
              </p>
              <div className="flex flex-wrap gap-x-4 gap-y-1.5">
                {statusLegend.map((s) => (
                  <span key={s.label} className="flex items-center gap-1.5 text-xs text-slate-600">
                    <span aria-hidden className={`w-3 h-3 rounded-sm ${s.swatch}`} />
                    {s.label}
                  </span>
                ))}
              </div>
            </div>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Getting help while you work
            </h2>
            <dl className="space-y-4">
              <div>
                <dt className="text-sm font-medium text-slate-900 mb-1">Get Hint</dt>
                <dd className="text-sm text-slate-700 leading-relaxed">
                  Requests one guided hint for the question you are on, never the answer itself.
                  After reading it, you can rate how helpful it was, this is optional. Hints are
                  not available once a question is locked. If you spend a while stuck on a
                  question, the tutor may proactively offer you a hint, you can accept or decline.
                </dd>
              </div>
              <div>
                <dt className="text-sm font-medium text-slate-900 mb-1">Tutor chat</dt>
                <dd className="text-sm text-slate-700 leading-relaxed">
                  Sits to the right of the question on a full-size screen (below it on a phone),
                  and is open by default. Ask it anything about the question you are on, including
                  ones that are already locked. Your conversation is saved and survives a page
                  refresh.
                </dd>
              </div>
            </dl>
            <p className="mt-4 text-sm font-medium text-slate-900 leading-relaxed">
              Neither will give you the answer. Both are there to help you think it through.
            </p>

            <div className="mt-4">
              <p className="text-xs text-slate-500 mb-2">On your quiz screen:</p>
              <div className="flex flex-col sm:flex-row gap-2" aria-hidden>
                <div className="sm:flex-[3] border border-slate-200 rounded-lg p-3 bg-slate-50 text-xs text-slate-500 text-center">
                  Question &amp; answer
                </div>
                <div className="sm:flex-[2] flex flex-col gap-2">
                  <div className="border border-slate-200 rounded-lg p-2.5 bg-slate-50 text-xs text-slate-500 text-center">
                    Hint
                  </div>
                  <div className="border border-slate-200 rounded-lg p-2.5 bg-slate-50 text-xs text-slate-500 text-center">
                    Tutor chat
                  </div>
                </div>
              </div>
            </div>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              How you are scored
            </h2>
            <p className="text-sm text-slate-700 leading-relaxed mb-3">
              When the exam ends, whether by finishing, submitting early, or running out of time,
              the results page reports four numbers, plus a breakdown by topic:
            </p>
            <dl className="space-y-3">
              {scoringMetrics.map((m) => (
                <div key={m.name}>
                  <dt className="text-sm font-medium text-slate-900">{m.name}</dt>
                  <dd className="text-sm text-slate-700 leading-relaxed">{m.detail}</dd>
                </div>
              ))}
            </dl>
            <p className="mt-3 text-sm text-slate-700 leading-relaxed">
              There is no separate deduction for a wrong answer. Your Grade only depends on
              whether a question was eventually correct. But using both attempts, or skipping
              instead of answering, does lower your Accuracy and Efficiency, since those are
              measured per attempt, not per question.
            </p>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Your profile
            </h2>
            <p className="text-sm text-slate-700 leading-relaxed">
              Open your profile anytime from the header link. It shows your student ID and lets
              you log out, which releases your device lock but does not pause the timer.
              Depending on your assigned group, you may also be able to choose your preferred
              hint style: Conceptual, Analogy, Socratic Question, or Worked Example. If your
              group has the system manage this for you, the choice is shown but disabled, with a
              note that it is managed for the session.
            </p>
          </section>

          <section>
            <h2 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-3">
              Before you start
            </h2>
            <p className="text-sm text-slate-700 leading-relaxed">
              You can only be logged in from one device at a time. Treat this like the proctored
              exam it is: stay on this tab for the full 25 minutes, and do not open other tabs,
              windows, or outside material while your timer is running.
            </p>
          </section>

          <div className="pt-6 border-t border-slate-200">
            <Link
              href="/login"
              className="block w-full py-2 px-4 text-sm font-semibold text-white text-center bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
            >
              Continue to login
            </Link>
            <p className="mt-3 text-xs text-slate-500 text-center">
              You will need the exam token provided by your instructor.
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}

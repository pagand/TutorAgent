import Image from 'next/image'
import Link from 'next/link'

type NavState = 'correct' | 'wrong_2' | 'skipped' | 'wrong_1' | 'current' | 'locked'

const navStyle: Record<NavState, string> = {
  correct: 'bg-emerald-500 text-white',
  wrong_2: 'bg-rose-500 text-white',
  skipped: 'bg-amber-400 text-white',
  wrong_1: 'bg-orange-400 text-white',
  current: 'bg-slate-200 text-slate-400 ring-2 ring-indigo-600 ring-offset-1',
  locked: 'bg-slate-200 text-slate-300',
}

const navStates: NavState[] = [
  'correct', 'correct', 'wrong_2', 'correct', 'skipped', 'wrong_1', 'current',
  ...Array<NavState>(18).fill('locked'),
]

const options = [
  'It gives each parameter its own effective step size',
  'It removes the need for a learning rate',
  'It guarantees convergence to the global minimum',
  'It forces every gradient to have unit norm',
]

const highlights = [
  { title: 'Adaptive hints', detail: 'Guidance that adjusts to what the student has shown mastery of.' },
  { title: 'Confidence capture', detail: 'An optional 1-10 self-rating with every answer.' },
  { title: 'Tutor chat', detail: 'Questions answered without giving away the exam answer.' },
]

function Figure() {
  return (
    <div
      role="img"
      aria-label="Static illustration of the exam screen: a timer, a question navigation strip, a multiple-choice question with a confidence bar, a hint, and a tutor chat excerpt."
      className="pointer-events-none select-none rounded-xl border border-slate-200 bg-white shadow-lg overflow-hidden"
    >
      <div className="flex items-center gap-1.5 px-3 py-2 bg-slate-100 border-b border-slate-200">
        <span className="w-2.5 h-2.5 rounded-full bg-slate-300" />
        <span className="w-2.5 h-2.5 rounded-full bg-slate-300" />
        <span className="w-2.5 h-2.5 rounded-full bg-slate-300" />
        <span className="ml-3 flex-1 max-w-xs text-[11px] text-slate-400 bg-white border border-slate-200 rounded-md px-2 py-0.5">
          air.da-tu.ca/quiz
        </span>
      </div>

      <div className="bg-slate-50" aria-hidden>
        <div className="bg-white border-b border-slate-200">
          <div className="px-4 py-2.5 flex items-center justify-between">
            <div className="flex items-center gap-3">
              <span className="text-sm font-bold text-slate-900 whitespace-nowrap">DaTu AIR</span>
              <div className="flex items-center gap-1.5">
                <span className="text-xs text-slate-400">⏱</span>
                <span className="font-mono text-sm tabular-nums text-slate-500 font-semibold">18:42</span>
                <span className="hidden sm:inline text-xs text-slate-400">remaining</span>
              </div>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-xs font-semibold text-white bg-rose-600 px-3 py-1.5 rounded-lg whitespace-nowrap">Submit Exam</span>
              <span className="text-xs font-medium text-indigo-600 bg-indigo-50 border border-indigo-200 px-3 py-1.5 rounded-lg">
                Profile
              </span>
            </div>
          </div>
          <div className="flex flex-wrap gap-1 px-4 py-2 border-t border-slate-200">
            {navStates.map((s, i) => (
              <span
                key={i}
                className={`w-6 h-6 rounded text-[11px] font-semibold flex items-center justify-center ${navStyle[s]}`}
              >
                {i + 1}
              </span>
            ))}
          </div>
        </div>

        <div className="p-4 flex flex-col md:flex-row gap-4">
          <div className="md:w-3/5">
            <div className="bg-white rounded-xl border border-slate-200 p-5">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-indigo-600 bg-indigo-50 px-2 py-1 rounded-full">ADAM</span>
                <span className="text-xs text-slate-400">Q7 of 25</span>
              </div>
              <p className="text-sm text-slate-800 leading-relaxed">
                Adam divides the running estimate of the gradient mean by the square root of the
                running estimate of the squared gradient. What is the main effect of this division?
              </p>
              <div className="my-3 space-y-1.5">
                {options.map((o, i) => (
                  <div
                    key={o}
                    className={`flex items-start p-2 border rounded-lg ${
                      i === 1 ? 'bg-indigo-50 border-indigo-400' : 'border-slate-200'
                    }`}
                  >
                    <span
                      className={`mt-0.5 h-3.5 w-3.5 shrink-0 rounded-full border flex items-center justify-center ${
                        i === 1 ? 'border-indigo-600' : 'border-slate-300'
                      }`}
                    >
                      {i === 1 && <span className="h-1.5 w-1.5 rounded-full bg-indigo-600" />}
                    </span>
                    <span className="ml-2.5 text-[13px] text-slate-800 leading-snug">{o}</span>
                  </div>
                ))}
              </div>
              <div className="p-2.5 rounded-lg border border-slate-200">
                <div className="flex items-center justify-between mb-1.5">
                  <p className="text-xs font-medium text-slate-600">How confident are you?</p>
                  <span className="text-xs text-slate-400">6/10</span>
                </div>
                <div className="flex items-center gap-2">
                  <span className="text-[10px] text-slate-400 shrink-0">guessing</span>
                  <div className="flex gap-1 flex-1">
                    {Array.from({ length: 10 }, (_, i) => (
                      <span key={i} className={`h-4 flex-1 rounded-sm ${i < 6 ? 'bg-indigo-600' : 'bg-slate-200'}`} />
                    ))}
                  </div>
                  <span className="text-[10px] text-slate-400 shrink-0">certain</span>
                </div>
              </div>
              <div className="flex gap-3 mt-3">
                <span className="px-4 py-1.5 text-sm font-medium text-amber-700 border-2 border-amber-400 rounded-lg">
                  ↷ Skip
                </span>
                <span className="px-5 py-2 text-sm font-medium text-white bg-indigo-600 rounded-lg">Submit Answer</span>
              </div>
            </div>
          </div>

          <div className="md:w-2/5 space-y-3">
            <div className="bg-white rounded-xl border border-slate-200 p-3">
              <h3 className="text-xs font-semibold text-slate-500 uppercase tracking-wide mb-2">Hint</h3>
              <div className="p-3 border-l-4 border-indigo-400 bg-indigo-50 rounded-r-lg">
                <div className="flex items-center gap-2 mb-1">
                  <span className="text-xs font-semibold text-indigo-700 uppercase tracking-wide">Hint</span>
                  <span className="text-xs text-indigo-500 bg-indigo-100 px-2 py-0.5 rounded-full">Socratic Question</span>
                </div>
                <p className="text-[13px] text-indigo-900 leading-relaxed">
                  Think about a parameter whose gradients have been consistently large. Should its
                  step be the same size as one whose gradients are small?
                </p>
              </div>
            </div>
            <div className="border border-slate-200 rounded-lg bg-white overflow-hidden">
              <div className="flex items-center justify-between px-3 py-2 text-sm font-medium text-slate-700">
                <span>Tutor chat</span>
                <span className="text-slate-400 text-xs">▲</span>
              </div>
              <div className="border-t border-slate-200 p-3 space-y-2 bg-slate-50">
                <div className="flex justify-end">
                  <div className="max-w-[85%] px-3 py-1.5 rounded-lg text-[13px] leading-relaxed bg-indigo-600 text-white rounded-br-none">
                    Why does Adam keep a second moment at all?
                  </div>
                </div>
                <div className="flex justify-start">
                  <div className="max-w-[90%] px-3 py-1.5 rounded-lg text-[13px] leading-relaxed bg-white border border-slate-200 text-slate-800 rounded-bl-none">
                    It tracks how large each parameter&apos;s recent gradients have been. What do you
                    think happens to a step when that estimate is large?
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

export default function Home() {
  return (
    <main className="min-h-screen bg-slate-50 px-4 py-8 sm:px-8 flex items-center">
      <div className="w-full max-w-7xl mx-auto grid grid-cols-1 lg:grid-cols-12 gap-8 lg:gap-10 items-center">
        <section className="lg:col-span-4">
          <Image
            src="/brand/logo-wordmark.png"
            alt="DaTu AIR"
            width={240}
            height={46}
            priority
            unoptimized
          />
          <h1 className="mt-6 text-2xl font-bold text-slate-900 leading-tight">
            AI tutor for adaptive exam practice
          </h1>
          <p className="mt-2 text-sm text-slate-600 leading-relaxed">
            A 1-hour exam on deep learning training and optimization, with guidance that adapts to the student.
          </p>

          <ul className="mt-6 space-y-3">
            {highlights.map((h) => (
              <li key={h.title} className="flex gap-3">
                <span aria-hidden className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-indigo-600" />
                <p className="text-sm text-slate-600 leading-snug">
                  <span className="font-semibold text-slate-900">{h.title}.</span> {h.detail}
                </p>
              </li>
            ))}
          </ul>

          <Link
            href="/login"
            className="mt-8 inline-block px-6 py-2.5 text-sm font-semibold text-white bg-indigo-600 rounded-lg hover:bg-indigo-700 transition-colors"
          >
            Start the exam
          </Link>
          <p className="mt-3 text-xs text-slate-500">You will need the exam token provided by your instructor.</p>
        </section>

        <div className="lg:col-span-8">
          <Figure />
        </div>
      </div>
    </main>
  )
}

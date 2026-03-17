'use client'

interface AnswerInputProps {
  questionType: 'multiple_choice' | 'fill_in_the_blank'
  options?: string[]
  value: string
  onChange: (value: string) => void
  disabled?: boolean
  wrongAnswer?: string  // grays out a previously-tried wrong option
}

export default function AnswerInput({ questionType, options, value, onChange, disabled, wrongAnswer }: AnswerInputProps) {
  return (
    <div className="my-4">
      {questionType === 'multiple_choice' && options && (
        <div className="space-y-2">
          {options.map((option, index) => {
            const val = (index + 1).toString()
            const selected = value === val
            const isWrong = wrongAnswer === val
            const isDisabled = disabled || isWrong

            return (
              <label
                key={index}
                className={[
                  'flex items-start p-3 border rounded-lg transition-colors',
                  isDisabled ? 'cursor-not-allowed' : 'cursor-pointer',
                  isWrong
                    ? 'bg-slate-100 border-slate-200 opacity-50'
                    : selected
                    ? 'bg-indigo-50 border-indigo-400'
                    : disabled
                    ? 'bg-slate-50 border-slate-200'
                    : 'border-slate-200 hover:bg-slate-50',
                ].join(' ')}
              >
                <input
                  type="radio"
                  name="answer"
                  value={val}
                  checked={selected}
                  onChange={(e) => !isDisabled && onChange(e.target.value)}
                  disabled={isDisabled}
                  className="mt-0.5 h-4 w-4 text-indigo-600 border-slate-300 focus:ring-indigo-500"
                />
                <span className={`ml-3 text-sm leading-snug ${isWrong ? 'line-through text-slate-400' : 'text-slate-800'}`}>
                  {option}
                </span>
              </label>
            )
          })}
        </div>
      )}

      {questionType === 'fill_in_the_blank' && (
        <input
          type="text"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          disabled={disabled}
          placeholder="Type your answer…"
          className="block w-full px-3 py-2 border border-slate-300 rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent disabled:bg-slate-100 disabled:cursor-not-allowed"
        />
      )}
    </div>
  )
}

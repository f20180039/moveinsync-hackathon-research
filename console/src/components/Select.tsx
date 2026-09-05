import { useId } from 'react'

export interface SelectOption<T extends string> {
  value: T
  label: string
}

export interface SelectProps<T extends string> {
  label: string
  value: T
  onChange: (value: T) => void
  options: SelectOption<T>[]
  size?: 'sm' | 'md'
  id?: string
}

// The one select every dropdown in the console uses (today: just the
// audience picker). Same height/padding/radius/focus-ring tokens as
// `Button`, and always paired with a visible <label> -- never a placeholder
// standing in for one.
export function Select<T extends string>({ label, value, onChange, options, size = 'md', id }: SelectProps<T>) {
  const autoId = useId()
  const selectId = id ?? autoId

  return (
    <div className="field">
      <label className="field__label" htmlFor={selectId}>
        {label}
      </label>
      <select
        id={selectId}
        className={`select select--${size}`}
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </div>
  )
}

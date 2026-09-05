import type { ButtonHTMLAttributes, ReactNode } from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost'
export type ButtonSize = 'sm' | 'md'

export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  variant?: ButtonVariant
  size?: ButtonSize
  /** Shows "…" and sets aria-busy, so a click can't double-fire mid-request. */
  busy?: boolean
  children: ReactNode
}

// The one button every control in the console uses -- Sweep now, fetch
// brief, Dispatch, Copy SQL, show/hide toggles, the legend toggle. Same
// height/padding/radius/focus-ring tokens as `Select`, so a row of controls
// reads as one system instead of a pile of ad-hoc elements.
export function Button({
  variant = 'secondary',
  size = 'md',
  busy = false,
  disabled,
  className,
  children,
  type = 'button',
  ...rest
}: ButtonProps) {
  const classes = ['btn', `btn--${variant}`, `btn--${size}`, className].filter(Boolean).join(' ')
  // While busy, the visible label collapses to "…"; if the label was plain
  // text, carry it forward as the accessible name so it doesn't vanish for
  // screen reader users mid-request.
  const busyLabel = busy && typeof children === 'string' ? children : undefined

  return (
    <button
      type={type}
      className={classes}
      disabled={disabled || busy}
      aria-busy={busy || undefined}
      aria-label={busyLabel}
      {...rest}
    >
      {busy ? '…' : children}
    </button>
  )
}

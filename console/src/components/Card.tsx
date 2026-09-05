import type { HTMLAttributes, ReactNode } from 'react'

export interface CardProps extends HTMLAttributes<HTMLDivElement> {
  children: ReactNode
}

// The shared card shell every panel on Overview/Alerts/Vendors builds on --
// a border, radius and padding, nothing else opinionated. Every usage
// supplies its own heading inside (a11y rule: cards have headings), Card
// itself doesn't render one.
export function Card({ className, children, ...rest }: CardProps) {
  const classes = ['card', className].filter(Boolean).join(' ')
  return (
    <div className={classes} {...rest}>
      {children}
    </div>
  )
}

'use client'

import { useState } from 'react'

/** One reading. Big number, small label, no sentence.
 *
 *  The caption is clamped to three lines so a long one cannot push the next
 *  reading off a 208px rail; clicking the tile lets it run to its end. */
export default function Metric({
  label, value, unit, tone = 'plain', sub,
}: {
  label: string
  value: string | number
  unit?: string
  tone?: 'plain' | 'ok' | 'warn' | 'alarm' | 'focus'
  sub?: string
}) {
  const [open, setOpen] = useState(false)
  const expandable = !!sub
  const flip = () => setOpen((o) => !o)
  return (
    <div
      className="metric"
      data-tone={tone}
      data-open={open ? '1' : '0'}
      role={expandable ? 'button' : undefined}
      tabIndex={expandable ? 0 : undefined}
      aria-expanded={expandable ? open : undefined}
      onClick={expandable ? flip : undefined}
      onKeyDown={expandable ? (e) => {
        if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); flip() }
      } : undefined}
    >
      <span className="m-label">{label}</span>
      <span className="m-value">
        {value}
        {unit && <em>{unit}</em>}
      </span>
      {sub && <span className="m-sub">{sub}</span>}
    </div>
  )
}

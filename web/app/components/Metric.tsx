'use client'

/** One reading. Big number, small label, no sentence. */
export default function Metric({
  label, value, unit, tone = 'plain', sub,
}: {
  label: string
  value: string | number
  unit?: string
  tone?: 'plain' | 'ok' | 'warn' | 'alarm' | 'focus'
  sub?: string
}) {
  return (
    <div className="metric" data-tone={tone}>
      <span className="m-label">{label}</span>
      <span className="m-value">
        {value}
        {unit && <em>{unit}</em>}
      </span>
      {sub && <span className="m-sub">{sub}</span>}
    </div>
  )
}

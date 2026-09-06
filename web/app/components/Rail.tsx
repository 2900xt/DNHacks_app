'use client'

import type { ReactNode } from 'react'

/**
 * One collapsible section of the right-hand rail.
 *
 * The rail replaces three panels that used to float wherever there was room
 * — depot top-left, inspector top-right, shortlist bottom-left — and met in
 * the middle on any short screen. One column, one edge, every panel a fold:
 * what the operator is not reading costs one header row, not a corner.
 */
export function Section({
  title, tag, tone = 'dim', open, onToggle, onClose, info, children,
}: {
  title: string
  tag?: string
  tone?: 'ok' | 'warn' | 'alarm' | 'dim' | 'focus'
  open: boolean
  onToggle: () => void
  onClose?: () => void
  info?: ReactNode
  children: ReactNode
}) {
  return (
    <section className="sec" data-open={open ? '1' : '0'}>
      <div className="sec-head">
        <button
          className="sec-toggle"
          onClick={onToggle}
          aria-expanded={open}
          title={open ? 'Collapse' : 'Expand'}
        >
          <span className="sec-chev" aria-hidden>▸</span>
          <span className="sec-title" title={title}>{title}</span>
        </button>
        {tag && <span className="tag" data-t={tone}>{tag}</span>}
        {info}
        {onClose && (
          <button className="ov-close" onClick={onClose} aria-label={`Close ${title}`}>✕</button>
        )}
      </div>
      <div className="sec-body">{children}</div>
    </section>
  )
}

/** A small circled i. Hover or focus shows the explanation; nothing to click,
 *  nothing to dismiss. The content is the same words the scorer states. */
export function Info({ label, children }: { label: string; children: ReactNode }) {
  return (
    <span className="info" onClick={(e) => e.stopPropagation()}>
      <span className="info-i" tabIndex={0} role="img" aria-label={label}>i</span>
      <span className="info-tip" role="tooltip">{children}</span>
    </span>
  )
}

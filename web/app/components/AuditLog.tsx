'use client'

import { useEffect, useRef } from 'react'

export type AuditKind = 'beat' | 'select' | 'cascade' | 'reset' | 'depot'

export interface AuditEntry {
  /** Wall clock, HH:MM:SS. Filled on the client — never rendered on the server. */
  t: string
  kind: AuditKind
  text: string
}

/**
 * The console's own paper trail.
 *
 * The pitch is that nothing on screen is a model guessing, and an auditor's next
 * question after "where did this number come from" is "who looked at it and
 * when". This is the strip that answers it. Right now it records what the
 * operator did — beat, inspection, simulated failure; the same component takes
 * data-provenance and depot-state rows when those land.
 *
 * Ascending, newest at the bottom, pinned to the tail like a terminal.
 */
export default function AuditLog({ entries }: { entries: AuditEntry[] }) {
  const bodyRef = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    const el = bodyRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [entries])

  return (
    <div className="audit" aria-label="Audit log">
      <div className="audit-head">
        <span className="audit-title">Audit log</span>
        <span className="audit-count">{entries.length}</span>
      </div>
      <div className="audit-body" ref={bodyRef} role="log" aria-live="polite">
        {entries.length === 0 ? (
          <div className="audit-row" data-kind="reset">
            <span className="a-t">—:—:—</span>
            <span className="a-text">Session opening.</span>
          </div>
        ) : (
          entries.map((e, i) => (
            <div className="audit-row" key={`${e.t}|${i}`} data-kind={e.kind}>
              <span className="a-t">{e.t}</span>
              <span className="a-kind">{e.kind}</span>
              <span className="a-text">{e.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

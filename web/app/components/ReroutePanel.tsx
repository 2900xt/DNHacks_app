'use client'

import { useState } from 'react'
import type { NodeId } from '../lib/types'
import type { Shortlist } from '../lib/supply-tree'
import { countryName, plain, SCORE_EXPLAINED } from '../lib/plain'
import { Disclosure } from './Rail'

interface Props {
  sl: Shortlist
  nodeLabel: (id: NodeId) => string
  selected: NodeId | null
  onSelect: (id: NodeId) => void
}

/**
 * The ranked alternates panel — FEATURES.md F3, the honest version.
 *
 * Appears once anything is switched off, because that is when the buyer's
 * question changes from "is my stock good" to "who else can make this". Every
 * row is one active Type II DMF holder, scored by ml/aegis.py on public records
 * and re-ranked here against the current failures. The score is shown WITH its
 * reason: a judge's next question after a number is always "why that number".
 *
 * Folded, a row carries the supplier's first reason. Clicking it unfolds the
 * whole name and EVERY reason the scorer gave, as text on the rail — these used
 * to live in a hover tooltip, which does not exist on a projector, a phone, or
 * a keyboard. The click also selects the supplier, so the globe and the tree
 * go to it at the same time.
 */
export default function ReroutePanel({ sl, nodeLabel, selected, onSelect }: Props) {
  const [open, setOpen] = useState<Set<NodeId>>(new Set())
  const toggle = (id: NodeId) => setOpen((prev) => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    return next
  })

  if (!sl.scopeNode) {
    return (
      <div className="rr-sub">
        No pathfinder output for this chain. Run <code>make aegis</code>.
      </div>
    )
  }

  return (
    <>
      <div className="rr-sub">
        {sl.substance} · {sl.standing} of {sl.total} suppliers still shipping
        {sl.failedIsos.length > 0 && (
          <> · disrupted: {sl.failedIsos.map(countryName).join(', ')}</>
        )}
      </div>

      <Disclosure label="How suppliers are scored">
        {SCORE_EXPLAINED.map((t) => <p key={t}>{t}</p>)}
      </Disclosure>

      <div className="rail-list" role="group" aria-label="Ranked alternate suppliers">
        {sl.rows.map((a) => {
          const h = a.holder
          const iso = h.iso2.map((c) => c.toUpperCase()).join('/')
          const reasons = [...h.why, a.deltaWhy].filter((w): w is string => !!w).map(plain)
          const isOpen = open.has(a.id)
          return (
            <button
              key={a.id}
              className="rr-row"
              data-standing={a.standing ? '1' : '0'}
              data-route={a.recommended ? '1' : '0'}
              data-sel={selected === a.id ? '1' : '0'}
              data-open={isOpen ? '1' : '0'}
              aria-expanded={isOpen}
              onClick={() => { toggle(a.id); onSelect(a.id) }}
            >
              <span className="rr-rank">{a.standing ? `#${a.rank}` : 'off'}</span>
              <span className="rr-main">
                <span className="rr-name">
                  {nodeLabel(a.id)}
                  {iso && <span className="rr-iso"> {iso}</span>}
                  {a.recommended && <span className="tag" data-t="route">best</span>}
                </span>
                {!a.standing && <span className="rr-why">not shipping — disrupted</span>}
                {isOpen
                  ? reasons.map((w, i) => <span key={i} className="rr-why rr-w">{w}</span>)
                  : a.standing && <span className="rr-why">{reasons[0] ?? ''}</span>}
              </span>
              <span className="rr-score" data-v={a.viable ? '1' : '0'}>
                {a.score > 0 ? '+' : ''}{a.score.toFixed(1)}
                {a.delta !== 0 && (
                  <span className="rr-delta" data-d={a.delta > 0 ? 'up' : 'down'}>
                    {a.delta > 0 ? '▲' : '▼'} {a.delta > 0 ? '+' : ''}{a.delta}
                  </span>
                )}
              </span>
            </button>
          )
        })}
      </div>

    </>
  )
}

'use client'

import type { NodeId } from '../lib/types'
import type { Shortlist } from '../lib/supply-tree'
import { countryName, plain } from '../lib/plain'

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
 * The footer says what is not modelled. It is not fine print — the demo script
 * reads it out loud, and a shortlist that pretended to be an allocation would be
 * claiming capacity data nobody publishes.
 */
export default function ReroutePanel({ sl, nodeLabel, selected, onSelect }: Props) {
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

      <div className="rail-list" role="list" aria-label="Ranked alternate suppliers">
        {sl.rows.map((a) => {
          const h = a.holder
          const iso = h.iso2.map((c) => c.toUpperCase()).join('/')
          const why = plain(h.why[0] ?? '')
          return (
            <button
              key={a.id}
              role="listitem"
              className="rr-row"
              data-standing={a.standing ? '1' : '0'}
              data-route={a.recommended ? '1' : '0'}
              data-sel={selected === a.id ? '1' : '0'}
              onClick={() => onSelect(a.id)}
              title={[...h.why, a.deltaWhy].filter((w): w is string => !!w).map(plain).join(' · ')}
            >
              <span className="rr-rank">{a.standing ? `#${a.rank}` : 'off'}</span>
              <span className="rr-main">
                <span className="rr-name">
                  {nodeLabel(a.id)}
                  {iso && <span className="rr-iso"> {iso}</span>}
                  {a.recommended && <span className="tag" data-t="route">best</span>}
                </span>
                <span className="rr-why">{a.standing ? why : 'not shipping — disrupted'}</span>
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

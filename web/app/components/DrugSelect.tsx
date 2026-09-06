'use client'

import { useEffect } from 'react'
import type { NodeId } from '../lib/types'
import { DRUGS, band, profileOf, type GraphFacts } from '../lib/drugs'

/**
 * Which of the six the demo is about.
 *
 * Sits at the top of the physical rail because that is where the story starts —
 * the bin on the table holds one drug, and this says which. Keys 1..6 select,
 * for the same reason the beats are on the spacebar: at hour 20 on a projector
 * you must not be hunting for a hitbox.
 *
 * Default is amoxicillin and it must stay that way — DEMO_PATH.md is locked on
 * "a pallet of amoxicillin". Everything else here is the what-if.
 */
export default function DrugSelect({
  value,
  onChange,
  facts,
}: {
  value: NodeId
  onChange: (id: NodeId) => void
  facts: GraphFacts
}) {
  const p = profileOf(value)
  const v = band(p, facts)

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const i = '123456'.indexOf(e.key)
      if (i < 0 || !DRUGS[i]) return
      e.preventDefault()
      onChange(DRUGS[i].id)
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [onChange])

  return (
    <>
      <div className="rail-head">
        <span className="rail-title">Focus drug</span>
        <span className="tag" data-t={v.band === 'high' ? 'alarm' : 'warn'}>
          {v.band === 'high' ? 'high impact' : 'substitutable'}
        </span>
      </div>

      <div className="drugsel" role="radiogroup" aria-label="Focus drug">
        {DRUGS.map((d, i) => (
          <button
            key={d.id}
            className="drug-pill"
            role="radio"
            aria-checked={d.id === value}
            data-on={d.id === value ? '1' : '0'}
            onClick={() => onChange(d.id)}
            title={`${d.label} — ${d.route} · key ${i + 1}`}
          >
            {d.short}
          </button>
        ))}
      </div>

      <div className="drug-facts">
        <p className="df-head">
          {p.label}
          <span className="df-route">{p.route}</span>
        </p>
        <p className="df-line">{p.indication}</p>
        <p className="df-line">
          <span className="df-key">Substitute</span>
          {p.redundancy === 'none' ? (
            <span className="df-none">none in its core indication</span>
          ) : null}
          {' '}{p.redundancyNote}
        </p>
        <p className="df-line">
          <span className="df-key">EO 13944</span>
          {p.eo13944 ?? 'not listed (Oct 30 2020)'}
        </p>
        {/* Decision 0003: a flagged node shows the rule and what fired it. */}
        <p className="df-line">
          <span className="df-key">Why</span>
          <span className="df-drivers">
            {v.drivers.map((d) => (
              <span key={d} className="df-driver">{d}</span>
            ))}
          </span>
        </p>
        <p className="df-rule">{v.rule}</p>
      </div>
    </>
  )
}

'use client'

import type { NodeRisk } from '../lib/risk-view'
import { RISK_TONE, pct } from '../lib/risk-view'
import Metric from './Metric'
import { Disclosure } from './Rail'

/**
 * The model's answer for one node: a percentage, what it is worth, and why.
 *
 * Three things are on screen that a risk number usually hides.
 *
 * The INTERVAL. 46% computed from 61 plants is really 33-60%, and a bare "46%"
 * claims three digits of precision the data cannot pay for. The bar shows the
 * interval as a band and the estimate as a line inside it.
 *
 * The BASIS. A plant with its own FDA record and an NDC inheriting its
 * marketer's are not the same claim, and neither is the population average
 * standing in for a plant nobody has inspected. The chip says which.
 *
 * The CEILING. 46% is the highest rate ever actually observed at any score, so
 * nothing is drawn above it. A node sitting there reads "at least" — the model
 * cannot separate it from the others up there, and says so instead of inventing
 * a decimal.
 */
export default function RiskPanel({ risk, ceiling }: { risk: NodeRisk | null; ceiling: number }) {
  // Absence is a finding, not a blank. 26 company nodes could not be resolved to
  // one establishment and the model refuses to attach another plant's history —
  // rendering that as nothing would read as "fine".
  if (!risk) {
    return (
      <Metric
        label="Disruption risk · 12 mo"
        value="not scored"
        tone="plain"
        sub="No FDA establishment could be matched to this node with confidence, so no history is attached. Not scored is not the same as low."
      />
    )
  }

  const { p12, range, band, basis, why, from, upstream, atCeiling } = risk
  // Scale the bar to the ceiling: that is the top of what the data supports, so
  // it is the honest end of the axis. A 0-100% axis would draw every plant in
  // the chain as a sliver and imply the empty right-hand half is reachable.
  const x = (v: number) => `${Math.min(100, (v / ceiling) * 100)}%`

  return (
    <>
      <Metric
        label="Disruption risk · 12 mo"
        value={atCeiling ? `≥ ${pct(p12)}` : pct(p12)}
        tone={RISK_TONE[band]}
      />

      <div className="rk-bar" title={`${pct(range[0])}–${pct(range[1])} at 95% confidence`}>
        <span className="rk-track">
          <span className="rk-range" style={{ left: x(range[0]), right: `calc(100% - ${x(range[1])})` }} />
          <span className="rk-point" data-t={RISK_TONE[band]} style={{ left: x(p12) }} />
        </span>
        <span className="rk-scale">
          <em>0</em>
          <em>{pct(ceiling)} — the highest rate ever observed</em>
        </span>
      </div>

      <div className="chips">
        <span className="tag" data-t={RISK_TONE[band]}>{band === 'raised' ? 'raised risk' : `${band} risk`}</span>
        <span className="tag" data-t="dim">
          {basis === 'measured' ? 'own record'
            : basis === 'supplier' ? 'supplier’s record'
            : basis === 'substance' ? 'same substance' : 'no record'}
        </span>
        {upstream !== undefined && (
          <span
            className="tag"
            data-t={upstream === 1 ? 'warn' : 'dim'}
            title={upstream === 1
              ? 'One plant upstream. There is nothing behind it if it stops.'
              : `${upstream} plants upstream. The figure is the most at-risk of them, not the chance all ${upstream} fail at once.`}
          >
            {upstream === 1 ? 'single source' : `${upstream} plants upstream`}
          </span>
        )}
        {atCeiling && (
          <span className="tag" data-t="alarm" title="Above everything the data can tell apart. Ranked by the raw score inside this group.">
            at the ceiling
          </span>
        )}
      </div>

      {from && <p className="rk-from">Carried from <strong>{from}</strong>.</p>}

      {why.length > 0 && (
        // Ordered by how much each line moved the score, not by template. Written
        // in template order the first line for one plant read "no failed FDA
        // inspection on record" while the thing driving its number was a refusal.
        <Disclosure label={`Why ${atCeiling ? '≥ ' : ''}${pct(p12)}`} open>
          <ul className="disc-list">
            {why.map((w) => <li key={w}>{w}</li>)}
          </ul>
        </Disclosure>
      )}
    </>
  )
}

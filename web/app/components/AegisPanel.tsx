'use client'

import type { Alternate, NodeId, RerouteNode } from '../lib/types'

/**
 * AEGIS — firm-level re-route for whatever the operator just switched off.
 *
 * This sits alongside the globe's country-level allocation, and the two answer
 * different questions on purpose:
 *
 *   allocate()   which JURISDICTIONS still carry supply, and what share each
 *                one now takes. Even split, because no per-holder capacity data
 *                exists.
 *   AEGIS        which SPECIFIC FIRMS hold an active filing for this substance,
 *                and whether routing to each would actually help.
 *
 * Scoring is done in `ml/aegis.py` and shipped as `web/data/reroute.json`.
 * Nothing is recomputed here - the panel renders what the algorithm decided, so
 * the number on screen is the number the self-check asserts.
 */

const fmtScore = (n: number) => (n > 0 ? `+${n.toFixed(1)}` : n.toFixed(1))

function Row({ a, rank }: { a: Alternate; rank: number }) {
  const viable = a.score > 0
  const risky = a.risk_flags.length > 0
  const unresolved = !a.matched_firm
  return (
    <li className={`aegis-row ${viable ? 'ok' : risky ? 'risk' : 'unknown'}`}>
      <div className="aegis-head">
        <span className="aegis-rank">{rank}</span>
        <span className="aegis-holder" title={a.holder}>{a.holder}</span>
        <span className="aegis-geo">{a.countries.join('/') || '—'}</span>
        <span className="aegis-score">{fmtScore(a.score)}</span>
      </div>
      <ul className="aegis-why">
        {a.why.map((w, i) => (
          <li key={i} className={w.startsWith('🔴') ? 'bad' : w.startsWith('⚠️') ? 'warn' : ''}>
            {w}
          </li>
        ))}
      </ul>
      {unresolved && (
        <p className="aegis-note">
          Not resolved to a registered establishment — capability unverified.
        </p>
      )}
    </li>
  )
}

export default function AegisPanel({
  reroute,
  downNode,
  label,
}: {
  reroute: RerouteNode | null
  downNode: NodeId | null
  label: string
}) {
  if (!downNode) return null

  if (!reroute) {
    return (
      <section className="aegis">
        <h3>AEGIS · re-route</h3>
        <p className="aegis-empty">
          No filing-level alternates for <strong>{label}</strong>. AEGIS covers the
          precursor and the six APIs; a finished product re-routes through its API,
          not on its own.
        </p>
      </section>
    )
  }

  const { alternates, viable, active_holders, affected_drugs, affected_products } = reroute
  const registered = alternates.filter((a) => a.matched_firm).length
  const outside = alternates.filter(
    (a) => a.matched_firm && a.countries.length &&
      !a.countries.some((c) => c === 'CHN' || c === 'IND'),
  ).length

  return (
    <section className="aegis">
      <h3>AEGIS · re-route around {reroute.label}</h3>

      <p className="aegis-impact">
        <strong>{affected_drugs.length}</strong> drug
        {affected_drugs.length === 1 ? '' : 's'} and{' '}
        <strong>{affected_products}</strong> product
        {affected_products === 1 ? '' : 's'} depend on this node.
      </p>

      {/* The headline, computed from the same rows the list below renders, so it
          cannot drift from what the operator can see. */}
      <p className={`aegis-verdict ${outside === 0 ? 'bad' : 'ok'}`}>
        {active_holders} active filing{active_holders === 1 ? '' : 's'} ·{' '}
        {registered} registered US establishment{registered === 1 ? '' : 's'} ·{' '}
        <strong>{outside}</strong> of those outside China/India
        {outside === 0 && ' — there is no route out of the chokepoint'}
      </p>

      {viable === 0 ? (
        <p className="aegis-empty">
          No viable alternate. Every filing is unregistered, inside the same
          chokepoint, or carries its own enforcement history.
        </p>
      ) : (
        <ol className="aegis-list">
          {alternates.map((a, i) => <Row key={a.holder} a={a} rank={i + 1} />)}
        </ol>
      )}

      <p className="aegis-limit">
        Not modelled: capacity · lead time · willingness to supply · current
        utilisation. No public source exists for any of them, so this is a
        procurement shortlist, not an allocation.
      </p>
    </section>
  )
}

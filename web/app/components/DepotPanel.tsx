'use client'

import { useDepot, useTicker } from '../lib/useDepot'
import { API_BASE, STATUS_LABEL, causeOf, elapsed, fmt, type DepotNode } from '../lib/depot'

/**
 * Beats 0 and 2 — the physical half.
 *
 * Degrades on purpose: the FastAPI depot service is a separate process, it is
 * not on Vercel, and venue wifi is assumed bad. When it is unreachable this rail
 * says so plainly instead of rendering an empty frame, because a panel that
 * looks broken mid-demo is worse than one that says "replay not running".
 */
export default function DepotPanel({ onBreach }: { onBreach?: (drugs: string[]) => void }) {
  useTicker(1000)
  const { nodes, link, lastEventAt } = useDepot()
  const list = Object.values(nodes)
  const bin: DepotNode | undefined = list.find((n) => n.latest) ?? list[0]

  if (!bin) {
    return (
      <div className="pane">
        <h2>Depot node</h2>
        <p className="tag" data-t={link === 'down' ? 'warn' : 'dim'}>
          {link === 'down' ? 'API unreachable' : 'waiting for telemetry'}
        </p>
        <p style={{ color: 'var(--text-faint)', fontSize: 11, marginTop: 8 }}>
          Start the depot service, then <code>make depot-demo</code> to replay a
          24-hour storage history. The graph works without it.
        </p>
      </div>
    )
  }

  const r = bin.latest ?? {}
  const spec = bin.spec ?? {}
  const breached = bin.status === 'mkt_breach'
  const held =
    typeof bin.excursion_s === 'number'
      ? bin.excursion_s + (lastEventAt ? (Date.now() - lastEventAt) / 1000 : 0)
      : null

  const tone = breached ? 'alarm' : bin.status === 'ok' ? 'ok' : 'warn'

  return (
    <>
      <div className="pane">
        <h2>Depot node</h2>
        <p className="insp-title" style={{ fontSize: 13 }}>{bin.label}</p>
        <div style={{ display: 'flex', gap: 6, marginTop: 6, flexWrap: 'wrap' }}>
          <span className="tag" data-t={tone}>{STATUS_LABEL[bin.status] ?? bin.status}</span>
          <span className="tag" data-t={link === 'live' ? 'focus' : 'warn'}>{link}</span>
        </div>
        {held !== null && (
          <p style={{ fontSize: 11, color: 'var(--text-dim)', marginTop: 6 }}>
            out of band {elapsed(held)}
          </p>
        )}
        {bin.reason && <p className="cite">{causeOf(bin.reason)}</p>}
      </div>

      <div className="pane">
        <h2>Mean kinetic temperature</h2>
        <dl className="kv">
          <div style={{ display: 'contents' }}>
            <dt>MKT</dt>
            <dd style={{ color: breached ? 'var(--alarm)' : 'var(--text)' }}>
              {fmt(bin.mkt_c)} °C{bin.mkt_provisional ? ' *' : ''}
            </dd>
          </div>
          <div style={{ display: 'contents' }}>
            <dt>Ceiling</dt><dd>{fmt(spec.mkt_c_max, 1)} °C</dd>
          </div>
          <div style={{ display: 'contents' }}>
            <dt>Arithmetic mean</dt><dd>{fmt(bin.mean_c)} °C</dd>
          </div>
          <div style={{ display: 'contents' }}>
            <dt>Band</dt>
            <dd>{fmt(spec.temp_c_min, 0)}–{fmt(spec.temp_c_max, 0)} °C</dd>
          </div>
          <div style={{ display: 'contents' }}>
            <dt>Window</dt>
            <dd>{fmt(bin.window_h, 1)} h · {bin.n_samples ?? 0}</dd>
          </div>
        </dl>
        <p className="cite" style={{ marginTop: 8 }}>
          USP &lt;659&gt; / ICH Q1A(R2), ΔH 83.144 kJ·mol⁻¹. MKT is time-weighted —
          it does not clear when the room cools.
        </p>
      </div>

      <div className="pane">
        <h2>Latest reading</h2>
        <dl className="kv">
          <div style={{ display: 'contents' }}>
            <dt>Temp (BME680)</dt><dd>{fmt(r.temp_c)} °C</dd>
          </div>
          <div style={{ display: 'contents' }}>
            <dt>Cross-check</dt><dd>{fmt(r.temp_c_xcheck)} °C</dd>
          </div>
          <div style={{ display: 'contents' }}>
            <dt>RH</dt><dd>{fmt(r.rh_pct)} %</dd>
          </div>
        </dl>
      </div>

      <div className="pane">
        <h2>Downstream ({bin.covers_drugs.length})</h2>
        {bin.covers_drugs.length === 0 ? (
          <p style={{ color: 'var(--text-faint)', fontSize: 11 }}>
            No <code>covers_drugs</code> on this bin — the hardware→graph seam is
            not wired yet.
          </p>
        ) : (
          <p style={{ fontSize: 11.5, color: 'var(--text-dim)' }}>
            {bin.covers_drugs.join(', ')}
          </p>
        )}
        {breached && bin.covers_drugs.length > 0 && onBreach && (
          <button
            className="ctl"
            style={{ marginTop: 8 }}
            onClick={() => onBreach(bin.covers_drugs)}
          >
            Fan out from this breach
          </button>
        )}
      </div>

      <div className="pane">
        <button
          className="ctl"
          onClick={() =>
            fetch(`${API_BASE}/depot/nodes/${bin.node_id}/reset`, { method: 'POST' })
              .catch(() => undefined)
          }
        >
          Reset latch (between judges)
        </button>
      </div>
    </>
  )
}

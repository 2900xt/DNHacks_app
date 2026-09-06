'use client'

import { useDepot, useTicker } from '../lib/useDepot'
import { API_BASE, STATUS_LABEL, fmt, type DepotNode } from '../lib/depot'
import Metric from './Metric'

/** Beats 0 and 2 — the physical half. Readings only; the numbers carry it. */
export default function DepotPanel({ onBreach }: { onBreach?: (drugs: string[]) => void }) {
  useTicker(1000)
  const { nodes, link } = useDepot()
  const list = Object.values(nodes)
  const bin: DepotNode | undefined = list.find((n) => n.latest) ?? list[0]

  if (!bin) {
    return (
      <div className="rail-head">
        <span className="rail-title">Depot node</span>
        <span className="tag" data-t="warn">{link === 'down' ? 'offline' : 'waiting'}</span>
      </div>
    )
  }

  const r = bin.latest ?? {}
  const spec = bin.spec ?? {}
  const breached = bin.status === 'mkt_breach'
  const overCeiling =
    bin.mkt_c != null && spec.mkt_c_max != null && bin.mkt_c > spec.mkt_c_max
  const tone = breached ? 'alarm' : bin.status === 'ok' ? 'ok' : 'warn'

  return (
    <>
      <div className="rail-head">
        <span className="rail-title">{bin.label?.replace(/^SNS Depot \d+ — /, '') ?? 'Bin'}</span>
        <span className="tag" data-t={tone}>{STATUS_LABEL[bin.status] ?? bin.status}</span>
      </div>

      <Metric
        label="Mean kinetic temp"
        value={fmt(bin.mkt_c)}
        unit="°C"
        tone={overCeiling ? 'alarm' : 'ok'}
        sub={`mean ${fmt(bin.mean_c)}°C · ceiling ${fmt(spec.mkt_c_max, 1)}°C`}
      />
      <Metric label="Temperature" value={fmt(r.temp_c)} unit="°C"
        sub={`band ${fmt(spec.temp_c_min, 0)}–${fmt(spec.temp_c_max, 0)}°C`} />
      <Metric label="Cross-check" value={fmt(r.temp_c_xcheck)} unit="°C"
        sub="DHT11" />
      <Metric label="Humidity" value={fmt(r.rh_pct)} unit="%"
        sub={spec.rh_pct_max != null ? `max ${fmt(spec.rh_pct_max, 0)}%` : undefined} />
      <Metric label="Window" value={fmt(bin.window_h, 1)} unit="h"
        sub={`${bin.n_samples ?? 0} readings`} />
      <Metric label="Covers" value={bin.covers_drugs.length} sub="drug products" />

      <div className="rail-foot">
        {breached && bin.covers_drugs.length > 0 && onBreach && (
          <button className="ctl" onClick={() => onBreach(bin.covers_drugs)}>
            Fan out from breach
          </button>
        )}
        <button
          className="ctl"
          onClick={() =>
            fetch(`${API_BASE}/depot/nodes/${bin.node_id}/reset`, { method: 'POST' })
              .catch(() => undefined)
          }
        >
          Reset latch
        </button>
      </div>
    </>
  )
}

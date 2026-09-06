'use client'

import { useState } from 'react'
import { useTicker, type Link } from '../lib/useDepot'
import { API_BASE, STATUS_LABEL, causeOf, fmt, type DepotNode } from '../lib/depot'
import Metric from './Metric'

const TONE: Record<string, 'ok' | 'warn' | 'alarm' | 'plain'> = {
  ok: 'ok',
  excursion: 'warn',
  mkt_breach: 'alarm',
  sensor_fault: 'warn',
  stale: 'warn',
  offline: 'plain',
}

/**
 * The physical half: every bin in ONE depot — the one under the country the
 * operator has selected — not every bin everywhere.
 *
 * Depots are local to a point of interest, the place the supplies flow in and
 * out of. A node is configured with the country it sits in (DEPOT_COUNTRY on
 * the device) and says so on every reading; the console slices the global
 * stream by that and hands this panel the slice. A sensor in the US is listed
 * under the US and under no other country, so "this bin is condemned" is also
 * a sentence about where.
 *
 * Hover previews a bin's readings; clicking pins it so the pointer can leave.
 * A depot has many bins and only some carry a live node — showing the whole
 * list is what makes "this one is condemned" mean anything.
 */
export default function DepotPanel({ bins, link, place, onBreach }: {
  bins: DepotNode[]
  link: Link
  /** The country's name, for the empty state. */
  place: string
  onBreach?: (drugs: string[]) => void
}) {
  useTicker(1000)
  const [pinned, setPinned] = useState<string | null>(null)
  const [hovered, setHovered] = useState<string | null>(null)

  const byId = new Map(bins.map((n) => [n.node_id, n]))
  const fallback = bins.find((n) => n.latest) ?? bins[0]
  const active: DepotNode | undefined =
    (hovered && byId.get(hovered)) || (pinned && byId.get(pinned)) || fallback

  if (bins.length === 0) {
    // A metric, not a rail-head: the section hides its first rail-head because
    // it already has a title, and an empty state that renders nothing is a bug.
    return (
      <div className="metric">
        <span className="m-label">
          {link === 'down'
            ? 'Depot service offline'
            : link === 'live' ? `No depot in ${place}` : 'Waiting for the depot service'}
        </span>
        <span className="m-sub">
          {link === 'live'
            ? 'No node reports from here. A node is listed under the country it is configured for, and only there.'
            : 'The depot stream is not reachable. Check NEXT_PUBLIC_API_BASE and that the API is up.'}
        </span>
      </div>
    )
  }

  const r = active?.latest ?? {}
  const spec = active?.spec ?? {}
  const breached = active?.status === 'mkt_breach'
  const overCeiling =
    active?.mkt_c != null && spec.mkt_c_max != null && active.mkt_c > spec.mkt_c_max

  // MKT above the ceiling is not yet a condemnation. The service deliberately
  // refuses to latch a breach on a window shorter than an hour, because MKT is a
  // multi-hour metric — so an un-latched bin showed a red number directly under
  // an "In specification" tag, and the panel read as contradicting itself on the
  // one question it exists to answer. Amber is the honest third state, and the
  // reason it is amber is the best line in the demo: say it on the tile.
  const ceiling = `ceiling ${fmt(spec.mkt_c_max, 1)}°C`
  const mktTone = breached ? 'alarm' : overCeiling ? 'warn' : 'ok'
  const mktSub = breached
    ? `${ceiling} · does not clear when the room cools`
    : overCeiling
      ? `${ceiling} · ${fmt(active?.window_h, 1)} h window, not condemned yet`
      : `mean ${fmt(active?.mean_c)}°C · ${ceiling}`
  // Only where the tile above does not already explain itself. On a condemned
  // bin the MKT sub-line says the same thing in fewer words, and the rail is
  // 208px wide — two components saying it twice just pushes readings off screen.
  const cause =
    active && active.status !== 'ok' && active.status !== 'mkt_breach'
      ? causeOf(active.reason)
      : ''

  return (
    <>
      <div className="rail-head">
        <span className="rail-title">Depot nodes</span>
        <span className="tag" data-t={link === 'live' ? 'focus' : 'warn'}>{bins.length}</span>
      </div>

      <div className="bin-list" onMouseLeave={() => setHovered(null)}>
        {bins.map((n) => (
          <button
            key={n.node_id}
            className="bin-row"
            data-active={active?.node_id === n.node_id ? '1' : '0'}
            data-pinned={pinned === n.node_id ? '1' : '0'}
            onMouseEnter={() => setHovered(n.node_id)}
            onFocus={() => setHovered(n.node_id)}
            onClick={() => setPinned(pinned === n.node_id ? null : n.node_id)}
          >
            <span className="bin-dot" data-t={TONE[n.status] ?? 'plain'} />
            <span className="bin-name">{n.label?.replace(/^SNS Depot \d+ — /, '') ?? n.node_id}</span>
            <span className="bin-temp">{n.latest?.temp_c != null ? `${fmt(n.latest.temp_c)}°` : '—'}</span>
          </button>
        ))}
      </div>

      {active && (
        <>
          <div className="rail-head">
            <span className="rail-title">{active.label?.replace(/^SNS Depot \d+ — /, '')}</span>
            <span className="tag" data-t={TONE[active.status] ?? 'plain'}>
              {STATUS_LABEL[active.status] ?? active.status}
            </span>
          </div>

          <Metric
            label="Mean kinetic temp"
            value={fmt(active.mkt_c)}
            unit="°C"
            tone={mktTone}
            sub={mktSub}
          />
          {cause && (
            <div className="metric">
              <span className="m-label">Cause</span>
              <span className="m-sub">{cause}</span>
            </div>
          )}
          <Metric label="Temperature" value={fmt(r.temp_c)} unit="°C"
            sub={`band ${fmt(spec.temp_c_min, 0)}–${fmt(spec.temp_c_max, 0)}°C`} />
          <Metric label="Cross-check" value={fmt(r.temp_c_xcheck)} unit="°C" sub="DHT11" />
          <Metric label="Humidity" value={fmt(r.rh_pct)} unit="%" />
          <Metric label="Window" value={fmt(active.window_h, 1)} unit="h"
            sub={`${active.n_samples ?? 0} readings`} />
          <Metric label="Covers" value={active.covers_drugs.length} sub="drug products" />

          <div className="rail-foot">
            {breached && active.covers_drugs.length > 0 && onBreach && (
              <button className="ctl" onClick={() => onBreach(active.covers_drugs)}>
                Fan out
              </button>
            )}
            <button
              className="ctl"
              onClick={() =>
                fetch(`${API_BASE}/depot/nodes/${active.node_id}/reset`, { method: 'POST' })
                  .catch(() => undefined)
              }
            >
              Reset latch
            </button>
          </div>
        </>
      )}
    </>
  )
}

'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { BacktestResult, Compliance, GraphEdge, GraphNode, NodeId, Signal } from '../lib/types'
import { BEATS, type BeatCtx, type NodeState } from '../lib/demo'
import GraphView from './GraphView'
import GlobeView from './GlobeView'
import NodeMetrics from './NodeMetrics'
import DepotPanel from './DepotPanel'
import EvidenceBar from './EvidenceBar'

export interface Payload {
  nodes: GraphNode[]
  edges: GraphEdge[]
  compliance: Record<NodeId, Compliance>
  signals: Record<NodeId, Signal[]>
  counts: { nodes: number; edges: number; signals: number; compliance: number }
  layerCounts: Record<number, number>
  backtest: BacktestResult
  /** Collapsed NDC/labeler counts, keyed by drug id. */
  ndcCount: Record<NodeId, number>
  labelerCount: Record<NodeId, number>
  /** Blast radius per spine node, measured on the FULL graph (products included). */
  downstreamOf: Record<NodeId, number>
  ctx: BeatCtx
}

/** Downstream reachability. Same traversal as lib/graph.ts cascade(): follow
 *  OUTGOING edges, because edges point the way material flows. */
function reachable(edges: GraphEdge[], from: NodeId): Set<NodeId> {
  const out = new Map<NodeId, NodeId[]>()
  for (const e of edges) (out.get(e.src) ?? out.set(e.src, []).get(e.src)!).push(e.dst)
  const seen = new Set<NodeId>([from])
  const q = [from]
  while (q.length) {
    for (const d of out.get(q.shift()!) ?? []) {
      if (seen.has(d)) continue
      seen.add(d)
      q.push(d)
    }
  }
  return seen
}

export default function Console({ payload }: { payload: Payload }) {
  const { nodes, edges, compliance, signals, counts, layerCounts, backtest,
          ndcCount, labelerCount, downstreamOf, ctx } = payload

  const [beat, setBeat] = useState(0)
  const [selected, setSelected] = useState<NodeId | null>(null)
  const [killed, setKilled] = useState<NodeId | null>(null)
  const [panel, setPanel] = useState(true)

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const nodeLabel = useCallback((id: NodeId) => byId.get(id)?.label ?? id, [byId])

  const b = BEATS[beat]

  const lit = useMemo<Set<NodeId>>(
    () => (killed ? reachable(edges, killed) : b.lit(ctx)),
    [killed, edges, b, ctx],
  )

  const states = useMemo<Record<NodeId, NodeState>>(() => {
    if (killed) {
      const s: Record<NodeId, NodeState> = { [killed]: 'focus' }
      for (const id of lit) if (id !== killed) s[id] = 'alarm'
      return s
    }
    return b.states?.(ctx) ?? {}
  }, [killed, lit, b, ctx])

  const go = useCallback((n: number) => {
    setKilled(null)
    setBeat(Math.max(0, Math.min(BEATS.length - 1, n)))
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      if (e.key === ' ' || e.key === 'ArrowRight') { e.preventDefault(); go(beat + 1) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); go(beat - 1) }
      else if (e.key === 'r' || e.key === 'R') { e.preventDefault(); go(0); setSelected(null) }
      else if (e.key === 'Escape') { setKilled(null); setSelected(null) }
      else if (e.key === 'g' || e.key === 'G') { e.preventDefault(); setPanel((p) => !p) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [beat, go])

  const sel = selected ? byId.get(selected) ?? null : null
  const selEdges = useMemo(
    () => (selected ? edges.filter((e) => e.src === selected || e.dst === selected) : []),
    [selected, edges],
  )
  const downstream = selected ? downstreamOf[selected] ?? 0 : 0

  /** Resting-state summary for the right rail. */
  const overview = useMemo(() => {
    const byCountry = new Map<string, number>()
    for (const e of edges) {
      if (e.rel !== 'incorporated_in') continue
      const c = byId.get(e.dst)?.country
      if (c) byCountry.set(c, (byCountry.get(c) ?? 0) + 1)
    }
    const holders = ctx.companies.length
    const top = [...byCountry.entries()].sort((a, b) => b[1] - a[1])[0]
    return {
      jurisdictions: ctx.countries.length,
      holders,
      drugs: ctx.drugs.length,
      concentration: top
        ? `${top[0].toUpperCase()} ${Math.round((top[1] / holders) * 100)}%`
        : '—',
    }
  }, [edges, byId, ctx])

  const onCascade = useCallback((id: NodeId) => setKilled(id), [])
  const onBreach = useCallback((drugs: string[]) => {
    setSelected(drugs[0] ?? null)
    go(3)
  }, [go])

  return (
    <div className="console" data-panel={panel ? 'open' : 'closed'}>
      <header className="head">
        <h1>CHOKEPOINT</h1>
        <span className="sub">6-APA penicillin family</span>
        <div className="spacer" />
        <div className="progress" role="group" aria-label={`Beat ${b.n} of ${BEATS.length - 1}`}>
          {BEATS.map((x, i) => (
            <span
              key={x.key}
              className="seg"
              data-on={i <= beat && !killed ? '1' : '0'}
              title={`${x.n} · ${x.label}`}
            />
          ))}
        </div>
        <span className="sub beatname">{killed ? 'simulated failure' : b.label}</span>
      </header>

      <aside className="rail-l" aria-label="Depot readings">
        <DepotPanel onBreach={onBreach} />
      </aside>

      <section className="map-wrap" aria-label="World map">
        <GlobeView
          nodes={nodes}
          edges={edges}
          lit={lit}
          selected={selected}
          onSelect={setSelected}
        />
        <div className="caption">
          {killed ? (
            <>
              <p className="say">
                {nodeLabel(killed)} goes down — {downstreamOf[killed] ?? lit.size - 1} downstream
                nodes affected, {lit.size - 1} of them on this map.
              </p>
              <p className="note">Esc to return to the demo path.</p>
            </>
          ) : (
            <>
              <p className="say">{b.say}</p>
              {b.note && <p className="note">{b.note}</p>}
            </>
          )}
        </div>
      </section>

      <aside className="rail-r" aria-label="Selection">
        <NodeMetrics
          overview={overview}
          node={sel}
          edges={selEdges}
          signals={selected ? signals[selected] ?? [] : []}
          compliance={selected ? compliance[selected] ?? null : null}
          nodeLabel={nodeLabel}
          onSelect={setSelected}
          onCascade={onCascade}
          downstream={downstream}
          ndc={selected ? ndcCount[selected] : undefined}
          labelers={selected ? labelerCount[selected] : undefined}
        />
      </aside>

      <section className="graph-panel" aria-label="Sourcing graph">
        <div className="panel-tabs">
          <span className="tab" data-on="1">Sourcing graph</span>
          <span className="tab-meta">{counts.nodes} nodes · {counts.edges} edges</span>
          <div className="spacer" />
          <button
            className="ctl"
            onClick={() => setPanel((p) => !p)}
            aria-expanded={panel}
            title="Toggle graph panel (g)"
          >
            {panel ? '▾' : '▴'}
          </button>
        </div>
        {panel && (
          <div className="panel-body">
            <GraphView
              nodes={nodes}
              edges={edges}
              lit={lit}
              states={states}
              selected={selected}
              onSelect={setSelected}
              compliance={compliance}
              ndcCount={ndcCount}
              showCompliance={!!b.compliance}
            />
          </div>
        )}
      </section>

      <footer className="bar">
        <EvidenceBar
          counts={counts}
          layerCounts={layerCounts}
          backtest={backtest}
          open={!!b.evidence}
        />
      </footer>
    </div>
  )
}

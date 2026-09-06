'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import type { BacktestResult, Compliance, GraphEdge, GraphNode, NodeId, Signal } from '../lib/types'
import { BEATS, type BeatCtx, type NodeState } from '../lib/demo'
import GraphView from './GraphView'
import GlobeView from './GlobeView'
import NodeMetrics from './NodeMetrics'
import DepotPanel from './DepotPanel'
import EvidenceKey from './EvidenceKey'

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
  const { nodes, edges, compliance, signals, counts, layerCounts,
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

  // The rail scrolls, and it kept its offset across selections — so clicking a
  // node could land you on its numbers with its name scrolled off the top, four
  // readings with nothing saying what they are about.
  const railRef = useRef<HTMLElement | null>(null)
  useEffect(() => { railRef.current?.scrollTo({ top: 0 }) }, [selected, killed])

  const sel = selected ? byId.get(selected) ?? null : null
  const selEdges = useMemo(
    () => (selected ? edges.filter((e) => e.src === selected || e.dst === selected) : []),
    [selected, edges],
  )
  const downstream = selected ? downstreamOf[selected] ?? 0 : 0

  /** Resting-state summary for the right rail.
   *
   *  Counts FILINGS, not company boxes. "8 active US filings to supply this
   *  precursor" is a locked line in DEMO_PATH, and the spine carries ten
   *  company nodes — the extra two are FEI site operators with no DMF of their
   *  own. Counting nodes puts 10 on the projector while the presenter says 8.
   *  The concentration figure shares the same denominator for the same reason:
   *  a percentage whose base is a different set than its label is a wrong
   *  number that happens to look right. */
  const overview = useMemo(() => {
    const filers = new Set(
      nodes
        .filter((n) => (n.attrs as Record<string, unknown> | undefined)?.dmf_status === 'A')
        .map((n) => n.id),
    )
    const byCountry = new Map<string, number>()
    for (const e of edges) {
      if (e.rel !== 'incorporated_in' || !filers.has(e.src)) continue
      const c = byId.get(e.dst)?.country
      if (c) byCountry.set(c, (byCountry.get(c) ?? 0) + 1)
    }
    const filings = filers.size
    const top = [...byCountry.entries()].sort((a, b) => b[1] - a[1])[0]
    return {
      jurisdictions: ctx.countries.length,
      filings,
      drugs: ctx.drugs.length,
      concentration: top && filings
        ? `${top[0].toUpperCase()} ${Math.round((top[1] / filings) * 100)}%`
        : '—',
    }
  }, [nodes, edges, byId, ctx])

  const onCascade = useCallback((id: NodeId) => setKilled(id), [])
  const onBreach = useCallback((drugs: string[]) => {
    setSelected(drugs[0] ?? null)
    go(3)
  }, [go])

  return (
    <div className="console" data-panel={panel ? 'open' : 'closed'}>
      <header className="head">
        <div className="brand">
          <Image className="mark" src="/ripple-mark.png" alt="" width={20} height={20} priority />
          <h1>RIPPLE</h1>
        </div>
        <span className="sub">6-APA penicillin family</span>
        <div className="spacer" />
        {/* The rail keeps its fill during a simulated failure and only recedes.
            A cascade is a branch off the demo path, not a reset of it — blanking
            the rail loses the one thing the operator needs, which is where Esc
            puts them back. */}
        <div className="progress" data-killed={killed ? '1' : '0'} role="group" aria-label="Demo beats">
          {BEATS.map((x, i) => (
            <button
              key={x.key}
              className="seg"
              onClick={() => go(i)}
              data-on={i <= beat ? '1' : '0'}
              data-now={i === beat && !killed ? '1' : '0'}
              title={`${i + 1}. ${x.label}`}
              aria-label={`Beat ${i + 1} of ${BEATS.length}: ${x.label}`}
              aria-current={i === beat && !killed ? 'step' : undefined}
            />
          ))}
        </div>
        <span className="sub beatname">{killed ? 'Simulated failure' : b.label}</span>
        <div className="steps">
          <button
            className="ctl"
            onClick={() => go(beat - 1)}
            disabled={beat === 0 && !killed}
          >
            Back
          </button>
          <button
            className="ctl"
            onClick={() => go(beat + 1)}
            disabled={beat === BEATS.length - 1 && !killed}
          >
            Next
          </button>
        </div>
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
        {/* The beat's claim, on screen. It was already written — demo.ts carries
            the presenter's exact wording and its evidence footnote — and until
            now it rendered nowhere, so the demo video and the phone fallback
            showed a diagram with no argument attached to it. */}
        <div className="caption" data-killed={killed ? '1' : '0'}>
          {killed ? (
            <>
              <p className="say">
                {nodeLabel(killed)} goes down. {downstreamOf[killed] ?? lit.size - 1} nodes
                downstream fail with it.
              </p>
              <p className="note">Esc returns to the demo path.</p>
            </>
          ) : (
            <>
              <p className="say">{b.say}</p>
              {b.note && <p className="note">{b.note}</p>}
            </>
          )}
        </div>
      </section>

      <aside className="rail-r" ref={railRef} aria-label="Selection">
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
          <Image className="mark mark-sm" src="/ripple-mark.png" alt="" width={14} height={14} />
          <span className="tab" data-on="1">Sourcing graph</span>
          <span className="tab-meta">
            {counts.nodes.toLocaleString()} nodes · {counts.edges.toLocaleString()} edges
            {b.evidence && ` · ${counts.signals.toLocaleString()} signals · ${counts.compliance} compliance rows`}
          </span>
          <div className="spacer" />
          <EvidenceKey layerCounts={layerCounts} open={!!b.evidence} />
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

    </div>
  )
}

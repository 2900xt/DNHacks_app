'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import type { BacktestResult, Compliance, GraphEdge, GraphNode, NodeId, Signal } from '../lib/types'
import { BEATS, type BeatCtx, type NodeState } from '../lib/demo'
import GraphView from './GraphView'
import Inspector from './Inspector'
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
  ctx: BeatCtx
}

/** Downstream reachability, client side. Same traversal as lib/graph.ts cascade():
 *  follow OUTGOING edges, because edges point the way material flows. */
function reachable(edges: GraphEdge[], from: NodeId): Set<NodeId> {
  const out = new Map<NodeId, NodeId[]>()
  for (const e of edges) {
    ;(out.get(e.src) ?? out.set(e.src, []).get(e.src)!).push(e.dst)
  }
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
  const { nodes, edges, compliance, signals, counts, layerCounts, backtest, ctx } = payload

  const [beat, setBeat] = useState(0)
  const [selected, setSelected] = useState<NodeId | null>(null)
  const [killed, setKilled] = useState<NodeId | null>(null)

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const nodeLabel = useCallback(
    (id: NodeId) => byId.get(id)?.label ?? id,
    [byId],
  )

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
      else if (e.key === 'ArrowLeft')             { e.preventDefault(); go(beat - 1) }
      else if (e.key === 'r' || e.key === 'R')    { e.preventDefault(); go(0); setSelected(null) }
      else if (e.key === 'Escape')                { setKilled(null); setSelected(null) }
      else if (/^[0-6]$/.test(e.key))             { e.preventDefault(); go(Number(e.key)) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [beat, go])

  const sel = selected ? byId.get(selected) ?? null : null
  const selEdges = useMemo(
    () => (selected ? edges.filter((e) => e.src === selected || e.dst === selected) : []),
    [selected, edges],
  )

  const onCascade = useCallback((id: NodeId) => setKilled(id), [])
  const onBreach = useCallback((drugs: string[]) => {
    // The hardware seam: a condemned bin fans out from the precursor those drugs
    // share, which is the whole point of beat 2 -> beat 3.
    setSelected(drugs[0] ?? null)
    go(3)
  }, [go])

  return (
    <div className="console">
      <header className="head">
        <h1>CHOKEPOINT</h1>
        <span className="sub">Sourcing risk · 6-APA penicillin family</span>
        <div className="spacer" />
        {BEATS.map((x, i) => (
          <button
            key={x.key}
            className="ctl"
            aria-pressed={i === beat && !killed}
            onClick={() => go(i)}
            title={`Beat ${x.n} — ${x.label}`}
          >
            {x.n} {x.label}
          </button>
        ))}
        <span className="sub" style={{ marginLeft: 8 }}>space ▸</span>
      </header>

      <aside className="rail-l" aria-label="Physical storage">
        <DepotPanel onBreach={onBreach} />
      </aside>

      <main className="main">
        <GraphView
          nodes={nodes}
          edges={edges}
          lit={lit}
          states={states}
          selected={selected}
          onSelect={setSelected}
          compliance={compliance}
          showCompliance={!!b.compliance}
        />
        <div className="caption">
          {killed ? (
            <>
              <div className="beat">Simulated failure</div>
              <p className="say">
                {nodeLabel(killed)} goes down — {lit.size - 1} downstream nodes affected.
              </p>
              <p className="note">
                Reachability over the merged graph. Press Esc to return to the demo path.
              </p>
            </>
          ) : (
            <>
              <div className="beat">Beat {b.n} · {b.label}</div>
              <p className="say">{b.say}</p>
              {b.note && <p className="note">{b.note}</p>}
            </>
          )}
        </div>
      </main>

      <aside className="rail-r" aria-label="Inspector">
        <Inspector
          node={sel}
          edges={selEdges}
          signals={selected ? signals[selected] ?? [] : []}
          compliance={selected ? compliance[selected] ?? null : null}
          nodeLabel={nodeLabel}
          onSelect={setSelected}
          onCascade={onCascade}
        />
      </aside>

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

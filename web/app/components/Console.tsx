'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import type { BacktestResult, Compliance, GraphEdge, GraphNode, NodeId, Signal } from '../lib/types'
import { AMOX, BEATS, type BeatCtx, type NodeState } from '../lib/demo'
import {
  allocate, buildTree, evaluate, impactLine, siblingDrugs, type Health,
} from '../lib/supply-tree'
import TreeView from './TreeView'
import GraphView from './GraphView'
import GlobeView from './GlobeView'
import NodeMetrics from './NodeMetrics'
import DepotPanel from './DepotPanel'
import EvidenceKey from './EvidenceKey'
import Readout from './Readout'
import AuditLog, { type AuditEntry, type AuditKind } from './AuditLog'

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

export default function Console({ payload }: { payload: Payload }) {
  const { nodes, edges, compliance, signals, counts, layerCounts,
          ndcCount, labelerCount, downstreamOf, ctx } = payload

  const [beat, setBeat] = useState(0)
  const [selected, setSelected] = useState<NodeId | null>(null)
  const [panel, setPanel] = useState(true)
  /** Which finished drug the tree is rooted at. The buyer starts holding one. */
  const [root, setRoot] = useState<NodeId>(AMOX)
  /** Everything the operator has switched off. The failure simulation IS this set. */
  const [compromised, setCompromised] = useState<Set<NodeId>>(new Set())
  const [view, setView] = useState<'tree' | 'graph'>('tree')

  /** The console's paper trail. Appended from effects rather than from the
   *  handlers, so a state change logs once no matter which control caused it —
   *  the keyboard, a tab, the tree, or the globe. Consecutive duplicates are
   *  dropped because StrictMode runs every effect twice in development. */
  const [audit, setAudit] = useState<AuditEntry[]>([])
  const log = useCallback((kind: AuditKind, text: string) => {
    setAudit((a) => {
      const last = a[a.length - 1]
      if (last && last.kind === kind && last.text === text) return a
      const t = new Date().toLocaleTimeString('en-GB', { hour12: false })
      return [...a.slice(-299), { t, kind, text }]
    })
  }, [])

  const byId = useMemo(() => new Map(nodes.map((n) => [n.id, n])), [nodes])
  const nodeLabel = useCallback((id: NodeId) => byId.get(id)?.label ?? id, [byId])

  const b = BEATS[beat]

  // --- the tree, and what the failures do to it ------------------------------
  const tree = useMemo(() => buildTree(nodes, edges, root), [nodes, edges, root])
  const rollups = useMemo(() => evaluate(tree, compromised), [tree, compromised])
  const routes = useMemo(() => allocate(tree, compromised), [tree, compromised])
  const rerouting = compromised.size > 0

  /** The chokepoint's own verdict. Every drug on this precursor inherits it —
   *  that inheritance is the fan-out, and it is why one node failing in Inner
   *  Mongolia is a sentence about six American drugs. */
  const chainHealth = useMemo<Health>(() => {
    for (const [id, r] of rollups) if (id.startsWith('precursor:')) return r.health
    return 'ok'
  }, [rollups])

  const siblings = useMemo(
    () => siblingDrugs(edges, tree).map((id) => ({
      id,
      label: nodeLabel(id),
      health: compromised.has(id) ? ('down' as Health) : chainHealth,
    })),
    [edges, tree, nodeLabel, compromised, chainHealth],
  )

  const rootHealth = rollups.get(root)?.health ?? 'ok'

  const toggle = useCallback((id: NodeId) => {
    setCompromised((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    setSelected(id)
  }, [])

  /** One click takes a whole jurisdiction out — an export ban, a border closure.
   *  All-off toggles back to all-on, so the same control undoes itself. */
  const toggleGroup = useCallback((ids: NodeId[]) => {
    setCompromised((prev) => {
      const next = new Set(prev)
      const allOff = ids.every((id) => next.has(id))
      for (const id of ids) {
        if (allOff) next.delete(id)
        else next.add(id)
      }
      return next
    })
  }, [])

  const restoreAll = useCallback(() => setCompromised(new Set()), [])

  const lit = useMemo<Set<NodeId>>(() => b.lit(ctx), [b, ctx])

  /** Beat states drive the columned graph; the cascade overrides them once
   *  anything is off, because a red box that means "beat 4 is talking about
   *  this" next to a red box that means "this is dead" is one red box too many. */
  const states = useMemo<Record<NodeId, NodeState>>(() => {
    if (!rerouting) return b.states?.(ctx) ?? {}
    const s: Record<NodeId, NodeState> = {}
    for (const [id, r] of rollups) {
      if (r.health === 'down') s[id] = 'alarm'
      else if (r.health === 'at-risk') s[id] = 'warn'
    }
    return s
  }, [rerouting, rollups, b, ctx])

  const go = useCallback((n: number) => {
    setBeat(Math.max(0, Math.min(BEATS.length - 1, n)))
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA')) return
      if (e.key === ' ' || e.key === 'ArrowRight') { e.preventDefault(); go(beat + 1) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); go(beat - 1) }
      else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault(); go(0); setSelected(null); restoreAll()
      } else if (e.key === 'Escape') { restoreAll(); setSelected(null) }
      else if (e.key === 'g' || e.key === 'G') { e.preventDefault(); setPanel((p) => !p) }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [beat, go, restoreAll])

  // --- what goes in the log --------------------------------------------------
  //
  // Guarded on a ref of the previous value rather than on the dependency array
  // alone: StrictMode runs every effect twice in development, and an audit log
  // that reports each action twice is worse than no audit log.
  const prevBeat = useRef<number | null>(null)
  useEffect(() => {
    if (prevBeat.current === beat) return
    prevBeat.current = beat
    log('beat', `Beat ${beat + 1} — ${BEATS[beat].label}`)
  }, [beat, log])

  const prevRoot = useRef<NodeId | null>(null)
  useEffect(() => {
    if (prevRoot.current === root) return
    prevRoot.current = root
    log('select', `Tree rooted at ${nodeLabel(root)}`)
  }, [root, log, nodeLabel])

  const prevSel = useRef<NodeId | null>(null)
  useEffect(() => {
    if (prevSel.current === selected) return
    prevSel.current = selected
    if (selected) log('select', `Inspect ${nodeLabel(selected)}`)
  }, [selected, log, nodeLabel])

  const prevOff = useRef<Set<NodeId>>(new Set())
  useEffect(() => {
    const prev = prevOff.current
    if (prev.size === compromised.size && [...compromised].every((id) => prev.has(id))) return
    for (const id of compromised) {
      if (!prev.has(id)) log('cascade', `${nodeLabel(id)} switched offline`)
    }
    for (const id of prev) {
      if (!compromised.has(id)) log('reset', `${nodeLabel(id)} restored`)
    }
    prevOff.current = new Set(compromised)
  }, [compromised, log, nodeLabel])

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

  const onBreach = useCallback((drugs: string[]) => {
    const d = drugs.find((x) => ctx.drugs.includes(x)) ?? drugs[0]
    if (d) { setRoot(d); setSelected(d) }
    go(3)
  }, [go, ctx.drugs])

  const impact = rerouting
    ? impactLine(nodeLabel(root), rollups.get(root), routes, compromised.size)
    : ''

  return (
    <div className="console" data-panel={panel ? 'open' : 'closed'}>
      {/* The nodes, vertical, in the third of the screen next to the map.
          Material flows DOWN the column — jurisdiction to drug product — and the
          map answers "where", so the two read as one sentence left to right. */}
      <section className="graph-panel" aria-label="Sourcing graph">
        <div className="panel-tabs">
          <Image className="mark mark-sm" src="/ripple-mark.png" alt="" width={14} height={14} />
          {/* Two readings of the same data. The tree is what the buyer needs;
              the columned graph is what an auditor asks for. Neither is a
              simplification of the other, so both stay. */}
          <button
            className="tab" data-on={view === 'tree' ? '1' : '0'}
            onClick={() => setView('tree')}
          >
            Supply tree
          </button>
          <button
            className="tab" data-on={view === 'graph' ? '1' : '0'}
            onClick={() => setView('graph')}
          >
            Full graph
          </button>
          <div className="spacer" />
          <button
            className="ctl"
            onClick={() => setPanel((p) => !p)}
            aria-expanded={panel}
            title="Collapse the node column (g)"
          >
            {panel ? '◂' : '▸'}
          </button>
        </div>
        <div className="panel-sub">
          <span className="tab-meta">
            {counts.nodes.toLocaleString()} nodes · {counts.edges.toLocaleString()} edges
            {b.evidence && ` · ${counts.signals.toLocaleString()} signals · ${counts.compliance} compliance rows`}
          </span>
          <div className="spacer" />
          <EvidenceKey layerCounts={layerCounts} open={!!b.evidence} />
        </div>
        {panel && (
          <div className="panel-body">
            {view === 'tree' ? (
              <TreeView
                tree={tree}
                rollups={rollups}
                compromised={compromised}
                onToggle={toggle}
                onToggleGroup={toggleGroup}
                selected={selected}
                onSelect={setSelected}
                siblings={siblings}
                rootHealth={rootHealth}
                onRoot={setRoot}
                onReset={restoreAll}
                compliance={compliance}
                ndcCount={ndcCount}
                showCompliance={!!b.compliance}
                states={states}
              />
            ) : (
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
            )}
          </div>
        )}
      </section>

      <section className="map-wrap" aria-label="World map">
        {/* The way back. The collapse control lives INSIDE the node column, so
            collapsing it took the control with it and left the keyboard as the
            only way back — a shortcut nobody can see. This tab is the door on
            the outside of the door. */}
        {!panel && (
          <button
            className="reopen"
            onClick={() => setPanel(true)}
            title="Show the node column (g)"
            aria-label="Show the node column"
          >
            ▸ Nodes
          </button>
        )}

        <GlobeView
          nodes={nodes}
          edges={edges}
          lit={lit}
          selected={selected}
          onSelect={setSelected}
          routes={routes}
          rerouting={rerouting}
        />

        {/* The physical half and the inspector float over the globe rather than
            taking columns off it. The globe is mostly empty ocean at the edges,
            and neither of these is on screen for the whole story: the depot
            carries beats 0–2, the inspector only exists once you ask it a
            question. */}
        <aside className="ov ov-depot" aria-label="Depot readings">
          <DepotPanel onBreach={onBreach} />
        </aside>

        {sel && (
          <aside className="ov ov-node" aria-label="Selection">
            <NodeMetrics
              node={sel}
              edges={selEdges}
              signals={selected ? signals[selected] ?? [] : []}
              compliance={selected ? compliance[selected] ?? null : null}
              nodeLabel={nodeLabel}
              onSelect={setSelected}
              onCascade={toggle}
              onClose={() => setSelected(null)}
              offline={selected ? compromised.has(selected) : false}
              rollup={selected ? rollups.get(selected) : undefined}
              downstream={downstream}
              ndc={selected ? ndcCount[selected] : undefined}
              labelers={selected ? labelerCount[selected] : undefined}
            />
          </aside>
        )}

        {/* Bottom right: the numbers, then the claim they support. The beat's
            own wording — and once anything is switched off, the consequence
            instead. Both are live text, not a caption written in advance: the
            numbers in the failure line are the same ones the tree and the globe
            are drawing. */}
        <div className="ov-read">
          <Readout overview={overview} />
          <div className="caption" data-killed={rerouting ? '1' : '0'} aria-live="polite">
            {rerouting ? (
              <>
                <p className="say">{impact}</p>
                <p className="note">
                  Load is split evenly across surviving qualified sources — there is no
                  public per-holder capacity figure to weight it with. Esc restores.
                </p>
              </>
            ) : (
              <>
                <p className="say">{b.say}</p>
                {b.note && <p className="note">{b.note}</p>}
              </>
            )}
          </div>
        </div>
      </section>

      <section className="audit-wrap">
        <AuditLog entries={audit} />
      </section>

    </div>
  )
}

'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import Image from 'next/image'
import type {
  BacktestResult, Compliance, GraphEdge, GraphNode, Jurisdictions, NodeId, Reroute, Signal,
} from '../lib/types'
import { verdicts as computeVerdicts } from '../lib/compliance'
import { AMOX, BEATS, type BeatCtx, type NodeState } from '../lib/demo'
import {
  allocate, buildTree, cutSet, evaluate, impactLine, optimalPath, shortlist, siblingDrugs,
  walk, type Health,
} from '../lib/supply-tree'
import ReroutePanel from './ReroutePanel'
import { Section } from './Rail'
import { countryName } from '../lib/plain'
import { useDepot } from '../lib/useDepot'
import { binsIn, worstOf, STATUS_LABEL } from '../lib/depot'
import TreeView, { type DrugOption } from './TreeView'
import GlobeView from './GlobeView'
import NodeMetrics from './NodeMetrics'
import ModelCard from './ModelCard'
import type { NodeRisk, RiskMeta } from '../lib/risk-view'

/** Risk band -> the colour vocabulary the graph already speaks. */
const RISK_STATE: Record<NodeRisk['band'], NodeState> = {
  low: 'ok', raised: 'warn', high: 'alarm',
}
import DepotPanel from './DepotPanel'
import AuditLog, { type AuditEntry, type AuditKind } from './AuditLog'
import AccountChip from './AccountChip'

export interface Payload {
  nodes: GraphNode[]
  edges: GraphEdge[]
  compliance: Record<NodeId, Compliance>
  signals: Record<NodeId, Signal[]>
  counts: { nodes: number; edges: number; signals: number; compliance: number }
  layerCounts: Record<number, number>
  backtest: BacktestResult
  /** The AEGIS shortlist — every DMF holder per precursor, scored once. */
  reroute: Reroute
  /** Buyer-side rule table (WTO GPA parties, the buyers offered). */
  jurisdictions: Jurisdictions
  /** 12-month disruption probability per node, and where it came from. */
  risk: Record<NodeId, NodeRisk>
  /** What the model was trained on, and whether its number can be believed. */
  riskMeta: RiskMeta
  /** ISO-2 of the buyer the console opens on — the depot's country. */
  buyer: string
  /** Collapsed NDC/labeler counts, keyed by drug id. */
  ndcCount: Record<NodeId, number>
  labelerCount: Record<NodeId, number>
  /** Blast radius per spine node, measured on the FULL graph (products included). */
  downstreamOf: Record<NodeId, number>
  ctx: BeatCtx
}

export default function Console({ payload }: { payload: Payload }) {
  const { nodes, edges, compliance, counts,
          ndcCount, labelerCount, downstreamOf, ctx, reroute,
          jurisdictions, risk, riskMeta, buyer: defaultBuyer } = payload

  const [beat, setBeat] = useState(0)
  /** Whose procurement rules the verdicts are judged against. A verdict is a
   *  property of (supplier, buyer, rule), not of the supplier alone; the US
   *  answer is precomputed, every other buyer is derived here from the WTO GPA
   *  party list, and a buyer with no loaded rule says so. */
  const [buyer, setBuyer] = useState(defaultBuyer)
  const verdicts = useMemo(
    () => computeVerdicts(nodes, compliance, buyer, jurisdictions),
    [nodes, compliance, buyer, jurisdictions],
  )
  const buyerLabel = jurisdictions.buyers.find((o) => o.iso2 === buyer)?.label ?? buyer.toUpperCase()
  const [selected, setSelected] = useState<NodeId | null>(null)
  const [panel, setPanel] = useState(true)
  /** Which finished drug the tree is rooted at. The buyer starts holding one. */
  const [root, setRoot] = useState<NodeId>(AMOX)
  /** Everything the operator has switched off. The failure simulation IS this set. */
  const [compromised, setCompromised] = useState<Set<NodeId>>(new Set())
  const [view, setView] = useState<'tree' | 'audit'>('tree')
  /** The operator has asked for the way around the failure. Cleared the
   *  moment there is no failure left to route around. */
  const [rerouted, setRerouted] = useState(false)
  /** Colour every node by its predicted 12-month disruption risk.
   *
   *  Off by default. The columned graph's colours mean something already —
   *  which beat is talking, and what the cascade killed — and two meanings on
   *  one colour is worse than one meaning and a toggle. */
  const [riskOverlay, setRiskOverlay] = useState(false)
  /** Which rail sections are unfolded. The depot starts open: it only exists
   *  while a country is selected, and selecting the country is the ask. */
  const [secOpen, setSecOpen] = useState(
    { node: true, aegis: true, depot: true, model: false })
  const toggleSec = useCallback(
    (k: 'node' | 'aegis' | 'depot' | 'model') => setSecOpen((o) => ({ ...o, [k]: !o[k] })),
    [],
  )
  /** The one connection to the depot service. Global stream, local depots:
   *  each node says which country it is in, and the rail shows a country's
   *  slice under that country and nowhere else. */
  const depot = useDepot()

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
  /** Every node that cannot ship — switched off, beneath one, or gated. The
   *  globe greys these; it is the same set the tree paints red. */
  const cut = useMemo(() => cutSet(tree, compromised), [tree, compromised])
  const rerouting = compromised.size > 0
  if (!rerouting && rerouted) setRerouted(false)
  const showRoute = rerouting && rerouted
  /** The best path is on screen at rest. A failure takes it down with the
   *  rest of the picture; it comes back, recomputed, when the operator asks. */
  const showPath = !rerouting || showRoute
  /** Ask AEGIS. One click, one log line, and the rail unfolds the answer. */
  const doReroute = useCallback(() => {
    setRerouted(true)
    setSecOpen((o) => ({ ...o, aegis: true }))
  }, [])

  /** The pathfinder, re-ranked against the same failures. The globe's even
   *  split says how much load each jurisdiction now carries; this says which
   *  holders a buyer could actually call, and why. Both are derived from the
   *  same `compromised` set, so they can never disagree about who is off. */
  const sl = useMemo(() => shortlist(reroute, tree, compromised, showPath), [reroute, tree, compromised, showPath])

  /** The chokepoint's own verdict. Every drug on this precursor inherits it —
   *  that inheritance is the fan-out, and it is why one node failing in Inner
   *  Mongolia is a sentence about six American drugs. */
  const chainHealth = useMemo<Health>(() => {
    for (const [id, r] of rollups) if (id.startsWith('precursor:')) return r.health
    return 'ok'
  }, [rollups])

  const rootHealth = rollups.get(root)?.health ?? 'ok'

  const [lastSel, setLastSel] = useState<NodeId | null>(selected)
  if (selected !== lastSel) {
    setLastSel(selected)
    if (selected) setSecOpen((o) => ({ ...o, node: true }))
  }

  /** Which register each supplier in the tree filed in — the globe needs it to
   *  know which plants ship the API to the buyer and which ship the precursor
   *  to an API plant. */
  const tiers = useMemo(() => {
    const api = new Set<NodeId>()
    const pre = new Set<NodeId>()
    if (tree) walk(tree, (t) => { if (t.kind === 'supplier') (t.tier === 'api' ? api : pre).add(t.id) })
    return { api, pre }
  }, [tree])

  /** Every finished drug in the graph, for the root picker. The ones that
   *  share this tree's precursor inherit the chokepoint's verdict; a drug on
   *  some other chain is only ever down if the operator switched it off. The
   *  list is derived from the nodes, so it grows with the data, not the code. */
  const drugs = useMemo<DrugOption[]>(() => {
    const onChain = new Set(siblingDrugs(edges, tree))
    const health = (id: NodeId): Health => {
      if (compromised.has(id)) return 'down'
      if (id === root) return rootHealth
      return onChain.has(id) ? chainHealth : 'ok'
    }
    return nodes
      .filter((n) => n.type === 'drug')
      .map((n) => ({ id: n.id, label: n.label ?? n.id, health: health(n.id), onChain: n.id === root || onChain.has(n.id) }))
      .sort((a, b) => a.label.localeCompare(b.label))
  }, [nodes, edges, tree, compromised, chainHealth, root, rootHealth])

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


  /** Switch one node off, or back on. For a PLANT that is a failure: it stops
   *  producing. For a COUNTRY it is an export halt: the country id goes into
   *  the same set, cutSet() reads it, and every plant inside keeps its own
   *  state — producing, unable to ship — which the tree and the globe draw in
   *  amber rather than red. Two disruptions, one switch, told apart by what
   *  was switched. */
  const toggle = useCallback((id: NodeId) => {
    setCompromised((prev) => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
    setSelected(id)
  }, [])

  const restoreAll = useCallback(() => setCompromised(new Set()), [])

  const lit = useMemo<Set<NodeId>>(() => b.lit(ctx), [b, ctx])

  /** Beat states drive the columned graph; the cascade overrides them once
   *  anything is off, because a red box that means "beat 4 is talking about
   *  this" next to a red box that means "this is dead" is one red box too many. */
  const states = useMemo<Record<NodeId, NodeState>>(() => {
    // A cascade outranks the overlay. Once something is switched off, red has to
    // keep meaning "this is dead" — a plant that is merely LIKELY to fail must
    // not look the same as one that already has.
    if (rerouting) {
      const s: Record<NodeId, NodeState> = {}
      for (const [id, r] of rollups) {
        if (r.health === 'down') s[id] = 'alarm'
        else if (r.health === 'at-risk') s[id] = 'warn'
      }
      return s
    }
    if (riskOverlay) {
      const s: Record<NodeId, NodeState> = {}
      for (const n of nodes) {
        const r = risk[n.id]
        // Unscored stays 'plain', not 'ok'. 26 company names could not be
        // resolved to one establishment, and painting them green would say the
        // model checked them and found nothing wrong.
        if (r) s[n.id] = RISK_STATE[r.band]
      }
      return s
    }
    return b.states?.(ctx) ?? {}
  }, [rerouting, rollups, riskOverlay, nodes, risk, b, ctx])

  const go = useCallback((n: number) => {
    setBeat(Math.max(0, Math.min(BEATS.length - 1, n)))
  }, [])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement | null
      if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return
      if (e.key === ' ' || e.key === 'ArrowRight') { e.preventDefault(); go(beat + 1) }
      else if (e.key === 'ArrowLeft') { e.preventDefault(); go(beat - 1) }
      else if (e.key === 'r' || e.key === 'R') {
        e.preventDefault(); go(0); setSelected(null); restoreAll()
      } else if (e.key === 'Escape') { restoreAll(); setSelected(null) }
      else if (e.key === 'g' || e.key === 'G') { e.preventDefault(); setPanel((p) => !p) }
      else if (e.key === 'k' || e.key === 'K') { e.preventDefault(); setRiskOverlay((v) => !v) }
      else if (e.key === 'Enter' && rerouting && !rerouted) { e.preventDefault(); doReroute() }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [beat, go, restoreAll, rerouting, rerouted, doReroute])

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

  const prevBuyer = useRef<string | null>(null)
  useEffect(() => {
    if (prevBuyer.current === buyer) return
    prevBuyer.current = buyer
    const rule = buyer === 'us' ? 'TAA + 1260H'
      : jurisdictions.gpa_parties.includes(buyer) ? 'WTO GPA reciprocity' : 'no rule on record'
    log('select', `Buyer set to ${buyerLabel} — ${rule}`)
  }, [buyer, buyerLabel, jurisdictions, log])

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
    const isPlace = (id: NodeId) => id.startsWith('country:')
    for (const id of compromised) {
      if (!prev.has(id)) {
        log('cascade', isPlace(id) ? `Exports halted from ${nodeLabel(id)}` : `${nodeLabel(id)} switched offline`)
      }
    }
    for (const id of prev) {
      if (!compromised.has(id)) {
        log('reset', isPlace(id) ? `Exports reopened from ${nodeLabel(id)}` : `${nodeLabel(id)} restored`)
      }
    }
    prevOff.current = new Set(compromised)
  }, [compromised, log, nodeLabel])

  /** The pathfinder's verdict goes in the log too — it is the line the buyer
   *  would act on, and an auditor wants to see it changing with the failures. */
  const prevVerdict = useRef<string | null>(null)
  useEffect(() => {
    if (!showRoute || !sl.scopeNode) { prevVerdict.current = null; return }
    const key = `${sl.scopeNode}|${sl.viable}/${sl.standing}|${sl.best?.id ?? ''}`
    if (prevVerdict.current === key) return
    prevVerdict.current = key
    log('cascade', sl.best
      ? `New route for ${sl.substance}: ${nodeLabel(sl.best.id)} (${sl.best.holder.iso2.map(countryName).join('/') || 'location unknown'})`
        + ` — ${sl.viable - 1} other usable supplier${sl.viable === 2 ? '' : 's'}`
      : `No usable supplier left for ${sl.substance}`)
  }, [showRoute, sl, log, nodeLabel])

  const sel = selected ? byId.get(selected) ?? null : null
  /** The depot under the selected country. Depots are local to a point of
   *  interest — the place supplies flow in and out of — so the sensor that is
   *  configured for the US is listed when the US is selected and under no
   *  other country. Nothing selected, or a plant: there is no depot to be
   *  under, so there is no depot section. */
  const depotBins = useMemo(
    () => (sel?.type === 'country' ? binsIn(depot.nodes, sel.country) : []),
    [depot.nodes, sel],
  )
  const depotWorst = worstOf(depotBins)
  const depotTag = depotBins.length === 0
    ? 'none'
    : depotWorst === null || depotWorst === 'ok'
      ? `${depotBins.length} bin${depotBins.length === 1 ? '' : 's'}`
      : STATUS_LABEL[depotWorst].toLowerCase()
  const depotTone = depotBins.length === 0
    ? 'dim' : depotWorst === 'mkt_breach' ? 'alarm' : depotWorst === 'ok' ? 'ok' : 'warn'
  const selOffline = selected ? compromised.has(selected) : false
  /** A plant inside a jurisdiction whose exports are halted. */
  const selHalted = !!sel && sel.type !== 'country' && !!sel.country
    && compromised.has(`country:${sel.country}`)
  /** ISO-2 of every jurisdiction whose exports are halted, for the globe. */
  const haltedIsos = useMemo(() => new Set(
    [...compromised].filter((id) => id.startsWith('country:'))
      .map((id) => byId.get(id)?.country).filter((c): c is string => !!c),
  ), [compromised, byId])
  const selEdges = useMemo(
    () => (selected ? edges.filter((e) => e.src === selected || e.dst === selected) : []),
    [selected, edges],
  )
  const downstream = selected ? downstreamOf[selected] ?? 0 : 0

  const onBreach = useCallback((drugs: string[]) => {
    const d = drugs.find((x) => ctx.drugs.includes(x)) ?? drugs[0]
    if (d) { setRoot(d); setSelected(d) }
    go(3)
  }, [go, ctx.drugs])

  const impact = rerouting
    ? impactLine(nodeLabel(root), rollups.get(root), routes, compromised.size)
    : ''

  /** The route, for every surface that is not the rail: the globe wants a
   *  jurisdiction, the graph wants a node, the readout wants both plus the
   *  share that jurisdiction now carries. One source, so they cannot disagree. */
  const routeIso = showRoute ? sl.best?.holder.iso2[0] ?? null : null
  /** The best path, end to end: precursor plant, API plant, buyer. The tree
   *  and the globe light the whole thing, not just the last hop: a route is a
   *  line from the buyer's product to the plant, and one green box is a dot,
   *  not a line. Null while a failure is shown and the operator has not yet
   *  asked for the answer. */
  const path = useMemo(() => optimalPath(sl, tree, cut, nodes), [sl, tree, cut, nodes])
  const routePath = useMemo<Set<string>>(() => path?.keys ?? new Set(), [path])

  return (
    <div className="console" data-panel={panel ? 'open' : 'closed'}>
      {/* The nodes, vertical, in the third of the screen next to the map.
          Material flows DOWN the column — jurisdiction to drug product — and the
          map answers "where", so the two read as one sentence left to right. */}
      <section className="graph-panel" aria-label="Sourcing graph">
        {/* Two readings of the same session, and nothing else on the row:
            the labels get the whole width, split evenly, so they can be set
            at a size a projector can read. The mark and the collapse control
            live on the line below with the counts. */}
        <div className="panel-tabs" role="tablist">
          <button
            className="tab" role="tab" aria-selected={view === 'tree'}
            data-on={view === 'tree' ? '1' : '0'}
            onClick={() => setView('tree')}
            title="The chain for one drug"
          >
            Supply tree
          </button>
          <button
            className="tab" role="tab" aria-selected={view === 'audit'}
            data-on={view === 'audit' ? '1' : '0'}
            onClick={() => setView('audit')}
            title="What this session did, and when"
          >
            Audit log
            <span className="tab-count">{audit.length}</span>
          </button>
        </div>
        <div className="panel-sub">
          <Image className="mark mark-sm" src="/ripple-mark.png" alt="" width={14} height={14} />
          <span className="tab-meta">
            {counts.nodes.toLocaleString()} nodes · {counts.edges.toLocaleString()} edges
            {b.evidence && ` · ${counts.signals.toLocaleString()} signals · ${counts.compliance} compliance rows`}
          </span>
          <div className="spacer" />
          <label className="strip-label" htmlFor="buyer">Buyer</label>
          <select
            id="buyer"
            className="drug-select buyer-select"
            value={buyer}
            onChange={(e) => setBuyer(e.target.value)}
            title="Whose procurement rules the PASS/FAIL verdicts are judged against"
          >
            {jurisdictions.buyers.map((o) => (
              <option key={o.iso2} value={o.iso2}>{o.label}</option>
            ))}
          </select>
          <button
            className="ctl"
            data-on={riskOverlay ? '1' : '0'}
            onClick={() => setRiskOverlay((v) => !v)}
            aria-pressed={riskOverlay}
            title="Colour every node by its predicted 12-month disruption risk (k)"
          >
            Risk
          </button>
          <button
            className="ctl"
            onClick={() => setPanel((p) => !p)}
            aria-expanded={panel}
            title="Collapse the node column (g)"
          >
            {panel ? '◂' : '▸'}
          </button>
        </div>
        {panel && (
          <div className="panel-body">
            {view === 'audit' ? (
              <AuditLog entries={audit} />
            ) : (
              <TreeView
                tree={tree}
                rollups={rollups}
                compromised={compromised}
                onToggle={toggle}
                onToggleGroup={toggleGroup}
                selected={selected}
                onSelect={setSelected}
                drugs={drugs}
                rootHealth={rootHealth}
                onRoot={setRoot}
                onReset={restoreAll}
                verdicts={verdicts}
                ndcCount={ndcCount}
                showCompliance={!!b.compliance}
                states={states}
                aegis={sl.byId}
                routePath={routePath}
              />
            )}
          </div>
        )}
      </section>

      <section className="map-wrap" aria-label="World map">
        {/* The way back, when the node column is collapsed. Top-left is free
            now that the rail owns the right edge. */}
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
          showRoute={showRoute}
          routeIso={routeIso}
          path={path}
          cut={cut}
          off={compromised}
          halted={haltedIsos}
          apiIds={tiers.api}
          preIds={tiers.pre}
          scoreOf={sl.byId}
        />

        {/* The rail. Everything that is ABOUT the picture — the node under
            inspection, the pathfinder's answer, the depot's readings — folds
            into one column on the right edge, and the picture keeps the rest. */}
        <aside className="rail" aria-label="Details">
          {sel && (
            <Section
              title={sel.label ?? sel.id}
              tag={sel.type}
              open={secOpen.node}
              onToggle={() => toggleSec('node')}
              onClose={() => setSelected(null)}
            >
              <NodeMetrics
                node={sel}
                edges={selEdges}
                verdict={selected ? verdicts[selected] ?? null : null}
                nodeLabel={nodeLabel}
                onSelect={setSelected}
                onCascade={toggle}
                offline={selOffline}
                halted={selHalted}
                rollup={selected ? rollups.get(selected) : undefined}
                downstream={downstream}
                ndc={selected ? ndcCount[selected] : undefined}
                labelers={selected ? labelerCount[selected] : undefined}
                alt={selected ? sl.byId.get(selected) : undefined}
                risk={selected ? risk[selected] ?? null : null}
                riskCeiling={riskMeta.ceiling}
              />
            </Section>
          )}

          {showRoute && (
            <Section
              title="Backup suppliers"
              tag={`${sl.viable} usable`}
              tone={sl.viable === 0 ? 'alarm' : 'ok'}
              open={secOpen.aegis}
              onToggle={() => toggleSec('aegis')}
            >
              <ReroutePanel sl={sl} nodeLabel={nodeLabel} selected={selected} onSelect={setSelected} />
            </Section>
          )}

          {/* The depot, under the country it is in. A node reporting from the
              US appears here when the US is selected and under no other
              country; a country with no node says so rather than borrowing
              someone else's. */}
          {sel?.type === 'country' && (
            <Section
              title={`Depot · ${sel.label ?? sel.id}`}
              tag={depotTag}
              tone={depotTone}
              open={secOpen.depot}
              onToggle={() => toggleSec('depot')}
            >
              <DepotPanel
                bins={depotBins}
                link={depot.link}
                place={sel.label ?? sel.id}
                onBreach={onBreach}
              />
            </Section>
          )}

          {/* Where the percentages come from. Folded shut by default — it is
              the answer to "says who", and that question is asked after the
              number is seen, not before. */}
          <Section
            title="How risk is scored"
            tag={`${riskMeta.coverage.scored} nodes`}
            open={secOpen.model}
            onToggle={() => toggleSec('model')}
          >
            <ModelCard meta={riskMeta} />
          </Section>

          {/* Bottom-right: the operator. Last in the column and pushed to its
              foot, so it is always in the corner and never under a section. */}
          <AccountChip medicines={drugs.length} sessionEvents={audit.length} />
        </aside>

        {/* Bottom-left: only after a failure. The consequence, and under it
            the one control this screen exists for — until it is pressed, when
            the pathfinder's answer takes its place. At rest there is nothing
            here: the beat's narration used to sit in this corner and read as
            noise next to the picture, so it stays in the presenter's script
            (lib/demo.ts) and off the screen. */}
        {rerouting && (
          <div className="ov-read">
            <div className="caption" data-killed="1" aria-live="polite">
              <p className="say">
                {impact}
                {showRoute && sl.best && (
                  <> <span className="say-route">New route: {nodeLabel(sl.best.id)}, {sl.best.holder.iso2.map(countryName).join('/') || 'location unknown'}.</span></>
                )}
                {showRoute && !sl.best && <> <span className="say-route">No usable supplier is left.</span></>}
              </p>
            </div>
            {!rerouted && (
              <button className="reroute" onClick={doReroute} title="Show the new route (Enter)">
                <span className="reroute-arrow" aria-hidden>➜</span>
                See new route
                <kbd>↵</kbd>
              </button>
            )}
          </div>
        )}
      </section>


    </div>
  )
}

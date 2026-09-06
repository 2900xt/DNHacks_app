// Loads the JSON artifacts, merges them, and answers graph questions.
// No database — decision 0004. Everything here runs in memory.

import nodesOpenfda from '@/data/nodes.openfda.json'
import edgesOpenfda from '@/data/edges.openfda.json'
import nodesCurated from '@/data/nodes.curated.json'
import edgesCurated from '@/data/edges.curated.json'
import complianceRaw from '@/data/compliance.json'
import signalsRaw from '@/data/signals.json'
import binsRaw from '@/data/bins.json'
import backtestRaw from '@/data/backtest.json'
import rerouteRaw from '@/data/reroute.json'

import type {
  GraphNode, GraphEdge, Signal, Compliance, Bin,
  NodeId, CascadeResult, BacktestResult, RerouteNode, RerouteData,
} from './types'

export interface Graph {
  nodes: Map<NodeId, GraphNode>
  edges: GraphEdge[]
  /** dst -> edges pointing at it. Used to walk UP the dependency graph. */
  incoming: Map<NodeId, GraphEdge[]>
  /** src -> edges leaving it. Used to trace DOWN to a precursor. */
  outgoing: Map<NodeId, GraphEdge[]>
  signals: Map<NodeId, Signal[]>
  compliance: Map<NodeId, Compliance>
  bins: Bin[]
}

let cached: Graph | null = null

/** Merge producers. Deduped by id, last write wins, and every collision is loud —
 *  a silent collision is how the fan-out breaks. */
export function loadGraph(): Graph {
  if (cached) return cached

  const nodes = new Map<NodeId, GraphNode>()
  for (const n of [...nodesOpenfda, ...nodesCurated] as GraphNode[]) {
    if (nodes.has(n.id)) {
      console.warn(`[graph] duplicate node id: ${n.id} — last write wins`)
    }
    nodes.set(n.id, n)
  }

  const seen = new Set<string>()
  const edges: GraphEdge[] = []
  for (const e of [...edgesOpenfda, ...edgesCurated] as GraphEdge[]) {
    if (e.layer === 3 && !e.citation) {
      console.warn(`[graph] layer-3 edge without citation, dropped: ${e.src} -> ${e.dst}`)
      continue
    }
    const key = `${e.src}|${e.dst}|${e.rel}`
    if (seen.has(key)) continue
    seen.add(key)
    edges.push(e)
  }

  const incoming = new Map<NodeId, GraphEdge[]>()
  const outgoing = new Map<NodeId, GraphEdge[]>()
  for (const e of edges) {
    ;(incoming.get(e.dst) ?? incoming.set(e.dst, []).get(e.dst)!).push(e)
    ;(outgoing.get(e.src) ?? outgoing.set(e.src, []).get(e.src)!).push(e)
  }

  const signals = new Map<NodeId, Signal[]>()
  for (const s of signalsRaw as Signal[]) {
    ;(signals.get(s.node_id) ?? signals.set(s.node_id, []).get(s.node_id)!).push(s)
  }
  for (const list of signals.values()) {
    list.sort((a, b) => b.observed_at.localeCompare(a.observed_at))
  }

  const compliance = new Map<NodeId, Compliance>()
  for (const c of complianceRaw as Compliance[]) compliance.set(c.node_id, c)

  cached = {
    nodes, edges, incoming, outgoing, signals, compliance,
    bins: binsRaw as Bin[],
  }
  return cached
}

export function getNode(id: NodeId) {
  const g = loadGraph()
  const node = g.nodes.get(id)
  if (!node) return null
  return {
    node,
    edges: [...(g.outgoing.get(id) ?? []), ...(g.incoming.get(id) ?? [])],
    signals: g.signals.get(id) ?? [],
    compliance: g.compliance.get(id) ?? null,
  }
}

/**
 * Everything that DEPENDS ON `nodeId` — the fan-out.
 *
 * Edges point the way material flows: precursor --feeds--> api
 * --formulated_into--> drug. So dependents are reached by following OUTGOING
 * edges. (Walking `incoming` looks right if you read "up the graph" literally,
 * and returns an empty set. It was wrong here once already.)
 *
 * From precursor:6-apa this lights all six penicillins even though none of them
 * has an official shortage. That is the payoff beat.
 */
export function cascade(nodeId: NodeId): CascadeResult {
  const g = loadGraph()
  const affected: GraphNode[] = []
  const firedBy: Signal[] = []
  const seen = new Set<NodeId>([nodeId])
  const queue: NodeId[] = [nodeId]

  while (queue.length) {
    const current = queue.shift()!
    for (const s of g.signals.get(current) ?? []) firedBy.push(s)

    for (const edge of g.outgoing.get(current) ?? []) {
      if (seen.has(edge.dst)) continue
      seen.add(edge.dst)
      const n = g.nodes.get(edge.dst)
      if (n) affected.push(n)
      queue.push(edge.dst)
    }
  }

  return {
    affected,
    // Parth owns the real thresholds — ml/cascade_rules.py.
    rule: 'reachability: everything upstream-dependent on the killed node',
    firedBy,
  }
}

export function getSignals(since?: string): Signal[] {
  const all = [...loadGraph().signals.values()].flat()
  const filtered = since ? all.filter((s) => s.observed_at >= since) : all
  return filtered.sort((a, b) => b.observed_at.localeCompare(a.observed_at))
}

export function getBacktest(): BacktestResult {
  return backtestRaw as BacktestResult
}

/** AEGIS re-route options for one node, or null if that node has none.
 *
 *  The artifact is keyed by node id and covers every precursor/api node in the
 *  graph, so a lookup works for whatever the operator switches off. Scoring is
 *  done in `ml/aegis.py`; nothing is recomputed here.
 */
export function getReroute(id: NodeId): RerouteNode | null {
  return (rerouteRaw as RerouteData).nodes[id] ?? null
}

/** Every node AEGIS can offer a route for. */
export function rerouteIndex(): Record<NodeId, RerouteNode> {
  return (rerouteRaw as RerouteData).nodes
}

export function counts() {
  const g = loadGraph()
  return {
    nodes: g.nodes.size,
    edges: g.edges.length,
    signals: [...g.signals.values()].flat().length,
    compliance: g.compliance.size,
    bins: g.bins.length,
  }
}

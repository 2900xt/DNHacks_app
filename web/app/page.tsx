// Server component. Loads the merged graph once, on the server, and hands the
// client only what the console renders.
//
// Why not import the JSON straight into the client: signals.json alone is ~3,100
// rows and would ship every one of them to the browser. Only signals attached to
// a node that is actually in this subgraph cross the boundary.

import { loadGraph, getBacktest, counts } from './lib/graph'
import type { Compliance, NodeId, Signal } from './lib/types'
import Console, { type Payload } from './components/Console'
import { APA } from './lib/demo'

const SIGNALS_PER_NODE = 8

export default function Page() {
  const g = loadGraph()

  const nodes = [...g.nodes.values()]
  const edges = g.edges

  const compliance: Record<NodeId, Compliance> = {}
  for (const n of nodes) {
    const c = g.compliance.get(n.id)
    if (c) compliance[n.id] = c
  }

  const signals: Record<NodeId, Signal[]> = {}
  for (const n of nodes) {
    const s = g.signals.get(n.id)
    if (s?.length) signals[n.id] = s.slice(0, SIGNALS_PER_NODE)
  }

  const layerCounts: Record<number, number> = {}
  for (const e of edges) layerCounts[e.layer] = (layerCounts[e.layer] ?? 0) + 1

  // Compliance on a company is inherited from its jurisdiction — the TAA verdict
  // is a country fact, and the graph already carries company -> country. Without
  // this the beat-5 overlay colours three country boxes and nothing else.
  for (const e of edges) {
    if (e.rel !== 'incorporated_in') continue
    const country = compliance[e.dst]
    if (country && !compliance[e.src]) {
      compliance[e.src] = {
        node_id: e.src,
        taa_pass: country.taa_pass,
        on_1260h: country.on_1260h,
        evidence: {
          ...country.evidence,
          inherited_from: e.dst,
          reason: `Inherited from ${e.dst}: ${String(country.evidence?.reason ?? '')}`,
        },
      }
    }
  }

  const ids = (p: string) => nodes.filter((n) => n.id.startsWith(p)).map((n) => n.id)

  const payload: Payload = {
    nodes,
    edges,
    compliance,
    signals,
    counts: counts(),
    layerCounts,
    backtest: getBacktest(),
    ctx: {
      fanout: [],
      companies: ids('company:'),
      countries: ids('country:'),
      drugs: ids('drug:'),
      apis: ids('api:'),
    },
  }

  // Everything downstream of the precursor — beat 4's set, computed once here so
  // the client never has to.
  const out = new Map<NodeId, NodeId[]>()
  for (const e of edges) (out.get(e.src) ?? out.set(e.src, []).get(e.src)!).push(e.dst)
  const seen = new Set<NodeId>([APA])
  const q: NodeId[] = [APA]
  while (q.length) {
    for (const d of out.get(q.shift()!) ?? []) {
      if (seen.has(d)) continue
      seen.add(d)
      q.push(d)
    }
  }
  payload.ctx.fanout = [...seen]

  return <Console payload={payload} />
}

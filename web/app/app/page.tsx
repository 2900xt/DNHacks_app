// Server component. Loads the merged graph, reduces it to the demo SPINE, and
// hands the client only what it renders.
//
// The full graph is 862 nodes, 760 of them individual NDCs. Rendering those as
// boxes is unreadable and beside the point: a risk manager wants "Amoxicillin —
// 19 NDCs", not 19 rectangles. So products are collapsed into counts on their
// drug, and every number that quantifies blast radius is still computed against
// the FULL graph, not the reduced one.

import { loadGraph, getBacktest, getReroute, getJurisdictions, counts } from '../lib/graph'
import type { Compliance, GraphEdge, NodeId, Signal } from '../lib/types'
import Console, { type Payload } from '../components/Console'
import { APA } from '../lib/demo'

export const metadata = {
  title: 'RIPPLE — sourcing risk console',
  description:
    'Trace a drug product to the precursor it shares, and see what else fails with it.',
}

const SIGNALS_PER_NODE = 8
/** Collapsed into counts rather than drawn. */
const COLLAPSED = new Set(['product'])

function downstream(out: Map<NodeId, NodeId[]>, from: NodeId): Set<NodeId> {
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

export default function Page() {
  const g = loadGraph()
  const all = [...g.nodes.values()]

  const out = new Map<NodeId, NodeId[]>()
  for (const e of g.edges) (out.get(e.src) ?? out.set(e.src, []).get(e.src)!).push(e.dst)

  // --- the spine ------------------------------------------------------------
  // Everything structurally attached to the precursor that is not an NDC.
  //
  // This MUST be a fixpoint, not a single sweep. The artifacts concatenate
  // openFDA edges before curated ones, so `active_in` (api -> drug) is visited
  // before `feeds` (precursor -> api) has put any api in the set. A single pass
  // silently drops all six drugs, and the fan-out beat renders nothing.
  const SPINE_RELS = new Set([
    'feeds', 'produced_by', 'active_in', 'incorporated_in', 'hosts', 'operated_by',
  ])
  const spine = new Set<NodeId>([APA])
  for (let grew = true; grew; ) {
    grew = false
    for (const e of g.edges) {
      if (!SPINE_RELS.has(e.rel)) continue
      if (spine.has(e.src) && !spine.has(e.dst)) { spine.add(e.dst); grew = true }
      else if (spine.has(e.dst) && !spine.has(e.src)) { spine.add(e.src); grew = true }
    }
  }
  for (const id of [...spine]) {
    const n = g.nodes.get(id)
    if (!n || COLLAPSED.has(n.type)) spine.delete(id)
  }

  const nodes = all.filter((n) => spine.has(n.id))
  const edges = g.edges.filter(
    (e) => spine.has(e.src) && spine.has(e.dst) && e.rel !== 'markets',
  )

  // --- collapsed product counts, per drug -----------------------------------
  const ndcCount: Record<NodeId, number> = {}
  const labelerCount: Record<NodeId, number> = {}
  const labelersByDrug = new Map<NodeId, Set<NodeId>>()
  const productOwner = new Map<NodeId, NodeId>()
  for (const e of g.edges) if (e.rel === 'markets') productOwner.set(e.dst, e.src)
  for (const e of g.edges) {
    if (e.rel !== 'marketed_as') continue
    ndcCount[e.src] = (ndcCount[e.src] ?? 0) + 1
    const owner = productOwner.get(e.dst)
    if (owner) {
      ;(labelersByDrug.get(e.src) ?? labelersByDrug.set(e.src, new Set()).get(e.src)!).add(owner)
    }
  }
  for (const [drug, set] of labelersByDrug) labelerCount[drug] = set.size

  // --- blast radius, against the FULL graph ---------------------------------
  const downstreamOf: Record<NodeId, number> = {}
  for (const n of nodes) downstreamOf[n.id] = downstream(out, n.id).size - 1

  // --- per-node side tables --------------------------------------------------
  const compliance: Record<NodeId, Compliance> = {}
  for (const n of nodes) {
    const c = g.compliance.get(n.id)
    if (c) compliance[n.id] = c
  }
  // A TAA verdict is a jurisdiction fact; the graph already carries company ->
  // country, so inherit it or the overlay colours three boxes and nothing else.
  for (const e of edges) {
    if (e.rel !== 'incorporated_in') continue
    const country = compliance[e.dst]
    if (country && !compliance[e.src]) {
      compliance[e.src] = {
        node_id: e.src,
        taa_pass: country.taa_pass,
        on_1260h: country.on_1260h,
        evidence: { ...country.evidence, inherited_from: e.dst },
      }
    }
  }

  const signals: Record<NodeId, Signal[]> = {}
  for (const n of nodes) {
    const s = g.signals.get(n.id)
    if (s?.length) signals[n.id] = s.slice(0, SIGNALS_PER_NODE)
  }

  const layerCounts: Record<number, number> = {}
  for (const e of g.edges) layerCounts[e.layer] = (layerCounts[e.layer] ?? 0) + 1

  const ids = (p: string) => nodes.filter((n) => n.id.startsWith(p)).map((n) => n.id)

  const payload: Payload = {
    nodes,
    edges: edges as GraphEdge[],
    compliance,
    signals,
    counts: counts(),
    layerCounts,
    backtest: getBacktest(),
    // AEGIS alternates, keyed by node. Server-side because the artifact is
    // static — the client only ever looks one up.
    reroute: getReroute(),
    // The buyer-side rule table, and the default buyer: the jurisdiction the
    // depot sits in. That is the hardware seam and the compliance layer
    // sharing one input.
    jurisdictions: getJurisdictions(),
    buyer: g.bins.find((b) => b.country)?.country?.toLowerCase() ?? 'us',
    ndcCount,
    labelerCount,
    downstreamOf,
    ctx: {
      fanout: [...downstream(out, APA)].filter((id) => spine.has(id)),
      companies: ids('company:'),
      countries: ids('country:'),
      drugs: ids('drug:'),
      apis: ids('api:'),
    },
  }

  return <Console payload={payload} />
}

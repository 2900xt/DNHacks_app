// Deterministic banded layout for the sourcing graph.
//
// WHY NOT force-directed: the fan-out is the demo's payoff, and it only reads if
// one node in the precursor band visibly sprays into six in the drug band. A
// physics sim re-settles differently every run and can bury that geometry at the
// worst possible moment. Bands are assigned by node TYPE, which is a fixed
// semantic order, so there is nothing to solve for — only within-band ordering,
// which a two-pass barycentre sweep handles at this size.
//
// WHY VERTICAL: the graph lives in a column one third of the screen wide and the
// full height of it. Material flows DOWN — jurisdiction, site, filing holder,
// precursor, active ingredient, drug product — and `precursor` sits in the
// middle on purpose. Sourcing collapses inward from countries and companies;
// product fans outward into APIs and drugs. The picture is an hourglass and
// 6-APA is the waist. That shape IS the thesis, and it is the shape a tall
// narrow panel was made for.
//
// Wide bands WRAP rather than stretch. Ten DMF holders laid out in one row would
// force the whole diagram to ten node-widths, and the SVG is fitted `meet` — so
// that one row would set the scale for everything and shrink every label past
// reading. Three across is what keeps the diagram's aspect near the panel's.

import type { GraphEdge, GraphNode, NodeId, NodeType } from './types'

export const BANDS: NodeType[] = [
  'country', 'facility', 'company', 'precursor', 'api', 'drug', 'product',
]

export const BAND_LABEL: Record<string, string> = {
  country: 'Jurisdiction',
  facility: 'Site',
  company: 'DMF holder',
  precursor: 'Precursor',
  api: 'Active ingredient',
  drug: 'Drug product',
  product: 'NDC',
}

/** Kept as an alias: the inspector and older call sites read column labels. */
export const COLUMN_LABEL = BAND_LABEL
export const COLUMNS = BANDS

export const NODE_W = 190
export const NODE_H = 40
/** Horizontal gap between nodes inside one band row. */
export const COL_GAP = 16
/** Vertical gap between wrapped rows inside one band. */
export const ROW_GAP = 18
/** Nodes per row before a band wraps. Three keeps the diagram near 0.8:1. */
export const PER_ROW = 3
export const BAND_LABEL_H = 22
export const BAND_GAP = 14
export const PAD_X = 20
export const PAD_TOP = 14
export const PAD_BOTTOM = 16

export interface Placed {
  id: NodeId
  node: GraphNode
  /** Index into BANDS. */
  band: number
  x: number
  y: number
}

export interface Band {
  band: number
  type: NodeType
  /** Baseline of the band's label, above its first row of nodes. */
  labelY: number
  count: number
}

export interface Layout {
  placed: Placed[]
  pos: Map<NodeId, Placed>
  width: number
  height: number
  bands: Band[]
}

/**
 * Material-flow direction for rendering.
 *
 * The data models edges as REFERENCES ("6-APA is produced_by X", "X is
 * incorporated_in CN"), which point the opposite way from how material actually
 * moves. Drawing them raw gives a picture with arrows colliding in the middle.
 * This maps each relation to the direction the material travels, so every arrow
 * on screen points the same way and the chain reads top to bottom. The reference
 * direction is preserved untouched in the data and shown in the inspector.
 */
export function flowOf(e: GraphEdge): [NodeId, NodeId] {
  switch (e.rel) {
    case 'produced_by':      // precursor <- company
    case 'incorporated_in':  // company   <- country
      return [e.dst, e.src]
    default:
      // feeds, active_in, hosts, operated_by are already in material order.
      return [e.src, e.dst]
  }
}

/**
 * What the arrow says, read in the direction it points.
 *
 * The two relations `flowOf` reverses get their active voice back — a country
 * "incorporates" a company, a company "produces" the precursor — because an
 * arrow pointing one way with a verb facing the other is worse than no verb.
 */
export const REL_VERB: Record<string, string> = {
  feeds: 'feeds',
  produced_by: 'produces',
  active_in: 'active in',
  incorporated_in: 'incorporates',
  hosts: 'hosts',
  operated_by: 'operated by',
  marketed_as: 'marketed as',
  markets: 'markets',
  formulated_into: 'formulated into',
}

export function relVerb(rel: string): string {
  return REL_VERB[rel] ?? rel.replace(/_/g, ' ')
}

function bandOf(n: GraphNode): number {
  const i = BANDS.indexOf(n.type)
  return i === -1 ? BANDS.length : i
}

/** Split n items into rows of at most PER_ROW, balanced so no row is a runt. */
function rowSizes(n: number): number[] {
  const rows = Math.max(1, Math.ceil(n / PER_ROW))
  const base = Math.floor(n / rows)
  const extra = n % rows
  return Array.from({ length: rows }, (_, i) => base + (i < extra ? 1 : 0))
}

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): Layout {
  const buckets = new Map<number, GraphNode[]>()
  for (const n of nodes) {
    const b = bandOf(n)
    ;(buckets.get(b) ?? buckets.set(b, []).get(b)!).push(n)
  }

  // Drop empty bands so a lane nobody has loaded yet (product:, before the
  // openFDA lane lands) does not leave a blank gutter mid-diagram.
  const used = [...buckets.keys()].sort((a, b) => a - b)

  const order = new Map<number, NodeId[]>()
  for (const b of used) {
    order.set(b, buckets.get(b)!
      .slice()
      .sort((x, y) => (x.label ?? x.id).localeCompare(y.label ?? y.id))
      .map((n) => n.id))
  }

  // Neighbour index, in flow order, for the barycentre sweep.
  const nbr = new Map<NodeId, NodeId[]>()
  for (const e of edges) {
    const [from, to] = flowOf(e)
    ;(nbr.get(from) ?? nbr.set(from, []).get(from)!).push(to)
    ;(nbr.get(to) ?? nbr.set(to, []).get(to)!).push(from)
  }

  const rank = new Map<NodeId, number>()
  const reindex = () => {
    for (const ids of order.values()) ids.forEach((id, i) => rank.set(id, i))
  }
  reindex()

  // Two sweeps is enough to settle ~28 nodes and keeps the result stable run to
  // run. Nodes with no placed neighbour keep their alphabetical rank.
  const bandOfId = new Map<NodeId, number>()
  for (const n of nodes) bandOfId.set(n.id, bandOf(n))

  for (let pass = 0; pass < 2; pass++) {
    for (const b of used) {
      const ids = order.get(b)!
      const bary = new Map<NodeId, number>()
      for (const id of ids) {
        const ns = (nbr.get(id) ?? []).filter((m) => bandOfId.get(m) !== b)
        const rs = ns.map((m) => rank.get(m)).filter((r): r is number => r != null)
        bary.set(id, rs.length ? rs.reduce((a, c) => a + c, 0) / rs.length : rank.get(id)!)
      }
      ids.sort((x, y) => (bary.get(x)! - bary.get(y)!) || x.localeCompare(y))
      reindex()
    }
  }

  const byId = new Map(nodes.map((n) => [n.id, n]))
  const width = PAD_X * 2 + PER_ROW * NODE_W + (PER_ROW - 1) * COL_GAP
  const inner = width - PAD_X * 2

  const placed: Placed[] = []
  const bands: Band[] = []
  let y = PAD_TOP

  for (const b of used) {
    const ids = order.get(b)!
    bands.push({ band: b, type: BANDS[b] ?? 'product', labelY: y + 10, count: ids.length })
    y += BAND_LABEL_H

    let i = 0
    for (const size of rowSizes(ids.length)) {
      // Centre each row on the diagram's axis so a two-node row does not hug
      // the left edge while the band above it is full width.
      const rowW = size * NODE_W + (size - 1) * COL_GAP
      const x0 = PAD_X + (inner - rowW) / 2
      for (let k = 0; k < size; k++, i++) {
        const id = ids[i]
        placed.push({ id, node: byId.get(id)!, band: b, x: x0 + k * (NODE_W + COL_GAP), y })
      }
      y += NODE_H + ROW_GAP
    }
    y += BAND_GAP - ROW_GAP
  }

  const height = y - BAND_GAP + ROW_GAP + PAD_BOTTOM
  return { placed, pos: new Map(placed.map((p) => [p.id, p])), width, height, bands }
}

/** Cubic bezier between two boxes, leaving the bottom and entering the top. */
export function edgePath(a: Placed, b: Placed): string {
  const x1 = a.x + NODE_W / 2, y1 = a.y + NODE_H
  const x2 = b.x + NODE_W / 2, y2 = b.y
  // Same band (shouldn't happen, but don't emit NaN if it does).
  if (Math.abs(y2 - y1) < 1) return `M${x1},${y1} L${x2},${y2}`
  const dy = Math.max(22, (y2 - y1) * 0.45)
  return `M${x1},${y1} C${x1},${y1 + dy} ${x2},${y2 - dy} ${x2},${y2}`
}

/** Where an edge's verb sits. For the curve above, t=0.5 is the plain midpoint. */
export function edgeMid(a: Placed, b: Placed): [number, number] {
  return [
    (a.x + b.x) / 2 + NODE_W / 2,
    (a.y + NODE_H + b.y) / 2,
  ]
}

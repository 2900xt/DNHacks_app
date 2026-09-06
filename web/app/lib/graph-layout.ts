// Deterministic layered layout for the sourcing graph.
//
// WHY NOT force-directed: the fan-out is the demo's payoff, and it only reads if
// one node in the precursor column visibly sprays into six in the drug column.
// A physics sim re-settles differently every run and can bury that geometry at
// the worst possible moment. Columns are assigned by node TYPE, which is a fixed
// semantic order, so there is nothing to solve for — only within-column ordering,
// which a two-pass barycentre sweep handles at this size.
//
// The column order puts `precursor` in the MIDDLE on purpose. Sourcing collapses
// inward from countries and companies; product fans outward into APIs and drugs.
// The picture is an hourglass and 6-APA is the waist. That shape IS the thesis.

import type { GraphEdge, GraphNode, NodeId, NodeType } from './types'

export const COLUMNS: NodeType[] = [
  'country', 'company', 'precursor', 'api', 'drug', 'product',
]

export const COLUMN_LABEL: Record<string, string> = {
  country: 'Jurisdiction',
  company: 'DMF holder',
  precursor: 'Precursor',
  api: 'Active ingredient',
  drug: 'Drug product',
  product: 'NDC',
}

export const NODE_W = 168
export const NODE_H = 38
export const COL_GAP = 214
export const ROW_GAP = 56
export const PAD_X = 26
export const PAD_TOP = 42
// The caption is an HTML overlay on .main, not part of the SVG, so the diagram
// only needs breathing room here — not a reserved caption band.
export const PAD_BOTTOM = 28

export interface Placed {
  id: NodeId
  node: GraphNode
  col: number
  x: number
  y: number
}

export interface Layout {
  placed: Placed[]
  pos: Map<NodeId, Placed>
  width: number
  height: number
  columns: { col: number; type: NodeType; x: number; count: number }[]
}

/**
 * Material-flow direction for rendering.
 *
 * The data models edges as REFERENCES ("6-APA is produced_by X", "X is
 * incorporated_in CN"), which point the opposite way from how material actually
 * moves. Drawing them raw gives a picture with arrows colliding in the middle.
 * This maps each relation to the direction the material travels, so every arrow
 * on screen points the same way and the chain reads left to right. The reference
 * direction is preserved untouched in the data and shown in the inspector.
 */
export function flowOf(e: GraphEdge): [NodeId, NodeId] {
  switch (e.rel) {
    case 'produced_by':      // precursor <- company
    case 'incorporated_in':  // company   <- country
      return [e.dst, e.src]
    default:                 // feeds, formulated_into: already material order
      return [e.src, e.dst]
  }
}

function colOf(n: GraphNode): number {
  const i = COLUMNS.indexOf(n.type)
  return i === -1 ? COLUMNS.length : i
}

export function layoutGraph(nodes: GraphNode[], edges: GraphEdge[]): Layout {
  const buckets = new Map<number, GraphNode[]>()
  for (const n of nodes) {
    const c = colOf(n)
    ;(buckets.get(c) ?? buckets.set(c, []).get(c)!).push(n)
  }

  // Drop empty columns so a lane nobody has loaded yet (product:, before the
  // openFDA lane lands) does not leave a blank gutter mid-diagram.
  const used = [...buckets.keys()].sort((a, b) => a - b)

  const order = new Map<number, NodeId[]>()
  for (const c of used) {
    order.set(c, buckets.get(c)!
      .slice()
      .sort((a, b) => (a.label ?? a.id).localeCompare(b.label ?? b.id))
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

  // Two sweeps is enough to settle ~24 nodes and keeps the result stable run to
  // run. Nodes with no placed neighbour keep their alphabetical rank.
  const colOfId = new Map<NodeId, number>()
  for (const n of nodes) colOfId.set(n.id, colOf(n))

  for (let pass = 0; pass < 2; pass++) {
    for (const c of used) {
      const ids = order.get(c)!
      const bary = new Map<NodeId, number>()
      for (const id of ids) {
        const ns = (nbr.get(id) ?? []).filter((m) => colOfId.get(m) !== c)
        const rs = ns.map((m) => rank.get(m)).filter((r): r is number => r != null)
        bary.set(id, rs.length ? rs.reduce((a, b) => a + b, 0) / rs.length : rank.get(id)!)
      }
      ids.sort((a, b) => (bary.get(a)! - bary.get(b)!) || a.localeCompare(b))
      reindex()
    }
  }

  const byId = new Map(nodes.map((n) => [n.id, n]))
  const tallest = Math.max(...used.map((c) => order.get(c)!.length))
  const height = PAD_TOP + tallest * ROW_GAP + PAD_BOTTOM
  const width = PAD_X * 2 + (used.length - 1) * COL_GAP + NODE_W

  const placed: Placed[] = []
  const columns: Layout['columns'] = []

  used.forEach((c, ci) => {
    const ids = order.get(c)!
    const x = PAD_X + ci * COL_GAP
    // Centre each column against the tallest one, so short columns sit on the
    // diagram's axis instead of hugging the top.
    const top = PAD_TOP + ((tallest - ids.length) * ROW_GAP) / 2
    columns.push({ col: c, type: COLUMNS[c] ?? 'product', x, count: ids.length })
    ids.forEach((id, i) => {
      placed.push({ id, node: byId.get(id)!, col: c, x, y: top + i * ROW_GAP })
    })
  })

  return { placed, pos: new Map(placed.map((p) => [p.id, p])), width, height, columns }
}

/** Cubic bezier between two boxes, entering/leaving horizontally. */
export function edgePath(a: Placed, b: Placed): string {
  const x1 = a.x + NODE_W, y1 = a.y + NODE_H / 2
  const x2 = b.x,          y2 = b.y + NODE_H / 2
  // Same column (shouldn't happen, but don't emit NaN if it does).
  if (Math.abs(x2 - x1) < 1) return `M${x1},${y1} L${x2},${y2}`
  const dx = Math.max(30, (x2 - x1) * 0.5)
  return `M${x1},${y1} C${x1 + dx},${y1} ${x2 - dx},${y2} ${x2},${y2}`
}

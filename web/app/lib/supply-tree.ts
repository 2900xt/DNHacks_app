// The bill of materials as a TREE, and what happens to it when a node fails.
//
// WHY A TREE AND NOT THE COLUMNED GRAPH: the columned view (graph-layout.ts) is
// the honest picture of the whole dataset — seven lanes, edges crossing, an
// hourglass waist. It is the right diagram for someone who already knows what a
// DMF is. It is the wrong diagram for the buyer, who has exactly one question:
// "what does my drug need, and what is still standing?" A tree answers that with
// its shape alone. Root = the finished drug she is trying to re-order. Down one
// level = what it is made of. Leaves = the places it actually comes from.
//
// The columned graph is kept, on a tab, because judges ask to see the raw thing.
//
// CASCADE DIRECTION: material flows UP this tree (leaf source -> precursor ->
// API -> drug), so a failure at any node propagates UP to the root. That is the
// opposite of the reachability walk in lib/graph.ts, which follows outgoing
// edges DOWN. Both are correct; they answer different questions. This one asks
// "is my drug still supplied", which is the question the demo is about.
//
// REDUNDANCY IS THE WHOLE POINT: a parent is not dead because one child died. It
// is dead when they ALL died, and at risk in between. Anything that just paints
// every ancestor red overstates the damage and a procurement person will spot it
// in one second.

import type { GraphEdge, GraphNode, NodeId } from './types'

export type Health = 'ok' | 'at-risk' | 'down'
export type TreeKind = 'drug' | 'api' | 'precursor' | 'supplier'

export interface TreeNode {
  id: NodeId
  node: GraphNode
  kind: TreeKind
  depth: number
  children: TreeNode[]
  /** ISO-2 of the jurisdiction a supplier is incorporated in, when resolved. */
  iso?: string
  countryId?: NodeId
  countryLabel?: string
}

/** What a node's subtree is worth after the failures are applied. */
export interface Rollup {
  health: Health
  /** Qualified leaf sources still standing beneath this node. */
  up: number
  /** Qualified leaf sources beneath it in total, failures included. */
  total: number
  /** True when this exact node was the one switched off. */
  origin: boolean
}

/** One jurisdiction's share of supply, recomputed after every failure. */
export interface Route {
  iso: string
  countryId: NodeId
  label: string
  total: number
  up: number
  /** Fraction of ALL surviving supply now carried by this jurisdiction, 0..1. */
  share: number
  down: boolean
}

export const LEVEL_LABEL: Record<TreeKind, string> = {
  drug: 'Final drug',
  api: 'Active ingredient',
  precursor: 'Precursor',
  supplier: 'Qualified sources',
}

/** Unresolved-jurisdiction bucket. DEMO_PATH is explicit that one of the eight
 *  filings has no resolved country, and inventing one for it is a lie a judge
 *  can check. It gets its own group and says so. */
export const UNRESOLVED = 'zz'

// ---------------------------------------------------------------------------
// build
// ---------------------------------------------------------------------------

/**
 * Assemble the tree for one finished drug.
 *
 * drug      <-active_in--   api
 * api       <-feeds------   precursor
 * precursor -produced_by->  company    (reference direction: the material runs
 *                                       the other way)
 * company   -incorporated_in-> country
 *
 * Which is already a tree, and already the bill of materials in the order a
 * person would say it out loud: amoxicillin is made from amoxicillin
 * trihydrate, which is built on 6-APA, which comes from eight filings in three
 * jurisdictions.
 */
export function buildTree(
  nodes: GraphNode[],
  edges: GraphEdge[],
  rootId: NodeId,
): TreeNode | null {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const root = byId.get(rootId)
  if (!root) return null

  const countryOf = new Map<NodeId, GraphNode>()
  for (const e of edges) {
    if (e.rel !== 'incorporated_in') continue
    const c = byId.get(e.dst)
    if (c) countryOf.set(e.src, c)
  }

  const supplierIds = (precursorId: NodeId) =>
    edges.filter((e) => e.rel === 'produced_by' && e.src === precursorId).map((e) => e.dst)

  const supplier = (id: NodeId, depth: number): TreeNode | null => {
    const n = byId.get(id)
    if (!n) return null
    const c = countryOf.get(id)
    return {
      id, node: n, kind: 'supplier', depth, children: [],
      iso: c?.country ?? undefined,
      countryId: c?.id,
      countryLabel: c?.label ?? c?.id,
    }
  }

  const precursorNodes = (parentId: NodeId, depth: number): TreeNode[] =>
    edges
      .filter((e) => e.rel === 'feeds' && e.dst === parentId)
      .map((e) => byId.get(e.src))
      .filter((n): n is GraphNode => !!n)
      .map((p) => ({
        id: p.id, node: p, kind: 'precursor' as const, depth,
        children: supplierIds(p.id)
          .map((id) => supplier(id, depth + 1))
          .filter((t): t is TreeNode => !!t)
          .sort(sortSuppliers),
      }))

  const apiNodes: TreeNode[] = edges
    .filter((e) => e.rel === 'active_in' && e.dst === rootId)
    .map((e) => byId.get(e.src))
    .filter((n): n is GraphNode => !!n)
    .map((a) => ({
      id: a.id, node: a, kind: 'api' as const, depth: 1,
      children: precursorNodes(a.id, 2),
    }))

  return {
    id: root.id, node: root, kind: 'drug', depth: 0,
    // A precursor wired straight to the drug rather than through an API would
    // otherwise vanish from the tree entirely. It does not happen in the current
    // artifacts; it is one line to make sure it never silently could.
    children: [...apiNodes, ...precursorNodes(rootId, 1)],
  }
}

/** Suppliers sit grouped by jurisdiction, so the concentration is visible as
 *  geometry rather than something you have to read off eight labels. Unresolved
 *  sorts last — it is a caveat, not a country. */
function sortSuppliers(a: TreeNode, b: TreeNode): number {
  const ka = a.iso ?? UNRESOLVED
  const kb = b.iso ?? UNRESOLVED
  if (ka !== kb) {
    if (ka === UNRESOLVED) return 1
    if (kb === UNRESOLVED) return -1
    return ka.localeCompare(kb)
  }
  return (a.node.label ?? a.id).localeCompare(b.node.label ?? b.id)
}

/** Every drug that draws on any precursor in this tree — the fan-out set. They
 *  share the chokepoint, so they share its fate. Two hops: the precursor feeds
 *  APIs, and each API is active in a drug. */
export function siblingDrugs(edges: GraphEdge[], tree: TreeNode | null): NodeId[] {
  if (!tree) return []
  const precursors = new Set<NodeId>()
  walk(tree, (t) => { if (t.kind === 'precursor') precursors.add(t.id) })

  const apis = new Set<NodeId>()
  for (const e of edges) if (e.rel === 'feeds' && precursors.has(e.src)) apis.add(e.dst)

  const out = new Set<NodeId>()
  for (const e of edges) {
    if (e.rel === 'active_in' && apis.has(e.src) && e.dst !== tree.id) out.add(e.dst)
  }
  return [...out]
}

export function walk(t: TreeNode, fn: (t: TreeNode) => void) {
  fn(t)
  for (const c of t.children) walk(c, fn)
}

export function flatten(t: TreeNode | null): TreeNode[] {
  if (!t) return []
  const out: TreeNode[] = []
  walk(t, (n) => out.push(n))
  return out
}

// ---------------------------------------------------------------------------
// cascade
// ---------------------------------------------------------------------------

/**
 * Roll failures up the tree.
 *
 * A leaf is worth one qualified source. A parent is worth the sum of its
 * children, EXCEPT that switching a node off zeroes its own contribution no
 * matter how healthy the things underneath it are — knocking out the precursor
 * strands its eight suppliers rather than deleting them, which is exactly what
 * an export ban does.
 */
export function evaluate(
  tree: TreeNode | null,
  compromised: Set<NodeId>,
): Map<NodeId, Rollup> {
  const out = new Map<NodeId, Rollup>()
  if (!tree) return out

  const visit = (t: TreeNode): Rollup => {
    const origin = compromised.has(t.id)
    let r: Rollup
    if (!t.children.length) {
      r = { health: origin ? 'down' : 'ok', up: origin ? 0 : 1, total: 1, origin }
    } else {
      const kids = t.children.map(visit)
      const total = kids.reduce((s, k) => s + k.total, 0)
      const up = origin ? 0 : kids.reduce((s, k) => s + k.up, 0)
      r = {
        health: up === 0 ? 'down' : up < total ? 'at-risk' : 'ok',
        up, total, origin,
      }
    }
    out.set(t.id, r)
    return r
  }

  visit(tree)
  return out
}

/**
 * Re-allocate demand across whatever is left, and hand the map the new picture.
 *
 * This is the "recalculate the routes" step and it is deliberately the simplest
 * defensible model: surviving qualified sources split the load evenly, so
 * knocking out half of them doubles what the other half carries. There is NO
 * public capacity data per DMF holder — FEATURES.md § cut order says so — and a
 * weighting invented to look sophisticated is a number a judge can ask about and
 * we cannot answer. Even split, stated plainly, is the honest version.
 *
 * A supplier whose chain is cut above it counts as down even though the supplier
 * itself is fine: it cannot ship through a dead precursor.
 */
export function allocate(
  tree: TreeNode | null,
  compromised: Set<NodeId>,
): Route[] {
  if (!tree) return []

  const groups = new Map<string, Route>()
  const bump = (t: TreeNode, alive: boolean) => {
    const iso = t.iso ?? UNRESOLVED
    const g = groups.get(iso) ?? {
      iso,
      countryId: t.countryId ?? '',
      label: t.countryLabel ?? 'Country unresolved',
      total: 0, up: 0, share: 0, down: false,
    }
    g.total += 1
    if (alive) g.up += 1
    groups.set(iso, g)
  }

  // `cut` carries downward: anything switched off strands everything under it.
  const visit = (t: TreeNode, cut: boolean) => {
    const dead = cut || compromised.has(t.id)
    if (!t.children.length) {
      if (t.kind === 'supplier') bump(t, !dead)
      return
    }
    for (const c of t.children) visit(c, dead)
  }
  visit(tree, false)

  const totalUp = [...groups.values()].reduce((s, g) => s + g.up, 0)
  const routes = [...groups.values()]
  for (const g of routes) {
    g.share = totalUp ? g.up / totalUp : 0
    g.down = g.up === 0
  }
  return routes.sort((a, b) => b.up - a.up || a.iso.localeCompare(b.iso))
}

// ---------------------------------------------------------------------------
// layout
// ---------------------------------------------------------------------------

/* The level-label gutter. Wide enough for "Qualified sources" to clear the
   first jurisdiction band; widening it is free while height sets the scale. */
export const GUTTER = 120
export const PAD_X = 20
export const PAD_TOP = 26
export const PAD_BOTTOM = 18
/* Pitch between levels. The top three are single boxes, so every pixel here is
   spent on branch curve rather than on content — and in a column this narrow the
   height is what sets the scale for the whole diagram. */
export const LEVEL_H = 94
export const LEAF_GAP = 14
/** Leaves WRAP. The tree lives in a column one third of the screen wide, and
 *  eight sources in one row makes a diagram four times wider than it is tall —
 *  which, fitted `meet`, renders every label at a quarter size. Two across, and
 *  each jurisdiction starting a fresh row, keeps the shape near the column's. */
export const LEAF_PER_ROW = 2
export const LEAF_ROW_GAP = 12
/** Space above a jurisdiction's first row for its band label. */
export const GROUP_LABEL_H = 24
/** Between one jurisdiction band and the next. */
export const GROUP_GAP = 12

export const NODE_W: Record<TreeKind, number> = {
  // Suppliers are the long names — "The United Laboratories (Inner Mongolia)"
  // — and the diagram is height-limited in this column, so widening them costs
  // nothing and buys three more characters before the ellipsis.
  drug: 272, api: 240, precursor: 254, supplier: 200,
}
export const NODE_H: Record<TreeKind, number> = {
  drug: 60, api: 58, precursor: 58, supplier: 66,
}

export interface Placed {
  t: TreeNode
  x: number; y: number; w: number; h: number
}

export interface Group {
  iso: string
  label: string
  countryId: NodeId
  x: number; w: number; y: number
  /** Band height. A jurisdiction with more than LEAF_PER_ROW sources spans
   *  several rows, so the band cannot assume one node's worth of height. */
  h: number
  ids: NodeId[]
}

export interface TreeLayout {
  placed: Placed[]
  pos: Map<NodeId, Placed>
  groups: Group[]
  levels: { depth: number; y: number; label: string }[]
  width: number
  height: number
}

/**
 * Bottom-up tidy layout. Leaves are laid out left to right in jurisdiction
 * groups; every parent centres over its children. Deterministic — a tree that
 * reflows differently on the projector than it did in rehearsal is a bug.
 */
export function layoutTree(tree: TreeNode | null): TreeLayout {
  const placed: Placed[] = []
  const groups: Group[] = []
  if (!tree) {
    return { placed, pos: new Map(), groups, levels: [], width: 100, height: 100 }
  }

  const yOf = (depth: number) => PAD_TOP + depth * LEVEL_H

  // Leaves first, in DFS order, so jurisdiction runs stay contiguous.
  const leaves: TreeNode[] = []
  ;(function collect(t: TreeNode) {
    if (!t.children.length) leaves.push(t)
    else t.children.forEach(collect)
  })(tree)

  const leafTop = leaves.length ? yOf(Math.max(...leaves.map((t) => t.depth))) : yOf(0)
  const leafPos = new Map<NodeId, { x: number; y: number }>()

  let y = leafTop
  let col = 0
  let lastIso: string | null = null
  let group: Group | null = null

  for (const t of leaves) {
    const w = NODE_W[t.kind]
    const h = NODE_H[t.kind]
    const iso = t.kind === 'supplier' ? (t.iso ?? UNRESOLVED) : '-'

    if (iso !== lastIso) {
      // A new jurisdiction always starts its own row, under its own label.
      if (lastIso !== null) y += h + LEAF_ROW_GAP + GROUP_GAP
      y += GROUP_LABEL_H
      col = 0
      lastIso = iso
      group = {
        iso,
        label: t.countryLabel ?? 'Country unresolved',
        countryId: t.countryId ?? '',
        x: GUTTER + PAD_X, w, y: y - GROUP_LABEL_H + 2, h,
        ids: [],
      }
      groups.push(group)
    } else if (col >= LEAF_PER_ROW) {
      y += h + LEAF_ROW_GAP
      col = 0
    }

    const x = GUTTER + PAD_X + col * (w + LEAF_GAP)
    leafPos.set(t.id, { x, y })
    col++

    if (group) {
      group.w = Math.max(group.w, x + w - group.x)
      group.h = y + h - group.y + 6
      group.ids.push(t.id)
    }
  }

  /** Returns the node's centre x. Leaves read their wrapped slot; every parent
   *  centres over its children, as before. */
  const place = (t: TreeNode): number => {
    const w = NODE_W[t.kind]
    const h = NODE_H[t.kind]
    let cx: number
    let ty: number

    if (!t.children.length) {
      const lp = leafPos.get(t.id)
      cx = (lp?.x ?? GUTTER + PAD_X) + w / 2
      ty = lp?.y ?? yOf(t.depth)
    } else {
      const kids = t.children.map(place)
      cx = (Math.min(...kids) + Math.max(...kids)) / 2
      ty = yOf(t.depth)
    }

    placed.push({ t, x: cx - w / 2, y: ty, w, h })
    return cx
  }

  place(tree)

  const right = Math.max(...placed.map((p) => p.x + p.w), ...groups.map((g) => g.x + g.w))
  const bottom = Math.max(...placed.map((p) => p.y + p.h), ...groups.map((g) => g.y + g.h))

  // Levels are labelled once, in a left gutter, instead of on every box.
  const levels: TreeLayout['levels'] = []
  const seen = new Set<number>()
  for (const p of placed.slice().sort((a, b) => a.t.depth - b.t.depth)) {
    if (seen.has(p.t.depth)) continue
    seen.add(p.t.depth)
    levels.push({ depth: p.t.depth, y: p.y + p.h / 2, label: LEVEL_LABEL[p.t.kind] })
  }

  return {
    placed,
    pos: new Map(placed.map((p) => [p.t.id, p])),
    groups,
    levels,
    width: right + PAD_X,
    height: bottom + PAD_BOTTOM,
  }
}

/** Parent bottom-centre to child top-centre. Curved rather than elbowed: the
 *  fan-out from one precursor to eight sources is the shape being sold, and
 *  right angles turn it into a bus bar. */
export function branchPath(parent: Placed, child: Placed): string {
  const x1 = parent.x + parent.w / 2
  const y1 = parent.y + parent.h
  const x2 = child.x + child.w / 2
  const y2 = child.y
  const d = Math.max(18, (y2 - y1) * 0.55)
  return `M${x1},${y1} C${x1},${y1 + d} ${x2},${y2 - d} ${x2},${y2}`
}

// ---------------------------------------------------------------------------
// wording
// ---------------------------------------------------------------------------

/** The one-line consequence, in the buyer's words. Shown on the map caption and
 *  read aloud on stage, so it says sources — never "nodes". */
export function impactLine(
  drugLabel: string,
  rollup: Rollup | undefined,
  routes: Route[],
  failures: number,
): string {
  if (!rollup) return ''
  const verb =
    rollup.health === 'down' ? 'has no qualified supply left'
      : rollup.health === 'at-risk' ? 'is still supplied, on a thinner base'
      : 'is unaffected'
  const live = routes.filter((r) => !r.down)
  const via = live.length
    ? ` Rerouted through ${list(live.map((r) => r.label))}.`
    : ''
  const s = failures === 1 ? '' : 's'
  return `${failures} failure${s} simulated. ${drugLabel} ${verb} — `
    + `${rollup.up} of ${rollup.total} qualified sources standing.${via}`
}

function list(xs: string[]): string {
  if (xs.length <= 1) return xs[0] ?? ''
  if (xs.length === 2) return `${xs[0]} and ${xs[1]}`
  return `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`
}

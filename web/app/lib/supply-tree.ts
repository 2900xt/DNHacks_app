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

import type { GraphEdge, GraphNode, NodeId, Reroute, RerouteHolder } from './types'

export type Health = 'ok' | 'at-risk' | 'down'
export type TreeKind = 'drug' | 'api' | 'precursor' | 'supplier'

export interface TreeNode {
  id: NodeId
  /** `${parentId}|${id}`. One company can hold a DMF for the API AND for the
   *  precursor, so the same id can sit in the tree twice; the key is unique. */
  key: string
  node: GraphNode
  kind: TreeKind
  depth: number
  children: TreeNode[]
  /** Which register a supplier filed in: for the API itself, or its precursor. */
  tier?: 'api' | 'precursor'
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

  const supplierIds = (parentId: NodeId) =>
    edges.filter((e) => e.rel === 'produced_by' && e.src === parentId).map((e) => e.dst)

  const supplier = (id: NodeId, depth: number, tier: 'api' | 'precursor', parentId: NodeId): TreeNode | null => {
    const n = byId.get(id)
    if (!n) return null
    const c = countryOf.get(id)
    return {
      id, key: `${parentId}|${id}`, node: n, kind: 'supplier', depth, children: [], tier,
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
        id: p.id, key: `${parentId}|${p.id}`, node: p, kind: 'precursor' as const, depth,
        children: supplierIds(p.id)
          .map((id) => supplier(id, depth + 1, 'precursor', p.id))
          .filter((t): t is TreeNode => !!t)
          .sort(sortSuppliers),
      }))

  // Two tiers under an API. Its own DMF holders — the plants a buyer actually
  // qualifies — and the precursor they all draw on, with ITS holders beneath.
  // The precursor is a gate, not a source: see evaluate().
  const apiNodes: TreeNode[] = edges
    .filter((e) => e.rel === 'active_in' && e.dst === rootId)
    .map((e) => byId.get(e.src))
    .filter((n): n is GraphNode => !!n)
    .map((a) => ({
      id: a.id, key: `${rootId}|${a.id}`, node: a, kind: 'api' as const, depth: 1,
      children: [
        ...supplierIds(a.id)
          .map((id) => supplier(id, 2, 'api', a.id))
          .filter((t): t is TreeNode => !!t)
          .sort(sortSuppliers),
        ...precursorNodes(a.id, 2),
      ],
    }))

  return {
    id: root.id, key: `root|${root.id}`, node: root, kind: 'drug', depth: 0,
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
/**
 * Everything that cannot ship, given the failures.
 *
 * Four ways in. Switched off itself — a plant failure. Inside a jurisdiction
 * whose EXPORTS are halted — the plant is producing and nothing leaves; the
 * country id sits in `compromised` for that. Underneath something switched
 * off — a plant behind a dead precursor cannot ship through it. Or GATED: an
 * API holder is standing, its own plant is fine, but every source of the
 * precursor it needs is gone, so it has nothing to make the API from. That
 * last one is what an export ban on 6-APA does to a plant in Italy, and it is
 * why the precursor sits under the API as a gate rather than beside its
 * holders as one more source.
 */
export function cutSet(tree: TreeNode | null, compromised: Set<NodeId>): Set<NodeId> {
  const cut = new Set<NodeId>()
  if (!tree) return cut
  const leavesOf = (t: TreeNode): TreeNode[] =>
    t.children.length ? t.children.flatMap(leavesOf) : [t]
  const visit = (t: TreeNode, dead: boolean) => {
    const halted = !!t.countryId && compromised.has(t.countryId)
    const d = dead || compromised.has(t.id) || halted
    if (d) cut.add(t.id)
    // Gates first, so their fate is known before the holders they gate.
    const gates = t.children.filter((c) => c.kind !== 'supplier')
    for (const c of gates) visit(c, d)
    const gated = gates.length > 0
      && gates.every((g) => cut.has(g.id) || leavesOf(g).every((l) => cut.has(l.id)))
    for (const c of t.children) if (c.kind === 'supplier') visit(c, d || gated)
  }
  visit(tree, false)
  return cut
}

export function evaluate(
  tree: TreeNode | null,
  compromised: Set<NodeId>,
): Map<NodeId, Rollup> {
  const out = new Map<NodeId, Rollup>()
  if (!tree) return out
  const cut = cutSet(tree, compromised)

  const visit = (t: TreeNode): Rollup => {
    const origin = compromised.has(t.id)
    let r: Rollup
    if (!t.children.length) {
      const dead = cut.has(t.id)
      r = { health: dead ? 'down' : 'ok', up: dead ? 0 : 1, total: 1, origin }
    } else {
      const kids = t.children.map(visit)
      // A node's SOURCES are its supplier children when it has any; the
      // precursor beneath an API is a gate on those, already applied by
      // cutSet, and is not counted as a ninth source of the API.
      const sups = t.children
        .map((c, i) => [c, kids[i]] as const)
        .filter(([c]) => c.kind === 'supplier')
        .map(([, k]) => k)
      const pool = sups.length ? sups : kids
      const total = pool.reduce((a, k) => a + k.total, 0)
      const up = origin || cut.has(t.id) ? 0 : pool.reduce((a, k) => a + k.up, 0)
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

  const cut = cutSet(tree, compromised)
  walk(tree, (t) => { if (t.kind === 'supplier') bump(t, !cut.has(t.id)) })

  const totalUp = [...groups.values()].reduce((s, g) => s + g.up, 0)
  const routes = [...groups.values()]
  for (const g of routes) {
    g.share = totalUp ? g.up / totalUp : 0
    g.down = g.up === 0
  }
  return routes.sort((a, b) => b.up - a.up || a.iso.localeCompare(b.iso))
}

// ---------------------------------------------------------------------------
// the AEGIS shortlist — who can still make it, ranked
// ---------------------------------------------------------------------------

/** One DMF holder, as the console sees it after the failures are applied. */
export interface Alternate {
  id: NodeId
  holder: RerouteHolder
  /** False once this holder, or anything above it in the tree, is switched off.
   *  A registered plant behind a dead precursor cannot ship through it. */
  standing: boolean
  /** 1-based, among STANDING holders, by re-ranked score. Absent when cut. */
  rank?: number
  /** The artifact's score re-ranked against the failure: `holder.score + delta`. */
  score: number
  /** What the failure did to this holder as a route, and the reason in words. */
  delta: number
  deltaWhy: string | null
  /** Standing AND re-ranked score > 0. */
  viable: boolean
  /** The one holder the console would call first. At most one row. */
  recommended: boolean
}

export interface Shortlist {
  /** Null when the tree has no precursor, or the artifact has no row for it. */
  precursor: NodeId | null
  substance: string
  rule: string
  /** The re-ranking rule, stated in the same voice as `rule`. */
  rerankRule: string
  notModelled: string[]
  /** Standing holders best first, then the cut ones in their resting order. */
  rows: Alternate[]
  byId: Map<NodeId, Alternate>
  total: number
  standing: number
  /** Standing AND score > 0 — the number the caption reports. */
  viable: number
  /** ISO-2 of every jurisdiction with at least one switched-off source. */
  failedIsos: string[]
  /** The recommended route, or null when nothing viable is standing. */
  best: Alternate | null
  /** Which register the rows come from. The API tier is what a buyer
   *  qualifies; the precursor tier is the answer when the failure is above
   *  every API holder at once. */
  scope: 'api' | 'precursor'
  scopeNode: NodeId | null
}

/** Re-ranking against the failure. The artifact scores a plant on its own
 *  record; this is the one term that depends on what just went down, so it
 *  lives here, where the failure is known. Stated verbatim on the rail. */
export const RERANK_TEXT =
  'Re-ranked against the failure: +2 when every site is outside the jurisdictions '
  + 'that just failed; −2 when it shares one. A site nobody can place gets neither.'
const AWAY_BONUS = 2
const SAME_PENALTY = -2

/**
 * Re-rank the pathfinder's output against the current failures.
 *
 * `ml/aegis.py` scores every holder ONCE, on its own registration, geography,
 * TAA status and enforcement history — none of which changes when a neighbour
 * goes down. What DOES change is whether a holder is still a way around the
 * failure: a second plant in the jurisdiction that just went dark is the same
 * exposure, not an alternative to it. So a failure is a filter plus one term —
 * drop what is cut, move survivors by where they sit relative to the failed
 * jurisdictions, and call the top viable one the route. That is what lets the
 * same artifact answer every click without a network on stage.
 */
export function shortlist(
  reroute: Reroute,
  tree: TreeNode | null,
  compromised: Set<NodeId>,
  /** Name a route. Off until the operator asks: a failure is shown the moment
   *  it happens; the answer to it is a step the operator takes. */
  wantRoute = true,
): Shortlist {
  const empty: Shortlist = {
    precursor: null, substance: '', rule: reroute.rule_text ?? '', rerankRule: RERANK_TEXT,
    notModelled: reroute.not_modelled ?? [],
    rows: [], byId: new Map(), total: 0, standing: 0, viable: 0, failedIsos: [], best: null,
    scope: 'api', scopeNode: null,
  }
  if (!tree) return empty

  const cut = cutSet(tree, compromised)
  let api: TreeNode | null = null
  let precursor: TreeNode | null = null
  walk(tree, (t) => {
    if (t.kind === 'api' && !api) api = t
    if (t.kind === 'precursor' && !precursor) precursor = t
  })
  const apiT = api as TreeNode | null
  const preT = precursor as TreeNode | null

  /** One tier's rows, re-ranked against ITS OWN failed jurisdictions. */
  const tier = (node: TreeNode | null, leaves: TreeNode[]) => {
    if (!node) return null
    const row = (reroute.precursors ?? []).find((p) => p.node === node.id)
    if (!row) return null
    const failed = new Set<string>()
    for (const l of leaves) if (cut.has(l.id) && l.iso && l.iso !== UNRESOLVED) failed.add(l.iso)
    const failedIsos = [...failed].sort()
    const failedTxt = failedIsos.map((c) => c.toUpperCase()).join('/')
    const standing: Alternate[] = []
    const down: Alternate[] = []
    for (const h of row.holders) {
      if (!h.node_id) continue
      const isStanding = !cut.has(h.node_id)
      let delta = 0
      let deltaWhy: string | null = null
      if (isStanding && failedIsos.length && h.iso2.length) {
        const shares = h.iso2.some((c) => failed.has(c))
        delta = shares ? SAME_PENALTY : AWAY_BONUS
        deltaWhy = shares
          ? `same jurisdiction as the failure (${failedTxt}) — same exposure, not a way around it`
          : `every site outside the failed jurisdiction${failedIsos.length === 1 ? '' : 's'} (${failedTxt})`
      } else if (isStanding && failedIsos.length) {
        deltaWhy = 'site cannot be placed — no diversification credit either way'
      }
      const score = h.score + delta
      const alt: Alternate = {
        id: h.node_id, holder: h, standing: isStanding,
        score, delta, deltaWhy, viable: isStanding && score > 0, recommended: false,
      }
      ;(isStanding ? standing : down).push(alt)
    }
    standing.sort((a, b) => b.score - a.score || b.holder.score - a.holder.score)
    standing.forEach((a, i) => { a.rank = i + 1 })
    const best = wantRoute && compromised.size > 0 && standing[0]?.viable ? standing[0] : null
    return { node, row, rows: [...standing, ...down], standing: standing.length,
      viable: standing.filter((a) => a.viable).length, failedIsos, best }
  }

  const apiLeaves = apiT ? apiT.children.filter((c) => c.kind === 'supplier') : []
  const preLeaves = preT ? preT.children : []
  const apiTier = tier(apiT, apiLeaves)
  const preTier = tier(preT, preLeaves)

  // Scope. A failure that only the precursor's register can answer — the
  // precursor itself, or a holder that files ONLY for it — is upstream of
  // every API holder, so that register is shown. A company that holds both
  // filings failing is still a failure the API register can route around,
  // and that is the register a buyer acts on; it wins whenever it can.
  const preIds = new Set<NodeId>(preT ? [preT.id, ...preLeaves.map((l) => l.id)] : [])
  const apiIds = new Set<NodeId>(apiLeaves.map((l) => l.id))
  const upstream = [...cut].some((id) => preIds.has(id) && !apiIds.has(id))
  const chosen = (upstream ? preTier : apiTier) ?? apiTier ?? preTier
  if (!chosen) return empty
  if (chosen.best) chosen.best.recommended = true

  // Both tiers' rows are addressable by id, so every supplier box on the tree
  // carries its rank even when the rail is showing the other register.
  const byId = new Map<NodeId, Alternate>()
  for (const t of [apiTier, preTier]) if (t && t !== chosen) for (const a of t.rows) byId.set(a.id, a)
  for (const a of chosen.rows) byId.set(a.id, a)

  return {
    precursor: preT?.id ?? null,
    substance: chosen.row.substance,
    rule: reroute.rule_text ?? '',
    rerankRule: RERANK_TEXT,
    notModelled: reroute.not_modelled ?? [],
    rows: chosen.rows,
    byId,
    total: chosen.rows.length,
    standing: chosen.standing,
    viable: chosen.viable,
    failedIsos: chosen.failedIsos,
    best: chosen.best,
    scope: chosen === preTier ? 'precursor' : 'api',
    scopeNode: chosen.node.id,
  }
}

/** The pathfinder's one-line verdict, for the caption under the impact line. */
export function shortlistLine(sl: Shortlist, label: (id: NodeId) => string): string {
  if (!sl.scopeNode) return ''
  if (sl.standing === 0) return 'AEGIS: nothing left to rank — every filing holder is offline.'
  if (sl.viable === 0) {
    return `AEGIS: no viable re-route. Every standing holder is unregistered in DECRS, `
      + `ambiguous, inside the same chokepoint, or carries its own enforcement history.`
  }
  const best = sl.best ?? sl.rows[0]
  const iso = (a: Alternate) => a.holder.iso2.map((c) => c.toUpperCase()).join('/') || '?'
  const signed = (n: number) => `${n > 0 ? '+' : ''}${n.toFixed(1)}`
  const away = best.delta > 0
    ? ` — outside ${sl.failedIsos.map((c) => c.toUpperCase()).join('/')}, ${signed(best.delta)} re-ranked`
    : ''
  const backup = sl.rows.find((a) => a.viable && a.id !== best.id)
  const next = backup ? ` Next: ${label(backup.id)} (${iso(backup)}, ${signed(backup.score)}).` : ''
  const others = sl.viable - 1
  return `AEGIS route for ${sl.substance}: ${label(best.id)} (${iso(best)}, ${signed(best.score)}${away}).`
    + ` ${others} other viable of ${sl.standing} standing.${next}`
}

// ---------------------------------------------------------------------------
// layout
// ---------------------------------------------------------------------------

/* No gutter: the tree owns the column's full width. Zero, not deleted, so the
   layout's x-origin still reads as one constant. */
export const GUTTER = 0
export const PAD_X = 20
export const PAD_TOP = 22
export const PAD_BOTTOM = 18
/** Space under a box before what hangs off it — room for the branch curve. */
export const LEVEL_GAP = 34
export const LEAF_GAP = 14
/** Leaves WRAP, two across, so the diagram keeps the column's shape. */
export const LEAF_PER_ROW = 2
export const LEAF_ROW_GAP = 12
/** Space above a jurisdiction's first row for its band label. */
export const GROUP_LABEL_H = 24
/** Between one jurisdiction band and the next. */
export const GROUP_GAP = 12
/** Between the last band of one tier and the box that starts the next. */
export const TIER_GAP = 30

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
  /** Keyed by TreeNode.key, not id — see TreeNode. */
  pos: Map<string, Placed>
  groups: Group[]
  width: number
  height: number
}

/**
 * Bottom-up tidy layout. Leaves are laid out left to right in jurisdiction
 * groups; every parent centres over its children. Deterministic — a tree that
 * reflows differently on the projector than it did in rehearsal is a bug.
 */
/**
 * A vertical flow, top to bottom, in the order a buyer reads:
 *
 *   drug
 *   api
 *     [API register: its holders, banded by jurisdiction]
 *     precursor
 *       [precursor register: its holders, banded by jurisdiction]
 *
 * Boxes take the width of two leaf columns; every internal node is centred
 * over those columns. The precursor is reached by a feed line down the left
 * margin (feedPath), because it is a gate under the API holders, not a
 * sibling of theirs. Height is whatever the content needs — the column
 * scrolls; the boxes never shrink to fit.
 */
export function layoutTree(tree: TreeNode | null): TreeLayout {
  const placed: Placed[] = []
  const groups: Group[] = []
  const pos = new Map<string, Placed>()
  if (!tree) return { placed, pos, groups, width: 100, height: 100 }

  const colW = NODE_W.supplier * LEAF_PER_ROW + LEAF_GAP * (LEAF_PER_ROW - 1)
  const centre = (w: number) => GUTTER + PAD_X + colW / 2 - w / 2
  let y = PAD_TOP

  const layGroups = (leaves: TreeNode[]) => {
    let col = 0
    let lastIso: string | null = null
    let group: Group | null = null
    let rowH = 0
    for (const t of leaves) {
      const w = NODE_W[t.kind]
      const h = NODE_H[t.kind]
      const iso = t.iso ?? UNRESOLVED
      if (iso !== lastIso) {
        if (lastIso !== null) y += rowH + LEAF_ROW_GAP + GROUP_GAP
        y += GROUP_LABEL_H
        col = 0
        lastIso = iso
        group = {
          iso,
          label: t.countryLabel ?? 'Country unresolved',
          countryId: t.countryId ?? '',
          // Every band spans both leaf columns, even a band of one. The
          // trunk runs down the gap between the columns (see trunkPath), and
          // a narrow band would put its right edge exactly under that line.
          x: GUTTER + PAD_X, w: colW, y: y - GROUP_LABEL_H + 2, h,
          ids: [],
        }
        groups.push(group)
      } else if (col >= LEAF_PER_ROW) {
        y += h + LEAF_ROW_GAP
        col = 0
      }
      const x = GUTTER + PAD_X + col * (w + LEAF_GAP)
      const p: Placed = { t, x, y, w, h }
      placed.push(p)
      pos.set(t.key, p)
      col++
      rowH = h
      if (group) {
        group.w = Math.max(group.w, x + w - group.x)
        group.h = y + h - group.y + 6
        group.ids.push(t.id)
      }
    }
    if (lastIso !== null) y += rowH + LEAF_ROW_GAP
  }

  const visit = (t: TreeNode) => {
    const w = NODE_W[t.kind]
    const h = NODE_H[t.kind]
    const p: Placed = { t, x: centre(w), y, w, h }
    placed.push(p)
    pos.set(t.key, p)
    y += h + LEVEL_GAP

    const sups = t.children.filter((c) => c.kind === 'supplier')
    if (sups.length) layGroups(sups)
    const gates = t.children.filter((c) => c.kind !== 'supplier')
    for (const g of gates) {
      if (sups.length) y += TIER_GAP
      visit(g)
    }
  }
  visit(tree)

  return {
    placed, pos, groups,
    width: GUTTER + PAD_X + colW + PAD_X,
    height: y + PAD_BOTTOM,
  }
}

/** The feed line from an API box down the left margin to its precursor —
 *  past the API's own holders, which it does not touch. */
export function feedPath(parent: Placed, child: Placed): string {
  const x1 = parent.x + 12
  const y1 = parent.y + parent.h
  const xm = 7
  const x2 = child.x + 12
  const y2 = child.y
  return `M${x1},${y1} Q${x1},${y1 + 22} ${xm},${y1 + 22} V${y2 - 22} Q${xm},${y2} ${x2},${y2}`
}

/** Between two boxes on the same centre line — drug to api — a straight drop.
 *  Anything else falls back to the old S-curve, which no current layout uses. */
export function branchPath(parent: Placed, child: Placed): string {
  const x1 = parent.x + parent.w / 2
  const y1 = parent.y + parent.h
  const x2 = child.x + child.w / 2
  const y2 = child.y
  if (Math.abs(x1 - x2) < 1) return `M${x1},${y1} V${y2}`
  const d = Math.max(18, (y2 - y1) * 0.55)
  return `M${x1},${y1} C${x1},${y1 + d} ${x2},${y2 - d} ${x2},${y2}`
}

/*
 * Suppliers hang off a TRUNK, not off seven curves from one point.
 *
 * The curves crossed every row between the parent and a far child, so which
 * line reached which box was a guess — and the diagram exists to show exactly
 * that: switch a supplier off and read what is downstream of it. Orthogonal
 * routing makes the connection followable: one vertical from the parent's foot
 * down the gap between the two leaf columns (the one vertical in this layout
 * that crosses no box, since parents are centred over that gap), and one elbow
 * per child that leaves the trunk along the row gap above the child and drops
 * into its top edge. Nothing overlaps a box; every line has one owner.
 */
/** Corner radius on an elbow. Small: a corner reads as a turn, a curve as a guess. */
export const ELBOW_R = 6
/** How far above a child's top edge its elbow runs. Inside LEAF_ROW_GAP (12)
 *  and below the band label's baseline (child.y - 14), so it crosses nothing. */
export const ELBOW_Y = 7

/** The trunk under a parent: from its foot to just above the last elbow. */
export function trunkPath(parent: Placed, children: Placed[]): string {
  const x = parent.x + parent.w / 2
  const y1 = parent.y + parent.h
  const y2 = Math.max(...children.map((c) => c.y)) - ELBOW_Y - ELBOW_R
  return `M${x},${y1} V${Math.max(y1, y2)}`
}

/** One child's elbow off the trunk: out along the row gap above it, then down
 *  into its own top edge. */
export function elbowPath(parent: Placed, child: Placed): string {
  const tx = parent.x + parent.w / 2
  const cx = child.x + child.w / 2
  const y = child.y - ELBOW_Y
  const dx = cx - tx
  if (Math.abs(dx) < 1) return `M${tx},${y - ELBOW_R} V${child.y}`
  const r = Math.min(ELBOW_R, Math.abs(dx) / 2, ELBOW_Y)
  const s = dx > 0 ? 1 : -1
  return `M${tx},${y - r} Q${tx},${y} ${tx + s * r},${y} `
    + `H${cx - s * r} Q${cx},${y} ${cx},${y + r} V${child.y}`
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
  return `${failures} disruption${s} simulated. ${drugLabel} ${verb} — `
    + `${rollup.up} of ${rollup.total} qualified sources standing.${via}`
}

function list(xs: string[]): string {
  if (xs.length <= 1) return xs[0] ?? ''
  if (xs.length === 2) return `${xs[0]} and ${xs[1]}`
  return `${xs.slice(0, -1).join(', ')} and ${xs[xs.length - 1]}`
}

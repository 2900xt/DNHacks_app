// CHOKEPOINT shared types.
// Source of truth: DNHacks_brain/team/briefs/README.md § The data contract
// Mirrored into ../../contracts/. Change both in the same commit.

/** Node ids are `type:key`, lowercase, ASCII, hyphen-separated.
 *  e.g. drug:amoxicillin · precursor:6-apa · company:fei:3004446312 · country:in */
export type NodeId = string

export type NodeType =
  | 'drug' | 'product' | 'api' | 'precursor' | 'company' | 'country' | 'facility'

/** How the company behind this node was identified. `company:name:` ids MUST be 'fuzzy'. */
export type ResolvedBy = 'fei' | 'duns' | 'fuzzy'

/** 1 = live API · 2 = official list · 3 = hand-curated (requires a citation). */
export type Layer = 1 | 2 | 3

export interface GraphNode {
  id: NodeId
  type: NodeType
  label?: string
  /** ISO-2, lowercased. */
  country?: string
  critical?: boolean
  attrs?: Record<string, unknown>
  resolved_by?: ResolvedBy
}

export interface GraphEdge {
  src: NodeId
  dst: NodeId
  rel: string
  layer: Layer
  /** Required when layer === 3. No citation, no edge. */
  citation?: string
}

export interface Signal {
  node_id: NodeId
  kind: string
  severity?: string
  source?: string
  observed_at: string
  url?: string
  payload?: Record<string, unknown>
}

export interface Compliance {
  node_id: NodeId
  taa_pass?: boolean
  on_1260h?: boolean
  evidence?: Record<string, unknown>
}

export interface Bin {
  id: string
  label?: string
  /** `drug:` ids. The hardware -> graph seam. */
  covers_drugs: NodeId[]
  /** ISO-2, lowercased — the `country:` node whose depot this bin sits in.
   *  Depots are local to a point of interest, not global. */
  country?: string
}

/** Live only — in-memory ring buffer in the API, never written to disk. */
export interface Telemetry {
  bin_id: string
  ts: string
  temp_c?: number
  humidity?: number
  mkt_c?: number
  state?: 'nominal' | 'excursion' | 'fault' | 'breach'
}

export interface BacktestResult {
  run_at?: string
  cutoff?: string
  params?: Record<string, unknown>
  result?: Record<string, unknown>
}

export interface CascadeResult {
  affected: GraphNode[]
  rule: string
  firedBy: Signal[]
}

// --- AEGIS pathfinder — web/data/reroute.json, emitted by ml/aegis.py --write ---

/** One DMF holder for a precursor, scored once on public records. The console
 *  applies exclusions itself: a holder's score does not depend on which other
 *  holder went down, so re-ranking survivors is a filter, not a re-run. */
export interface RerouteHolder {
  /** `company:` node id, or null when the graph carries no node for this filing. */
  node_id: NodeId | null
  /** Holder name as spelled in the DMF register. */
  holder: string
  /** DECRS firm name it resolved to; null = not found or ambiguous. */
  matched_firm: string | null
  /** ISO-3, from DECRS addresses. Empty when unmatched. */
  countries: string[]
  /** Same countries, ISO-2 lowercased — the graph's convention. */
  iso2: string[]
  feis: string[]
  score: number
  /** score > 0. */
  viable: boolean
  registered_api: boolean
  in_chokepoint: boolean
  /** true = TAA-designated · false = not designated · null = unknown. */
  taa: boolean | null
  risk_flags: string[]
  /** One clause per scoring axis that fired. Rendered verbatim. */
  why: string[]
}

export interface ReroutePrecursor {
  node: NodeId
  substance: string
  spellings: number
  active_holders: number
  inactive_holders: number
  affected_drugs: NodeId[]
  affected_products: number
  viable: number
  /** Best first. */
  holders: RerouteHolder[]
}

export interface Reroute {
  generated_at?: string
  rule?: string
  rule_text?: string
  /** Stated on every output rather than buried — there is no public source. */
  not_modelled?: string[]
  chokepoint_iso2?: string[]
  precursors?: ReroutePrecursor[]
}

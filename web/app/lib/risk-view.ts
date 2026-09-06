// Types and formatting for the next-failure model's answer.
//
// SPLIT FROM `risk.ts` ON PURPOSE. risk.ts imports risk.ui.json, so anything
// that imports risk.ts pulls 645 KB in with it — and a 'use client' component
// that does so ships the entire artifact to the browser, which is exactly what
// the compact file existed to prevent. Client components import from here;
// only server code imports risk.ts.
//
// Nothing in this file reads data. If you are about to add an import of
// `@/data/...` below, it belongs in risk.ts instead.

/** What one node's risk looks like once it reaches the client. */
export interface NodeRisk {
  /** Probability of a disruption in the next 12 months. 0-1. */
  p12: number
  /** 95% interval for p12, from the calibration block it landed in. */
  range: [number, number]
  band: 'low' | 'raised' | 'high'
  /** Plain-English reasons, ordered by how much each moved the score. */
  why: string[]
  /**
   * Where the number came from:
   *   measured   this plant's own FDA record
   *   supplier   the worst plant that makes it, named in `from`
   *   substance  the worst plant making the same substance — weaker, may not
   *              be the plant that makes this one
   *   base-rate  no FDA record at all; the population average
   */
  basis: 'measured' | 'supplier' | 'substance' | 'base-rate'
  /** Label of the plant the number came from, when it is not this node. */
  from?: string
  /** Distinct plants upstream. 1 behind a 40% figure is a shortage; 50 is not. */
  upstream?: number
  /** True when the plant is above everything the data can tell apart. */
  atCeiling?: boolean
}

export interface RiskMeta {
  runAt: string
  trainedAt: string
  horizonDays: number
  ceiling: number
  coverage: { ui_nodes: number; scored: number; direct: number; inherited: number }
  ruleText: string
  calibration: {
    method: string
    /** Predicted vs observed, out of fold. The evidence the number is earned. */
    reliability: {
      predicted: number; observed: number; n: number
      range: [number, number]; inside: boolean
    }[]
    curve: { observed_rate: number; n: number; range: [number, number] }[]
  }
  training: {
    sources: {
      name: string; what: string; rows: number; url: string
      breakdown?: Record<string, number>
      span?: { from: string; to: string }
      establishments?: number
      countries?: number
    }[]
    fit: {
      cutoff: string; plants: number; positives: number; base_rate: number
      label: string; why_this_cutoff: string
      features: number; features_withheld: string[]; withheld_because: string
    }
    out_of_fold: string
  }
  notModelled: string[]
}

// --- presentation helpers, safe on the client ------------------------------

export const RISK_TONE: Record<NodeRisk['band'], 'ok' | 'warn' | 'alarm'> = {
  low: 'ok', raised: 'warn', high: 'alarm',
}

/** "8.4%". Below 1% the first decimal is the only informative digit. */
export function pct(p: number): string {
  return p < 0.01 ? `${(p * 100).toFixed(2)}%` : `${(p * 100).toFixed(1)}%`
}

/** What the basis means, in one sentence, for the tile caption. */
export const BASIS_NOTE: Record<NodeRisk['basis'], string> = {
  measured: 'From this plant’s own FDA inspection and import-refusal record.',
  supplier: 'This node makes nothing itself — it carries the risk of the plant that supplies it.',
  substance: 'No supplier could be resolved, so this is the most at-risk plant making the same substance. It may not be the plant that makes this one.',
  'base-rate': 'No FDA record for this plant, so this is the population average — not a finding about it.',
}

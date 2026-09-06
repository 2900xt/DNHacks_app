// The buyer-side verdict. Mirrors ml/compliance.py `determine(..., buyer=)`.
//
// A verdict is a function of the supplier's country, the BUYER's jurisdiction,
// and the rule that jurisdiction uses. compliance.json holds the US answer,
// precomputed; jurisdictions.json holds the WTO GPA party list. Everything else
// is derived here, in the browser, so switching the buyer costs nothing.

import type { Compliance, GraphNode, Jurisdictions, NodeId } from './types'
import { countryName } from './plain'

export interface Verdict {
  status: 'pass' | 'fail' | 'unknown' | 'na'
  /** Chip text: "TAA PASS", "GPA FAIL", "NO RULE", ... */
  tag: string
  rule: 'us' | 'gpa' | 'none'
  /** One sentence a judge can read. Never empty. */
  reason: string
  /** DoD 1260H is a US list. Always false for any other buyer. */
  flag1260h: boolean
}

export const TONE: Record<Verdict['status'], 'ok' | 'alarm' | 'dim'> = {
  pass: 'ok', fail: 'alarm', unknown: 'dim', na: 'dim',
}

/** The country a verdict is about. A country is itself; a company carries the
 *  country its compliance row resolved via the incorporated_in hop, else the
 *  node's own attribute. */
export function supplierCountry(node: GraphNode, row: Compliance | null | undefined): string | null {
  if (node.type === 'country') return node.id.replace(/^country:/, '')
  const ev = (row?.evidence ?? {}) as Record<string, unknown>
  const c = typeof ev.country === 'string' ? ev.country : node.country
  return c ? c.replace(/^country:/, '').toLowerCase() : null
}

export function verdict(
  node: GraphNode, row: Compliance | null | undefined, buyer: string, J: Jurisdictions,
): Verdict | null {
  if (node.type !== 'company' && node.type !== 'country') return null
  const name = (iso: string) => J.buyers.find((b) => b.iso2 === iso)?.label ?? countryName(iso)

  if (buyer === 'us') {
    if (!row) return null
    const ev = (row.evidence ?? {}) as Record<string, unknown>
    const p = row.taa_pass
    const status = p === true ? 'pass' : p === false ? 'fail' : 'unknown'
    return {
      status,
      tag: status === 'unknown' ? 'TAA ?' : `TAA ${status.toUpperCase()}`,
      rule: 'us',
      reason: typeof ev.reason === 'string' ? ev.reason : 'No TAA determination on record.',
      flag1260h: row.on_1260h === true,
    }
  }

  const who = name(buyer)
  if (!J.gpa_parties.includes(buyer)) {
    return {
      status: 'na', tag: 'NO RULE', rule: 'none', flag1260h: false,
      reason: `No procurement rule on record for a ${who} buyer. Only the US (TAA, 1260H) and WTO GPA reciprocity are loaded.`,
    }
  }
  const iso2 = supplierCountry(node, row)
  if (!iso2) {
    return {
      status: 'unknown', tag: 'GPA ?', rule: 'gpa', flag1260h: false,
      reason: `No country resolved for ${node.label ?? node.id}, so GPA eligibility cannot be determined.`,
    }
  }
  if (iso2 === buyer) {
    return {
      status: 'pass', tag: 'DOMESTIC', rule: 'gpa', flag1260h: false,
      reason: `${name(iso2)} is the buyer's own jurisdiction.`,
    }
  }
  return J.gpa_parties.includes(iso2)
    ? {
        status: 'pass', tag: 'GPA PASS', rule: 'gpa', flag1260h: false,
        reason: `${name(iso2)} is a WTO GPA party, so a ${who} public buyer must give it access to covered procurement. Eligible in principle; coverage schedules and thresholds vary per party.`,
      }
    : {
        status: 'fail', tag: 'GPA FAIL', rule: 'gpa', flag1260h: false,
        reason: `${name(iso2)} is not a WTO GPA party, so a ${who} public buyer has no treaty obligation to consider it.`,
      }
}

export function verdicts(
  nodes: GraphNode[], compliance: Record<NodeId, Compliance>, buyer: string, J: Jurisdictions,
): Record<NodeId, Verdict> {
  const out: Record<NodeId, Verdict> = {}
  for (const n of nodes) {
    const v = verdict(n, compliance[n.id], buyer, J)
    if (v) out[n.id] = v
  }
  return out
}

// The next-failure model's answer, per node. `ml/risk/emit.py` writes it.
//
// SERVER ONLY. It reads risk.ui.json — the compact projection emitted by the
// same run as risk.json, which is 2 MB of features, drivers and site lists that
// no screen reads. Audit against risk.json; render from this.
//
// Even so, `riskFor` cuts it to the nodes actually on screen: the console draws
// about a hundred of 1,706. Import this from a SERVER component and pass the
// slice down. Importing it from a client component ships the whole file to the
// browser and undoes the point.

import riskRaw from '@/data/risk.ui.json'
import type { NodeId } from './types'
import type { NodeRisk, RiskMeta } from './risk-view'

export type { NodeRisk, RiskMeta } from './risk-view'

interface RawPlant {
  p12: number
  p12_range: [number, number]
  band: string
  evidence: string[]
  basis: string
  attribution?: string
  label?: string
  inherited_from?: string
  upstream_plants?: number
  at_ceiling?: boolean
}

const RAW = riskRaw as unknown as {
  run_at: string; trained_at: string; horizon_days: number
  rule_text: string
  coverage: RiskMeta['coverage']
  calibration: {
    method: string; ceiling: number
    reliability: RiskMeta['calibration']['reliability']
    curve: RiskMeta['calibration']['curve']
  }
  training: RiskMeta['training']
  not_modelled: string[]
  plants: Record<string, RawPlant>
}

/** `basis` + `attribution` collapse to one word the panel can show. */
function basisOf(r: RawPlant): NodeRisk['basis'] {
  if (r.basis === 'base_rate_only') return 'base-rate'
  if (r.basis !== 'inherited') return 'measured'
  return r.attribution === 'molecule' ? 'substance' : 'supplier'
}

/**
 * The risk rows for the nodes given, and nothing else.
 *
 * Nodes with no row are simply absent — 26 company names could not be resolved
 * to a single establishment, and the model refuses to guess rather than attach
 * some other plant's history. The panel renders that absence as "not scored",
 * which is the honest reading and not the same as "low".
 */
export function riskFor(ids: Iterable<NodeId>): Record<NodeId, NodeRisk> {
  const out: Record<NodeId, NodeRisk> = {}
  for (const id of ids) {
    const r = RAW.plants[id]
    if (!r) continue
    const basis = basisOf(r)
    out[id] = {
      p12: r.p12,
      range: r.p12_range,
      band: (r.band as NodeRisk['band']) ?? 'low',
      why: r.evidence ?? [],
      basis,
      // Only when the number came from somewhere ELSE. A base-rate node has no
      // source plant — setting `from` to its own label would render as
      // "Carried from <itself>".
      ...(basis === 'supplier' || basis === 'substance' ? { from: r.label } : {}),
      ...(r.upstream_plants ? { upstream: r.upstream_plants } : {}),
      ...(r.at_ceiling ? { atCeiling: true } : {}),
    }
  }
  return out
}

export function getRiskMeta(): RiskMeta {
  return {
    runAt: RAW.run_at,
    trainedAt: RAW.trained_at,
    horizonDays: RAW.horizon_days,
    ceiling: RAW.calibration.ceiling,
    coverage: RAW.coverage,
    ruleText: RAW.rule_text,
    calibration: {
      method: RAW.calibration.method,
      reliability: RAW.calibration.reliability,
      curve: RAW.calibration.curve,
    },
    training: RAW.training,
    notModelled: RAW.not_modelled,
  }
}

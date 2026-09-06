// The six 6-APA drugs, as demo subjects.
//
// WHY THIS FILE EXISTS
// --------------------
// Every one of these six runs through the same precursor, so their UPSTREAM risk
// is identical by construction — that identity is the whole CHOKEPOINT thesis and
// it is what beat 4 reveals. What differs between them is DOWNSTREAM: how much US
// supply rides on the drug, how thin its own API filing base is, and whether a
// clinician can substitute anything for it. Those three axes are what makes
// picking a different drug change the screen instead of just changing a label.
//
// WHAT IS HARDCODED HERE AND WHAT IS NOT
// --------------------------------------
// Only the CLINICAL facts are hardcoded — indication and therapeutic redundancy.
// They are not in any dataset we ingest (see DRUG_SELECTION.md § Layer 2: "this
// is chemistry, not a database"), they are stable, and each carries a source.
// Every NUMBER on screen still comes from the graph artifacts at render time
// (active_dmfs, NDC counts, labeler counts) — do not copy those in here, they
// will drift from the artifacts and the panel will contradict itself.
//
// >>> MODEL SEAM <<<
// `band()` below is the placeholder for Parth's model. It is deliberately a
// readable rule, not a magic number, because decisions/0003-transparent-risk-rules
// requires the UI to be able to show rule + firing evidence for any flagged node.
// When the model lands, replace the body of `band()` with its output and keep the
// `drivers` array — the rail renders the drivers, not the score, and that is the
// part a judge asks about.

import type { NodeId } from './types'

export type Band = 'high' | 'medium' | 'low'
export type Redundancy = 'none' | 'partial'

export interface DrugProfile {
  id: NodeId
  /** The API node this drug hangs off. 6-APA feeds all six of these. */
  api: NodeId
  label: string
  /** Fits a 208px rail pill. */
  short: string
  route: 'oral' | 'IV'
  /** One line: what a clinician loses if this goes away. */
  indication: string
  /** The honest substitution answer. Never overstate "no substitute". */
  redundancy: Redundancy
  redundancyNote: string
  /** EO 13944 (Oct 30 2020). Three of the six are listed; three are not. */
  eo13944: string | null
  /** Beat 1's evidence footnote, per drug. */
  note: string
  /** Sources for the two hand-curated claims above. */
  sources: string[]
}

/** Locked demo path is amoxicillin — DEMO_PATH.md § The scenario. Changing the
 *  focus is a what-if the presenter drives, never the default. */
export const DEFAULT_FOCUS: NodeId = 'drug:amoxicillin'

export const DRUGS: DrugProfile[] = [
  {
    id: 'drug:amoxicillin',
    api: 'api:amoxicillin-trihydrate',
    label: 'Amoxicillin',
    short: 'Amox',
    route: 'oral',
    indication:
      'Oral first line — otitis media, strep pharyngitis, community-acquired pneumonia. The most-prescribed antibiotic in the US, 60M+ prescriptions a year.',
    redundancy: 'partial',
    redundancyNote:
      'Cephalexin and azithromycin substitute in mild disease. Neither displaces it as first line in paediatric otitis media, and neither is the countermeasure.',
    eo13944: 'Amoxicillin liquid / oral API only · Biological Threat MCMs',
    note: 'Amoxicillin is on the EO 13944 essential medicines list (Oct 30 2020), liquid / oral API only.',
    sources: ['FDA EO 13944 Essential Medicines (Oct 30 2020)', 'CFR — The Pharma Choke Point'],
  },
  {
    id: 'drug:ampicillin',
    api: 'api:ampicillin',
    label: 'Ampicillin',
    short: 'Amp',
    route: 'IV',
    indication:
      'IV workhorse — neonatal sepsis with gentamicin, Listeria meningitis, enterococcal endocarditis with ceftriaxone.',
    redundancy: 'none',
    redundancyNote:
      'No substitute for Listeria: cephalosporins have no intrinsic activity against it, which is exactly why ampicillin is in every empiric neonatal and older-adult meningitis regimen. TMP-SMX is the penicillin-allergy fallback, not an equal.',
    eo13944: 'Ampicillin IV API only · Anti-Microbial',
    note: 'Ampicillin is on the EO 13944 list (Oct 30 2020), IV API only. It is the one of the six with no therapeutic substitute in its core indication.',
    sources: ['FDA EO 13944 Essential Medicines (Oct 30 2020)', 'StatPearls — Ampicillin', 'Medscape — Listeriosis medication'],
  },
  {
    id: 'drug:piperacillin',
    api: 'api:piperacillin',
    label: 'Piperacillin',
    short: 'Pip',
    route: 'IV',
    indication:
      'Broad-spectrum empiric IV, given as piperacillin/tazobactam — hospital-acquired pneumonia, febrile neutropenia, intra-abdominal sepsis. Anti-pseudomonal.',
    redundancy: 'partial',
    redundancyNote:
      'Meropenem and cefepime cover the same ground. Substituting at scale drives carbapenem use, which is the resistance outcome stewardship programmes exist to avoid.',
    eo13944: 'Piperacillin / Tazobactam IV APIs only · Anti-Microbial',
    note: 'Piperacillin is on the EO 13944 list (Oct 30 2020) as piperacillin / tazobactam, IV APIs only. Its substitute is a carbapenem — the swap has a resistance cost.',
    sources: ['FDA EO 13944 Essential Medicines (Oct 30 2020)', 'ASHP drug shortage detail — piperacillin/tazobactam injection'],
  },
  {
    id: 'drug:dicloxacillin',
    api: 'api:dicloxacillin-sodium',
    label: 'Dicloxacillin',
    short: 'Diclox',
    route: 'oral',
    indication:
      'The only oral anti-staphylococcal penicillin marketed in the US — MSSA skin and soft-tissue infection, and the oral step-down off IV therapy.',
    redundancy: 'partial',
    redundancyNote:
      'Cephalexin is the practical oral substitute and is widely used for it.',
    eo13944: null,
    note: 'Dicloxacillin is NOT on the EO 13944 list — and it has the thinnest filing base of the six. Absence from the list is not absence of risk; that gap is the argument.',
    sources: ['FDA EO 13944 Essential Medicines (Oct 30 2020) — absent', 'FDA Type II DMF register, sheet 2Q2026-EXCEL'],
  },
  {
    id: 'drug:nafcillin',
    api: 'api:nafcillin-sodium',
    label: 'Nafcillin',
    short: 'Naf',
    route: 'IV',
    indication:
      'IV anti-staphylococcal — MSSA bacteraemia and endocarditis. Hepatically cleared, so it is the one that does not need renal dose adjustment.',
    redundancy: 'partial',
    redundancyNote:
      'Cefazolin is the accepted alternative. Vancomycin is not: in MSSA bacteraemia it carries roughly 2–3× the mortality and morbidity of an anti-staphylococcal penicillin.',
    eo13944: null,
    note: 'Nafcillin is not on the EO 13944 list. It is still a drug of choice for MSSA bacteraemia, and the reflex substitute — vancomycin — is measurably worse.',
    sources: ['FDA EO 13944 Essential Medicines (Oct 30 2020) — absent', 'BMC Infect Dis — nafcillin/cefazolin vs vancomycin in MSSA bacteraemia'],
  },
  {
    id: 'drug:oxacillin',
    api: 'api:oxacillin-sodium',
    label: 'Oxacillin',
    short: 'Ox',
    route: 'IV',
    indication:
      'IV anti-staphylococcal, interchangeable with nafcillin for MSSA bacteraemia and endocarditis. It is the drug methicillin resistance is tested and named against.',
    redundancy: 'partial',
    redundancyNote:
      'Cefazolin substitutes. Vancomycin is a downgrade in MSSA for the same reason it is for nafcillin.',
    eo13944: null,
    note: 'Oxacillin is not on the EO 13944 list. Every MSSA / MRSA susceptibility report in the country is phrased against it.',
    sources: ['FDA EO 13944 Essential Medicines (Oct 30 2020) — absent', 'BMC Infect Dis — anti-staphylococcal penicillins vs vancomycin in MSSA'],
  },
]

const BY_ID = new Map(DRUGS.map((d) => [d.id, d]))

export function profileOf(id: NodeId | null | undefined): DrugProfile {
  return (id && BY_ID.get(id)) || BY_ID.get(DEFAULT_FOCUS)!
}

/** Facts the graph owns. Passed in rather than copied into this file so the rail
 *  and the artifacts can never disagree. */
export interface GraphFacts {
  /** `active_dmfs` off the drug node — how many filings can supply its own API. */
  filings?: number
  /** Collapsed NDC count for the drug. */
  ndc?: number
  /** Distinct labelers marketing it. */
  labelers?: number
}

export interface Verdict {
  band: Band
  /** Shown verbatim on the rail. Decision 0003: rule text on screen, always. */
  rule: string
  /** Why this band, one clause per axis that fired. */
  drivers: string[]
}

/** Thin filing base — the threshold is stated so it can be argued with. */
const THIN_FILINGS = 3
/** "A lot of US supply rides on this" — NDC count, not a market-share claim. */
const WIDE_EXPOSURE = 100

export const RULE_TEXT =
  'Downstream impact v0 — HIGH if the drug has no therapeutic substitute, ' +
  `or ≤${THIN_FILINGS} active DMF filings for its own API, ` +
  `or ≥${WIDE_EXPOSURE} NDCs riding on it. Upstream risk is identical across all six by construction.`

/**
 * >>> MODEL SEAM — replace this body with Parth's model output. <<<
 *
 * Keep the shape. The rail renders `rule` and `drivers`, not the band on its own,
 * because a judge's next question after a colour is always "why that colour".
 */
export function band(p: DrugProfile, f: GraphFacts): Verdict {
  const drivers: string[] = []

  if (p.redundancy === 'none') drivers.push('No therapeutic substitute in its core indication')
  if (f.filings != null && f.filings <= THIN_FILINGS)
    drivers.push(`${f.filings} active DMF filing${f.filings === 1 ? '' : 's'} for its own API`)
  if (f.ndc != null && f.ndc >= WIDE_EXPOSURE) drivers.push(`${f.ndc} NDCs ride on it`)

  if (drivers.length === 0) {
    drivers.push('Substitutable, and neither its filing base nor its exposure is extreme')
    // Still not "low": it is downstream of the same single precursor as the others.
    return { band: 'medium', rule: RULE_TEXT, drivers }
  }
  return { band: 'high', rule: RULE_TEXT, drivers }
}

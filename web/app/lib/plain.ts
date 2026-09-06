/**
 * The scorer speaks in register names — DECRS, TAA, OAI, DMF. A risk manager
 * does not, and should not have to. Every reason string the artifact emits
 * maps here to one plain sentence; anything unmapped passes through with its
 * acronyms expanded. Keep the scorer's wording in ml/aegis.py exact — it is
 * the audit trail — and translate here, at the last moment before the screen.
 */

const ISO3_NAME: Record<string, string> = {
  CHN: 'China', IND: 'India', AUT: 'Austria', ITA: 'Italy', ESP: 'Spain', ISR: 'Israel',
  USA: 'the US', KOR: 'South Korea', DEU: 'Germany', FRA: 'France', GBR: 'the UK', JPN: 'Japan',
  CHE: 'Switzerland', NLD: 'the Netherlands', IRL: 'Ireland', PRT: 'Portugal', BEL: 'Belgium',
}
const ISO2_NAME: Record<string, string> = {
  cn: 'China', in: 'India', at: 'Austria', it: 'Italy', es: 'Spain', il: 'Israel', us: 'the US',
  kr: 'South Korea', de: 'Germany', fr: 'France', gb: 'the UK', jp: 'Japan', ch: 'Switzerland',
  nl: 'the Netherlands', ie: 'Ireland', pt: 'Portugal', be: 'Belgium',
}

/** Company suffixes the register writes in capitals and a reader does not. */
const SUFFIX: Record<string, string> = {
  GMBH: 'GmbH', SPA: 'SpA', SRL: 'Srl', SLU: 'SLU', SL: 'SL', SA: 'SA', AG: 'AG',
  BV: 'BV', NV: 'NV', LTD: 'Ltd', LTDA: 'Ltda', LLC: 'LLC', INC: 'Inc', CO: 'Co',
  PVT: 'Pvt', PTE: 'Pte', PLC: 'PLC', AS: 'AS', AB: 'AB', OY: 'Oy', KG: 'KG',
  DE: 'de', CV: 'CV', USA: 'USA', UK: 'UK', API: 'API', ACS: 'ACS', DSM: 'DSM',
}

/**
 * The DMF register spells every holder in capitals — "SANDOZ GMBH" — and the
 * console used to show it that way. A name is read, not scanned; it gets title
 * case, with the corporate suffixes the way their owners write them. Labels
 * that already carry lower case ("ACS Dobfar SpA") are left exactly as found.
 */
export function displayName(label: string): string {
  if (label !== label.toUpperCase() || !/[A-Z]/.test(label)) return label
  return label
    .split(/(\s+|[()/,.-])/)
    .map((w) => {
      if (!/[A-Z]/.test(w)) return w
      if (SUFFIX[w]) return SUFFIX[w]
      return w.charAt(0) + w.slice(1).toLowerCase()
    })
    .join('')
}

export function countryName(iso: string): string {
  const k = iso.toLowerCase()
  return ISO2_NAME[k] ?? ISO3_NAME[iso.toUpperCase()] ?? iso.toUpperCase()
}

function names(list: string): string {
  return list.split('/').map((c) => countryName(c.trim())).join(' and ')
}

const RULES: [RegExp, (m: RegExpMatchArray) => string][] = [
  [/^registered API manufacturer$/, () => 'FDA lists this plant as making the ingredient'],
  [/^registered establishment, not flagged API$/, () => 'FDA-registered site, but not listed for this ingredient'],
  [/^not found in DECRS/, () => 'not in the FDA plant register, so its ability to supply is unconfirmed'],
  [/AMBIGUOUS in DECRS/, () => 'two FDA plant records match this name, so it was not scored'],
  [/same chokepoint region \(([^)]+)\)/, (m) => `in the same region as the bottleneck (${names(m[1])})`],
  [/^outside CN\/IN \(([^)]+)\)/, (m) => `outside China and India (${names(m[1])})`],
  [/^mixed footprint: ([^ ]+) AND ([^ ]+)/, (m) => `sites both outside (${names(m[1])}) and inside (${names(m[2])}) China and India`],
  [/^TAA-designated/, () => 'US government buyers may purchase from its country'],
  [/^not TAA-designated/, () => 'US government buyers (VA, DoD) may not purchase from its country'],
  [/^TAA depends on the site/, () => 'government eligibility depends on which site ships'],
  [/own risk: (.+)$/, (m) => {
    const years = [...new Set(m[1].match(/\d{4}/g) ?? [])].sort()
    const refusals = /refusal/i.test(m[1])
    return `failed FDA inspections${refusals ? ' or refused shipments' : ''}${years.length ? ` (${years.join(', ')})` : ''}`
  }],
  [/site country from the graph record \(([^)]+)\)/, (m) => `location (${names(m[1])}) from our records, not the FDA register`],
  [/^every site outside the failed jurisdictions? \(([^)]+)\)/, (m) => `outside the disrupted area (${names(m[1])})`],
  [/^same jurisdiction as the failure \(([^)]+)\)/, (m) => `inside the disrupted area (${names(m[1])})`],
  [/^site cannot be placed/, () => 'location unknown, so no credit either way'],
]

export function plain(why: string): string {
  const w = why.replace(/^[\u26A0\uFE0F\u{1F534}\s]+/u, '').trim()
  for (const [re, f] of RULES) {
    const m = w.match(re)
    if (m) return f(m)
  }
  return w
    .replace(/\bDECRS\b/g, 'the FDA plant register')
    .replace(/\bDMF\b/g, 'FDA filing')
    .replace(/\bTAA\b/g, 'government-purchase rules')
    .replace(/\bOAI\b/g, 'failed FDA inspection')
    .replace(/\bcGMP refusal\b/g, 'refused shipment')
}

/** How the score works, for the circled i. No acronyms. */
export const SCORE_EXPLAINED = [
  'Each backup supplier is scored from public FDA records.',
  '+3 if the FDA lists the plant as making this ingredient (+1 if it is registered but not for this ingredient). '
  + '+2 if all of its sites are outside China and India (+1 if some are). '
  + '+1.5 if US government buyers may purchase from its country. '
  + '−2 for every failed FDA inspection or refused shipment on its own record.',
  'After a disruption: +2 if the supplier is outside the disrupted area, −2 if it is inside it.',
  'Above zero means it could supply. Nobody publishes capacity, lead time, price or willingness to sell, '
  + 'so this ranks who could supply — it does not promise how much.',
]

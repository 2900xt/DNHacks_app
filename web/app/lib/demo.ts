// The demo as a state machine.
//
// Source of truth: DNHacks_brain/strategy/DEMO_PATH.md (LOCKED Sat 21:40).
// One beat per state, advanced with the SPACEBAR. Two reasons it is keyboard
// driven rather than a click target: on stage at hour 20 you must not be hunting
// for a hitbox, and keyboard operability of the graph is explicitly scored under
// Best in Design (usability, 40/100). The same key path is the accessibility path.
//
// The `say` lines are the presenter's script, and the numbers in them are the
// EXACT wording from DEMO_PATH § "The numbers that go on screen". Do not round
// them, do not collapse "4 of the 8 filings" and "3 of the 6 drugs" into one
// figure — they count different things and the panel is equipped to catch it.

import type { NodeId } from './types'

export const AMOX = 'drug:amoxicillin'
export const AMOX_API = 'api:amoxicillin-trihydrate'
export const APA = 'precursor:6-apa'

export type NodeState = 'ok' | 'alarm' | 'focus' | 'plain'

export interface Beat {
  n: number
  key: string
  label: string
  say: string
  note?: string
  /** Nodes lit for this beat. Everything else dims but stays on the map. */
  lit: (ctx: BeatCtx) => Set<NodeId>
  /** Per-node visual state overrides. */
  states?: (ctx: BeatCtx) => Record<NodeId, NodeState>
  /** Beat 5 turns the TAA/1260H verdicts on. */
  compliance?: boolean
  /** Beat 6 opens the evidence readout. */
  evidence?: boolean
  /** Beat 2 is the physical failure — the depot rail takes over. */
  breach?: boolean
}

export interface BeatCtx {
  /** Everything reachable downstream of 6-APA, precomputed on the server. */
  fanout: NodeId[]
  companies: NodeId[]
  countries: NodeId[]
  drugs: NodeId[]
  apis: NodeId[]
}

const all = (c: BeatCtx) =>
  new Set<NodeId>([APA, ...c.fanout, ...c.companies, ...c.countries, ...c.drugs, ...c.apis])

export const BEATS: Beat[] = [
  {
    n: 0,
    key: 'open',
    label: 'On the table',
    say: 'A real bin, a real sensor, reading nominal.',
    note: 'The node on the table is live. Storage class CRT, mean kinetic temperature under the USP <659> ceiling.',
    lit: (c) => all(c),
    states: () => ({ [AMOX]: 'ok' }),
  },
  {
    n: 1,
    key: 'pallet',
    label: 'Her pallet',
    say: 'A hospital group’s supply manager is holding a pallet of amoxicillin. Green. This is her whole job — is my stock good?',
    note: 'Amoxicillin is on the EO 13944 essential medicines list (Oct 30 2020), liquid / oral API only.',
    lit: (c) => all(c),
    states: () => ({ [AMOX]: 'ok' }),
  },
  {
    n: 2,
    key: 'breach',
    label: 'Excursion',
    say: 'We heat the bin. Mean kinetic temperature breaches the ceiling — and MKT does not clear when the room cools. The stock is condemned.',
    note: 'A cold-chain company can tell you the box got hot. Only this tells you the box getting hot is unrecoverable.',
    breach: true,
    lit: (c) => all(c),
    states: () => ({ [AMOX]: 'alarm' }),
  },
  {
    n: 3,
    key: 'trace',
    label: 'Trace down',
    say: 'Fine — re-order it. Trace down: drug product, to active ingredient, to the precursor they all share. 8 active US filings to supply it.',
    note: 'A DMF is a filing, not a supplier. Two of the eight share a parent — The United Laboratories. There are exactly two places on earth this comes from.',
    lit: (c) => new Set([AMOX, AMOX_API, APA, ...c.companies, ...c.countries]),
    states: () => ({ [APA]: 'focus', [AMOX]: 'alarm' }),
  },
  {
    n: 4,
    key: 'fanout',
    label: 'Fan back out',
    say: 'And back out. Every other penicillin runs through the same precursor — and not one of them is showing a shortage today.',
    note: '4 of the 8 filings and 3 of the 6 drugs sit on the EO 13944 list. Both numbers, because they count different things.',
    lit: (c) => all(c),
    states: (c) => Object.fromEntries([
      [APA, 'focus' as NodeState],
      ...c.drugs.map((d) => [d, 'alarm' as NodeState]),
    ]),
  },
  {
    n: 5,
    key: 'compliance',
    label: 'Compliance',
    say: 'Over the alternates: Trade Agreements Act, and the 1260H list. Austria passes. India and China do not.',
    note: 'FAR 25.003 designated countries — 132 rows, 127 distinct. First beat to cut if we are on the three-minute clock.',
    compliance: true,
    lit: (c) => all(c),
    states: () => ({ [APA]: 'focus' }),
  },
  {
    n: 6,
    key: 'evidence',
    label: 'Evidence',
    say: 'Every edge on this screen carries its layer and its citation. Nothing here is a model guessing.',
    note: 'Layer 1 live API, layer 2 official list, layer 3 hand-curated with a citation — no citation, no edge.',
    evidence: true,
    lit: (c) => all(c),
    states: () => ({ [APA]: 'focus' }),
  },
]

'use client'

/**
 * What the three edge colours mean, and how many edges each layer contributes.
 *
 * This lives in the graph panel's tab bar rather than in a footer of its own:
 * the panel is already the shortest thing on screen relative to what it draws,
 * and a legend is worth ten pixels of chrome, not a whole row of it.
 *
 * The layer names are the contract's own words (types.ts: 1 = live API,
 * 2 = official list, 3 = hand-curated, citation required). Beat 6's claim is
 * "nothing here is a model guessing" — that claim needs the counts on screen,
 * not just in the script, so `open` adds them.
 */

const LAYERS = [
  { n: 1, name: 'Live API' },
  { n: 2, name: 'Official list' },
  { n: 3, name: 'Cited' },
] as const

export default function EvidenceKey({
  layerCounts, open,
}: {
  layerCounts: Record<number, number>
  open: boolean
}) {
  return (
    <div className="legend" aria-label="Edge provenance">
      {LAYERS.map(({ n, name }) => (
        <span key={n} className={`pill l${n}`} title={`Layer ${n} — ${name}`}>
          <i />
          {name}
          {open && <b> {(layerCounts[n] ?? 0).toLocaleString()}</b>}
        </span>
      ))}
    </div>
  )
}

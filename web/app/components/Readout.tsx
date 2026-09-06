'use client'

/**
 * The four numbers that sit above the caption, bottom-right over the globe.
 *
 * This is the resting answer to the operator's standing question — how
 * concentrated is this supply — and it stays on screen through every beat, so
 * the caption's claim always has its evidence directly above it. Counts
 * FILINGS, not company boxes: see the note on `overview` in Console.
 */
export interface Overview {
  jurisdictions: number
  filings: number
  drugs: number
  concentration: string
}

export default function Readout({ overview }: { overview: Overview }) {
  return (
    <div className="readout" aria-label="Supply concentration">
      <div className="ro">
        <b>{overview.jurisdictions}</b>
        <span>jurisdictions</span>
      </div>
      <div className="ro">
        <b>{overview.filings}</b>
        <span>active filings</span>
      </div>
      <div className="ro" data-tone="alarm">
        <b>{overview.drugs}</b>
        <span>drugs downstream</span>
      </div>
      <div className="ro">
        <b>{overview.concentration}</b>
        <span>top jurisdiction</span>
      </div>
    </div>
  )
}

'use client'

import type { BacktestResult } from '../lib/types'

interface Props {
  counts: { nodes: number; edges: number; signals: number; compliance: number }
  layerCounts: Record<number, number>
  backtest: BacktestResult
  open: boolean
}

export default function EvidenceBar({ counts, layerCounts, backtest, open }: Props) {
  const hasBacktest = backtest && Object.keys(backtest).length > 0
  const result = (backtest?.result ?? {}) as Record<string, unknown>

  return (
    <div className="evbar">
      <div className="stat"><b>{counts.nodes}</b><span>nodes</span></div>
      <div className="stat"><b>{counts.edges}</b><span>edges</span></div>
      <div className="stat"><b>{counts.signals.toLocaleString()}</b><span>signals</span></div>
      <div className="stat"><b>{counts.compliance}</b><span>compliance rows</span></div>

      {open && (
        hasBacktest ? (
          <div className="stat">
            <b>{String(result.score ?? result.value ?? '—')}</b>
            <span>backtest</span>
          </div>
        ) : (
          <div className="stat">
            <b style={{ color: 'var(--warn)' }}>pending</b>
            <span>backtest — say the entity-res number instead</span>
          </div>
        )
      )}

      <div className="legend">
        {([1, 2, 3] as const).map((l) => (
          <span key={l} className={`pill l${l}`}>
            <i /> L{l} {['live API', 'official list', 'hand-curated'][l - 1]}
            {' '}({layerCounts[l] ?? 0})
          </span>
        ))}
      </div>
    </div>
  )
}

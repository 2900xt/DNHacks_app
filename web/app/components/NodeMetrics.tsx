'use client'

import type { Compliance, GraphEdge, GraphNode, NodeId, Signal } from '../lib/types'
import Metric from './Metric'

interface Props {
  overview: { jurisdictions: number; filings: number; drugs: number; concentration: string }
  node: GraphNode | null
  edges: GraphEdge[]
  signals: Signal[]
  compliance: Compliance | null
  nodeLabel: (id: NodeId) => string
  onSelect: (id: NodeId) => void
  onCascade: (id: NodeId) => void
  downstream: number
  ndc?: number
  labelers?: number
}

/** Numeric attributes worth a tile, per node type. Order is the order an
 *  auditor asks for them. */
const TILES: Record<string, [string, string, string?][]> = {
  company: [
    ['dmf', 'DMF'], ['dmf_status', 'Status'], ['dmf_filed', 'Filed'],
    ['fei', 'FEI'], ['decrs_sites', 'Sites'],
  ],
  drug: [
    ['active_dmfs', 'Active DMFs'], ['distinct_dmf_holders', 'Holders'],
  ],
  precursor: [],
  country: [],
  api: [],
}

export default function NodeMetrics({
  overview, node, edges, signals, compliance, nodeLabel, onSelect, onCascade, downstream,
  ndc, labelers,
}: Props) {
  // Resting state is not empty state: with nothing selected the rail answers the
  // question the operator already has — how concentrated is this supply?
  if (!node) {
    return (
      <>
        <div className="rail-head">
          <span className="rail-title">Supply concentration</span>
        </div>
        <Metric label="Jurisdictions" value={overview.jurisdictions} sub="that make 6-APA" />
        <Metric label="Active DMF filings" value={overview.filings} sub="to supply 6-APA" />
        <Metric label="Drugs downstream" value={overview.drugs} tone="alarm"
          sub="every US penicillin" />
        <Metric label="Top jurisdiction" value={overview.concentration}
          sub={`of the ${overview.filings} active filings`} />
      </>
    )
  }

  const a = (node.attrs ?? {}) as Record<string, unknown>
  const tiles = (TILES[node.type] ?? []).filter(([k]) => a[k] != null && a[k] !== '')
  const src = typeof a.source_url === 'string' ? a.source_url : null

  return (
    <>
      <div className="rail-head">
        <span className="rail-title">{node.label ?? node.id}</span>
        <span className="tag" data-t="dim">{node.type}</span>
      </div>

      <div className="chips">
        {node.critical && <span className="tag" data-t="warn">critical</span>}
        {node.resolved_by === 'fuzzy' && <span className="tag" data-t="warn">fuzzy match</span>}
        {a.country_unverified === true && <span className="tag" data-t="warn">country unverified</span>}
        {a.state_owned === true && <span className="tag" data-t="warn">state owned</span>}
        {compliance?.taa_pass !== undefined && (
          <span className="tag" data-t={compliance.taa_pass ? 'ok' : 'alarm'}>
            TAA {compliance.taa_pass ? 'PASS' : 'FAIL'}
          </span>
        )}
        {compliance?.on_1260h && <span className="tag" data-t="alarm">1260H</span>}
        {a.eo13944_listed === true && <span className="tag" data-t="warn">EO 13944</span>}
      </div>

      {tiles.map(([k, label]) => (
        <Metric key={k} label={label} value={String(a[k])} />
      ))}

      {ndc !== undefined && ndc > 0 && (
        <Metric label="NDCs" value={ndc} sub={labelers ? `${labelers} labelers` : undefined} />
      )}
      <Metric label="Downstream" value={downstream} sub="nodes depend on this"
        tone={downstream > 0 ? 'alarm' : 'plain'} />
      <Metric label="Edges" value={edges.length} />
      <Metric label="Signals" value={signals.length} />

      <div className="rail-foot">
        <button className="ctl" onClick={() => onCascade(node.id)}>Simulate failure</button>
        {src && <a className="ctl" href={src} target="_blank" rel="noreferrer">Source</a>}
      </div>

      <div className="rail-list">
        {edges.slice(0, 12).map((e, i) => {
          const other = e.src === node.id ? e.dst : e.src
          return (
            <button
              key={`${e.src}|${e.dst}|${e.rel}|${i}`}
              className="link-row"
              onClick={() => onSelect(other)}
              title={e.citation ?? e.rel}
            >
              <span className={`pill l${e.layer}`}><i /></span>
              <span className="lr-name">{nodeLabel(other)}</span>
              <span className="lr-rel">{e.rel}</span>
            </button>
          )
        })}
      </div>
    </>
  )
}

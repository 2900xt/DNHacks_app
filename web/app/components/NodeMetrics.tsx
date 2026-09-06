'use client'

import type { Compliance, GraphEdge, GraphNode, NodeId, Signal } from '../lib/types'
import type { Rollup } from '../lib/supply-tree'
import { relVerb } from '../lib/graph-layout'
import Metric from './Metric'

interface Props {
  node: GraphNode | null
  edges: GraphEdge[]
  signals: Signal[]
  compliance: Compliance | null
  nodeLabel: (id: NodeId) => string
  onSelect: (id: NodeId) => void
  /** Switch this node off, or back on. */
  onCascade: (id: NodeId) => void
  /** Dismiss the inspector. It is an overlay now, so it needs a way out. */
  onClose: () => void
  /** True when this node is one of the switched-off ones. */
  offline: boolean
  /** Its standing in the current tree, when it is part of one. */
  rollup?: Rollup
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

/**
 * The inspector, now an overlay on the map rather than a standing rail.
 *
 * It renders only when a node is selected. The resting summary moved to the
 * bottom-right readout, which never leaves the screen — so this panel no longer
 * has to be two things at once, and it can be absent instead of empty.
 */
export default function NodeMetrics({
  node, edges, signals, compliance, nodeLabel, onSelect, onCascade, onClose, offline,
  rollup, downstream, ndc, labelers,
}: Props) {
  if (!node) return null

  const a = (node.attrs ?? {}) as Record<string, unknown>
  const tiles = (TILES[node.type] ?? []).filter(([k]) => a[k] != null && a[k] !== '')
  const src = typeof a.source_url === 'string' ? a.source_url : null

  return (
    <>
      <div className="rail-head">
        <span className="rail-title">{node.label ?? node.id}</span>
        <span className="tag" data-t="dim">{node.type}</span>
        <button className="ov-close" onClick={onClose} aria-label="Close inspector">✕</button>
      </div>

      <div className="chips">
        {offline && <span className="tag" data-t="alarm">offline</span>}
        {!offline && rollup?.health === 'at-risk' && (
          <span className="tag" data-t="warn">at risk</span>
        )}
        {!offline && rollup?.health === 'down' && (
          <span className="tag" data-t="alarm">no supply</span>
        )}
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
      {rollup && rollup.total > 1 && (
        <Metric
          label="Qualified sources"
          value={`${rollup.up} / ${rollup.total}`}
          sub="still standing beneath this node"
          tone={rollup.health === 'down' ? 'alarm' : rollup.health === 'at-risk' ? 'warn' : 'ok'}
        />
      )}
      <Metric label="Downstream" value={downstream} sub="nodes depend on this"
        tone={downstream > 0 ? 'alarm' : 'plain'} />
      <Metric label="Edges" value={edges.length} />
      <Metric label="Signals" value={signals.length} />

      <div className="rail-foot">
        <button className="ctl" onClick={() => onCascade(node.id)}>
          {offline ? 'Restore node' : 'Simulate failure'}
        </button>
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
              <span className="lr-rel">{relVerb(e.rel)}</span>
            </button>
          )
        })}
      </div>
    </>
  )
}

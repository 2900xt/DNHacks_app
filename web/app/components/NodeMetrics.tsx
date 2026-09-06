'use client'

import type { Compliance, GraphEdge, GraphNode, NodeId } from '../lib/types'
import type { Alternate, Rollup } from '../lib/supply-tree'
import { relVerb } from '../lib/graph-layout'
import Metric from './Metric'
import { Info } from './Rail'
import { plain } from '../lib/plain'

interface Props {
  node: GraphNode | null
  edges: GraphEdge[]
  compliance: Compliance | null
  nodeLabel: (id: NodeId) => string
  onSelect: (id: NodeId) => void
  /** Switch this node off, or back on. */
  onCascade: (id: NodeId) => void
  /** True when this node is one of the switched-off ones. For a country,
   *  that means its exports are halted. */
  offline: boolean
  /** A plant that is producing but cannot ship: its jurisdiction is halted. */
  halted: boolean
  /** Its standing in the current tree, when it is part of one. */
  rollup?: Rollup
  downstream: number
  ndc?: number
  labelers?: number
  /** This node's row in the AEGIS shortlist, re-ranked, when it is a DMF holder. */
  alt?: Alternate
}

/**
 * The inspector: what this node is, what state it is in, and what to do to it.
 *
 * It used to carry a tile for every attribute on the record — DMF number,
 * status, filing date, FEI — and a Source link. Those are the record, and the
 * record is one hover away on the globe; on the rail they were four numbers
 * under a name, read by nobody. What stays is what changes: the standing, the
 * score, the blast radius, the switch.
 */
export default function NodeMetrics({
  node, edges, compliance, nodeLabel, onSelect, onCascade, offline, halted,
  rollup, downstream, ndc, labelers, alt,
}: Props) {
  if (!node) return null
  const a = (node.attrs ?? {}) as Record<string, unknown>
  const where = [a.city, node.country ? String(node.country).toUpperCase() : null]
    .filter((x) => typeof x === 'string' && x).join(', ')

  return (
    <>
      <div className="chips">
        {offline && (
          <span className="tag" data-t={node.type === 'country' ? 'warn' : 'alarm'}>
            {node.type === 'country' ? 'exports halted' : 'offline'}
          </span>
        )}
        {!offline && halted && <span className="tag" data-t="warn">export halted</span>}
        {!offline && !halted && rollup?.health === 'at-risk' && (
          <span className="tag" data-t="warn">at risk</span>
        )}
        {!offline && !halted && rollup?.health === 'down' && (
          <span className="tag" data-t="alarm">no supply</span>
        )}
        {node.critical && <span className="tag" data-t="warn">critical</span>}
        {compliance?.taa_pass !== undefined && (
          <span className="tag" data-t={compliance.taa_pass ? 'ok' : 'alarm'}>
            TAA {compliance.taa_pass ? 'PASS' : 'FAIL'}
          </span>
        )}
        {compliance?.on_1260h && <span className="tag" data-t="alarm">1260H</span>}
        {a.eo13944_listed === true && <span className="tag" data-t="warn">EO 13944</span>}
        {alt && !offline && !halted && (
          <span className="tag" data-t={alt.recommended ? 'route' : alt.viable ? 'ok' : 'alarm'}>
            {alt.recommended ? 'best backup' : alt.viable ? 'usable backup' : 'not usable'}
          </span>
        )}
        {where && <span className="tag" data-t="dim">{where}</span>}
      </div>

      {alt && (
        <div className="metric-row">
          <Metric
            label="Supplier score"
            value={`${alt.score > 0 ? '+' : ''}${alt.score.toFixed(1)}`}
            sub={alt.rank ? `#${alt.rank} of the suppliers still shipping` : offline ? 'not shipping' : 'cut off upstream'}
            tone={alt.viable ? 'ok' : 'alarm'}
          />
          <Info label="Why this score">
            <b>Why {alt.score > 0 ? '+' : ''}{alt.score.toFixed(1)}</b>
            <ul>
              {alt.holder.why.map((w) => <li key={w}>{plain(w)}</li>)}
              {alt.deltaWhy && (
                <li data-delta={alt.delta > 0 ? 'up' : alt.delta < 0 ? 'down' : 'none'}>
                  {alt.delta !== 0 ? `${alt.delta > 0 ? '+' : ''}${alt.delta}: ` : ''}{plain(alt.deltaWhy)}
                </li>
              )}
            </ul>
          </Info>
        </div>
      )}

      {ndc !== undefined && ndc > 0 && (
        <Metric label="NDCs" value={ndc} sub={labelers ? `${labelers} labelers` : undefined} />
      )}
      {rollup && rollup.total > 1 && (
        <Metric
          label="Qualified sources"
          value={`${rollup.up} / ${rollup.total}`}
          sub="still shipping"
          tone={rollup.health === 'down' ? 'alarm' : rollup.health === 'at-risk' ? 'warn' : 'ok'}
        />
      )}
      <Metric label="Depends on it" value={downstream} sub="products and ingredients downstream"
        tone={downstream > 0 ? 'alarm' : 'plain'} />

      <div className="rail-foot">
        <button className="ctl" onClick={() => onCascade(node.id)}>
          {node.type === 'country'
            ? (offline ? 'Reopen exports' : 'Halt exports from here')
            : (offline ? 'Restore plant' : 'Simulate plant failure')}
        </button>
      </div>

      {edges.length > 0 && (
        <div className="rail-list">
          {edges.slice(0, 8).map((e, i) => {
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
          {edges.length > 8 && (
            <div className="lr-more">+{edges.length - 8} more</div>
          )}
        </div>
      )}
    </>
  )
}

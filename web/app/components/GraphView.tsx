'use client'

import { useMemo } from 'react'
import type { Compliance, GraphEdge, GraphNode, NodeId } from '../lib/types'
import type { NodeState } from '../lib/demo'
import {
  COLUMN_LABEL, NODE_H, NODE_W, edgePath, flowOf, layoutGraph,
} from '../lib/graph-layout'

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  lit: Set<NodeId>
  states: Record<NodeId, NodeState>
  selected: NodeId | null
  onSelect: (id: NodeId) => void
  compliance: Record<NodeId, Compliance>
  /** NDCs collapsed onto their drug, so 760 boxes become one number. */
  ndcCount: Record<NodeId, number>
  showCompliance: boolean
}

/** Second line inside a node box: the one fact that matters for its type. */
function subtitle(
  n: GraphNode, comp: Compliance | undefined, showCompliance: boolean, ndc?: number,
): string {
  const a = (n.attrs ?? {}) as Record<string, unknown>
  if (showCompliance && comp) {
    if (comp.taa_pass === true) return 'TAA PASS'
    if (comp.taa_pass === false) return 'TAA FAIL'
  }
  if (n.type === 'company' && a.dmf) return `DMF ${a.dmf}${a.dmf_status === 'A' ? ' · active' : ''}`
  if (n.type === 'drug') {
    if (ndc) return `${ndc} NDCs${a.eo13944_listed ? ' · EO 13944' : ''}`
    return a.eo13944_listed ? 'EO 13944' : `${a.active_dmfs ?? 0} active DMFs`
  }
  if (n.type === 'facility') return String(a.fei ? `FEI ${a.fei}` : 'site')
  if (n.type === 'country') return String(n.country ?? '').toUpperCase()
  if (n.type === 'precursor') return 'shared nucleus'
  return ''
}

function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max - 1).trimEnd() + '…'
}

export default function GraphView({
  nodes, edges, lit, states, selected, onSelect, compliance, ndcCount, showCompliance,
}: Props) {
  const L = useMemo(() => layoutGraph(nodes, edges), [nodes, edges])

  return (
    <svg
      className="graph"
      viewBox={`0 0 ${L.width} ${L.height}`}
      preserveAspectRatio="xMidYMin meet"
      role="group"
      aria-label="Sourcing graph. Use tab to move between nodes, enter to inspect."
    >
      <defs>
        {[1, 2, 3].map((layer) => (
          <marker
            key={layer}
            id={`arrow-${layer}`}
            viewBox="0 0 8 8" refX="7" refY="4"
            markerWidth="6" markerHeight="6" orient="auto-start-reverse"
          >
            <path d="M0,1 L7,4 L0,7 z" fill={`var(--layer${layer})`} />
          </marker>
        ))}
      </defs>

      {L.columns.map((c) => (
        <text key={c.col} className="col-label" x={c.x} y={20}>
          {COLUMN_LABEL[c.type] ?? c.type}
        </text>
      ))}

      <g>
        {edges.map((e, i) => {
          const [fromId, toId] = flowOf(e)
          const a = L.pos.get(fromId)
          const b = L.pos.get(toId)
          if (!a || !b) return null
          const on = lit.has(fromId) && lit.has(toId)
          return (
            <path
              key={`${e.src}|${e.dst}|${e.rel}|${i}`}
              className="gedge"
              data-layer={e.layer}
              data-lit={on ? 'on' : 'off'}
              d={edgePath(a, b)}
              markerEnd={`url(#arrow-${e.layer})`}
            />
          )
        })}
      </g>

      <g>
        {L.placed.map((p) => {
          const comp = compliance[p.id]
          const st: NodeState =
            states[p.id] ??
            (showCompliance && comp?.taa_pass === false ? 'alarm'
              : showCompliance && comp?.taa_pass === true ? 'ok'
              : 'plain')
          const on = lit.has(p.id)
          const sub = subtitle(p.node, comp, showCompliance, ndcCount[p.id])
          return (
            <g
              key={p.id}
              className="gnode"
              data-lit={on ? 'on' : 'off'}
              data-state={on ? st : 'plain'}
              data-sel={selected === p.id ? '1' : '0'}
              transform={`translate(${p.x},${p.y})`}
              tabIndex={0}
              role="button"
              aria-label={`${p.node.label ?? p.id}. ${sub}`}
              onClick={() => onSelect(p.id)}
              onKeyDown={(ev) => {
                if (ev.key === 'Enter' || ev.key === ' ') {
                  // Space is the beat advance globally; inside a node it selects.
                  ev.preventDefault()
                  ev.stopPropagation()
                  onSelect(p.id)
                }
              }}
            >
              <rect width={NODE_W} height={NODE_H} rx="3" />
              <text x="9" y={sub ? 16 : 23}>
                {truncate(p.node.label ?? p.id, 25)}
              </text>
              {sub && <text className="n-sub" x="9" y="28">{sub}</text>}
            </g>
          )
        })}
      </g>
    </svg>
  )
}

'use client'

import type { Compliance, GraphEdge, GraphNode, NodeId, Signal } from '../lib/types'

interface Props {
  node: GraphNode | null
  edges: GraphEdge[]
  signals: Signal[]
  compliance: Compliance | null
  nodeLabel: (id: NodeId) => string
  onSelect: (id: NodeId) => void
  onCascade: (id: NodeId) => void
}

const LAYER_NAME: Record<number, string> = {
  1: 'live API', 2: 'official list', 3: 'hand-curated',
}

/** Attribute keys worth surfacing, in the order an auditor would ask for them. */
const SHOW: [string, string][] = [
  ['dmf', 'DMF'],
  ['dmf_status', 'DMF status'],
  ['dmf_type', 'DMF type'],
  ['dmf_filed', 'Filed'],
  ['dmf_subject', 'Subject'],
  ['active_dmfs', 'Active DMFs'],
  ['distinct_dmf_holders', 'Distinct holders'],
  ['fei', 'FEI'],
  ['duns', 'DUNS'],
  ['operations', 'Operations'],
  ['decrs_address_iso3', 'DECRS country'],
  ['decrs_sites', 'DECRS sites'],
  ['parent', 'Parent'],
  ['state_owned', 'State owned'],
  ['eo13944_listed', 'EO 13944'],
  ['eo13944_row', 'EO 13944 row'],
  ['eo13944_category', 'Category'],
  ['taa_designated', 'TAA designated'],
]

export default function Inspector({
  node, edges, signals, compliance, nodeLabel, onSelect, onCascade,
}: Props) {
  if (!node) {
    return (
      <div className="pane">
        <h2>Inspector</h2>
        <p style={{ color: 'var(--text-faint)', fontSize: 12 }}>
          Select any node to see what it is, how we know, and what depends on it.
        </p>
        <p style={{ color: 'var(--text-faint)', fontSize: 11, marginTop: 10 }}>
          Every claim on this screen is one click from its source. A risk manager
          cannot act on a number they cannot defend.
        </p>
      </div>
    )
  }

  const a = (node.attrs ?? {}) as Record<string, unknown>
  const rows = SHOW.filter(([k]) => a[k] !== undefined && a[k] !== null && a[k] !== '')
  const unverified = a.country_unverified === true

  return (
    <>
      <div className="pane">
        <h2>Inspector</h2>
        <p className="insp-title">{node.label ?? node.id}</p>
        <p className="insp-id">{node.id}</p>
        <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          <span className="tag" data-t="dim">{node.type}</span>
          {node.critical && <span className="tag" data-t="warn">critical</span>}
          {node.resolved_by && (
            <span className="tag" data-t={node.resolved_by === 'fuzzy' ? 'warn' : 'dim'}>
              matched: {node.resolved_by}
            </span>
          )}
          {unverified && <span className="tag" data-t="warn">country unverified</span>}
        </div>
        <button
          className="ctl"
          style={{ marginTop: 10 }}
          onClick={() => onCascade(node.id)}
        >
          Simulate failure of this node
        </button>
      </div>

      {compliance && (
        <div className="pane">
          <h2>Compliance</h2>
          <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
            {compliance.taa_pass !== undefined && (
              <span className="tag" data-t={compliance.taa_pass ? 'ok' : 'alarm'}>
                TAA {compliance.taa_pass ? 'PASS' : 'FAIL'}
              </span>
            )}
            {compliance.on_1260h !== undefined && (
              <span className="tag" data-t={compliance.on_1260h ? 'alarm' : 'dim'}>
                1260H {compliance.on_1260h ? 'LISTED' : 'not listed'}
              </span>
            )}
          </div>
          {typeof compliance.evidence?.reason === 'string' && (
            <p className="cite">{compliance.evidence.reason}</p>
          )}
          {typeof compliance.evidence?.url === 'string' && (
            <p style={{ margin: '6px 0 0', fontSize: 11 }}>
              <a href={compliance.evidence.url} target="_blank" rel="noreferrer">
                {String(compliance.evidence.far ?? 'source')}
              </a>
            </p>
          )}
        </div>
      )}

      {rows.length > 0 && (
        <div className="pane">
          <h2>Attributes</h2>
          <dl className="kv">
            {rows.map(([k, label]) => (
              <div key={k} style={{ display: 'contents' }}>
                <dt>{label}</dt>
                <dd>{String(a[k])}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      <div className="pane">
        <h2>Provenance</h2>
        {typeof a.source === 'string' && <p className="cite">{a.source}</p>}
        {typeof a.country_evidence === 'string' && (
          <p className="cite" style={{ marginTop: 6 }}>{a.country_evidence}</p>
        )}
        {typeof a.source_url === 'string' && (
          <p style={{ margin: '8px 0 0', fontSize: 11 }}>
            <a href={a.source_url} target="_blank" rel="noreferrer">Open source document</a>
          </p>
        )}
        {!a.source && !a.source_url && (
          <p style={{ color: 'var(--text-faint)', fontSize: 11 }}>No source recorded.</p>
        )}
      </div>

      <div className="pane">
        <h2>Edges ({edges.length})</h2>
        {edges.map((e, i) => {
          const other = e.src === node.id ? e.dst : e.src
          const dir = e.src === node.id ? '→' : '←'
          return (
            <div className="edge-row" key={`${e.src}|${e.dst}|${e.rel}|${i}`}>
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8 }}>
                <span className="edge-rel">{dir} {e.rel}</span>
                <span className={`pill l${e.layer}`}>
                  <i /> L{e.layer} {LAYER_NAME[e.layer]}
                </span>
              </div>
              <button
                className="ctl"
                style={{ marginTop: 4, width: '100%', textAlign: 'left' }}
                onClick={() => onSelect(other)}
              >
                {nodeLabel(other)}
              </button>
              {e.citation && <p className="cite">{e.citation}</p>}
            </div>
          )
        })}
      </div>

      <div className="pane">
        <h2>Signals ({signals.length})</h2>
        {signals.length === 0 && (
          <p style={{ color: 'var(--text-faint)', fontSize: 11 }}>
            No signals recorded against this node.
          </p>
        )}
        {signals.slice(0, 8).map((s, i) => (
          <div className="sig-row" key={i}>
            <time>{s.observed_at}</time>
            <div>
              <span className="tag" data-t={s.severity === 'high' ? 'alarm' : 'dim'}>
                {s.kind}
              </span>
              {s.source && (
                <span style={{ color: 'var(--text-faint)', marginLeft: 6, fontSize: 11 }}>
                  {s.source}
                </span>
              )}
              {s.url && (
                <div style={{ fontSize: 11, marginTop: 2 }}>
                  <a href={s.url} target="_blank" rel="noreferrer">source</a>
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}

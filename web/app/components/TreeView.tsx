'use client'

import { useMemo } from 'react'
import type { Compliance, NodeId } from '../lib/types'
import type { NodeState } from '../lib/demo'
import {
  branchPath, layoutTree, UNRESOLVED,
  type Health, type Rollup, type TreeNode,
} from '../lib/supply-tree'

export interface SiblingChip {
  id: NodeId
  label: string
  health: Health
}

interface Props {
  tree: TreeNode | null
  rollups: Map<NodeId, Rollup>
  compromised: Set<NodeId>
  /** Switch one node off, or back on. */
  onToggle: (id: NodeId) => void
  /** Switch a whole jurisdiction off, or back on. */
  onToggleGroup: (ids: NodeId[]) => void
  selected: NodeId | null
  onSelect: (id: NodeId) => void
  /** The other drugs on the same precursor, with the fate they inherit. */
  siblings: SiblingChip[]
  rootHealth: Health
  onRoot: (id: NodeId) => void
  onReset: () => void
  compliance: Record<NodeId, Compliance>
  ndcCount: Record<NodeId, number>
  showCompliance: boolean
  /** Beat highlighting. Never health — health is only ever the cascade. */
  states: Record<NodeId, NodeState>
}

function truncate(s: string, max: number): string {
  return s.length <= max ? s : s.slice(0, max - 1).trimEnd() + '…'
}

/**
 * Character budgets, computed from the box rather than guessed.
 *
 * These labels were truncated to a CONSTANT — 22 characters for a supplier, 30
 * for everything else — across four different box widths, with a 20px power
 * switch parked in the top-right corner that the constant knew nothing about.
 * Every box overran it: a supplier had room for 16 characters and was given 22,
 * so the name ran under the switch. The budget has to come from the geometry.
 *
 * The stack is monospaced, so an advance of 0.6em is exact enough to fit to.
 */
const MONO_ADVANCE = 0.6
const TEXT_X = 11
/** The switch's left edge relative to the box's right, plus breathing room. */
const KILL_GUTTER = 38

function fits(px: number, fontPx: number): number {
  return Math.max(4, Math.floor(px / (fontPx * MONO_ADVANCE)))
}

/** The one fact that belongs under a node's name, per level. */
function subtitle(t: TreeNode, ndc: number | undefined): string {
  const a = (t.node.attrs ?? {}) as Record<string, unknown>
  switch (t.kind) {
    case 'drug':
      return [
        ndc ? `${ndc} NDCs` : null,
        a.eo13944_listed || a.eo_13944 ? 'EO 13944 essential' : null,
      ].filter(Boolean).join(' · ') || 'finished drug product'
    case 'api':
      return 'active ingredient'
    case 'precursor':
      return Array.isArray(a.feeds_drugs)
        ? `shared nucleus · feeds ${a.feeds_drugs.length} drugs`
        : 'shared nucleus'
    case 'supplier':
      return a.dmf
        ? `DMF ${a.dmf}${a.dmf_status === 'A' ? ' · active' : ''}`
        : 'filing holder'
  }
}

/** Capacity readout under an internal node. A leaf is one source and does not
 *  need "1 / 1" written on it. */
function capacity(r: Rollup | undefined, kind: TreeNode['kind']): string {
  if (!r || kind === 'supplier') return ''
  return `${r.up} / ${r.total} sources`
}

export default function TreeView({
  tree, rollups, compromised, onToggle, onToggleGroup, selected, onSelect,
  siblings, rootHealth, onRoot, onReset, compliance, ndcCount, showCompliance, states,
}: Props) {
  const L = useMemo(() => layoutTree(tree), [tree])

  if (!tree) {
    return <div className="map-empty">no chain for this drug</div>
  }

  const rootLabel = tree.node.label ?? tree.id
  const failures = compromised.size

  return (
    <div className="tree-wrap">
      {/* The drug switcher doubles as the fan-out. Every chip here runs through
          the same precursor, so when the precursor degrades they all change
          colour at once — that IS beat 4, and it needs no extra screen. */}
      <div className="tree-strip">
        <span className="strip-label">Final drug</span>
        <button
          className="drug-chip"
          data-on="1"
          data-health={rootHealth}
          onClick={() => onSelect(tree.id)}
        >
          {rootLabel}
        </button>
        {siblings.map((s) => (
          <button
            key={s.id}
            className="drug-chip"
            data-on="0"
            data-health={s.health}
            onClick={() => onRoot(s.id)}
            title={`Show the chain for ${s.label}`}
          >
            {s.label}
          </button>
        ))}
        <span className="spacer" />
        <span className="strip-hint">
          {failures
            ? `${failures} node${failures === 1 ? '' : 's'} switched off`
            : 'Click ⏻ on any node to knock it out'}
        </span>
        {failures > 0 && (
          <button className="ctl" onClick={onReset}>Restore all</button>
        )}
      </div>

      <div className="tree-body">
      <svg
        className="tree"
        viewBox={`0 0 ${L.width} ${L.height}`}
        preserveAspectRatio="xMidYMid meet"
        role="group"
        aria-label={
          `Supply tree for ${rootLabel}. Tab to move between nodes, `
          + 'enter to inspect, and use each node’s power button to simulate a failure.'
        }
      >
        {/* level labels, in a gutter, so no box has to carry its own category */}
        {L.levels.map((lv) => (
          <text key={lv.depth} className="tlevel" x={16} y={lv.y}>
            {lv.label}
          </text>
        ))}

        {/* jurisdiction bands under the leaves */}
        <g>
          {L.groups.map((g) => {
            const ids = g.ids
            const allDown = ids.every((id) => rollups.get(id)?.up === 0)
            const anyDown = ids.some((id) => rollups.get(id)?.up === 0)
            return (
              <g
                key={g.iso}
                className="tgroup"
                data-health={allDown ? 'down' : anyDown ? 'at-risk' : 'ok'}
              >
                <rect
                  x={g.x - 8} y={g.y - 4}
                  width={g.w + 16} height={g.h + 8}
                  rx="6"
                />
                <text
                  className="tgroup-label"
                  x={g.x - 2} y={g.y + 8}
                  role="button"
                  tabIndex={0}
                  aria-label={
                    `${allDown ? 'Restore' : 'Simulate failure of'} all `
                    + `${ids.length} sources in ${g.label}`
                  }
                  onClick={() => onToggleGroup(ids)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault(); e.stopPropagation(); onToggleGroup(ids)
                    }
                  }}
                >
                  {g.iso === UNRESOLVED ? 'Country unresolved' : g.label} · {ids.length}
                </text>
              </g>
            )
          })}
        </g>

        {/* branches */}
        <g>
          {L.placed.map((p) =>
            p.t.children.map((c) => {
              const cp = L.pos.get(c.id)
              if (!cp) return null
              const r = rollups.get(c.id)
              return (
                <path
                  key={`${p.t.id}|${c.id}`}
                  className="tbranch"
                  data-health={r?.up === 0 ? 'down' : r?.health ?? 'ok'}
                  d={branchPath(p, cp)}
                />
              )
            }),
          )}
        </g>

        {/* nodes */}
        <g>
          {L.placed.map((p) => {
            const t = p.t
            const r = rollups.get(t.id)
            const off = compromised.has(t.id)
            const comp = compliance[t.id]
            const sub = subtitle(t, ndcCount[t.id])
            const cap = capacity(r, t.kind)
            const frac = r && r.total ? r.up / r.total : 0
            const beat = states[t.id]
            const taa = showCompliance && comp?.taa_pass !== undefined
              ? (comp.taa_pass ? 'TAA PASS' : 'TAA FAIL')
              : null

            const nameFont = t.kind === 'drug' ? 15 : 13
            const nameMax = fits(p.w - TEXT_X - KILL_GUTTER, nameFont)
            const lineMax = fits(p.w - TEXT_X * 2, 10)
            // "7 / 8 sources" at 10px mono, right-aligned, plus a gap.
            const barW = Math.max(24, p.w - TEXT_X * 2 - cap.length * 6 - 12)
            const geo = [
              t.countryLabel ? null : 'country unresolved',
              taa,
            ].filter(Boolean).join(' · ')

            return (
              <g
                key={t.id}
                className="tnode"
                data-kind={t.kind}
                data-health={r?.health ?? 'ok'}
                data-off={off ? '1' : '0'}
                data-sel={selected === t.id ? '1' : '0'}
                data-beat={beat ?? 'plain'}
                transform={`translate(${p.x},${p.y})`}
              >
                <rect
                  className="tbox"
                  width={p.w} height={p.h} rx="4"
                  tabIndex={0}
                  role="button"
                  aria-label={`${t.node.label ?? t.id}. ${sub}. ${cap || 'one qualified source'}`}
                  onClick={() => onSelect(t.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault(); e.stopPropagation(); onSelect(t.id)
                    }
                  }}
                />

                <text className="t-name" x={TEXT_X} y="21">
                  {truncate(t.node.label ?? t.id, nameMax)}
                </text>
                {/* The subtitle line carries the failure notice rather than a
                    badge squeezed in beside it — one line, one job, and nothing
                    to collide with the capacity bar below. */}
                <text className="t-sub" x={TEXT_X} y="36">
                  {off ? 'OFFLINE · simulated failure' : truncate(sub, lineMax)}
                </text>

                {t.kind === 'supplier' ? (
                  // The jurisdiction band already names the country, once, above
                  // these boxes. Repeating it inside all four of China's is four
                  // lines that say nothing the reader did not just read. It stays
                  // only where it carries something the band does not.
                  geo && (
                    <text className="t-sub t-geo" x={TEXT_X} y="53">
                      {truncate(geo, lineMax)}
                    </text>
                  )
                ) : (
                  <>
                    <rect className="t-bar-bg" x={TEXT_X} y="45" width={barW} height="5" rx="2.5" />
                    <rect
                      className="t-bar" x={TEXT_X} y="45"
                      width={Math.max(0, barW * frac)} height="5" rx="2.5"
                    />
                    <text className="t-cap" x={p.w - TEXT_X} y="51" textAnchor="end">{cap}</text>
                  </>
                )}

                {/* The failure switch. Always visible rather than hover-only:
                    it is the one control the whole panel exists for, and a
                    hover affordance does not survive a projector or a phone. */}
                <g
                  className="t-kill"
                  transform={`translate(${p.w - 24},14)`}
                  role="button"
                  tabIndex={0}
                  aria-pressed={off}
                  aria-label={
                    `${off ? 'Restore' : 'Simulate failure of'} ${t.node.label ?? t.id}`
                  }
                  onClick={(e) => { e.stopPropagation(); onToggle(t.id) }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault(); e.stopPropagation(); onToggle(t.id)
                    }
                  }}
                >
                  <circle r="10" />
                  <path d="M0,-5 V0.5" />
                  <path d="M-3.6,-3.2 A5,5 0 1 0 3.6,-3.2" />
                </g>
              </g>
            )
          })}
        </g>
      </svg>
      </div>
    </div>
  )
}

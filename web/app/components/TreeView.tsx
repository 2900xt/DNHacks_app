'use client'

import { useEffect, useMemo, useState } from 'react'
import type { Compliance, NodeId } from '../lib/types'
import type { NodeState } from '../lib/demo'
import {
  branchPath, elbowPath, feedPath, layoutTree, trunkPath, UNRESOLVED,
  type Alternate, type Health, type Placed, type Rollup, type TreeNode,
} from '../lib/supply-tree'

export interface DrugOption {
  id: NodeId
  label: string
  health: Health
  /** Runs through the same precursor as the current root. */
  onChain: boolean
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
  /** Every finished drug the tree can be rooted at, with the fate each inherits. */
  drugs: DrugOption[]
  rootHealth: Health
  onRoot: (id: NodeId) => void
  onReset: () => void
  compliance: Record<NodeId, Compliance>
  ndcCount: Record<NodeId, number>
  showCompliance: boolean
  /** Beat highlighting. Never health — health is only ever the cascade. */
  states: Record<NodeId, NodeState>
  /** The AEGIS rank and score per supplier, re-ranked against the failures. */
  aegis: Map<NodeId, Alternate>
  /** Drug → API → precursor → route holder. Empty until a route exists. */
  routePath: Set<NodeId>
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
    case 'supplier': {
      const city = typeof a.city === 'string' && a.city ? ` · ${a.city}` : ''
      return a.dmf
        ? `DMF ${a.dmf}${a.dmf_status === 'A' ? ' · active' : ''}${city}`
        : `filing holder${city}`
    }
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
  drugs, rootHealth, onRoot, onReset, compliance, ndcCount, showCompliance, states,
  aegis, routePath,
}: Props) {
  const L = useMemo(() => layoutTree(tree), [tree])

  /** Re-rooting rebuilds the chain from the top, and the screen should say so.
   *  Five of the seven boxes are the same boxes for every drug on this
   *  precursor — that sameness IS the chokepoint — so a swap that only changed
   *  two labels looked like a swap that had not happened. The whole diagram
   *  remounts (the svg is keyed on the root) and draws in top-down, and the
   *  strip names the new root for a moment. Derived during render, not in an
   *  effect: the first render of a new root is the one that must know. */
  const [seenRoot, setSeenRoot] = useState<NodeId | null>(tree?.id ?? null)
  const [flash, setFlash] = useState<NodeId | null>(null)
  if (tree && tree.id !== seenRoot) {
    setSeenRoot(tree.id)
    if (seenRoot !== null) setFlash(tree.id)
  }
  useEffect(() => {
    if (!flash) return
    const t = setTimeout(() => setFlash(null), 1800)
    return () => clearTimeout(t)
  }, [flash])

  if (!tree) {
    return <div className="map-empty">no chain for this drug</div>
  }

  const rootLabel = tree.node.label ?? tree.id
  const failures = compromised.size

  return (
    <div className="tree-wrap">
      {/* One control, not a row of chips: six chips already wrapped to a second
          line and stole it from the tree, and the list is meant to grow. The
          fan-out still reads here — every drug on this precursor carries the
          chokepoint's verdict in its own option text. */}
      <div className="tree-strip">
        <label className="strip-label" htmlFor="root-drug">Final drug</label>
        <select
          id="root-drug"
          className="drug-select"
          data-health={rootHealth}
          data-flash={flash ? '1' : '0'}
          value={tree.id}
          onChange={(e) => { onRoot(e.target.value); onSelect(e.target.value) }}
          title="Root the tree at a different finished drug"
        >
          {drugs.map((d) => (
            <option key={d.id} value={d.id}>
              {d.label}
              {d.health === 'down' ? ' · down' : d.health === 'at-risk' ? ' · at risk' : ''}
            </option>
          ))}
        </select>
        <span className="strip-hint" data-flash={flash ? '1' : '0'}>
          {flash
            ? `Chain rebuilt for ${rootLabel}`
            : failures
              ? `${failures} disruption${failures === 1 ? '' : 's'} simulated`
              : 'Click ⏻ on any node to knock it out'}
        </span>
        {failures > 0 && (
          <button className="ctl" onClick={onReset}>Restore all</button>
        )}
      </div>

      <div className="tree-body">
      <svg
        key={tree.id}
        className="tree"
        viewBox={`0 0 ${L.width} ${L.height}`}
        preserveAspectRatio="xMidYMin meet"
        role="group"
        aria-label={
          `Supply tree for ${rootLabel}. Tab to move between nodes, `
          + 'enter to inspect, and use each node’s power button to simulate a failure.'
        }
      >

        {/* jurisdiction bands under the leaves */}
        <g>
          {L.groups.map((g) => {
            const ids = g.ids
            const allDown = ids.every((id) => rollups.get(id)?.up === 0)
            const anyDown = ids.some((id) => rollups.get(id)?.up === 0)
            // The band control is an EXPORT halt on the jurisdiction — every
            // plant keeps producing, nothing leaves — not a failure of each
            // plant. Only the unresolved bucket, which is not a place, falls
            // back to switching its members off one by one.
            const halted = !!g.countryId && compromised.has(g.countryId)
            const bandAction = g.countryId
              ? `${halted ? 'Reopen exports from' : 'Halt exports from'} ${g.label} (${ids.length} plant${ids.length === 1 ? '' : 's'})`
              : `${allDown ? 'Restore' : 'Simulate failure of'} all ${ids.length} sources in ${g.label}`
            const bandToggle = () => (g.countryId ? onToggle(g.countryId) : onToggleGroup(ids))
            return (
              <g
                key={`${g.iso}|${g.y}`}
                className="tgroup"
                data-halt={halted ? '1' : '0'}
                data-health={allDown ? 'down' : anyDown ? 'at-risk' : 'ok'}
                style={{ '--d': 3 } as React.CSSProperties}
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
                  aria-label={bandAction}
                  onClick={bandToggle}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault(); e.stopPropagation(); bandToggle()
                    }
                  }}
                >
                  {g.iso === UNRESOLVED ? 'Country unresolved' : g.label} · {ids.length}
                  {halted ? ' · EXPORTS HALTED' : ''}
                </text>
              </g>
            )
          })}
        </g>

        {/* branches — orthogonal, so a line can be followed to its box. A
            parent's suppliers hang off ONE trunk down the gap between the leaf
            columns; each supplier gets its own elbow out of that trunk. The
            trunk carries the parent's standing, the elbow the child's, so a
            dead supplier is a dashed elbow off a live trunk — which is what
            "one source down, the rest still shipping" looks like. */}
        <g>
          {L.placed.map((p) => {
            const sups = p.t.children.filter((c) => c.kind === 'supplier')
            const supPlaced = sups
              .map((c) => L.pos.get(c.key))
              .filter((x): x is Placed => !!x)
            const pr = rollups.get(p.t.id)
            return (
              <g key={`b|${p.t.key}`}>
                {supPlaced.length > 0 && (
                  <path
                    className="tbranch"
                    data-trunk="1"
                    data-health={pr?.up === 0 ? 'down' : pr?.health ?? 'ok'}
                    data-route={routePath.has(p.t.id) && sups.some((c) => routePath.has(c.id)) ? '1' : '0'}
                    style={{ '--d': p.t.depth } as React.CSSProperties}
                    d={trunkPath(p, supPlaced)}
                  />
                )}
                {p.t.children.map((c) => {
                  const cp = L.pos.get(c.key)
                  if (!cp) return null
                  const r = rollups.get(c.id)
                  const feed = c.kind === 'precursor' && p.t.kind === 'api'
                  const d = feed ? feedPath(p, cp)
                    : c.kind === 'supplier' ? elbowPath(p, cp)
                    : branchPath(p, cp)
                  return (
                    <path
                      key={`${p.t.key}|${c.key}`}
                      className="tbranch"
                      data-feed={feed ? '1' : '0'}
                      data-health={r?.up === 0 ? 'down' : r?.health ?? 'ok'}
                      data-route={routePath.has(p.t.id) && routePath.has(c.id) ? '1' : '0'}
                      style={{ '--d': p.t.depth } as React.CSSProperties}
                      d={d}
                    />
                  )
                })}
              </g>
            )
          })}
        </g>

        {/* nodes */}
        <g>
          {L.placed.map((p) => {
            const t = p.t
            const r = rollups.get(t.id)
            const off = compromised.has(t.id)
            const halted = !off && !!t.countryId && compromised.has(t.countryId)
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
            // The pathfinder's verdict sits on the supplier box itself, so the
            // rank a buyer would call in is read off the tree, not a side table.
            const alt = t.kind === 'supplier' ? aegis.get(t.id) : undefined
            const aegisTxt = alt && alt.standing
              ? `${alt.recommended ? 'NEW ROUTE · ' : ''}#${alt.rank} · score ${alt.score > 0 ? '+' : ''}${alt.score.toFixed(1)}`
              : null
            const geo = [
              aegisTxt,
              t.countryLabel ? null : 'no country',
              taa,
            ].filter(Boolean).join(' · ')

            return (
              <g
                key={t.key}
                className="tnode"
                data-kind={t.kind}
                data-health={r?.health ?? 'ok'}
                data-off={off ? '1' : '0'}
                data-sel={selected === t.id ? '1' : '0'}
                data-beat={beat ?? 'plain'}
                data-viable={alt ? (alt.viable ? '1' : '0') : undefined}
                data-route={alt?.recommended ? '1' : '0'}
                data-halt={halted ? '1' : '0'}
                style={{ '--d': t.depth } as React.CSSProperties}
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
                  {off ? 'OFFLINE · plant failure' : halted ? `EXPORT HALTED · ${t.countryLabel ?? 'jurisdiction'}` : truncate(sub, lineMax)}
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

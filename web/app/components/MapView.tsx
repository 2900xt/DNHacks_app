'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphEdge, GraphNode, NodeId } from '../lib/types'

interface Country { iso: string; name: string; cx: number; cy: number; d: string }
interface WorldFile { w: number; h: number; countries: Country[] }

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  lit: Set<NodeId>
  selected: NodeId | null
  onSelect: (id: NodeId) => void
}

/** Where the material is going. The buyer is a US hospital group — every arc
 *  on this map terminates here, which is the whole point of drawing it. */
const DEST = { iso: 'us', cx: 498, cy: 287 }

/** The visible window into the 2000x1000 equirectangular plate. Every
 *  jurisdiction we model, plus the buyer, sits between about 0N and 72N —
 *  showing the southern ocean would waste half the panel. Zoom centring must
 *  use THIS box's centre, not the plate's, or a focused country lands on the
 *  bottom edge. */
const VIEW = { x: 0, y: 70, w: 2000, h: 500 }
const CX = VIEW.x + VIEW.w / 2
const CY = VIEW.y + VIEW.h / 2

/** Quadratic arc, bowed away from the equator so long routes read as flight
 *  paths instead of chords through the map. */
function arc(x1: number, y1: number, x2: number, y2: number): string {
  const mx = (x1 + x2) / 2
  const my = (y1 + y2) / 2
  const dx = x2 - x1
  const dy = y2 - y1
  const len = Math.hypot(dx, dy)
  // Perpendicular offset, capped so short hops don't balloon.
  const bow = Math.min(len * 0.22, 150)
  const nx = -dy / (len || 1)
  const ny = dx / (len || 1)
  return `M${x1},${y1} Q${mx + nx * bow},${my + ny * bow} ${x2},${y2}`
}

export default function MapView({ nodes, edges, lit, selected, onSelect }: Props) {
  const [world, setWorld] = useState<WorldFile | null>(null)

  useEffect(() => {
    let ok = true
    fetch('/world.map.json')
      .then((r) => r.json())
      .then((d: WorldFile) => ok && setWorld(d))
      .catch(() => undefined)
    return () => { ok = false }
  }, [])

  /** iso2 -> the country node, and how many DMF holders sit in it. */
  const jurisdictions = useMemo(() => {
    const m = new Map<string, { node: GraphNode; holders: string[] }>()
    for (const n of nodes) {
      if (n.type !== 'country' || !n.country) continue
      m.set(n.country, { node: n, holders: [] })
    }
    for (const e of edges) {
      if (e.rel !== 'incorporated_in') continue
      const c = nodes.find((n) => n.id === e.dst)?.country
      if (c && m.has(c)) m.get(c)!.holders.push(e.src)
    }
    return m
  }, [nodes, edges])

  /** Which country the current selection sits in, so the map follows the graph. */
  const focusIso = useMemo(() => {
    if (!selected) return null
    const n = nodes.find((x) => x.id === selected)
    if (n?.country) return n.country
    const up = edges.find((e) => e.src === selected && e.rel === 'incorporated_in')
    if (!up) return null
    return nodes.find((x) => x.id === up.dst)?.country ?? null
  }, [selected, nodes, edges])

  const view = useMemo(() => {
    if (!world) return { k: 1, tx: 0, ty: 0 }
    const c = focusIso ? world.countries.find((x) => x.iso === focusIso) : null
    if (!c) return { k: 1, tx: 0, ty: 0 }
    const k = 2.0
    return { k, tx: CX - c.cx * k, ty: CY - c.cy * k }
  }, [world, focusIso])

  const prefersReduced = useRef(false)
  useEffect(() => {
    prefersReduced.current =
      typeof window !== 'undefined' &&
      window.matchMedia('(prefers-reduced-motion: reduce)').matches
  }, [])

  if (!world) {
    return <div className="map-empty">loading map…</div>
  }

  return (
    <svg
      className="map"
      viewBox={`${VIEW.x} ${VIEW.y} ${VIEW.w} ${VIEW.h}`}
      preserveAspectRatio="xMidYMid slice"
      role="group"
      aria-label="World map of sourcing jurisdictions"
    >
      <defs>
        <linearGradient id="arcgrad" x1="0" y1="0" x2="1" y2="0">
          <stop offset="0%" stopColor="var(--alarm)" stopOpacity="0.05" />
          <stop offset="55%" stopColor="var(--alarm)" stopOpacity="0.85" />
          <stop offset="100%" stopColor="var(--focus)" stopOpacity="0.9" />
        </linearGradient>
        <radialGradient id="pulse">
          <stop offset="0%" stopColor="var(--alarm)" stopOpacity="0.55" />
          <stop offset="100%" stopColor="var(--alarm)" stopOpacity="0" />
        </radialGradient>
      </defs>

      <g
        className="map-zoom"
        style={{
          transform: `translate(${view.tx}px, ${view.ty}px) scale(${view.k})`,
          transition: prefersReduced.current ? 'none' : 'transform .7s cubic-bezier(.4,0,.2,1)',
        }}
      >
        <g className="land">
          {world.countries.map((c) => {
            const j = jurisdictions.get(c.iso)
            const isDest = c.iso === DEST.iso
            return (
              <path
                key={c.iso}
                d={c.d}
                className="country"
                vectorEffect="non-scaling-stroke"
                data-role={j ? 'source' : isDest ? 'dest' : 'none'}
                data-lit={j && lit.has(j.node.id) ? 'on' : 'off'}
                data-sel={j && selected === j.node.id ? '1' : '0'}
                onClick={j ? () => onSelect(j.node.id) : undefined}
                style={{ cursor: j ? 'pointer' : 'default' }}
              >
                {j && <title>{`${c.name} — ${j.holders.length} DMF holder(s)`}</title>}
              </path>
            )
          })}
        </g>

        <g className="arcs">
          {[...jurisdictions.entries()].map(([iso, j]) => {
            const c = world.countries.find((x) => x.iso === iso)
            if (!c || j.holders.length === 0) return null
            const on = lit.has(j.node.id)
            return (
              <path
                key={iso}
                className="route"
                vectorEffect="non-scaling-stroke"
                data-lit={on ? 'on' : 'off'}
                d={arc(c.cx, c.cy, DEST.cx, DEST.cy)}
                style={{ strokeWidth: 1 + j.holders.length * 0.7 }}
              />
            )
          })}
        </g>

      </g>

      <g className="pins">
        {[...jurisdictions.entries()].map(([iso, j]) => {
          const c = world.countries.find((x) => x.iso === iso)
          if (!c) return null
          const on = lit.has(j.node.id)
          const px = c.cx * view.k + view.tx
          const py = c.cy * view.k + view.ty
          return (
            <g
              key={iso}
              className="pin"
              data-lit={on ? 'on' : 'off'}
              data-sel={selected === j.node.id || focusIso === iso ? '1' : '0'}
              style={{
                transform: `translate(${px}px, ${py}px)`,
                transition: prefersReduced.current ? 'none' : 'transform .7s cubic-bezier(.4,0,.2,1)',
              }}
              onClick={() => onSelect(j.node.id)}
              tabIndex={0}
              role="button"
              aria-label={`${c.name}, ${j.holders.length} DMF holders`}
              onKeyDown={(e) => {
                if (e.key === 'Enter') { e.preventDefault(); onSelect(j.node.id) }
              }}
            >
              {on && <circle className="pin-pulse" r="40" fill="url(#pulse)" />}
              <circle className="pin-dot" r="7" />
              <text className="pin-count" y="-16">{j.holders.length}</text>
              <text className="pin-name" y="28">{c.name}</text>
            </g>
          )
        })}
        <g
          className="pin dest"
          style={{
            transform: `translate(${DEST.cx * view.k + view.tx}px, ${DEST.cy * view.k + view.ty}px)`,
            transition: prefersReduced.current ? 'none' : 'transform .7s cubic-bezier(.4,0,.2,1)',
          }}
        >
          <circle className="pin-dot" r="6" />
          <text className="pin-name" y="26">Point of care</text>
        </g>
      </g>
    </svg>
  )
}
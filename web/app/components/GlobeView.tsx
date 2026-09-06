'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphEdge, GraphNode, NodeId } from '../lib/types'

interface Centroid { lat: number; lng: number }
interface Feature { properties: { iso: string; name: string }; geometry: unknown }
interface WorldGlobe { features: Feature[]; centroids: Record<string, Centroid> }

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  lit: Set<NodeId>
  selected: NodeId | null
  onSelect: (id: NodeId) => void
}

/** The buyer. Every arc terminates here — that is why the globe is worth drawing. */
const DEST = 'us'

/** Textures ship inside three-globe and are copied into public/globe/ at build
 *  time, never fetched from a CDN: the venue network is assumed hostile and the
 *  whole demo has to run on localhost. */
const EARTH = '/globe/earth-night.jpg'
const BUMP = '/globe/earth-topology.png'

/* eslint-disable @typescript-eslint/no-explicit-any */

export default function GlobeView({ nodes, edges, lit, selected, onSelect }: Props) {
  const holder = useRef<HTMLDivElement | null>(null)
  const globeRef = useRef<any>(null)
  const [world, setWorld] = useState<WorldGlobe | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let ok = true
    fetch('/world.globe.json')
      .then((r) => r.json())
      .then((d: WorldGlobe) => ok && setWorld(d))
      .catch(() => undefined)
    return () => { ok = false }
  }, [])

  /** iso2 -> country node + the DMF holders incorporated there. */
  const jurisdictions = useMemo(() => {
    const m = new Map<string, { node: GraphNode; holders: string[] }>()
    for (const n of nodes) {
      if (n.type === 'country' && n.country) m.set(n.country, { node: n, holders: [] })
    }
    for (const e of edges) {
      if (e.rel !== 'incorporated_in') continue
      const c = nodes.find((n) => n.id === e.dst)?.country
      if (c && m.has(c)) m.get(c)!.holders.push(e.src)
    }
    return m
  }, [nodes, edges])

  /** Which jurisdiction the selection sits in, so the globe follows the graph. */
  const focusIso = useMemo(() => {
    if (!selected) return null
    const n = nodes.find((x) => x.id === selected)
    if (n?.country) return n.country
    const up = edges.find((e) => e.src === selected && e.rel === 'incorporated_in')
    return up ? nodes.find((x) => x.id === up.dst)?.country ?? null : null
  }, [selected, nodes, edges])

  // --- create once ---------------------------------------------------------
  useEffect(() => {
    if (!world || !holder.current || globeRef.current) return
    let disposed = false

    ;(async () => {
      const Globe = (await import('globe.gl')).default
      if (disposed || !holder.current) return

      const g = new Globe(holder.current)
        .backgroundColor('rgba(0,0,0,0)')
        .globeImageUrl(EARTH)
        .bumpImageUrl(BUMP)
        .showAtmosphere(true)
        .atmosphereColor('#4a9eda')
        .atmosphereAltitude(0.15)
        // Only the jurisdictions we model get a polygon. Highlighting three
        // countries is reliable; hexifying all 175 was not.
        .polygonCapColor((d: any) => d.cap)
        .polygonSideColor((d: any) => d.side)
        .polygonStrokeColor((d: any) => d.stroke)
        .polygonAltitude((d: any) => d.alt)
        .polygonsTransitionDuration(600)
        .onPolygonClick((d: any) => d.nodeId && onSelect(d.nodeId))
        .arcColor((d: any) => d.colors)
        .arcAltitudeAutoScale(0.45)
        .arcStroke((d: any) => d.stroke)
        .arcDashLength(0.38)
        .arcDashGap(0.22)
        .arcDashAnimateTime((d: any) => d.speed)
        .labelLat((d: any) => d.lat)
        .labelLng((d: any) => d.lng)
        .labelText((d: any) => d.text)
        .labelSize(1.8)
        .labelDotRadius((d: any) => d.dot)
        .labelColor((d: any) => d.color)
        .labelResolution(2)
        .labelAltitude(0.02)
        .onLabelClick((d: any) => d.nodeId && onSelect(d.nodeId))

      const ctl = g.controls() as any
      ctl.autoRotate = true
      ctl.autoRotateSpeed = 0.3
      ctl.enableDamping = true
      ctl.dampingFactor = 0.08
      ctl.minDistance = 170
      ctl.maxDistance = 520

      g.pointOfView({ lat: 28, lng: 60, altitude: 2.3 }, 0)

      globeRef.current = g
      setReady(true)
    })()

    return () => {
      disposed = true
      const g = globeRef.current
      if (g?._destructor) g._destructor()
      globeRef.current = null
    }
  }, [world, onSelect])

  // --- size to the pane ----------------------------------------------------
  useEffect(() => {
    if (!ready || !holder.current) return
    const el = holder.current
    const fit = () => {
      const r = el.getBoundingClientRect()
      globeRef.current?.width(r.width)?.height(r.height)
    }
    fit()
    const ro = new ResizeObserver(fit)
    ro.observe(el)
    return () => ro.disconnect()
  }, [ready])

  // --- data that changes with the beat -------------------------------------
  useEffect(() => {
    const g = globeRef.current
    if (!g || !world) return

    const polys = world.features
      .filter((f) => jurisdictions.has(f.properties.iso) || f.properties.iso === DEST)
      .map((f) => {
        const iso = f.properties.iso
        const j = jurisdictions.get(iso)
        const on = !!j && lit.has(j.node.id)
        const isDest = iso === DEST
        return {
          ...f,
          nodeId: j?.node.id ?? '',
          cap: isDest
            ? 'rgba(74,158,218,0.28)'
            : on ? 'rgba(229,72,77,0.62)' : 'rgba(229,72,77,0.20)',
          side: isDest ? 'rgba(74,158,218,0.15)' : 'rgba(229,72,77,0.18)',
          stroke: isDest ? '#4a9eda' : on ? '#ff6b70' : 'rgba(229,72,77,0.5)',
          alt: on ? 0.026 : 0.012,
        }
      })
    g.polygonsData(polys)

    const dest = world.centroids[DEST]
    const arcs = [...jurisdictions.entries()]
      .filter(([, j]) => j.holders.length > 0)
      .map(([iso, j]) => {
        const src = world.centroids[iso]
        const on = lit.has(j.node.id)
        return {
          startLat: src.lat, startLng: src.lng,
          endLat: dest.lat, endLng: dest.lng,
          colors: on
            ? ['rgba(229,72,77,0.05)', 'rgba(229,72,77,0.95)', 'rgba(74,158,218,0.9)']
            : ['rgba(160,90,95,0.03)', 'rgba(160,90,95,0.40)', 'rgba(74,158,218,0.35)'],
          stroke: on ? 0.4 + j.holders.length * 0.16 : 0.22,
          speed: on ? 2200 : 6000,
        }
      })
    g.arcsData(arcs)

    const labels: any[] = [...jurisdictions.entries()].map(([iso, j]) => {
      const c = world.centroids[iso]
      const on = lit.has(j.node.id)
      return {
        lat: c.lat, lng: c.lng,
        text: String(j.holders.length),
        color: on ? '#ffd7d8' : 'rgba(205,218,232,0.62)',
        dot: on ? 0.65 : 0.38,
        nodeId: j.node.id,
      }
    })
    labels.push({
      lat: dest.lat, lng: dest.lng,
      text: '',
      color: 'rgba(150,200,235,0.9)',
      dot: 0.42,
      nodeId: '',
    })
    g.labelsData(labels)
  }, [ready, world, jurisdictions, lit])

  // --- fly to the focused jurisdiction --------------------------------------
  useEffect(() => {
    const g = globeRef.current
    if (!g || !world) return
    const ctl = g.controls() as any
    if (!focusIso) {
      ctl.autoRotate = true
      g.pointOfView({ lat: 28, lng: 60, altitude: 2.3 }, 1200)
      return
    }
    const c = world.centroids[focusIso]
    if (!c) return
    ctl.autoRotate = false
    g.pointOfView({ lat: c.lat, lng: c.lng, altitude: 1.5 }, 1000)
  }, [ready, world, focusIso])

  // globe.gl owns `holder` and its destructor tears that subtree down; React
  // must never own a child of it or removeChild throws. Loading state is a
  // sibling.
  return (
    <div className="globe-holder">
      {!ready && <div className="map-empty globe-loading">initialising globe…</div>}
      <div className="globe-canvas" ref={holder} />
    </div>
  )
}

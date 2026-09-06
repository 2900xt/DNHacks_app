'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphEdge, GraphNode, NodeId } from '../lib/types'
import type { Route } from '../lib/supply-tree'

interface Centroid { lat: number; lng: number }
interface Feature { properties: { iso: string; name: string }; geometry: unknown }
interface WorldGlobe { features: Feature[]; centroids: Record<string, Centroid> }

interface Props {
  nodes: GraphNode[]
  edges: GraphEdge[]
  lit: Set<NodeId>
  selected: NodeId | null
  onSelect: (id: NodeId) => void
  /** Supply split per jurisdiction, recomputed on every simulated failure. */
  routes: Route[]
  /** True once anything is switched off: the globe stops showing filing counts
   *  and starts showing where the load actually went. */
  rerouting: boolean
}

/** The buyer. Every arc terminates here — that is why the globe is worth drawing. */
const DEST = 'us'

/** Textures ship inside three-globe and are copied into public/globe/ at build
 *  time, never fetched from a CDN: the venue network is assumed hostile and the
 *  whole demo has to run on localhost. */
const EARTH = '/globe/earth-night.jpg'
const BUMP = '/globe/earth-topology.png'

/* eslint-disable @typescript-eslint/no-explicit-any */

export default function GlobeView({
  nodes, edges, lit, selected, onSelect, routes, rerouting,
}: Props) {
  const holder = useRef<HTMLDivElement | null>(null)
  const globeRef = useRef<any>(null)
  /** The CSS media query kills transitions and keyframes; a WebGL ring is
   *  neither, so it has to be asked separately. */
  const reduced = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
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
        // Outlines, not fills. A whole country flooded red says "China makes
        // this", which is both too big a claim and too blunt a picture: the
        // thing that matters is a handful of POINTS. The polygon survives only
        // as a hairline, to say which jurisdiction a source sits in and to keep
        // a click target the size of a country.
        .polygonCapColor(() => 'rgba(0,0,0,0)')
        .polygonSideColor(() => 'rgba(0,0,0,0)')
        .polygonStrokeColor((d: any) => d.stroke)
        .polygonAltitude(() => 0.004)
        .polygonsTransitionDuration(600)
        .onPolygonClick((d: any) => d.nodeId && onSelect(d.nodeId))
        // The sources themselves. Red where it comes from, blue where it goes.
        .pointLat((d: any) => d.lat)
        .pointLng((d: any) => d.lng)
        .pointColor((d: any) => d.color)
        .pointAltitude((d: any) => d.alt)
        .pointRadius((d: any) => d.radius)
        .pointsTransitionDuration(500)
        .onPointClick((d: any) => d.nodeId && onSelect(d.nodeId))
        // The ripple. Named for it, so it had better be here: each live source
        // pushes a ring out across the surface, and the period is the thing you
        // read — a jurisdiction carrying more of the supply pulses faster.
        .ringLat((d: any) => d.lat)
        .ringLng((d: any) => d.lng)
        .ringAltitude(0.006)
        .ringColor((d: any) => d.colorFn)
        .ringMaxRadius((d: any) => d.maxR)
        .ringPropagationSpeed((d: any) => d.speed)
        .ringRepeatPeriod((d: any) => d.period)
        .ringResolution(72)
        .arcColor((d: any) => d.colors)
        .arcAltitudeAutoScale(0.45)
        .arcStroke((d: any) => d.stroke)
        .arcDashLength(0.38)
        .arcDashGap(0.22)
        .arcDashAnimateTime((d: any) => d.speed)
        .labelLat((d: any) => d.lat)
        .labelLng((d: any) => d.lng)
        .labelText((d: any) => d.text)
        .labelSize((d: any) => d.size ?? 1.8)
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

  // --- data that changes with the beat, and with the cascade ---------------
  //
  // Two modes, one renderer. At rest the globe answers "where does this come
  // from" and the number over each country is its count of active filings. The
  // moment anything is switched off in the tree it answers a different question
  // — "where does it come from NOW" — and the same number becomes that
  // jurisdiction's share of the supply that is still standing. Arcs are drawn
  // proportional to that share, so re-routing is a thing you watch happen
  // rather than a caption claiming it did.
  //
  // The load is split evenly across surviving sources (see supply-tree.ts
  // allocate()). There is no per-holder capacity data in any public dataset, and
  // a weighted split would be a number we could not source.
  useEffect(() => {
    const g = globeRef.current
    if (!g || !world) return

    const byIso = new Map(routes.map((r) => [r.iso, r]))
    const anySupply = routes.some((r) => !r.down)
    const dest = world.centroids[DEST]

    const polys = world.features
      .filter((f) => jurisdictions.has(f.properties.iso) || f.properties.iso === DEST)
      .map((f) => {
        const iso = f.properties.iso
        const j = jurisdictions.get(iso)
        const r = byIso.get(iso)
        const on = !!j && lit.has(j.node.id)
        const isDest = iso === DEST
        const dead = rerouting && !!r && r.down
        return {
          ...f,
          nodeId: j?.node.id ?? '',
          // Faint enough to read as context, not as a claim about the country.
          stroke: isDest ? 'rgba(74,158,218,0.26)'
            : dead ? 'rgba(120,132,148,0.16)'
            : on || rerouting ? 'rgba(229,72,77,0.30)' : 'rgba(229,72,77,0.14)',
        }
      })
    g.polygonsData(polys)

    // --- the points, and the ripples off them --------------------------------
    //
    // WHERE THESE SIT, precisely. Every one of the eight active filings resolves
    // to a COUNTRY and no further: DECRS carries `decrs_address_iso3` (CHN, AUT,
    // IND) and no street, city or coordinate, and none of the eight nodes has a
    // `city` attribute. So each source point is anchored at its jurisdiction's
    // centroid, and the country keeps a hairline outline to say the point means
    // "somewhere in here" rather than "at this spot". Scattering the eight into
    // invented plant locations would look better and would be a lie on a screen
    // whose whole claim is that nothing on it is a guess. Drop real site
    // coordinates into this list and the renderer needs no changes.
    const points: any[] = []
    const rings: any[] = []

    for (const [iso, j] of jurisdictions) {
      const c = world.centroids[iso]
      if (!c || j.holders.length === 0) continue
      const r = byIso.get(iso)
      const on = lit.has(j.node.id)
      const dead = rerouting && !!r && r.down
      const share = rerouting && r && !r.down ? r.share : 0
      const weight = rerouting ? share : j.holders.length / 8

      points.push({
        lat: c.lat, lng: c.lng,
        color: dead ? 'rgba(120,132,148,0.55)'
          : on || rerouting ? '#e5484d' : 'rgba(229,72,77,0.55)',
        radius: dead ? 0.22 : 0.3 + weight * 0.55,
        alt: 0.012,
        nodeId: j.node.id,
      })

      // A dark source does not ripple. That absence is the whole point of the
      // cascade: the map goes quiet where the supply stopped.
      if (dead || reduced) continue
      rings.push({
        lat: c.lat, lng: c.lng,
        maxR: 3.2 + weight * 4.2,
        speed: 1.5 + weight * 1.1,
        period: on || rerouting ? 1500 - weight * 550 : 3200,
        colorFn: (t: number) => `rgba(229,72,77,${(1 - t) * (on || rerouting ? 0.62 : 0.26)})`,
      })
    }

    const starvedDest = rerouting && !anySupply
    points.push({
      lat: dest.lat, lng: dest.lng,
      color: starvedDest ? '#e5484d' : '#4a9eda',
      radius: 0.5,
      alt: 0.012,
      nodeId: '',
    })
    if (!reduced) {
      rings.push({
        lat: dest.lat, lng: dest.lng,
        maxR: 4.5,
        speed: 1.1,
        period: starvedDest ? 900 : 2600,
        colorFn: (t: number) => (starvedDest
          ? `rgba(229,72,77,${(1 - t) * 0.6})`
          : `rgba(74,158,218,${(1 - t) * 0.5})`),
      })
    }

    g.pointsData(points)
    g.ringsData(rings)

    const arcs = [...jurisdictions.entries()]
      .filter(([, j]) => j.holders.length > 0)
      .map(([iso, j]) => {
        const src = world.centroids[iso]
        const r = byIso.get(iso)
        const on = lit.has(j.node.id)
        const dead = rerouting && !!r && r.down
        if (dead) {
          return {
            startLat: src.lat, startLng: src.lng,
            endLat: dest.lat, endLng: dest.lng,
            colors: ['rgba(120,132,148,0.02)', 'rgba(120,132,148,0.18)', 'rgba(120,132,148,0.06)'],
            stroke: 0.12,
            speed: 0,
          }
        }
        // Thickness is the share it now carries, so the survivors visibly
        // fatten as their neighbours go dark.
        const stroke = rerouting && r
          ? 0.35 + r.share * 2.4
          : on ? 0.4 + j.holders.length * 0.16 : 0.22
        return {
          startLat: src.lat, startLng: src.lng,
          endLat: dest.lat, endLng: dest.lng,
          colors: on || rerouting
            ? ['rgba(229,72,77,0.05)', 'rgba(229,72,77,0.95)', 'rgba(74,158,218,0.9)']
            : ['rgba(160,90,95,0.03)', 'rgba(160,90,95,0.40)', 'rgba(74,158,218,0.35)'],
          stroke,
          speed: rerouting ? 1400 : on ? 2200 : 6000,
        }
      })
    g.arcsData(arcs)

    const labels: any[] = [...jurisdictions.entries()].map(([iso, j]) => {
      const c = world.centroids[iso]
      const r = byIso.get(iso)
      const on = lit.has(j.node.id)
      const dead = rerouting && !!r && r.down
      return {
        lat: c.lat, lng: c.lng,
        text: rerouting && r
          ? (r.down ? 'OFFLINE' : `${Math.round(r.share * 100)}%`)
          : String(j.holders.length),
        // A word needs to sit smaller than a two-character count or it swamps
        // the country it is labelling.
        size: dead ? 0.95 : rerouting ? 1.5 : 1.8,
        color: dead ? 'rgba(150,162,178,0.7)'
          : rerouting ? '#ffd7d8'
          : on ? '#ffd7d8' : 'rgba(205,218,232,0.62)',
        // The points layer draws the marker now; a second dot here would sit
        // inside the first one and fight it.
        dot: 0,
        nodeId: j.node.id,
      }
    })
    labels.push({
      lat: dest.lat, lng: dest.lng,
      text: '',
      color: 'rgba(150,200,235,0.9)',
      dot: 0,
      nodeId: '',
    })
    g.labelsData(labels)
  }, [ready, world, jurisdictions, lit, routes, rerouting, reduced])

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

'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import type { GraphEdge, GraphNode, NodeId } from '../lib/types'
import type { Alternate, Route } from '../lib/supply-tree'

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
  /** ISO-2 of the jurisdiction the AEGIS route runs through. Null at rest. */
  routeIso: string | null
  /** The route holder itself, so its own plant goes green. */
  routeId: NodeId | null
  /** Every node that cannot ship right now — the tree's red set, exactly. */
  cut: Set<NodeId>
  /** What the operator switched off, plant ids and country ids alike. */
  off: Set<NodeId>
  /** ISO-2 of every jurisdiction whose exports are halted. */
  halted: Set<string>
  /** The operator has asked for the route. Until then a failure is red and
   *  nothing is green. */
  showRoute: boolean
  /** Which register each supplier in the current tree filed in. */
  apiIds: Set<NodeId>
  preIds: Set<NodeId>
  /** Every scored supplier, both registers, so a precursor plant is paired
   *  with the best-scoring API plant it could reasonably feed, not merely
   *  the nearest. */
  scoreOf: Map<NodeId, Alternate>
}

/** The new route's colour. Not the green of "healthy": a route is a change,
 *  and it has to read as one against red failures and amber halts. */
const ROUTE = '#2ee6c5'
const ROUTE_RGB = '46,230,197'

/** Great-circle distance, in degrees of arc. Only ever compared. */
function arcDeg(a: { lat: number; lng: number }, b: { lat: number; lng: number }): number {
  const r = Math.PI / 180
  const x = Math.sin(((b.lat - a.lat) * r) / 2) ** 2
    + Math.cos(a.lat * r) * Math.cos(b.lat * r) * Math.sin(((b.lng - a.lng) * r) / 2) ** 2
  return (2 * Math.asin(Math.sqrt(x))) / r
}

/** A DMF holder with a placed plant: lat/lng from ml/sites.py via graph.ts. */
interface Plant {
  node: GraphNode
  lat: number
  lng: number
  city: string | null
}

/** Three letters for a plant's city, the way a departures board would write
 *  it. Default is the first three letters of the DECRS city; the overrides
 *  are the places where that reads as the wrong town or as nothing at all. */
const CITY_CODE: Record<string, string> = {
  huhehaote: 'HOH',        // Hohhot
  'bayan nur': 'BYN',
  'kfar saba': 'KFS',
  'ansan-si': 'ANS',
  "albano sant'alessandro": 'ALB',
}
function cityCode(city: string | null, country: string | null | undefined): string {
  if (!city) return (country ?? '').toUpperCase()
  const key = city.trim().toLowerCase()
  if (CITY_CODE[key]) return CITY_CODE[key]
  return key.replace(/[^a-z]/g, '').slice(0, 3).toUpperCase()
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
  nodes, edges, lit, selected, onSelect, routes, rerouting, showRoute, routeIso, routeId, cut,
  off, halted, apiIds, preIds, scoreOf,
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

  /** The plants. Every company in the spine that ml/sites.py could place —
   *  a DMF holder for an API or for the precursor — at its DECRS city. */
  const plants = useMemo<Plant[]>(() => nodes
    .filter((n) => n.type === 'company')
    .map((n) => {
      const a = (n.attrs ?? {}) as Record<string, unknown>
      return typeof a.lat === 'number' && typeof a.lng === 'number'
        ? { node: n, lat: a.lat, lng: a.lng, city: typeof a.city === 'string' ? a.city : null }
        : null
    })
    .filter((p): p is Plant => !!p), [nodes])

  /** Where the selection is, so the globe follows the graph — and follows a
   *  disruption, since disrupting a node selects it. A placed plant is its
   *  city; anything else is its jurisdiction's centroid. */
  const focusIso = useMemo(() => {
    if (!selected) return null
    const n = nodes.find((x) => x.id === selected)
    if (n?.country) return n.country
    const up = edges.find((e) => e.src === selected && e.rel === 'incorporated_in')
    return up ? nodes.find((x) => x.id === up.dst)?.country ?? null : null
  }, [selected, nodes, edges])
  const focusPoint = useMemo(() => {
    if (!selected) return null
    const a = (nodes.find((x) => x.id === selected)?.attrs ?? {}) as Record<string, unknown>
    return typeof a.lat === 'number' && typeof a.lng === 'number' ? { lat: a.lat, lng: a.lng } : null
  }, [selected, nodes])

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
        .pointLabel((d: any) => {
          if (d.buyer) return `<div class="gl-tip"><b>The buyer</b><br>United States<br><i>${d.state}</i></div>`
          if (!d.plant) return ''
          const a = (d.plant.node.attrs ?? {}) as Record<string, unknown>
          const where = [d.plant.city, String(d.plant.node.country ?? '').toUpperCase()].filter(Boolean).join(', ')
          const filing = a.dmf ? `DMF ${a.dmf}${a.dmf_subject ? ` · ${a.dmf_subject}` : ''}` : ''
          return `<div class="gl-tip"><b>${d.plant.node.label ?? d.plant.node.id}</b><br>${where}`
            + `${filing ? `<br>${filing}` : ''}<br><i>${d.state}</i></div>`
        })
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
        const isRoute = showRoute && iso === routeIso
        return {
          ...f,
          nodeId: j?.node.id ?? '',
          // Faint enough to read as context, not as a claim about the country.
          stroke: isDest ? 'rgba(74,158,218,0.26)'
            : isRoute ? `rgba(${ROUTE_RGB},0.55)`
            : dead ? (halted.has(iso) ? 'rgba(217,144,58,0.45)' : 'rgba(120,132,148,0.16)')
            : on || rerouting ? 'rgba(229,72,77,0.30)' : 'rgba(229,72,77,0.14)',
        }
      })
    g.polygonsData(polys)

    // --- the plants: one point, one ripple and one arc each --------------
    //
    // Two hops, because that is how the material moves. A precursor plant
    // ships 6-APA to an API plant; the API plant ships the finished API to the
    // buyer. The register does not say which precursor plant supplies which
    // API plant, so each 6-APA arc goes to the NEAREST standing API plant in
    // this chain and the hover says so — an illustrative pairing, stated as
    // one. A company that holds both filings is integrated: its arc goes
    // straight to the buyer. Plants in neither register for this drug — they
    // hold a filing for another penicillin on the same nucleus — sit dim,
    // without an arc, until the root changes to a drug they make.
    const points: any[] = []
    const rings: any[] = []
    const arcs: any[] = []

    const apiPlants = plants.filter((pl) => apiIds.has(pl.node.id))
    const apiStanding = apiPlants.filter((pl) => !cut.has(pl.node.id))
    // The API plant a precursor plant would feed: the one with the best
    // supplier score after a distance penalty (one point per ~4,000 km), so a
    // well-scored plant one country over beats a poorly-scored one next door.
    // Same words on hover: the register does not record the real pairing.
    const nearestApi = (from: Plant): Plant | null => {
      const pool = apiStanding.length ? apiStanding : apiPlants
      let best: Plant | null = null
      let bestV = -Infinity
      for (const q of pool) {
        if (q.node.id === from.node.id) continue
        const v = (scoreOf.get(q.node.id)?.score ?? 0) - arcDeg(from, q) / 36
        if (v > bestV) { bestV = v; best = q }
      }
      return best
    }
    const pairOf = new Map<NodeId, Plant>()
    for (const pl of plants) {
      if (preIds.has(pl.node.id) && !apiIds.has(pl.node.id)) {
        const q = nearestApi(pl)
        if (q) pairOf.set(pl.node.id, q)
      }
    }
    // The route, as a chain: the precursor plant AND the API plant it feeds.
    const routeChain = new Set<NodeId>()
    if (showRoute && routeId) {
      routeChain.add(routeId)
      const q = pairOf.get(routeId)
      if (q) routeChain.add(q.node.id)
    }

    for (const pl of plants) {
      const id = pl.node.id
      const iso = pl.node.country ?? ''
      const j = jurisdictions.get(iso)
      const r = byIso.get(iso)
      const inApi = apiIds.has(id)
      const inPre = preIds.has(id)
      const inChain = inApi || inPre
      const on = lit.has(id) || (!!j && lit.has(j.node.id))
      const dead = rerouting && cut.has(id)
      // Three ways to be dark, told apart on the map. A plant FAILURE is grey:
      // it makes nothing. An export HALT is amber: it is producing and nothing
      // leaves the jurisdiction. Gated — its precursor supply is gone — is grey
      // too, with its own words on hover.
      const plantOff = off.has(id)
      const haltedHere = inChain && !plantOff && halted.has(iso)
      const isRoute = routeChain.has(id)
      const share = rerouting && r && !r.down ? r.share : 0
      const pair = pairOf.get(id)
      const who = inApi ? 'API manufacturer' : '6-APA manufacturer'
      const state = !inChain ? `${who} — holds a filing for another API on this nucleus, not in this chain`
        : plantOff ? `${who} — plant failure, producing nothing`
        : haltedHere ? `${who} — producing, but exports from ${iso.toUpperCase()} are halted: nothing leaves`
        : dead ? `${who} — cannot ship: its precursor supply is gone`
        : isRoute ? `${who} — ${id === routeId ? 'AEGIS route' : 'AEGIS route, receives the precursor'}`
        : inApi ? `${who} — ships the API to the buyer${rerouting ? ` · ${iso.toUpperCase()} carries ${Math.round(share * 100)}%` : ''}`
        : pair ? `${who} — ships 6-APA to ${pair.node.label ?? pair.node.id}${pair.city ? ` (${pair.city})` : ''}, the best-scoring API plant within reach; the register does not record who buys from whom`
        : `${who} — ships 6-APA`

      points.push({
        lat: pl.lat, lng: pl.lng,
        color: !inChain ? 'rgba(229,72,77,0.28)'
          : haltedHere ? 'rgba(217,144,58,0.85)'
          : dead ? 'rgba(120,132,148,0.55)'
          : isRoute ? ROUTE
          : on || rerouting ? '#e5484d' : 'rgba(229,72,77,0.7)',
        radius: !inChain ? 0.17 : haltedHere ? 0.22 : dead ? 0.16 : isRoute ? 0.42 : 0.26,
        alt: 0.012,
        nodeId: id,
        plant: pl,
        state,
      })
      if (!inChain) continue

      // A dark source does not ripple. That absence is the whole point of the
      // cascade: the map goes quiet where the supply stopped.
      if (!dead && !reduced) {
        rings.push({
          lat: pl.lat, lng: pl.lng,
          maxR: isRoute ? 5 : 2.6 + share * 3,
          speed: 1.4 + share * 1.1,
          period: isRoute ? 1000 : on || rerouting ? 1600 - share * 500 : 3400,
          colorFn: isRoute
            ? (t: number) => `rgba(${ROUTE_RGB},${(1 - t) * 0.75})`
            : (t: number) => `rgba(229,72,77,${(1 - t) * (on || rerouting ? 0.6 : 0.3)})`,
        })
      }

      // Where this plant's arc ends: the buyer, or the API plant it feeds.
      const to = inApi || !pair ? dest : { lat: pair.lat, lng: pair.lng }
      const hop = inApi || !pair ? 'api' : 'pre'
      if (dead) {
        arcs.push({
          startLat: pl.lat, startLng: pl.lng, endLat: to.lat, endLng: to.lng,
          colors: haltedHere
            ? ['rgba(217,144,58,0.03)', 'rgba(217,144,58,0.28)', 'rgba(217,144,58,0.08)']
            : ['rgba(120,132,148,0.02)', 'rgba(120,132,148,0.18)', 'rgba(120,132,148,0.06)'],
          stroke: 0.1, speed: 0,
        })
        continue
      }
      // The API hop ends blue, at the buyer. The precursor hop ends red, at
      // another plant. Thickness is the share its jurisdiction now carries;
      // the route runs green end to end, fastest of all.
      arcs.push({
        startLat: pl.lat, startLng: pl.lng, endLat: to.lat, endLng: to.lng,
        colors: isRoute
          ? [`rgba(${ROUTE_RGB},0.15)`, `rgba(${ROUTE_RGB},1)`, hop === 'api' ? 'rgba(74,158,218,0.95)' : `rgba(${ROUTE_RGB},0.9)`]
          : hop === 'pre'
            ? (on || rerouting
              ? ['rgba(229,72,77,0.05)', 'rgba(229,72,77,0.8)', 'rgba(229,72,77,0.55)']
              : ['rgba(180,90,95,0.03)', 'rgba(180,90,95,0.4)', 'rgba(180,90,95,0.3)'])
            : (on || rerouting
              ? ['rgba(229,72,77,0.05)', 'rgba(229,72,77,0.9)', 'rgba(74,158,218,0.85)']
              : ['rgba(180,90,95,0.03)', 'rgba(180,90,95,0.45)', 'rgba(74,158,218,0.4)']),
        stroke: isRoute ? 0.9 + share * 1.4 : rerouting ? 0.28 + share * 1.2 : on ? 0.36 : 0.22,
        speed: isRoute ? 900 : rerouting ? 1400 : on ? 2200 : 5200,
      })
    }

    const starvedDest = rerouting && !anySupply
    points.push({
      lat: dest.lat, lng: dest.lng,
      color: starvedDest ? '#e5484d' : '#4a9eda',
      radius: 0.5,
      alt: 0.012,
      nodeId: '',
      buyer: true,
      state: starvedDest ? 'no qualified supply is reaching it' : 'every route ends here; it makes nothing',
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
    g.arcsData(arcs)

    // Each plant in THIS drug's chain gets its city's three-letter code, set
    // small and pale beside the marker: the marker already says "a plant is
    // here", the code says where, and the tree bands say how many. A country
    // whose plants are all dark gets one word at its centroid instead — that
    // is the one thing the codes cannot say on their own.
    const standingCount = new Map<string, number>()
    const chainCount = new Map<string, number>()
    for (const pl of plants) {
      const id = pl.node.id
      if (!apiIds.has(id) && !preIds.has(id)) continue
      const iso = pl.node.country ?? ''
      chainCount.set(iso, (chainCount.get(iso) ?? 0) + 1)
      if (!cut.has(id)) standingCount.set(iso, (standingCount.get(iso) ?? 0) + 1)
    }
    const labels: any[] = []
    for (const pl of plants) {
      const id = pl.node.id
      if (!apiIds.has(id) && !preIds.has(id)) continue
      const iso = pl.node.country ?? ''
      const dead = rerouting && cut.has(id)
      const isRoute = routeChain.has(id)
      labels.push({
        lat: pl.lat, lng: pl.lng,
        text: cityCode(pl.city, pl.node.country),
        size: isRoute ? 0.8 : 0.66,
        color: dead ? (halted.has(iso) ? 'rgba(217,144,58,0.6)' : 'rgba(150,162,178,0.45)')
          : isRoute ? '#b6f0d0'
          : 'rgba(210,218,228,0.78)',
        dot: 0,
        nodeId: id,
      })
    }
    for (const [iso, j] of jurisdictions) {
      if ((chainCount.get(iso) ?? 0) === 0) continue
      if (!rerouting || (standingCount.get(iso) ?? 0) > 0) continue
      const c = world.centroids[iso]
      labels.push({
        lat: c.lat, lng: c.lng,
        text: halted.has(iso) ? 'EXPORTS HALTED' : 'OFFLINE',
        size: 0.95,
        color: halted.has(iso) ? 'rgba(217,144,58,0.85)' : 'rgba(150,162,178,0.7)',
        dot: 0,
        nodeId: j.node.id,
      })
    }
    labels.push({
      lat: dest.lat, lng: dest.lng,
      text: '',
      color: 'rgba(150,200,235,0.9)',
      dot: 0,
      nodeId: '',
    })
    g.labelsData(labels)
  }, [ready, world, jurisdictions, plants, lit, routes, rerouting, showRoute, routeIso, routeId, cut, off, halted, apiIds, preIds, scoreOf, reduced])

  // --- fly to the focused jurisdiction --------------------------------------
  //
  // A selection wins. Failing that, a route: the moment AEGIS names one, the
  // globe turns to show where the material would now come from, because a
  // green arc on the far side of the planet is a route nobody saw.
  useEffect(() => {
    const g = globeRef.current
    if (!g || !world) return
    const ctl = g.controls() as any
    const target = focusIso ?? (showRoute ? routeIso : null)
    if (!target) {
      ctl.autoRotate = true
      g.pointOfView({ lat: 28, lng: 60, altitude: 2.3 }, 1200)
      return
    }
    const c = focusPoint ?? world.centroids[target]
    if (!c) return
    ctl.autoRotate = false
    g.pointOfView({ lat: c.lat, lng: c.lng, altitude: focusPoint ? 1.25 : focusIso ? 1.5 : 1.9 }, 1000)
  }, [ready, world, focusIso, focusPoint, showRoute, routeIso])

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

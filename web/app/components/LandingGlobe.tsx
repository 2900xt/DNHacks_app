'use client'

// The console's globe, stripped to a backdrop.
//
// Same renderer, same textures, same colour language as GlobeView — red where
// supply comes from, blue where it lands, arcs animating between them. It is
// decorative here, so everything interactive is off: no click handlers, no
// polygon layer, no labels, no camera moves. What survives is the part that
// reads at a glance from across a room.
//
// The jurisdictions are passed in from the server, counted off the real graph,
// because a landing page that invents its own supply sources is exactly the
// drift this page was rebuilt to stop.

import { useEffect, useRef, useState } from 'react'

export interface Jurisdiction {
  iso: string
  /** Active DMF holders incorporated there. Drives arc weight and ring speed. */
  holders: number
}

interface Centroid { lat: number; lng: number }
interface WorldGlobe { centroids: Record<string, Centroid> }

const DEST = 'us'
const EARTH = '/globe/earth-night.jpg'
const BUMP = '/globe/earth-topology.png'

/* eslint-disable @typescript-eslint/no-explicit-any */

export default function LandingGlobe({ sources }: { sources: Jurisdiction[] }) {
  const holder = useRef<HTMLDivElement | null>(null)
  const globeRef = useRef<any>(null)
  const [world, setWorld] = useState<WorldGlobe | null>(null)
  const [ready, setReady] = useState(false)

  const reduced = typeof window !== 'undefined'
    && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches

  useEffect(() => {
    let ok = true
    fetch('/world.globe.json')
      .then((r) => r.json())
      .then((d: WorldGlobe) => ok && setWorld(d))
      .catch(() => undefined)
    return () => { ok = false }
  }, [])

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
        // Pushed brighter and wider than the console's. On the console the
        // atmosphere competes with live readings; here it IS the light source
        // for the whole page, and the blue is the point.
        .atmosphereColor('#5ab0ea')
        .atmosphereAltitude(0.24)
        .pointLat((d: any) => d.lat)
        .pointLng((d: any) => d.lng)
        .pointColor((d: any) => d.color)
        .pointAltitude(0.012)
        .pointRadius((d: any) => d.radius)
        .ringLat((d: any) => d.lat)
        .ringLng((d: any) => d.lng)
        .ringAltitude(0.006)
        .ringColor((d: any) => d.colorFn)
        .ringMaxRadius((d: any) => d.maxR)
        .ringPropagationSpeed((d: any) => d.speed)
        .ringRepeatPeriod((d: any) => d.period)
        .ringResolution(72)
        .arcColor((d: any) => d.colors)
        .arcAltitudeAutoScale(0.32)
        .arcStroke((d: any) => d.stroke)
        .arcDashLength(0.34)
        .arcDashGap(0.2)
        .arcDashAnimateTime((d: any) => d.speed)

      const ctl = g.controls() as any
      ctl.autoRotate = !reduced
      // Slower than the console's 0.3. This one is in someone's peripheral
      // vision while they read a headline; at console speed it pulls the eye
      // off the copy.
      ctl.autoRotateSpeed = 0.18
      ctl.enableDamping = true
      ctl.dampingFactor = 0.08
      ctl.enableZoom = false
      ctl.enablePan = false
      ctl.enableRotate = false

      // Far enough out that the limb of the sphere and the full arc span are
      // both in frame. Centred between the sources and the destination rather
      // than on either: at 2.1 altitude over Asia the globe filled the pane as
      // flat texture and every arc terminated off-screen, which is the one
      // thing this backdrop exists to show.
      g.pointOfView({ lat: 26, lng: 34, altitude: 2.55 }, 0)

      globeRef.current = g
      setReady(true)
    })()

    return () => {
      disposed = true
      const g = globeRef.current
      if (g?._destructor) g._destructor()
      globeRef.current = null
    }
  }, [world, reduced])

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

  useEffect(() => {
    const g = globeRef.current
    if (!g || !world) return

    const dest = world.centroids[DEST]
    const total = sources.reduce((n, s) => n + s.holders, 0) || 1
    const points: any[] = []
    const rings: any[] = []
    const arcs: any[] = []

    for (const s of sources) {
      const c = world.centroids[s.iso]
      if (!c) continue
      const weight = s.holders / total

      points.push({
        lat: c.lat, lng: c.lng,
        color: '#e5484d',
        radius: 0.32 + weight * 0.6,
      })
      if (!reduced) {
        rings.push({
          lat: c.lat, lng: c.lng,
          maxR: 3.4 + weight * 4.4,
          speed: 1.5 + weight * 1.1,
          period: 2000 - weight * 700,
          colorFn: (t: number) => `rgba(229,72,77,${(1 - t) * 0.55})`,
        })
      }
      arcs.push({
        startLat: c.lat, startLng: c.lng,
        endLat: dest.lat, endLng: dest.lng,
        colors: ['rgba(229,72,77,0.04)', 'rgba(229,72,77,0.85)', 'rgba(90,176,234,0.9)'],
        stroke: 0.34 + weight * 1.5,
        speed: reduced ? 0 : 2600 - weight * 700,
      })
    }

    points.push({ lat: dest.lat, lng: dest.lng, color: '#5ab0ea', radius: 0.52 })
    if (!reduced) {
      rings.push({
        lat: dest.lat, lng: dest.lng,
        maxR: 4.8, speed: 1.1, period: 2400,
        colorFn: (t: number) => `rgba(90,176,234,${(1 - t) * 0.5})`,
      })
    }

    g.pointsData(points)
    g.ringsData(rings)
    g.arcsData(arcs)
  }, [ready, world, sources, reduced])

  return <div className="hero-globe" ref={holder} aria-hidden="true" />
}

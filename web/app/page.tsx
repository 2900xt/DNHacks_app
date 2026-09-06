// The landing page. Server component; the only thing it reads off the merged
// graph is where the active filings sit, to light the globe. One viewport, no
// scroll. The console is the product; this page exists to get a judge into it.

import Link from 'next/link'
import Image from 'next/image'
import SiteNav from './components/SiteNav'
import LandingGlobe, { type Jurisdiction } from './components/LandingGlobe'
import { loadGraph } from './lib/graph'

/** Where the eight active filings actually sit, counted off the merged graph.
 *  Same derivation the console's globe uses (country node + `incorporated_in`),
 *  so the backdrop and the instrument cannot tell different stories. */
function sourceJurisdictions(): Jurisdiction[] {
  const g = loadGraph()
  const nodes = [...g.nodes.values()]
  const iso = new Map<string, string>()
  for (const n of nodes) if (n.type === 'country' && n.country) iso.set(n.id, n.country)

  const tally = new Map<string, number>()
  for (const e of g.edges) {
    if (e.rel !== 'incorporated_in') continue
    const c = iso.get(e.dst)
    if (c) tally.set(c, (tally.get(c) ?? 0) + 1)
  }
  return [...tally].map(([iso, holders]) => ({ iso, holders }))
}

export default function Landing() {
  const sources = sourceJurisdictions()

  return (
    <div className="site">
      <SiteNav />

      <header className="hero">
        <LandingGlobe sources={sources} />
        <div className="hero-veil" />
        <div className="hero-in">
          <p className="eyebrow">Ripple</p>
          <h1>We keep an eye on where<br /><em>medicines get made.</em></h1>
          <p className="hero-sub">
            Factories go quiet, drugs denature, and ports back up. <br />
            We notice and tell you who else can make the stuff.
          </p>
          <div className="hero-cta">
            <Link className="btn btn-primary btn-lg" href="/app">Open the console</Link>
          </div>
          <p className="hero-src">All public records. Nothing fancy.</p>
        </div>
      </header>

      <footer className="site-foot">
        <Link className="nav-mark" href="/">
          <Image src="/ripple-mark.png" alt="" width={18} height={18} />
          <span>RIPPLE</span>
        </Link>
        <p>Made at DNHacks 2026. Not advice, medical or otherwise.</p>
        <Link href="/app">Open the console →</Link>
      </footer>
    </div>
  )
}

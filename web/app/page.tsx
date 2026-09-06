// The landing page. Server component: every number on it is read out of the
// merged graph at build time by `counts()`, the same function the console
// uses, so the marketing copy cannot drift from the artifact the way a
// hand-typed stat in a static HTML file does.
//
// Held to two screens on purpose — a hero and one scroll. The console is the
// product; this page exists to get a judge into it.

import Link from 'next/link'
import Image from 'next/image'
import SiteNav from './components/SiteNav'
import LandingGlobe, { type Jurisdiction } from './components/LandingGlobe'
import { counts, loadGraph } from './lib/graph'

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

const fmt = (n: number) => n.toLocaleString('en-US')

const PLANS = [
  {
    name: 'Watch',
    price: 'Free',
    unit: '',
    line: 'Follow one medicine. Updated every day.',
    features: ['1 medicine', 'Daily warnings', 'View-only access'],
    cta: 'Start watching',
    featured: false,
  },
  {
    name: 'Operate',
    price: '$2,400',
    unit: '/mo',
    line: 'Everything, plus backup suppliers and a record of what changed.',
    features: ['Unlimited medicines', 'Backup suppliers, ranked', 'Exportable history', 'Warehouse sensor feeds'],
    cta: 'Subscribe',
    featured: true,
  },
  {
    name: 'Federal',
    price: 'Custom',
    unit: '',
    line: 'For government buyers. Runs on your own systems.',
    features: ['Government sourcing rules', 'Runs on your infrastructure', 'Single sign-on and roles'],
    cta: 'Talk to us',
    featured: false,
  },
]

export default function Landing() {
  const c = counts()
  const sources = sourceJurisdictions()

  return (
    <div className="site">
      <SiteNav />

      <header className="hero">
        <LandingGlobe sources={sources} />
        <div className="hero-veil" />
        <div className="hero-in">
          <p className="eyebrow">Ripple</p>
          <h1>Supply chain monitoring<br /><em>for medicines.</em></h1>
          <p className="hero-sub">
            We track where the world&rsquo;s drugs are actually made, notice when something
            goes wrong, and show you who else could make it instead.
          </p>
          <div className="hero-cta">
            <Link className="btn btn-primary btn-lg" href="/app">Open the console</Link>
            <Link className="btn btn-ghost btn-lg" href="#plans">See pricing</Link>
          </div>
          <p className="hero-src">Built on public government records</p>
        </div>
      </header>

      <section id="how" className="band band-how">
        <div className="how-row">
          <div className="how-cell">
            <p className="how-step">01 — Watch</p>
            <p className="how-n">{fmt(c.signals)}</p>
            <p className="how-t">Warning signs picked up at drug factories around the world.</p>
          </div>
          <div className="how-cell">
            <p className="how-step">02 — Trace</p>
            <p className="how-n">{fmt(c.nodes)} <span>things we track</span></p>
            <p className="how-t">One factory stops, and we show you every medicine that stops with it.</p>
          </div>
          <div className="how-cell">
            <p className="how-step">03 — Switch</p>
            <p className="how-n">Ranked</p>
            <p className="how-t">Who else can make it — so you know your options before you need them.</p>
          </div>
        </div>
      </section>

      <section id="plans" className="band band-plans">
        <div className="band-head">
          <h2>Plans</h2>
          <p>Everything we use is public. Keeping an eye on it daily is the job.</p>
        </div>

        <div className="plans">
          {PLANS.map((p) => (
            <div className="plan" key={p.name} data-featured={p.featured ? '1' : '0'}>
              {p.featured && <span className="plan-flag">Most picked</span>}
              <p className="plan-name">{p.name}</p>
              <p className="plan-price">{p.price}<span>{p.unit}</span></p>
              <p className="plan-line">{p.line}</p>
              <ul className="plan-feat">
                {p.features.map((f) => <li key={f}>{f}</li>)}
              </ul>
              <Link className={`btn ${p.featured ? 'btn-primary' : 'btn-ghost'} plan-cta`} href="/login">
                {p.cta}
              </Link>
            </div>
          ))}
        </div>

        <p className="plans-fine">
          Built at DNHacks 2026. The prices are made up and nothing is charged. You need an
          account to open the console; all the data underneath it is public.
        </p>
      </section>

      <footer className="site-foot">
        <Link className="nav-mark" href="/">
          <Image src="/ripple-mark.png" alt="" width={18} height={18} />
          <span>RIPPLE</span>
        </Link>
        <p>Built on public government records. Not medical or purchasing advice.</p>
        <Link href="/app">Open the console →</Link>
      </footer>
    </div>
  )
}

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
    line: 'One drug, public feeds, refreshed daily.',
    features: ['1 tracked drug', 'openFDA signal feed', 'Read-only console'],
    cta: 'Start watching',
    featured: false,
  },
  {
    name: 'Operate',
    price: '$2,400',
    unit: '/mo',
    line: 'The full graph, scored re-routes, and the audit trail.',
    features: ['Unlimited drugs', 'Re-route scoring', 'Exportable audit trail', 'Depot sensor ingest'],
    cta: 'Subscribe',
    featured: true,
  },
  {
    name: 'Federal',
    price: 'Custom',
    unit: '',
    line: 'TAA and 1260H screening, deployed inside your boundary.',
    features: ['TAA / EO 13944 screening', 'On-prem or GovCloud', 'SSO + role separation'],
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
          <p className="eyebrow">Sourcing risk console</p>
          <h1>A supplier goes down.<br /><em>What else just broke?</em></h1>
          <p className="hero-sub">
            Ripple reads disruption out of public FDA feeds, propagates it through a real
            sourcing graph, and ranks the alternates that can actually supply you —
            including when the honest answer is that none of them can.
          </p>
          <div className="hero-cta">
            <Link className="btn btn-primary btn-lg" href="/app">Open the console</Link>
            <Link className="btn btn-ghost btn-lg" href="#plans">See pricing</Link>
          </div>
          <p className="hero-src">
            openFDA · Type II DMF register · DECRS · Federal Register · UN Comtrade
          </p>
        </div>
      </header>

      <section id="how" className="band band-how">
        <div className="how-row">
          <div className="how-cell">
            <p className="how-step">01 — Detect</p>
            <p className="how-n">{fmt(c.signals)}</p>
            <p className="how-t">Signals joined to FEI-registered establishments — refusals,
              inspection classifications, regulatory actions.</p>
          </div>
          <div className="how-cell">
            <p className="how-step">02 — Ripple</p>
            <p className="how-n">{fmt(c.nodes)} <span>nodes · {fmt(c.edges)} edges</span></p>
            <p className="how-t">One node fails and everything structurally downstream of it
              fails at once — before any of it reaches a shortage list.</p>
          </div>
          <div className="how-cell">
            <p className="how-step">03 — Re-route</p>
            <p className="how-n">Scored</p>
            <p className="how-t">Who else holds an active filing and a US registration, ranked
              by whether moving there actually diversifies you.</p>
          </div>
        </div>
      </section>

      <section id="plans" className="band band-plans">
        <div className="band-head">
          <h2>Plans</h2>
          <p>The graph is public record. Watching it every morning is the product.</p>
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
          Built at DNHacks 2026. Pricing is illustrative — no billing is wired up. The
          console is behind a sign-in; the data under it is all public record.
        </p>
      </section>

      <footer className="site-foot">
        <Link className="nav-mark" href="/">
          <Image src="/ripple-mark.png" alt="" width={18} height={18} />
          <span>RIPPLE</span>
        </Link>
        <p>openFDA · FDA Type II DMF register · DECRS · Federal Register · UN Comtrade ·
          EO 13944 · DoD 1260H. Not medical or procurement advice.</p>
        <Link href="/app">Open the console →</Link>
      </footer>
    </div>
  )
}

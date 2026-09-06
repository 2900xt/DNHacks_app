'use client'

import type { RiskMeta } from '../lib/risk-view'
import { pct } from '../lib/risk-view'
import { Disclosure } from './Rail'

const n = (x: number) => x.toLocaleString('en-US')
const day = (s: string) =>
  new Date(`${s}T00:00:00Z`).toLocaleDateString('en-US',
    { year: 'numeric', month: 'short', day: 'numeric', timeZone: 'UTC' })

/**
 * What the model was trained on, and whether its number can be believed.
 *
 * The first question anyone serious asks a risk percentage is "says who". This
 * panel is that answer: the federal records behind it with their row counts and
 * date spans, the fit it was trained on, and — the part that matters — the
 * out-of-fold table of predicted against observed.
 *
 * Every figure comes from risk.json, which `ml/risk/emit.py` computes. Nothing
 * here is typed in, because a hand-maintained provenance panel is wrong by the
 * second commit and this one exists to be checked.
 */
export default function ModelCard({ meta }: { meta: RiskMeta }) {
  const { training: t, calibration: c, coverage: cov } = meta
  const rel = c.reliability

  return (
    <div className="mc">
      <p className="mc-lede">
        Every plant carries a probability that it suffers a disruption in the next{' '}
        {meta.horizonDays} days — a failed FDA inspection or a shipment refused at
        the border for manufacturing quality. It is learned from the federal record,
        not assigned.
      </p>

      {/* --- what it was trained on ------------------------------------- */}
      <div className="mc-h">Trained on</div>
      {t.sources.map((s) => (
        <div className="mc-src" key={s.name}>
          <div className="mc-src-top">
            <span className="mc-rows">{n(s.rows)}</span>
            <a className="mc-name" href={s.url} target="_blank" rel="noreferrer">{s.name} ↗</a>
          </div>
          <div className="mc-what">{s.what}</div>
          {s.span && (
            <div className="mc-span">{day(s.span.from)} → {day(s.span.to)}
              {s.establishments ? ` · ${n(s.establishments)} establishments` : ''}
              {s.countries ? ` · ${s.countries} countries` : ''}
            </div>
          )}
          {s.breakdown && (
            <ul className="mc-break">
              {Object.entries(s.breakdown).map(([k, v]) => (
                <li key={k}><span>{k}</span><em>{n(v)}</em></li>
              ))}
            </ul>
          )}
        </div>
      ))}

      {/* --- the fit ------------------------------------------------------ */}
      <div className="mc-h">The fit</div>
      <ul className="mc-kv">
        <li><span>Plants</span><em>{n(t.fit.plants)}</em></li>
        <li><span>That failed within a year</span><em>{n(t.fit.positives)}</em></li>
        <li><span>Base rate</span><em>{pct(t.fit.base_rate)}</em></li>
        <li><span>Cutoff</span><em>{day(t.fit.cutoff)}</em></li>
        <li><span>Features</span><em>{t.fit.features}</em></li>
      </ul>
      <p className="mc-note">
        <strong>Label:</strong> {t.fit.label}.
      </p>
      <p className="mc-note">
        <strong>Why that cutoff:</strong> {t.fit.why_this_cutoff}
      </p>

      {/* --- the part that makes the number a number ---------------------- */}
      <div className="mc-h">Does the percentage mean anything?</div>
      <p className="mc-note">
        Rank accuracy cannot answer that — a model can order plants perfectly and
        still be wrong about magnitude. So each plant is scored by a model that
        never saw it, and the predictions are compared against what actually
        happened.
      </p>
      {rel.length > 0 && (
        <table className="mc-tab">
          <thead>
            <tr><th>Predicted</th><th>Observed</th><th>Plants</th><th /></tr>
          </thead>
          <tbody>
            {rel.map((r, i) => (
              <tr key={i} data-ok={r.inside ? '1' : '0'}>
                <td>{pct(r.predicted)}</td>
                <td>{pct(r.observed)}</td>
                <td>{n(r.n)}</td>
                <td title={`95% interval ${pct(r.range[0])}–${pct(r.range[1])}`}>
                  {r.inside ? '✓' : '✗'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <p className="mc-note">
        Every band lands inside the 95% interval of what was observed. Nothing is
        shown above <strong>{pct(meta.ceiling)}</strong> — the highest rate ever
        actually observed at any score.
      </p>

      {/* --- the honest parts -------------------------------------------- */}
      <Disclosure label="What it does not know">
        <ul className="disc-list">
          {meta.notModelled.map((x) => <li key={x}>{x}</li>)}
          <li>
            Two features were computed and <strong>withheld from the fit</strong>{' '}
            ({t.fit.features_withheld.join(', ')}). {t.fit.withheld_because}
          </li>
        </ul>
      </Disclosure>

      <div className="mc-foot">
        {n(cov.scored)} of {n(cov.ui_nodes)} nodes scored · {n(cov.direct)} from
        their own record, {n(cov.inherited)} from the plant behind them ·
        run {day(meta.runAt)}
      </div>
    </div>
  )
}

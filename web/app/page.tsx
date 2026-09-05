"use client";

import { useMemo } from "react";
import { useDepot, useHistory, useTicker } from "./lib/useDepot";
import { API_BASE, elapsed, fmt, type DepotNode } from "./lib/depot";

export default function Page() {
  useTicker(1000);
  const { nodes, link, lastEventAt } = useDepot();
  const list = useMemo(() => Object.values(nodes), [nodes]);
  const primary: DepotNode | undefined = list.find((n) => n.latest) ?? list[0];
  const points = useHistory(primary?.node_id, lastEventAt);

  if (!primary) {
    return (
      <main>
        <h1>CHOKEPOINT — depot viewer</h1>
        <p>
          No bins. Is the API up? <code>make dev</code>
        </p>
      </main>
    );
  }

  const r = primary.latest ?? {};
  const spec = primary.spec ?? {};
  const ceiling = spec.mkt_c_max;

  // The stream fires on state change, not on the clock, so the server's second
  // count freezes on screen. Advance it locally.
  const held =
    typeof primary.excursion_s === "number"
      ? primary.excursion_s + (lastEventAt ? (Date.now() - lastEventAt) / 1000 : 0)
      : null;

  return (
    <main>
      <h1>CHOKEPOINT — depot viewer</h1>
      <p style={{ color: "#666", margin: 0 }}>
        {link} · {primary.device_id ?? "no device"} ·{" "}
        <button
          onClick={() =>
            fetch(`${API_BASE}/depot/nodes/${primary.node_id}/reset`, { method: "POST" })
          }
        >
          reset
        </button>
      </p>

      <hr />

      <h2>{primary.label}</h2>
      <p className="status" data-s={primary.status}>
        {primary.status}
        {held !== null && <span> · out of band {elapsed(held)}</span>}
      </p>
      {primary.reason && <p className="reason">{primary.reason}</p>}

      <h2>Latest reading</h2>
      <table>
        <tbody>
          <Row k="temp_c (BME680, authoritative)" v={`${fmt(r.temp_c)} °C`} />
          <Row k="temp_c_xcheck (DHT11)" v={`${fmt(r.temp_c_xcheck)} °C`} />
          <Row k="rh_pct" v={`${fmt(r.rh_pct)} %`} />
          <Row k="rh_pct_xcheck" v={`${fmt(r.rh_pct_xcheck)} %`} />
          <Row k="pressure_hpa" v={fmt(r.pressure_hpa, 1)} />
          <Row k="gas_ohms" v={fmt(r.gas_ohms, 0)} />
          <Row k="voc_index" v={fmt(r.voc_index)} />
          <Row k="mq2_mv" v={fmt(r.mq2_mv, 0)} />
          <Row k="ts" v={r.ts ?? "—"} />
        </tbody>
      </table>

      <h2>Evaluation</h2>
      <table>
        <tbody>
          <Row k="arithmetic mean" v={`${fmt(primary.mean_c)} °C`} />
          <Row
            k="mean kinetic temperature"
            v={`${fmt(primary.mkt_c)} °C${primary.mkt_provisional ? " (provisional)" : ""}`}
          />
          <Row k="mkt ceiling" v={`${fmt(ceiling, 1)} °C`} />
          <Row k="band" v={`${fmt(spec.temp_c_min, 1)} – ${fmt(spec.temp_c_max, 1)} °C`} />
          <Row k="rh ceiling" v={`${fmt(spec.rh_pct_max, 0)} %`} />
          <Row k="storage_class" v={primary.storage_class} />
          <Row k="window" v={`${fmt(primary.window_h, 3)} h · ${primary.n_samples ?? 0} readings`} />
        </tbody>
      </table>

      <h2>Downstream drugs ({primary.covers_drugs.length})</h2>
      <p>{primary.covers_drugs.join(", ") || "—"}</p>

      <h2>History ({points.length} points)</h2>
      <p style={{ color: "#666" }}>
        {points.length
          ? `${fmt(points[0].temp_c)} °C → ${fmt(points[points.length - 1].temp_c)} °C over ${fmt(
              (points[points.length - 1].ts - points[0].ts) / 3600,
              2,
            )} h`
          : "no data"}
      </p>

      <h2>All bins</h2>
      <table>
        <tbody>
          {list.map((n) => (
            <tr key={n.node_id}>
              <th>{n.label}</th>
              <td>
                <span className="status" data-s={n.status}>{n.status}</span>{" "}
                {n.latest?.temp_c != null ? `${fmt(n.latest.temp_c)} °C` : "—"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}

function Row({ k, v }: { k: string; v: string }) {
  return (
    <tr>
      <th>{k}</th>
      <td>{v}</td>
    </tr>
  );
}

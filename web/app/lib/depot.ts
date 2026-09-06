// Mirrors contracts/schemas/depot.schema.json. If that file changes, change this
// one in the same commit — the UI must never invent a field.

export type DepotStatus =
  | "ok"
  | "excursion"
  | "mkt_breach"
  | "sensor_fault"
  | "stale"
  | "offline";

export interface Reading {
  ts?: string | null;
  temp_c?: number | null;
  rh_pct?: number | null;
  pressure_hpa?: number | null;
  gas_ohms?: number | null;
  temp_c_xcheck?: number | null;
  rh_pct_xcheck?: number | null;
  mq2_mv?: number | null;
  mq2_rs_r0?: number | null;
  voc_index?: number | null;
  voc_bme?: number | null;
  voc_mq2?: number | null;
}

export interface Spec {
  temp_c_min?: number;
  temp_c_max?: number;
  temp_c_excursion_min?: number | null;
  temp_c_excursion_max?: number | null;
  mkt_c_max?: number | null;
  rh_pct_max?: number | null;
}

export interface DepotNode {
  node_id: string;
  label: string;
  /** ISO-2, lowercased — the `country:` node whose depot this bin sits in.
   *  Depots are local to a point of interest, not global: a bin is listed
   *  under this country and under no other. Null = unplaced, listed nowhere. */
  country?: string | null;
  material?: string | null;
  storage_class: string;
  spec?: Spec;
  status: DepotStatus;
  reason?: string | null;
  latest?: Reading | null;
  mkt_c?: number | null;
  mean_c?: number | null;
  n_samples?: number;
  window_h?: number | null;
  mkt_provisional?: boolean;
  excursion_s?: number | null;
  covers_drugs: string[];
  device_id?: string | null;
  battery_pct?: number | null;
}

export interface HistoryPoint {
  ts: number;
  temp_c: number;
}

export const API_BASE =
  process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000";

/** Operator-facing name for each state. The interface says what the auditor would say. */
export const STATUS_LABEL: Record<DepotStatus, string> = {
  ok: "In specification",
  excursion: "Excursion",
  mkt_breach: "Stock condemned",
  sensor_fault: "Cannot certify",
  stale: "No signal",
  offline: "Never reported",
};

/** Empty-state copy. An empty screen should still direct the operator. */
export const STATUS_BLURB: Record<DepotStatus, string> = {
  ok: "Storage conditions are within the band for this class.",
  excursion: "Conditions are outside the band and the dwell time has elapsed.",
  mkt_breach:
    "Cumulative heat load has exceeded the ceiling. This does not clear when the room cools.",
  sensor_fault:
    "The reading cannot be trusted, so this bin is neither passed nor failed.",
  stale: "Readings stopped arriving. A bin you cannot see is not a bin you can certify.",
  offline: "This bin has never reported. Power the node and check its node_id.",
};

/** The API embeds a live second count in `reason`, but the stream only fires on
 *  state change, so that number goes stale on screen. We render our own ticking
 *  timer instead — this strips the frozen one so the two never contradict. */
export function causeOf(reason?: string | null): string {
  if (!reason) return "";
  const m = reason.match(/^Out of band for \d+s:\s*(.*)$/);
  return m ? m[1].replace(/^./, (c) => c.toUpperCase()) : reason;
}

export function fmt(n: number | null | undefined, digits = 1): string {
  return n === null || n === undefined || Number.isNaN(n)
    ? "—"
    : n.toFixed(digits);
}

/** The bins in one country's depot. Depots are local to the point of interest
 *  the supplies flow in and out of, so a node reporting from the US is listed
 *  under the US and nowhere else — this is the only way the UI ever reads the
 *  depot list. */
export function binsIn(
  nodes: Record<string, DepotNode>,
  iso: string | null | undefined,
): DepotNode[] {
  if (!iso) return [];
  const k = iso.toLowerCase();
  return Object.values(nodes).filter((n) => (n.country ?? "").toLowerCase() === k);
}

/** Worst first — the same precedence the API sorts by. */
const RANK: DepotStatus[] = ["mkt_breach", "sensor_fault", "excursion", "stale", "offline", "ok"];
export function worstOf(bins: DepotNode[]): DepotStatus | null {
  let worst: DepotStatus | null = null;
  for (const b of bins) {
    if (worst === null || RANK.indexOf(b.status) < RANK.indexOf(worst)) worst = b.status;
  }
  return worst;
}

export function elapsed(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m ${s % 60}s`;
  return `${Math.floor(m / 60)}h ${m % 60}m`;
}

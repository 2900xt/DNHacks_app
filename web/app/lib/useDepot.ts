"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { API_BASE, type DepotNode, type HistoryPoint } from "./depot";

type Link = "connecting" | "live" | "down";

/**
 * One connection to the depot service.
 *
 * `/depot/stream` emits a single node per event, only when that node's state
 * actually changes, so this merges by node_id rather than replacing a list.
 * Native EventSource already retries on drop, which is what we want on a venue
 * network — the link indicator reflects it rather than hiding it.
 */
export function useDepot() {
  const [nodes, setNodes] = useState<Record<string, DepotNode>>({});
  const [link, setLink] = useState<Link>("connecting");
  const [lastEventAt, setLastEventAt] = useState<number>(0);

  useEffect(() => {
    let cancelled = false;
    fetch(`${API_BASE}/depot/nodes`)
      .then((r) => r.json())
      .then((list: DepotNode[]) => {
        if (cancelled) return;
        setNodes(Object.fromEntries(list.map((n) => [n.node_id, n])));
      })
      .catch(() => undefined);

    const es = new EventSource(`${API_BASE}/depot/stream`);
    es.onopen = () => setLink("live");
    es.onmessage = (ev) => {
      const n: DepotNode = JSON.parse(ev.data);
      setNodes((prev) => ({ ...prev, [n.node_id]: n }));
      setLastEventAt(Date.now());
      setLink("live");
    };
    es.onerror = () => setLink("down");

    return () => {
      cancelled = true;
      es.close();
    };
  }, []);

  return { nodes, link, lastEventAt };
}

/**
 * Temperature history for the trace.
 *
 * Seeded from `/history` so a page refresh mid-demo repaints the whole window
 * instead of starting from a blank chart, then resynced on a slow timer. The
 * live feel comes from the readouts, not from this.
 */
export function useHistory(nodeId: string | undefined, tick: unknown) {
  const [points, setPoints] = useState<HistoryPoint[]>([]);
  const last = useRef(0);

  const load = useCallback(() => {
    if (!nodeId) return;
    fetch(`${API_BASE}/depot/nodes/${nodeId}/history?limit=600`)
      .then((r) => r.json())
      .then((d) => setPoints(d.points ?? []))
      .catch(() => undefined);
  }, [nodeId]);

  useEffect(() => {
    load();
    const id = setInterval(load, 4000);
    return () => clearInterval(id);
  }, [load]);

  // Also pull immediately when a stream event lands, so the trace keeps up with
  // a replay that plays 24h of history in a couple of seconds.
  useEffect(() => {
    const now = Date.now();
    if (now - last.current > 700) {
      last.current = now;
      load();
    }
  }, [tick, load]);

  return points;
}

/** Wall-clock ticker, so elapsed timers advance between stream events. */
export function useTicker(ms = 1000) {
  const [, setN] = useState(0);
  useEffect(() => {
    const id = setInterval(() => setN((n) => n + 1), ms);
    return () => clearInterval(id);
  }, [ms]);
}

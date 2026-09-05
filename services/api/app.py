"""
CHOKEPOINT API — depot-node slice.

Scope: ingest storage telemetry, evaluate it against USP bands, and serve the
result as graph nodes. The sourcing graph (drugs, plants, 6-APA) is a separate
concern and belongs to whoever owns that half — this file deliberately does not
touch it. The seam between them is `covers_drugs` on each depot node.

In-memory by design. There is no database and there should not be one before noon.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from depot import STATUS_RANK, Bin

VERSION = "0.1.0-depot"
SEED = Path(__file__).parent / "seed" / "depot_bins.json"

app = FastAPI(title="CHOKEPOINT API", version=VERSION)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)

BINS: dict[str, Bin] = {}


def _load_seed() -> None:
    for spec in json.loads(SEED.read_text()):
        b = Bin(**spec)
        _tune(b)
        BINS[b.node_id] = b


def _tune(b: Bin) -> None:
    b.dwell_s = float(os.getenv("DEPOT_DWELL_S", "8"))
    b.window_s = float(os.getenv("DEPOT_WINDOW_S", "86400"))
    b.min_window_s = float(os.getenv("DEPOT_MIN_WINDOW_S", "3600"))
    b.xcheck_tolerance_c = float(os.getenv("DEPOT_XCHECK_TOLERANCE_C", "3.0"))


def _parse_ts(raw: Optional[str]) -> Optional[float]:
    """Device clocks drift and most of these will never see NTP, so receipt time
    wins by default. The exception is replay: it plays a real multi-hour history
    faster than real time, and collapsing that onto receipt time would produce an
    MKT computed over four seconds. DEPOT_TRUST_DEVICE_TS=1 turns that off."""
    if not raw or os.getenv("DEPOT_TRUST_DEVICE_TS", "0") in ("0", "false", "no"):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.timestamp()


_load_seed()


# --- models -------------------------------------------------------------------

class Location(BaseModel):
    lat: float
    lon: float
    alt_m: Optional[float] = None
    accuracy_m: Optional[float] = None


class Telemetry(BaseModel):
    """contracts/schemas/telemetry.schema.json"""

    device_id: str = Field(min_length=1)
    node_id: Optional[str] = None
    ts: Optional[str] = None
    seq: Optional[int] = None
    readings: dict[str, Any]
    location: Optional[Location] = None
    battery_pct: Optional[float] = None


# --- routes -------------------------------------------------------------------

@app.get("/health")
def health() -> dict[str, Any]:
    return {"ok": True, "version": VERSION, "bins": len(BINS)}


@app.post("/telemetry", status_code=202)
def post_telemetry(t: Telemetry) -> dict[str, Any]:
    now = _parse_ts(t.ts) or time.time()
    node_id = t.node_id or t.device_id

    b = BINS.get(node_id)
    if b is None:
        # A device flashed at 4am with a typo'd node_id must SHOW UP, not 404.
        b = Bin(node_id=node_id, label=f"Unregistered — {node_id}", storage_class="crt")
        _tune(b)
        BINS[node_id] = b

    b.ingest(t.readings, now, device_id=t.device_id, battery_pct=t.battery_pct)
    status, _ = b.status(now)
    return {"accepted": True, "node_id": node_id, "status": status}


@app.get("/depot/nodes")
def list_nodes() -> list[dict[str, Any]]:
    now = time.time()
    nodes = [b.to_node(now) for b in BINS.values()]
    nodes.sort(key=lambda n: (STATUS_RANK.get(n["status"], 9), n["node_id"]))
    return nodes


@app.get("/depot/nodes/{node_id}")
def get_node(node_id: str) -> dict[str, Any]:
    b = BINS.get(node_id)
    if b is None:
        raise HTTPException(status_code=404, detail=f"no such bin: {node_id}")
    return b.to_node()


@app.post("/depot/nodes/{node_id}/reset")
def reset_node(node_id: str) -> dict[str, Any]:
    """Clear latched MKT breach between demo runs. You WILL need this between judges."""
    b = BINS.get(node_id)
    if b is None:
        raise HTTPException(status_code=404, detail=f"no such bin: {node_id}")
    b.reset()
    return {"reset": node_id}


def _change_key(n: dict[str, Any]) -> str:
    """What counts as a change worth pushing.

    Deliberately excludes `excursion_s`, `latest.ts` and `reason`: all three
    advance with the wall clock even when no new reading has arrived (`reason`
    embeds an elapsed-seconds count), so keying on them makes the stream fire
    twice a second forever once a bin goes out of band. Status, MKT and the
    actual readings are the real signal — and the full node, reason included,
    still rides in every event body.
    """
    latest = n.get("latest") or {}
    return json.dumps(
        {
            "status": n["status"],
            "mkt_c": n["mkt_c"],
            "temp_c": latest.get("temp_c"),
            "rh_pct": latest.get("rh_pct"),
            "temp_c_xcheck": latest.get("temp_c_xcheck"),
            "gas_ohms": latest.get("gas_ohms"),
            "mq2_mv": latest.get("mq2_mv"),
        },
        sort_keys=True,
    )


@app.get("/depot/stream")
async def stream() -> StreamingResponse:
    async def gen():
        last: dict[str, str] = {}
        # Prime, so a client that connects mid-demo renders immediately.
        for n in list_nodes():
            last[n["node_id"]] = _change_key(n)
            yield f"data: {json.dumps(n)}\n\n"
        while True:
            await asyncio.sleep(0.5)
            for n in list_nodes():
                key = _change_key(n)
                if last.get(n["node_id"]) != key:
                    last[n["node_id"]] = key
                    yield f"data: {json.dumps(n)}\n\n"

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

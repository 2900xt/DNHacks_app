"""
Storage-condition evaluation for depot nodes.

This is the only place in CHOKEPOINT where a node's health comes from physics
instead of from a sourcing model. Everything here is deliberately boring and
testable; app.py just wires HTTP around it.

References for the numbers (say these on stage, they are checkable):
  - USP <659> Packaging and Storage Requirements — the CRT / cool / refrigerated
    / frozen bands, and the principle that brief excursions are permitted so long
    as the mean kinetic temperature stays under the ceiling.
  - USP <1079> / ICH Q1A(R2) — mean kinetic temperature, dH = 83.144 kJ/mol.
  - ICH Q1A(R2) long-term condition 25 C / 60% RH — where the humidity ceiling
    comes from. 6-APA is a beta-lactam: the ring hydrolyses, so moisture is the
    real degradation driver, not heat alone.
"""

from __future__ import annotations

import math
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Deque, Optional

# --- mean kinetic temperature -------------------------------------------------

DELTA_H = 83_144.0  # J/mol, the conventional value used across ICH/USP practice
R_GAS = 8.314       # J/(mol*K)


def mean_kinetic_temperature(
    samples: list[tuple[float, float]] | list[float],
) -> Optional[float]:
    """MKT in degrees C, time-weighted.

    Accepts either [(ts, temp_c), ...] or a bare [temp_c, ...] (equal weights).

    MKT is a TIME-weighted metric: an hour at 40 C is not one sample at 40 C.
    Weighting by sample count instead of elapsed time silently misreports the
    heat load whenever the device drops packets or the sample rate changes —
    both of which will happen tonight. Each sample is weighted by the interval
    it represents; the final sample inherits the previous interval.
    """
    if not samples:
        return None

    if isinstance(samples[0], (int, float)):
        temps = [float(t) for t in samples]  # type: ignore[arg-type]
        weights = [1.0] * len(temps)
    else:
        pairs = sorted(samples)  # type: ignore[arg-type]
        temps = [t for _, t in pairs]
        if len(pairs) == 1:
            weights = [1.0]
        else:
            weights = [pairs[i + 1][0] - pairs[i][0] for i in range(len(pairs) - 1)]
            weights.append(weights[-1])
            weights = [w if w > 0 else 1e-9 for w in weights]

    total = sum(weights)
    if total <= 0:
        return None
    acc = sum(
        w * math.exp(-DELTA_H / (R_GAS * (t + 273.15)))
        for w, t in zip(weights, temps)
    )
    mean_k = acc / total
    if mean_k <= 0.0:
        return None
    return (DELTA_H / R_GAS) / (-math.log(mean_k)) - 273.15


# --- storage classes ----------------------------------------------------------

STORAGE_CLASSES: dict[str, dict[str, Optional[float]]] = {
    # Controlled Room Temperature. The right class for a 6-APA / API powder reserve.
    "crt": {
        "temp_c_min": 20.0, "temp_c_max": 25.0,
        "temp_c_excursion_min": 15.0, "temp_c_excursion_max": 30.0,
        "mkt_c_max": 25.0, "rh_pct_max": 60.0,
    },
    "cool": {
        "temp_c_min": 8.0, "temp_c_max": 15.0,
        "temp_c_excursion_min": None, "temp_c_excursion_max": None,
        "mkt_c_max": 15.0, "rh_pct_max": 60.0,
    },
    "refrigerated": {
        "temp_c_min": 2.0, "temp_c_max": 8.0,
        "temp_c_excursion_min": None, "temp_c_excursion_max": None,
        "mkt_c_max": 8.0, "rh_pct_max": None,
    },
    "frozen": {
        "temp_c_min": -25.0, "temp_c_max": -10.0,
        "temp_c_excursion_min": None, "temp_c_excursion_max": None,
        "mkt_c_max": -10.0, "rh_pct_max": None,
    },
}


@dataclass
class Bin:
    """One physical storage location. Devices are swappable; bins are not."""

    node_id: str
    label: str
    storage_class: str = "crt"
    material: Optional[str] = None
    covers_drugs: list[str] = field(default_factory=list)

    # Tuning. Demo defaults are deliberately fast — a judge will not stand there
    # for 30 minutes. Report window_h honestly in the payload and say it on stage.
    dwell_s: float = 8.0
    stale_after_s: float = 30.0
    window_s: float = 900.0
    # An MKT computed over 30 seconds is not a storage claim, it is a
    # thermometer with extra steps. Below this span we report MKT as
    # provisional and refuse to latch a breach on it.
    min_window_s: float = 3600.0
    # BME680 is +/-1 C, DHT11 is +/-2 C, so 3 C is the worst case two healthy
    # parts can legitimately differ by. Beyond that one of them has failed, and
    # a bin whose reading you cannot trust is not a bin you can certify.
    xcheck_tolerance_c: float = 3.0

    # State.
    device_id: Optional[str] = None
    battery_pct: Optional[float] = None
    last_ts: Optional[float] = None
    latest: dict[str, Any] = field(default_factory=dict)
    history: Deque[tuple[float, float]] = field(default_factory=lambda: deque(maxlen=20_000))
    out_of_band_since: Optional[float] = None
    sensor_fault: Optional[str] = None
    mkt_latched: bool = False  # condemned stock does not un-condemn when the room cools

    # -- ingest ---------------------------------------------------------------

    def ingest(self, readings: dict[str, Any], ts: float,
               device_id: Optional[str] = None,
               battery_pct: Optional[float] = None) -> None:
        self.last_ts = ts
        if device_id:
            self.device_id = device_id
        if battery_pct is not None:
            self.battery_pct = battery_pct

        temp = _num(readings.get("temp_c"))
        xtemp = _num(readings.get("temp_c_xcheck"))
        self.latest = {
            "ts": _iso(ts),
            "temp_c": temp,
            "rh_pct": _num(readings.get("rh_pct")),
            "pressure_hpa": _num(readings.get("pressure_hpa")),
            "gas_ohms": _num(readings.get("gas_ohms")),
            "temp_c_xcheck": xtemp,
            "rh_pct_xcheck": _num(readings.get("rh_pct_xcheck")),
            "mq2_mv": _num(readings.get("mq2_mv")),
            # Volatiles, ADVISORY ONLY. Passed through to the UI and never read
            # by _in_band(), status() or the MKT: 0 on this index means "the air
            # the node booted in", not "clean", and nothing in it is calibrated
            # against a gas standard. A bin is condemned by heat and moisture,
            # not by a smell. It earns its place by making a warehouse-smoke
            # event visible early, which is a different job from certifying.
            "mq2_rs_r0": _num(readings.get("mq2_rs_r0")),
            "voc_index": _num(readings.get("voc_index")),
            "voc_bme": _num(readings.get("voc_bme")),
            "voc_mq2": _num(readings.get("voc_mq2")),
        }

        # Cross-check BEFORE anything else uses the reading. The DHT11 is not a
        # fallback — it cannot certify a 5 C band on its own — but two
        # independent sensors diverging is how a failed part announces itself.
        if temp is None:
            self.sensor_fault = (
                "Authoritative sensor (BME680) is not reporting. The DHT11 "
                "cross-check cannot certify this bin on its own — +/-2 C is 40% "
                "of a 20-25 C band."
            )
        elif xtemp is not None and abs(temp - xtemp) > self.xcheck_tolerance_c:
            self.sensor_fault = (
                f"BME680 reads {temp:.1f} C, DHT11 reads {xtemp:.1f} C — a "
                f"{abs(temp - xtemp):.1f} C disagreement against a "
                f"{self.xcheck_tolerance_c:.0f} C tolerance. One of them has "
                f"failed; this bin cannot be certified until it is resolved."
            )
        else:
            self.sensor_fault = None

        if temp is None:
            return
        self.history.append((ts, temp))
        self._trim(ts)

        if self._in_band(temp, self.latest["rh_pct"]):
            self.out_of_band_since = None
        elif self.out_of_band_since is None:
            self.out_of_band_since = ts

        mkt = self.mkt()
        ceiling = self.spec()["mkt_c_max"]
        if (mkt is not None and ceiling is not None and mkt > ceiling
                and self._span() >= self.min_window_s):
            self.mkt_latched = True

    def reset(self) -> None:
        """Clear latched state between demo runs. Not a production affordance —
        in the real thing, condemned stock stays condemned until a human dispositions it."""
        self.history.clear()
        self.out_of_band_since = None
        self.mkt_latched = False
        self.sensor_fault = None
        self.latest = {}
        self.last_ts = None

    # -- derived --------------------------------------------------------------

    def spec(self) -> dict[str, Optional[float]]:
        return STORAGE_CLASSES.get(self.storage_class, STORAGE_CLASSES["crt"])

    def mkt(self) -> Optional[float]:
        return mean_kinetic_temperature(list(self.history))

    def status(self, now: Optional[float] = None) -> tuple[str, Optional[str]]:
        now = now if now is not None else time.time()
        spec = self.spec()

        if self.last_ts is None:
            return "offline", "No reading yet — device has never reported."

        age = now - self.last_ts
        if age > self.stale_after_s:
            return "stale", (
                f"No reading for {int(age)}s. A bin you cannot see is not a bin you can certify."
            )

        # MKT breach outranks everything: it is the criterion that condemns stock.
        if self.mkt_latched:
            mkt = self.mkt()
            return "mkt_breach", (
                f"Mean kinetic temperature {mkt:.1f} C exceeds the {spec['mkt_c_max']:.0f} C "
                f"ceiling for this class. The heat load is cumulative — this does not clear "
                f"when the room cools."
            )

        # Ranks below a latched MKT breach (that determination was already made
        # from good history) but above everything else: an untrustworthy reading
        # cannot clear a bin, and it cannot condemn one either.
        if self.sensor_fault:
            return "sensor_fault", self.sensor_fault

        if self.out_of_band_since is not None:
            held = now - self.out_of_band_since
            if held >= self.dwell_s:
                return "excursion", self._excursion_reason(held)

        return "ok", None

    def to_node(self, now: Optional[float] = None) -> dict[str, Any]:
        """Serialise to contracts/schemas/depot.schema.json."""
        now = now if now is not None else time.time()
        status, reason = self.status(now)
        excursion_s = (
            round(now - self.out_of_band_since, 1)
            if self.out_of_band_since is not None else None
        )
        mkt = self.mkt()
        return {
            "node_id": self.node_id,
            "label": self.label,
            "material": self.material,
            "storage_class": self.storage_class,
            "spec": dict(self.spec()),
            "status": status,
            "reason": reason,
            "latest": self.latest or None,
            "mkt_c": round(mkt, 2) if mkt is not None else None,
            "window_h": round(self._span() / 3600.0, 4) if self.history else None,
            "mkt_provisional": self._span() < self.min_window_s,
            "excursion_s": excursion_s,
            "covers_drugs": list(self.covers_drugs),
            "device_id": self.device_id,
            "battery_pct": self.battery_pct,
        }

    # -- internals ------------------------------------------------------------

    def _in_band(self, temp: Optional[float], rh: Optional[float]) -> bool:
        spec = self.spec()
        if temp is not None:
            lo, hi = spec["temp_c_min"], spec["temp_c_max"]
            if lo is not None and temp < lo:
                return False
            if hi is not None and temp > hi:
                return False
        if rh is not None and spec["rh_pct_max"] is not None and rh > spec["rh_pct_max"]:
            return False
        return True

    def _excursion_reason(self, held: float) -> str:
        spec = self.spec()
        temp, rh = self.latest.get("temp_c"), self.latest.get("rh_pct")
        parts: list[str] = []
        if temp is not None:
            if spec["temp_c_max"] is not None and temp > spec["temp_c_max"]:
                parts.append(f"{temp:.1f} C is above the {spec['temp_c_max']:.0f} C ceiling")
            elif spec["temp_c_min"] is not None and temp < spec["temp_c_min"]:
                parts.append(f"{temp:.1f} C is below the {spec['temp_c_min']:.0f} C floor")
        if rh is not None and spec["rh_pct_max"] is not None and rh > spec["rh_pct_max"]:
            parts.append(
                f"{rh:.0f}% RH is above the {spec['rh_pct_max']:.0f}% ceiling "
                f"(beta-lactam hydrolysis)"
            )
        why = "; ".join(parts) or "out of band"
        return f"Out of band for {int(held)}s: {why}."

    def _trim(self, now: float) -> None:
        while self.history and (now - self.history[0][0]) > self.window_s:
            self.history.popleft()

    def _span(self) -> float:
        if len(self.history) < 2:
            return 0.0
        return self.history[-1][0] - self.history[0][0]


def _num(v: Any) -> Optional[float]:
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _iso(ts: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


STATUS_RANK = {
    "mkt_breach": 0,
    "sensor_fault": 1,
    "excursion": 2,
    "stale": 3,
    "offline": 4,
    "ok": 5,
}

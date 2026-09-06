"""Sites — the API-tier DMF holders, placed on the map.

    python3 ml/sites.py            # -> web/data/nodes.sites.json, edges.sites.json, geo.json

The console's tree used to stop at the precursor: drug -> API -> 6-APA -> the
eight 6-APA filers. That skips a real tier. The FDA DMF register lists who holds
an ACTIVE Type II DMF for each finished API itself — amoxicillin trihydrate,
ampicillin, and the rest — and those are the plants a US buyer actually
qualifies. This script emits that tier as graph nodes and edges, resolved
through DECRS the same way aegis.py resolves the 6-APA holders, so AEGIS can
score and re-rank them with the same rule.

WHERE A SITE IS DRAWN
---------------------
DECRS carries a street address per FEI. The CITY is parsed out of it and
geocoded against GeoNames (cities1000: every place over 1,000 people, with
population and alternate spellings), restricted to the address's own country
and, on a name shared by several places, taking the most populous — Datong,
Shanxi over the four smaller Datongs. A site that geocodes is drawn at its
city; one that does not is drawn at its country's centroid and says so
(`geo: "country"`). Nothing is placed at a street: the gazetteer is city-level,
and a dot at a city is the honest resolution of a record that names a city.

Only DECRS-MATCHED holders are emitted. A DMF holder DECRS cannot place has no
country, no site and no registration to ship — it would be a box with nothing
in it. Its absence is still visible: the register count on the API node.
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml.aegis import (  # noqa: E402
    ISO3_TO_ISO2, REPO, CACHE, _match, build_index, decrs_rows, dmf_holders, fetch,
    squash, substance_for,
)
from ml.xlsx import rows as xlsx_rows  # noqa: E402
from ml.aegis import DMF_URL, DMF_XLSX  # noqa: E402

CITIES_URL = "https://download.geonames.org/export/dump/cities1000.zip"
CITIES = CACHE / "geonames" / "cities1000.zip"
WORLD = REPO / "web" / "public" / "world.globe.json"

COUNTRY_NAME = {
    "at": "Austria", "cn": "China", "in": "India", "us": "United States", "il": "Israel",
    "it": "Italy", "es": "Spain", "kr": "South Korea", "de": "Germany", "fr": "France",
    "gb": "United Kingdom", "jp": "Japan", "ch": "Switzerland", "nl": "Netherlands",
    "pt": "Portugal", "ie": "Ireland", "mx": "Mexico", "br": "Brazil", "tw": "Taiwan",
    "sg": "Singapore", "be": "Belgium", "dk": "Denmark", "se": "Sweden", "pl": "Poland",
    "cz": "Czechia", "hu": "Hungary", "hr": "Croatia", "si": "Slovenia", "sk": "Slovakia",
    "ro": "Romania", "bg": "Bulgaria", "gr": "Greece", "tr": "Turkey", "ca": "Canada",
    "au": "Australia", "nz": "New Zealand", "th": "Thailand", "vn": "Vietnam", "id": "Indonesia",
    "my": "Malaysia", "ar": "Argentina", "cl": "Chile", "co": "Colombia", "pe": "Peru",
    "eg": "Egypt", "ru": "Russia", "fi": "Finland", "no": "Norway",
}

# Suffixes and qualifiers a gazetteer does not carry.
CITY_NOISE = re.compile(
    r"\b(city|district|dist|county|province|prefecture|town|village|industrial|zone|park|"
    r"tehsil|taluka|mandal|nagar|p\.?o\.?|post|near|opp|road|rd|street|st|no)\b\.?", re.I)
STRIP_SUFFIX = re.compile(r"-(shi|si|gu|ku|do|gun|ken|fu)$", re.I)


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"[^a-z0-9]+", "", s)


def gazetteer() -> dict[str, dict[str, list[tuple[float, float, int, str]]]]:
    """iso2 -> normalised name (own and alternates) -> [(lat, lng, population, admin1)].

    The most populous place wins a name. Alternate names are what make Chinese
    addresses resolve at all: DECRS writes Hohhot as `Huhehaote`.
    """
    import zipfile
    fetch(CITIES_URL, CITIES, timeout=300)
    out: dict[str, dict[str, tuple[float, float, int]]] = {}
    with zipfile.ZipFile(CITIES) as z:
        text = z.read("cities1000.txt").decode("utf-8")
    for line in text.splitlines():
        f = line.split("\t")
        if len(f) < 15:
            continue
        iso = f[8].lower()
        pop = int(f[14] or 0)
        lat, lng = float(f[4]), float(f[5])
        d = out.setdefault(iso, {})
        names = [f[1], f[2], *f[3].split(",")]
        for nm in names:
            k = norm(STRIP_SUFFIX.sub("", nm.strip()))
            if not k:
                continue
            d.setdefault(k, []).append((lat, lng, pop, f[10]))
    return out


def city_candidates(address: str, holder: str) -> list[str]:
    """Tokens from the address that could be the city, most likely first.

    DECRS addresses read street, ..., city, region+postcode, country (ISO3).
    So the field before the region is the city, and the fields inward from it
    are district / locality qualifiers that name a place at least as specific.
    Whole fields are tried first, from the city field inward, then the region
    field, then single words inside fields (`Dezhou City` -> Dezhou). The
    holder's own name is used ONLY when there is no address at all — a name
    like `Inner Mongolia Changsheng` contains a word that is also some town
    somewhere, and taking it over a real address put the plant in Chongqing.
    """
    parts = [p.strip() for p in re.sub(r"\([A-Z]{3}\)\s*$", "", address).split(",")]
    parts = [p for p in parts if p]
    if parts:
        parts = parts[:-1]  # the country name
    clean = []
    for p in parts:
        p2 = re.sub(r"\b[A-Z]{1,2}-?\d[\w-]*\b|\b\d[\w-]*\b", " ", p)  # postcodes, numbers
        p2 = re.sub(r"\([^)]*\)", " ", p2)
        p2 = CITY_NOISE.sub(" ", p2).strip(" .-")
        clean.append(p2)
    fields = [c for c in clean if c]
    order: list[str] = []
    if len(fields) >= 2:
        order += list(reversed(fields[:-1]))   # city field, then inward
        order.append(fields[-1])               # region, last resort among fields
    else:
        order += fields
    words = []
    for f in order:
        for w in f.split():
            w = STRIP_SUFFIX.sub("", w)
            if len(w) >= 4:
                words.append(w)
    out = order + words
    if not address.strip():
        out += [w for w in holder.split() if len(w) >= 5 and w.isalpha()]
    seen: set[str] = set()
    uniq = []
    for c in out:
        k = norm(STRIP_SUFFIX.sub("", c))
        if k and k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq


def geocode(gaz, iso2: str, address: str, holder: str) -> tuple[float, float, str] | None:
    """The place: most populous holder of the name — unless the address names a
    US state in parentheses, `(MA)`, in which case that state's Lee beats the
    bigger Lee in Florida."""
    table = gaz.get(iso2) or {}
    m = re.search(r"\(([A-Z]{2})\)", address)
    admin1 = m.group(1) if (m and iso2 == "us") else None
    for cand in city_candidates(address, holder):
        k = norm(STRIP_SUFFIX.sub("", cand))
        hits = table.get(k)
        if not hits and len(k) >= 7:
            # Transliteration drift: DECRS writes Sangareddy, GeoNames Sangareddi.
            # A shared stem of all-but-one character, inside one country, on a
            # candidate that came from the city field, is the same place.
            stem = k[:-1]
            near = [h for kk, hs in table.items() if kk.startswith(stem) and len(kk) <= len(k) + 1 for h in hs]
            hits = near or None
        if not hits:
            continue
        if admin1:
            in_state = [h for h in hits if h[3] == admin1]
            if in_state:
                hits = in_state
        lat, lng, _pop, _a1 = max(hits, key=lambda h: h[2])
        return lat, lng, cand.strip()
    return None


def slug(holder: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", holder.lower()).strip("-")
    return f"company:name:{s}"


def main() -> int:
    nodes: dict[str, dict] = {}
    for f in ("nodes.openfda.json", "nodes.curated.json"):
        for n in json.loads((REPO / "web" / "data" / f).read_text()):
            nodes[n["id"]] = n
    world = json.loads(WORLD.read_text())
    centroids = world["centroids"]
    gaz = gazetteer()
    by_core, _sig = build_index()
    addr_by_fei = {(r.get("FEI_NUMBER") or "").strip(): r.get("ADDRESS") or "" for r in decrs_rows()}

    # DMF numbers per (holder, substance), so each node carries its own filing.
    fetch(DMF_URL, DMF_XLSX)
    dmf_no: dict[tuple[str, str], tuple[str, str, str]] = {}
    it = xlsx_rows(DMF_XLSX)
    next(it)
    for r in it:
        if len(r) < 6 or r[2] != "II" or r[1] != "A" or not (r[4] and r[5]):
            continue
        dmf_no.setdefault((r[4].strip(), squash(r[5])), (r[0], r[5].strip(), r[3]))

    out_nodes: list[dict] = []
    out_edges: list[dict] = []
    geo: dict[str, dict] = {}
    countries_seen: set[str] = {n["country"] for n in nodes.values() if n["type"] == "country" and n.get("country")}
    emitted: set[str] = set()
    out_ids: set[str] = set()

    targets = [n for n in nodes.values() if n["type"] in ("api", "precursor")]
    for node in sorted(targets, key=lambda n: (n["type"] != "precursor", n["id"])):
        substance = substance_for(node)
        groups, spellings = dmf_holders(substance)
        tier = "precursor" if node["type"] == "precursor" else "api"
        placed = 0
        for h in sorted(groups["active"]):
            rec, note = _match(h, by_core)
            nid = slug(h)
            if not rec:
                # The 6-APA tier keeps its curated country-only nodes; a hint
                # from the holder's name still places TUL Chengdu at Chengdu.
                if nid in nodes and nodes[nid].get("country"):
                    iso2 = nodes[nid]["country"]
                    g = geocode(gaz, iso2, "", h)
                    if g:
                        geo[nid] = {"lat": g[0], "lng": g[1], "city": g[2], "geo": "city", "country": iso2,
                                    "evidence": f"city named in the DMF holder name; DECRS has no row"}
                    elif iso2 in centroids:
                        geo[nid] = {"lat": centroids[iso2]["lat"], "lng": centroids[iso2]["lng"],
                                    "city": None, "geo": "country", "country": iso2, "evidence": "country centroid"}
                continue
            feis = sorted(f for f in rec["feis"] if f)
            iso3 = sorted(rec["countries"])[0] if rec["countries"] else None
            iso2 = ISO3_TO_ISO2.get(iso3, iso3.lower()) if iso3 else None
            if not iso2:
                continue
            # The site: first FEI whose address is in the matched country.
            address = ""
            fei = feis[0] if feis else ""
            for f in feis:
                a = addr_by_fei.get(f, "")
                if a.endswith(f"({iso3})"):
                    address, fei = a, f
                    break
            g = geocode(gaz, iso2, address, h)
            if g:
                geo[nid] = {"lat": g[0], "lng": g[1], "city": g[2], "geo": "city", "country": iso2,
                            "evidence": f"DECRS FEI {fei} address, city geocoded (GeoNames cities1000)"}
            elif iso2 in centroids:
                geo[nid] = {"lat": centroids[iso2]["lat"], "lng": centroids[iso2]["lng"],
                            "city": None, "geo": "country", "country": iso2,
                            "evidence": f"DECRS FEI {fei} address could not be geocoded; country centroid"}
            else:
                continue
            placed += 1

            if tier == "api":
                # The filing itself rides in the side table too, for holders the
                # openFDA lane already carries as labelers with no DMF on them.
                d0 = dmf_no.get((h, squash(substance))) or next(
                    (v for (hh, ss), v in dmf_no.items() if hh == h and ss.startswith(squash(substance)[:8])), None)
                if d0 and "dmf" not in geo[nid]:
                    geo[nid].update({"dmf": int(d0[0]) if d0[0].isdigit() else d0[0],
                                     "dmf_status": "A", "dmf_subject": d0[1]})
                if iso2 not in countries_seen:
                    countries_seen.add(iso2)
                    out_nodes.append({
                        "id": f"country:{iso2}", "type": "country",
                        "label": COUNTRY_NAME.get(iso2, iso2.upper()), "country": iso2,
                        "critical": False, "attrs": {"source": "DECRS establishment address"},
                    })
                d = dmf_no.get((h, squash(substance))) or next(
                    (v for (hh, ss), v in dmf_no.items() if hh == h and ss.startswith(squash(substance)[:8])), None)
                # A holder the openFDA lane already carries as a LABELER gets no
                # second node — one id, one box — but it still gets its country
                # edge here, because the labeler record never had one.
                if nid not in emitted:
                    emitted.add(nid)
                    out_edges.append({
                        "src": nid, "dst": f"country:{iso2}", "rel": "incorporated_in", "layer": 1,
                        "citation": f"FDA DECRS drls_reg — FEI {fei}, '{rec['name']}', address ends ({iso3}). "
                                    "https://www.accessdata.fda.gov/cder/drls_reg.zip",
                    })
                if nid not in nodes and nid not in out_ids:
                    out_ids.add(nid)
                    out_nodes.append({
                        "id": nid, "type": "company", "label": h, "country": iso2,
                        "critical": False, "resolved_by": "fuzzy",
                        "attrs": {
                            "dmf": int(d[0]) if d and d[0].isdigit() else d[0] if d else None,
                            "dmf_status": "A", "dmf_type": "II",
                            "dmf_subject": d[1] if d else substance,
                            "tier": "api",
                            "decrs_firm": rec["name"], "fei": fei,
                            "city": geo[nid]["city"],
                            "country_evidence": f"DECRS '{rec['name']}' = {iso3}",
                        },
                    })
                out_edges.append({
                    "src": node["id"], "dst": nid, "rel": "produced_by", "layer": 2,
                    "citation": f"FDA Type II DMF register — DMF {d[0] if d else '?'}, active, "
                                f"subject '{d[1] if d else substance}', holder '{h}'. {DMF_URL}",
                })
        print(f"  {node['id']:<32} {len(groups['active']):>3} active filings, {placed:>3} placed", file=sys.stderr)

    d = REPO / "web" / "data"
    (d / "nodes.sites.json").write_text(json.dumps(out_nodes, indent=2, ensure_ascii=False) + "\n")
    (d / "edges.sites.json").write_text(json.dumps(out_edges, indent=2, ensure_ascii=False) + "\n")
    (d / "geo.json").write_text(json.dumps(geo, indent=2, ensure_ascii=False) + "\n")
    cities = sum(1 for g in geo.values() if g["geo"] == "city")
    print(f"  wrote {len(out_nodes)} nodes, {len(out_edges)} edges, {len(geo)} sites placed "
          f"({cities} at a city, {len(geo) - cities} at a country centroid)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

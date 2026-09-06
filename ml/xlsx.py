"""A minimal read-only .xlsx reader, stdlib only.

`ml/load/load_dmf.py` uses openpyxl from `ml/.venv`. That venv does not exist on
every machine and `pip install` on venue wifi is not a dependency the Sunday
build should have — same reasoning as the stdlib websocket client in
`ml/signals/qlik.py`.

An .xlsx is a zip of XML. Rows live in `xl/worksheets/sheet1.xml`; string cells
hold an index into `xl/sharedStrings.xml` rather than the text itself.

    from ml.xlsx import rows
    for r in rows("file.xlsx"):
        ...
"""

from __future__ import annotations

import re
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"


def _shared_strings(z: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in z.namelist():
        return []
    root = ET.fromstring(z.read("xl/sharedStrings.xml"))
    out = []
    for si in root.findall(f"{NS}si"):
        # A string can be split across several <t> runs; join them.
        out.append("".join(t.text or "" for t in si.iter(f"{NS}t")))
    return out


def _col_index(ref: str) -> int:
    """'BC12' -> 54. Cells are sparse, so position must come from the ref."""
    letters = re.match(r"([A-Z]+)", ref or "A").group(1)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def rows(path: str | Path, sheet: str = "xl/worksheets/sheet1.xml"):
    """Yield each row as a list of strings. Blank cells become ''."""
    with zipfile.ZipFile(path) as z:
        shared = _shared_strings(z)
        with z.open(sheet) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if el.tag != f"{NS}row":
                    continue
                cells: dict[int, str] = {}
                for c in el.findall(f"{NS}c"):
                    v = c.find(f"{NS}v")
                    if c.get("t") == "inlineStr":
                        is_el = c.find(f"{NS}is")
                        text = "".join(t.text or "" for t in is_el.iter(f"{NS}t")) if is_el is not None else ""
                    elif v is None or v.text is None:
                        text = ""
                    elif c.get("t") == "s":
                        idx = int(v.text)
                        text = shared[idx] if idx < len(shared) else ""
                    else:
                        text = v.text
                    cells[_col_index(c.get("r", "A"))] = text
                yield [cells.get(i, "") for i in range(max(cells) + 1)] if cells else []
                el.clear()

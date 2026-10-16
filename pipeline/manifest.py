"""Which raw files the published figures were built from, byte for byte.

`data/raw/manifest.json` records sha256, size and FAO release date of every raw input. `atlas
download` refreshes it; `atlas build` refuses to run if a raw file changed since (someone replaced
a file by hand without recording it), and export copies the hashes into the web data so every
published number can be traced to the exact files.

Also checks that raw files still have the shape the pipeline assumes (columns, units, element
names): FAO renames things between releases, and a silent rename would drop data, not fail.
"""

from __future__ import annotations

import hashlib
import json
import logging
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd

from . import config

log = logging.getLogger(__name__)

MANIFEST = config.RAW / "manifest.json"


def raw_inputs() -> dict[str, Path]:
    """Raw files the published figures depend on, keyed by a stable name."""
    from . import jrc

    f = config.RAW / "faostat"
    return {
        "fao_fbs": f / config.FAOSTAT_FILES["fbs"],
        "fao_tm": f / config.FAOSTAT_FILES["trade_matrix"],
        "fao_catalogue": f / config.FAOSTAT_CATALOGUE,
        "jrc_bal_zip": jrc.ZIP,
        "jrc_bal": jrc.CSV,
        "gisco_countries": config.RAW / "gisco" / "CNTR_RG_20M_2024_4326.geojson",
    }


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def snapshot() -> dict[str, dict]:
    from .export import faostat_release

    out = {}
    for key, path in raw_inputs().items():
        if not path.exists():
            continue
        st = path.stat()
        entry = {"path": str(path.relative_to(config.ROOT)), "sha256": sha256(path),
                 "bytes": st.st_size,
                 "modified": datetime.fromtimestamp(st.st_mtime, UTC).isoformat(timespec="seconds")}
        if key in ("fao_fbs", "fao_tm"):
            entry["released"] = faostat_release(path.name)
        out[key] = entry
    return out


def record() -> dict:
    """Write the manifest for the raw files as they are now."""
    snap = snapshot()
    MANIFEST.write_text(json.dumps({"recorded": datetime.now(UTC).isoformat(timespec="seconds"),
                                    "files": snap}, indent=2) + "\n", encoding="utf-8")
    log.info("recorded %s (%d files)", MANIFEST, len(snap))
    return snap


def load() -> dict[str, dict]:
    if not MANIFEST.exists():
        return {}
    return json.loads(MANIFEST.read_text(encoding="utf-8"))["files"]


class ManifestError(RuntimeError):
    pass


def check() -> dict[str, dict]:
    """Raw files must match the manifest. Without a manifest (first build after this was added),
    record one."""
    recorded = load()
    if not recorded:
        log.warning("no %s: recording the raw files as they are now", MANIFEST.name)
        return record()
    now = snapshot()
    changed = [k for k in now if k in recorded and now[k]["sha256"] != recorded[k]["sha256"]]
    missing = [k for k in recorded if k not in now]
    if changed or missing:
        raise ManifestError(
            f"raw files differ from {MANIFEST.name}: changed {changed}, missing {missing}. "
            "If this is a deliberate new download, run `atlas download` (or `atlas manifest`).")
    return now


# ------------------------------------------------------------------------------------------------
# shape of the raw files

FBS_COLUMNS = {"Area Code (M49)", "Item Code", "Item", "Element", "Year", "Unit", "Value", "Flag"}
FBS_UNITS = {
    "Food supply (kcal/capita/day)": "kcal/cap/d",
    "Protein supply quantity (g/capita/day)": "g/cap/d",
    "Total Population - Both sexes": "1000 No",
}
FBS_DEFAULT_UNIT = "1000 t"
FBS_FLAGS = {"A", "E", "I", "X", "M", "T", "B", "P"}  # FAOSTAT flag codes seen in bulk files


def check_fbs_shape(fbs: pd.DataFrame) -> list[str]:
    """Problems with harmonised FBS rows (`data/interim/fbs.parquet`): every element the pipeline
    uses present, each with the unit the formulas assume, known flags only, no duplicate keys."""
    problems = []
    present = set(fbs["element"].unique())
    for el in config.FBS_ELEMENTS.values():
        if el not in present:
            problems.append(f"element missing from FBS: {el!r}")
    units = fbs.groupby("element")["unit"].unique()
    for el, us in units.items():
        want = FBS_UNITS.get(el, FBS_DEFAULT_UNIT)
        bad = sorted(set(us) - {want})
        if bad:
            problems.append(f"FBS {el!r} has unit {bad}, expected {want!r}")
    flags = set(fbs["flag"].dropna().unique()) - FBS_FLAGS
    if flags:
        problems.append(f"unknown FBS flags: {sorted(flags)}")
    dup = fbs.duplicated(["iso3", "item_code", "element", "year"]).sum()
    if dup:
        problems.append(f"{dup} duplicate FBS rows (iso3, item_code, element, year)")
    return problems


def check_zip_header(path: Path, required: set[str]) -> list[str]:
    """The All_Data CSV in a FAOSTAT zip still has the columns we read."""
    with zipfile.ZipFile(path) as z:
        name = next(n for n in z.namelist() if "All_Data" in n and n.lower().endswith(".csv"))
        with z.open(name) as fh:
            header = fh.readline().decode("latin-1").strip().lstrip("﻿")
    cols = {c.strip('"') for c in header.split(",")}
    missing = required - cols
    return [f"{path.name}: columns missing {sorted(missing)}"] if missing else []

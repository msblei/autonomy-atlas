"""Stream the FAOSTAT Detailed Trade Matrix out of its zip (never unzipped to disk) and cache the
quantity rows (tonnes, 2010+) as Parquet in verify/.cache/. Independent of pipeline/.

Usage: .venv/bin/python -I verify/tm_cache.py
"""
from __future__ import annotations

import hashlib
import sys
import time
import zipfile
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pcsv
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parent.parent
TM_ZIP = ROOT / "data/raw/faostat/Trade_DetailedTradeMatrix_E_All_Data_(Normalized).zip"
CACHE = Path(__file__).resolve().parent / ".cache"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def cache_path(digest: str) -> Path:
    return CACHE / f"tm_qty_{digest[:16]}.parquet"


def build(digest: str | None = None) -> Path:
    digest = digest or sha256(TM_ZIP)
    out = cache_path(digest)
    if out.exists():
        return out
    CACHE.mkdir(exist_ok=True)
    t0 = time.time()
    z = zipfile.ZipFile(TM_ZIP)
    name = next(n for n in z.namelist() if "All_Data" in n)
    cols = ["Reporter Country Code (M49)", "Partner Country Code (M49)", "Item Code",
            "Element", "Year", "Unit", "Value"]
    types = {"Reporter Country Code (M49)": pa.string(), "Partner Country Code (M49)": pa.string(),
             "Item Code": pa.int32(), "Element": pa.string(), "Year": pa.int32(),
             "Unit": pa.string(), "Value": pa.float64()}
    with z.open(name) as fh:
        reader = pcsv.open_csv(
            fh,
            read_options=pcsv.ReadOptions(block_size=64 << 20),
            convert_options=pcsv.ConvertOptions(include_columns=cols, column_types=types),
        )
        tmp = out.with_suffix(".tmp")
        writer = None
        n_in = n_out = 0
        for batch in reader:
            n_in += batch.num_rows
            mask = pc.and_(
                pc.and_(pc.greater_equal(batch["Year"], 2010), pc.equal(batch["Unit"], "t")),
                pc.is_in(batch["Element"], pa.array(["Import quantity", "Export quantity"])),
            )
            b = pa.Table.from_batches([batch]).filter(mask)
            if b.num_rows == 0:
                continue
            strip = lambda a: pc.utf8_lpad(pc.utf8_ltrim(a, "'"), 3, "0")
            b = pa.table({
                "rep": strip(b["Reporter Country Code (M49)"]),
                "par": strip(b["Partner Country Code (M49)"]),
                "item": b["Item Code"],
                "flow": pc.if_else(pc.equal(b["Element"], "Import quantity"), "imports", "exports"),
                "year": b["Year"],
                "t": b["Value"],
            })
            if writer is None:
                writer = pq.ParquetWriter(tmp, b.schema)
            writer.write_table(b)
            n_out += b.num_rows
        writer.close()
        tmp.rename(out)
    print(f"trade matrix: {n_in:,} rows read, {n_out:,} kept, {time.time()-t0:.0f}s", file=sys.stderr)
    return out


if __name__ == "__main__":
    print(build())

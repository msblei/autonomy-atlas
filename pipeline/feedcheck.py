"""The EU's imported feed protein against DG AGRI's own EU feed protein balance sheet
(methodology, "Feed", second opinion). Compared, never substituted, as with USDA.

DG AGRI publishes, per marketing year (July-June) and protein source, the EU's feed use in crude
protein and the part of EU origin; meal crushed from imported beans counts as not of EU origin,
the rule feed.py follows. FAO has no roughage (grass, silage maize, fodder legumes), so the
comparison leaves DG AGRI's roughage out: what is compared is concentrate feed.

Output data/processed/feed_check.parquet: source, dgagri_protein_mt, dgagri_imported_mt,
dgagri_imported_pct, fao_protein_mt, fao_imported_mt, fao_imported_pct (window means).
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from . import config
from .feed import EU_ITEMS

log = logging.getLogger(__name__)

XLSX = config.RAW / "dgagri" / "eu-feed-protein-balance-sheet_en.xlsx"
OUT = config.PROCESSED / "feed_check.parquet"
GAP_PP = 10  # points between the two imported shares of concentrate protein that need a look

# DG AGRI row (first cell, upper case, "(of which)" dropped) -> our FAO SUA items
SOURCES = {
    "CEREALS": {56, 15, 44, 27, 83, 32, 97, 75, 71, 79, 103, 108},  # whole grains (feed_items.csv)
    "SOYA BEAN MEALS": {238},
    "RAPESEED MEALS": {272},
    "SUNFLOWER MEALS": {269},
}
LABELS = {"CEREALS": "Cereals (grain)", "SOYA BEAN MEALS": "Soya bean meal",
          "RAPESEED MEALS": "Rapeseed meal", "SUNFLOWER MEALS": "Sunflower meal",
          "CONCENTRATES": "All concentrate feed (without roughage)"}


def marketing_years(years: tuple[int, int]) -> list[str]:
    """The FBS window's calendar years -> the marketing years starting in them (2021 -> 2021-22)."""
    return [f"{y}-{(y + 1) % 100:02d}" for y in range(years[0], years[1] + 1)]


def read_year(path, sheet: str) -> dict[str, tuple[float, float]]:
    """One marketing year's sheet: {row: (feed use, of EU origin)} in million t of crude protein.
    Columns found by their headers "(H) = …" and "(I) = …", not by position (the share column's
    header, "(J) = (I) / (H)", names both too)."""
    raw = pd.read_excel(path, sheet_name=sheet, header=None)
    head = next(i for i in range(10) if str(raw.iat[i, 0]).strip() == "Protein source")
    cols = {c: j for j, v in enumerate(raw.iloc[head]) for c in ("(H)", "(I)")
            if f"{c} =" in " ".join(str(v).split())}
    if set(cols) != {"(H)", "(I)"}:
        raise ValueError(f"{sheet}: no columns (H) and (I) in the header")
    out = {}
    for _, r in raw.iloc[head + 1:].iterrows():
        name = " ".join(str(r.iat[0]).replace("(of which)", "").split()).upper()
        h, i = pd.to_numeric(r.iat[cols["(H)"]], errors="coerce"), pd.to_numeric(r.iat[cols["(I)"]], errors="coerce")
        if name in (*SOURCES, "ROUGHAGE", "TOTAL") and name not in out and pd.notna(h):
            out[name] = (float(h), float(i))
    missing = {*SOURCES, "ROUGHAGE", "TOTAL"} - set(out)
    if missing:
        raise ValueError(f"{sheet}: rows not found: {sorted(missing)}")
    return out


def dgagri(path, years: tuple[int, int]) -> pd.DataFrame:
    """DG AGRI's window means per source: protein fed and imported (not of EU origin), Mt."""
    sheets = pd.ExcelFile(path).sheet_names
    want = [y for y in marketing_years(years) if y in sheets]
    if not want:
        raise ValueError(f"no sheet for {marketing_years(years)} in {path.name}")
    if len(want) < years[1] - years[0] + 1:
        log.warning("DG AGRI feed protein: only %s of %s", want, marketing_years(years))
    rows = []
    for y in want:
        d = read_year(path, y)
        conc = (d["TOTAL"][0] - d["ROUGHAGE"][0], d["TOTAL"][1] - d["ROUGHAGE"][1])
        for k, (h, i) in {**{k: d[k] for k in SOURCES}, "CONCENTRATES": conc}.items():
            rows.append({"source": k, "year": y, "protein": h, "imported": h - i})
    m = pd.DataFrame(rows).groupby("source")[["protein", "imported"]].mean()
    m.attrs["years"] = want
    return m


def compare(dg: pd.DataFrame, fao_items: pd.DataFrame) -> pd.DataFrame:
    fao = {"CONCENTRATES": fao_items}
    fao.update({k: fao_items[fao_items["item_code"].isin(codes)] for k, codes in SOURCES.items()})
    rows = []
    for k in [*SOURCES, "CONCENTRATES"]:
        p, m = fao[k]["protein_t"].sum() / 1e6, fao[k]["imported_t"].sum() / 1e6
        rows.append({"source": LABELS[k],
                     "dgagri_protein_mt": dg.at[k, "protein"], "dgagri_imported_mt": dg.at[k, "imported"],
                     "dgagri_imported_pct": 100 * dg.at[k, "imported"] / dg.at[k, "protein"],
                     "fao_protein_mt": p, "fao_imported_mt": m,
                     "fao_imported_pct": 100 * m / p if p > 0 else np.nan})
    return pd.DataFrame(rows)


def run() -> None:
    from .trade import fbs_window

    items = config.PROCESSED / EU_ITEMS
    if not XLSX.exists() or not items.exists():
        log.warning("no DG AGRI feed protein balance or no EU feed items: no comparison "
                    "(`atlas download --source dgagri`)")
        OUT.unlink(missing_ok=True)
        return
    years = fbs_window()
    dg = dgagri(XLSX, years)
    out = compare(dg, pd.read_parquet(items))
    out.attrs = {}
    out.assign(years=f"{years[0]}-{years[1]}", dgagri_years=", ".join(dg.attrs["years"])).to_parquet(OUT, index=False)
    c = out.iloc[-1]
    log.info("EU imported concentrate feed protein: FAO %.1f%%, DG AGRI %.1f%% (%s)",
             c["fao_imported_pct"], c["dgagri_imported_pct"], ", ".join(dg.attrs["years"]))

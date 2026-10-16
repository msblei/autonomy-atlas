"""Raw files -> tidy Parquet in data/interim/.

Output schema (long format), one file per source table:
    iso3, item_code, item, element, year, unit, value, flag, source
Country key is ISO3 (joined via M49 codes from mappings/countries.yaml, never via names).
"""

from __future__ import annotations

import logging
import zipfile
from pathlib import Path

import pandas as pd
import yaml

from . import config

log = logging.getLogger(__name__)

# ------------------------------------------------------------------------------------------------
# mappings


def load_countries() -> pd.DataFrame:
    """Every FBS country: the European core (countries.yaml: groups, Eurostat codes, notes) plus
    the rest of the world (world.csv, group "World"). Column `europe` marks the core."""
    rows = yaml.safe_load((config.MAPPINGS / "countries.yaml").read_text(encoding="utf-8"))
    europe = pd.DataFrame(rows)
    europe["m49"] = europe["m49"].astype(str).str.zfill(3)
    europe["europe"] = True
    world = pd.read_csv(config.MAPPINGS / "world.csv", comment="#", dtype=str, encoding="utf-8")
    world["m49"] = world["m49"].str.zfill(3)
    world = world[~world["iso3"].isin(europe["iso3"]) & ~world["m49"].isin(europe["m49"])]
    world["group"] = "World"
    world["europe"] = False
    return pd.concat([europe, world], ignore_index=True)


def load_products() -> dict:
    return yaml.safe_load((config.MAPPINGS / "products.yaml").read_text(encoding="utf-8"))


def item_to_group() -> pd.DataFrame:
    """Long table: item (FBS name) -> group key, group label."""
    rows = []
    for key, g in load_products()["groups"].items():
        for item in g["items"]:
            rows.append({"item": item, "group": key, "group_label": g["label"]})
    return pd.DataFrame(rows)


# ------------------------------------------------------------------------------------------------
# FAOSTAT

_FAO_COLS = {
    "Area Code (M49)": "m49",
    "Item Code": "item_code",
    "Item": "item",
    "Element": "element",
    "Year": "year",
    "Unit": "unit",
    "Value": "value",
    "Flag": "flag",
}


def _clean_m49(s: pd.Series) -> pd.Series:
    # FAOSTAT writes M49 as "'040" in some releases to stop spreadsheets dropping zeros.
    return s.astype(str).str.replace("'", "", regex=False).str.strip().str.zfill(3)


# FAO areas that are not countries: world, continents, M49 regions, the EU and country groups,
# and "China" (159 = mainland 156 + Hong Kong + Macao + Taiwan, each of which we have separately).
FAO_EU27_M49 = "097"
KNOWN_AGGREGATES = {
    "001", "002", "005", "009", "011", "013", "014", "015", "017", "018", "019", "021", "029",
    "030", "034", "035", "039", "053", "054", "057", "061", "097", "142", "143", "145", "150",
    "151", "154", "155", "159", "199", "432", "722", "901", "902",
}


class UnknownAreaError(ValueError):
    pass


def _check_areas(unmapped: set[str], fname: str) -> None:
    """An FAO area we neither map nor know as an aggregate would silently drop a country (FAO
    adds and renames areas between releases)."""
    unknown = sorted(unmapped - KNOWN_AGGREGATES)
    if unknown:
        raise UnknownAreaError(f"{fname}: M49 areas neither in world.csv/countries.yaml nor known "
                               f"aggregates: {unknown}")


def read_faostat_zip(path: Path) -> pd.DataFrame:
    """Read the All_Data CSV inside a FAOSTAT Normalized bulk ZIP, restricted to scope countries."""
    countries = load_countries()
    with zipfile.ZipFile(path) as z:
        names = [n for n in z.namelist() if "All_Data" in n and n.lower().endswith(".csv")]
        if not names:
            raise FileNotFoundError(f"no All_Data CSV in {path.name}: {z.namelist()}")
        with z.open(names[0]) as f:
            df = pd.read_csv(
                f,
                usecols=lambda c: c in _FAO_COLS,
                encoding="latin-1",
                dtype={"Area Code (M49)": str, "Item Code": str, "Year": "Int64"},
                low_memory=False,
            )
    df = df.rename(columns=_FAO_COLS)
    df["m49"] = _clean_m49(df["m49"])
    _check_areas(set(df["m49"]) - set(countries["m49"]), path.name)
    eu = df[df["m49"] == FAO_EU27_M49]
    if len(eu):
        # FAO's own EU27 row: members summed, intra-EU trade included. Kept to cross-check our
        # bloc's production (pipeline/validate.py), never shown.
        eu.assign(iso3="EU27_FAO").drop(columns="m49").to_parquet(
            config.INTERIM / f"{path.stem.split('_E_')[0]}_fao_eu27.parquet", index=False)
    df = df.merge(countries[["m49", "iso3"]], on="m49", how="inner").drop(columns="m49")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["source"] = path.stem.split("_E_")[0]
    cols = ["iso3", "item_code", "item", "element", "year", "unit", "value", "flag", "source"]
    return df[cols]


def harmonise_fbs(*, raw: Path | None = None) -> Path:
    raw = raw or config.RAW / "faostat" / config.FAOSTAT_FILES["fbs"]
    from .manifest import FBS_COLUMNS, check_fbs_shape, check_zip_header

    problems = check_zip_header(raw, FBS_COLUMNS)
    df = read_faostat_zip(raw)
    df = df[df["element"].isin(config.FBS_ELEMENTS.values())]
    problems += check_fbs_shape(df)
    if problems:
        raise ValueError("FBS file is not shaped as the pipeline assumes:\n  " + "\n  ".join(problems))

    # Report mapping gaps so products.yaml can be fixed.
    mapped = set(item_to_group()["item"])
    present = set(df["item"].unique())
    missing_in_file = sorted(mapped - present)
    unmapped = sorted(present - mapped)
    if missing_in_file:
        log.warning("products.yaml names not found in FBS file: %s", missing_in_file)
    if unmapped:
        log.info("FBS items with no group (kept at item level): %s", unmapped)

    out = config.INTERIM / "fbs.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    log.info("wrote %s (%d rows, %d countries, years %s-%s)",
             out, len(df), df["iso3"].nunique(), df["year"].min(), df["year"].max())
    return out


# ------------------------------------------------------------------------------------------------
# Eurostat (phase 3: regional crops)


def read_eurostat_tsv(path: Path) -> pd.DataFrame:
    """Eurostat SDMX TSV: first column holds the dimension keys joined by commas,
    remaining columns are years with values like '123.4 e' (flag after a space)."""
    df = pd.read_csv(path, sep="\t", compression="infer", dtype=str)
    key_col = df.columns[0]
    dims = key_col.split("\\")[0].split(",")
    keys = df[key_col].str.split(",", expand=True)
    keys.columns = dims
    long = pd.concat([keys, df.drop(columns=key_col)], axis=1).melt(
        id_vars=dims, var_name="year", value_name="raw"
    )
    long["year"] = long["year"].str.strip().astype(int)
    parts = long["raw"].str.strip().str.split(" ", n=1, expand=True)
    long["value"] = pd.to_numeric(parts[0].replace(":", pd.NA), errors="coerce")
    long["flag"] = parts[1] if parts.shape[1] > 1 else pd.NA
    return long.drop(columns="raw")


def harmonise_eurostat_regional(*, raw: Path | None = None) -> Path:
    code = config.EUROSTAT_DATASETS["crops_regional"]
    raw = raw or config.RAW / "eurostat" / f"{code}.tsv.gz"
    df = read_eurostat_tsv(raw)
    out = config.INTERIM / f"eurostat_{code}.parquet"
    df.to_parquet(out, index=False)
    log.info("wrote %s (%d rows)", out, len(df))
    return out


# ------------------------------------------------------------------------------------------------


def run() -> None:
    config.ensure_dirs()
    harmonise_fbs()
    regional = config.RAW / "eurostat" / f"{config.EUROSTAT_DATASETS['crops_regional']}.tsv.gz"
    if regional.exists():
        harmonise_eurostat_regional(raw=regional)
    else:
        log.info("no Eurostat regional file yet; skipping (phase 3)")

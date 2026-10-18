"""CEPII BACI: reconciled world trade, for fish outside the EU and a check on FAO's trade matrix.

Methodology, "BACI". Reads BACI_HS17_V202601.zip (kept zipped; one CSV per year, streamed) for the
FBS window and writes

    data/interim/baci_yearly.parquet  iso3 (reporter), partner, group, flow, year, tonnes, primary
                                      (both directions: each BACI flow is one country's exports and
                                      the other's imports)
    data/processed/baci_vs_fao.parquet  the comparison with the trade matrix (audit page)

Fish partners for countries outside the EU go into trade_partners via trade.run
(`fish_partners`); EU members and the EU bloc keep Comext.
"""

from __future__ import annotations

import logging
import zipfile

import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from . import comext, config, crosswalk
from .compute import EU_BLOC

log = logging.getLogger(__name__)

RELEASE = "V202601"
ZIP = config.RAW / "baci" / f"BACI_HS17_{RELEASE}.zip"
YEARLY = "baci_yearly.parquet"
COMPARE = "baci_vs_fao.parquet"
# "Other Asia, nes" is Taiwan in the UN's trade statistics (FAO lists it as Taiwan).
ISO3_FIX = {"S19": "TWN"}


def countries() -> dict[int, str]:
    """BACI country code -> ISO3 of our country lists (world.csv, trade_only.csv)."""
    from .harmonise import load_countries
    from .trade import load_trade_only

    ours = set(load_countries()["iso3"]) | set(load_trade_only()["iso3"])
    with zipfile.ZipFile(ZIP) as z:
        c = pd.read_csv(z.open(f"country_codes_{RELEASE}.csv"), dtype={"country_iso3": str})
    c["iso3"] = c["country_iso3"].replace(ISO3_FIX)
    c = c[c["iso3"].isin(ours)]
    return dict(zip(c["country_code"].astype(int), c["iso3"], strict=True))


def factors(hs: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    """HS 2017 code x year -> group and factor (methodology, "BACI", products)."""
    h = hs[hs["version"] == 2017][["hs", "group", "to_primary"]]
    plain = h[~h["to_primary"].isin(["eumofa", "cn8"])]
    plain = pd.concat([plain.assign(year=y) for y in years], ignore_index=True)
    plain["factor"] = pd.to_numeric(plain["to_primary"].replace("", "1"))
    mixed = h[h["to_primary"].isin(["eumofa", "cn8"])]
    mix = pd.read_parquet(config.INTERIM / comext.MIX) if (config.INTERIM / comext.MIX).exists() \
        else pd.DataFrame(columns=["hs2017", "year", "factor", "tonnes"])
    mix = mix.set_index(["hs2017", "year"])["factor"]
    cf = comext.load_eumofa()
    cf = cf.assign(hs6=cf["cn8"].str[:6])
    rows = []
    for r in mixed.itertuples():
        for y in years:
            f = mix.get((r.hs, y))
            if f is None and r.to_primary == "eumofa":
                m = cf[(cf["hs6"] == r.hs) & (cf["year"] == y)]["cf"]
                f = float(m.median()) if len(m) else None
            rows.append({"hs": r.hs, "group": r.group, "year": y, "factor": f})
    m = pd.DataFrame(rows)
    # neither: the nearest year with a factor, else 1
    for code, sub in m.groupby("hs"):
        have = sub.dropna(subset=["factor"])
        for i in sub.index[sub["factor"].isna()]:
            y = m.at[i, "year"]
            m.at[i, "factor"] = (have.iloc[(have["year"] - y).abs().argsort().iloc[0]]["factor"]
                                 if len(have) else 1.0)
    out = pd.concat([plain[["hs", "group", "year", "factor"]], m], ignore_index=True)
    return out.rename(columns={"hs": "k"})


def read(years: tuple[int, int], fac: pd.DataFrame, codes: dict[int, str]) -> pd.DataFrame:
    """Stream the yearly files, keep food in the groups, both directions per flow."""
    keep = pa.array(sorted(set(fac["k"])))
    parts = []
    with zipfile.ZipFile(ZIP) as z:
        for y in range(years[0], years[1] + 1):
            with z.open(f"BACI_HS17_Y{y}_{RELEASE}.csv") as fh:
                t = pacsv.read_csv(fh, convert_options=pacsv.ConvertOptions(
                    column_types={"k": pa.string(), "i": pa.int64(), "j": pa.int64(),
                                  "v": pa.float64(), "q": pa.float64()}))
            t = t.filter(pc.is_in(t["k"], value_set=keep)).to_pandas()
            parts.append(t)
    d = pd.concat(parts, ignore_index=True).rename(columns={"t": "year"})
    noq = d["q"].isna()
    log.info("baci: %.2f%% of food value has no quantity (left out)",
             100 * d.loc[noq, "v"].sum() / d["v"].sum())
    d = d[~noq]
    d = d.merge(fac, on=["k", "year"], how="inner")
    d["exp"], d["imp"] = d["i"].map(codes), d["j"].map(codes)
    d = d[d["exp"].notna() & d["imp"].notna() & (d["exp"] != d["imp"])]
    d["primary"] = d["q"] * d["factor"]
    g = d.groupby(["exp", "imp", "group", "year"], as_index=False)[["q", "primary"]].sum()
    ex = g.rename(columns={"exp": "iso3", "imp": "partner"}).assign(flow="exports")
    im = g.rename(columns={"imp": "iso3", "exp": "partner"}).assign(flow="imports")
    return pd.concat([ex, im], ignore_index=True).rename(columns={"q": "tonnes"})


def extract(years: tuple[int, int]) -> None:
    dest = config.INTERIM / YEARLY
    if not ZIP.exists():
        log.warning("no BACI; run `atlas download --source baci` (795 MB)")
        dest.unlink(missing_ok=True)
        return
    y = list(range(years[0], years[1] + 1))
    d = read(years, factors(crosswalk.load(), y), countries())
    d.to_parquet(dest, index=False)
    log.info("wrote %s (%d rows; world fish trade %.1f Mt a year, live weight)", dest, len(d),
             d.query("group == 'fish' and flow == 'imports'")["primary"].sum() / len(y) / 1e6)


def fish_partners(yearly: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Fish partners of every country outside the EU, yearly mean over `years`, live weight:
    iso3, group, flow, partner, tonnes, source "baci"."""
    f = yearly[(yearly["group"] == "fish") & yearly["year"].between(*years)
               & ~yearly["iso3"].isin(config.EU27) & (yearly["iso3"] != EU_BLOC)]
    n = years[1] - years[0] + 1
    out = f.groupby(["iso3", "group", "flow", "partner"], as_index=False)["primary"].sum()
    return out.assign(tonnes=out["primary"] / n, source="baci").drop(columns="primary")


def compare_with_fao(yearly: pd.DataFrame, partners: pd.DataFrame, years: tuple[int, int],
                     mirror: set[str]) -> pd.DataFrame:
    """Per country, group (not fish) and flow over `years`: BACI against the flows the partner
    lists use, kt a year: iso3, group, flow, baci_kt, fao_kt, ratio, mirror."""
    n = years[1] - years[0] + 1
    b = yearly[(yearly["group"] != "fish") & yearly["year"].between(*years)]
    b = b.groupby(["iso3", "group", "flow"])["primary"].sum() / n / 1000
    f = partners[partners["flow"].isin(["imports", "exports"]) & (partners["group"] != "fish")
                 & (partners["iso3"] != EU_BLOC)]
    f = f.groupby(["iso3", "group", "flow"])["tonnes"].sum() / 1000
    j = pd.concat([b.rename("baci_kt"), f.rename("fao_kt")], axis=1).fillna(0.0).reset_index()
    j["ratio"] = j["baci_kt"] / j["fao_kt"].where(j["fao_kt"] > 0)
    j["mirror"] = j["iso3"].isin(mirror)
    return j


def run_compare(years: tuple[int, int]) -> None:
    src, tp = config.INTERIM / YEARLY, config.PROCESSED / "trade_partners.parquet"
    dest = config.PROCESSED / COMPARE
    if not (src.exists() and tp.exists()):
        dest.unlink(missing_ok=True)
        return
    p = pd.read_parquet(tp)
    p = p[~p["source"].isin(["comext", "baci", "traced"])]
    mirror = set(p.loc[p["source"].isin(["mirror", "mixed"]), "iso3"])
    j = compare_with_fao(pd.read_parquet(src), p, years, mirror)
    j.assign(years=f"{years[0]}-{years[1]}").to_parquet(dest, index=False)
    log.info("wrote %s (%d country-group-flows; median BACI/FAO %.2f)", dest, len(j), j["ratio"].median())

"""FAOSTAT Detailed Trade Matrix -> who each country buys its food from and sells it to.

Output data/processed/trade_partners.parquet, one row per country × group × flow × partner:
    iso3, group, flow (imports | exports | grown), partner, tonnes,
    source (reported | mirror | traced), years

`tonnes` is the yearly mean over the same window as the FBS figures, in product weight as traded
(a tonne of flour counts as a tonne; mappings/trade_items.csv), except dairy, which is in milk
equivalent (`to_primary`, the EU's factors: a tonne of cheese is 3.58 t of milk, of milk powder
7.57 t). That is fine for "which share comes from where" within one food group.

Flows come from the reporting country. When a country reported nothing for a flow in a year
(Russia, Belarus and others since 2022), its partners' reports are used instead: exports that
others say they sent it become its imports ("mirror" flows), and vice versa. When a country
leaves one food group out of its reports (Australia's sugar exports), partners' reports replace
that group over the window (`fill_underreported`, partner lists only).

The EU27 bloc gets only trade with non-members: what the EU as a whole buys from and sells to the
rest of the world.

flow "grown" traces imports back to where they were grown (`trace_origins`): coffee Germany buys
from the Netherlands mostly counts as Brazilian, Vietnamese, ... coffee.
"""

from __future__ import annotations

import csv
import logging
import zipfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.csv as pacsv

from . import baci, comext, config
from .compute import EU_BLOC
from .harmonise import load_countries

log = logging.getLogger(__name__)

TM_ZIP = config.FAOSTAT_FILES["trade_matrix"]
TM_CSV = "Trade_DetailedTradeMatrix_E_All_Data_(Normalized).csv"
FLOWS = {"Import quantity": "imports", "Export quantity": "exports"}
MIRROR = {"imports": "exports", "exports": "imports"}

_COLS = {
    "Reporter Country Code (M49)": "reporter",
    "Partner Country Code (M49)": "partner",
    "Item Code": "item_code",
    "Element": "element",
    "Year": "year",
    "Unit": "unit",
    "Value": "value",
}


def load_item_groups() -> dict[int, str]:
    """Trade item code -> products.yaml group, for the items that belong to a group."""
    path = config.MAPPINGS / "trade_items.csv"
    with path.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {int(r["item_code"]): r["group"] for r in rows if r["group"]}


ITEM_KEY = "item:"  # extra-EU share keys per FBS item ("item:Bananas"), next to the group keys


def load_item_fbs() -> dict[int, str]:
    """Trade item code -> FBS item (`fbs_item`, fruit and meat only), for the EU bloc's per-item
    extra-EU shares."""
    path = config.MAPPINGS / "trade_items.csv"
    with path.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {int(r["item_code"]): r["fbs_item"] for r in rows if r.get("fbs_item")}


def load_item_factors() -> dict[int, float]:
    """Trade item code -> kg of primary product per kg traded (`to_primary`; dairy in milk
    equivalent). Items without a factor count as traded."""
    path = config.MAPPINGS / "trade_items.csv"
    with path.open(encoding="utf-8") as f:
        rows = csv.DictReader(line for line in f if not line.startswith("#"))
        return {int(r["item_code"]): float(r["to_primary"]) for r in rows if r.get("to_primary")}


def read_matrix(years: tuple[int, int], items: dict[int, str],
                factors: dict[int, float] | None = None) -> pd.DataFrame:
    """Stream the 8.5 GB CSV out of the zip, keeping food quantities in tonnes for `years`."""
    path = config.RAW / "faostat" / TM_ZIP
    codes = pa.array(sorted(items), pa.int64())
    elements = pa.array(list(FLOWS))
    y0, y1 = years
    parts = []
    with zipfile.ZipFile(path) as zf, zf.open(TM_CSV) as fh:
        reader = pacsv.open_csv(
            fh,
            read_options=pacsv.ReadOptions(block_size=64 << 20),
            convert_options=pacsv.ConvertOptions(
                include_columns=list(_COLS),
                column_types={"Reporter Country Code (M49)": pa.string(),
                              "Partner Country Code (M49)": pa.string(),
                              "Item Code": pa.int64(), "Year": pa.int64(), "Value": pa.float64()},
            ),
        )
        for batch in reader:
            mask = pc.and_(
                pc.and_(pc.greater_equal(batch["Year"], y0), pc.less_equal(batch["Year"], y1)),
                pc.and_(pc.is_in(batch["Item Code"], value_set=codes),
                        pc.and_(pc.is_in(batch["Element"], value_set=elements),
                                pc.equal(batch["Unit"], "t"))),
            )
            kept = batch.filter(mask)
            if kept.num_rows:
                parts.append(kept.to_pandas())
    df = pd.concat(parts, ignore_index=True).rename(columns=_COLS)
    for c in ("reporter", "partner"):
        df[c] = df[c].str.lstrip("'").str.zfill(3)
    df["group"] = df["item_code"].map(items)
    df["flow"] = df["element"].map(FLOWS)
    # "value": tonnes as traded; "primary": in the FBS basis where the mapping converts (dairy in
    # milk equivalent). Partner lists use "primary", the EU-bloc shares behind the balances "value".
    df["primary"] = df["value"] * df["item_code"].map(factors or {}).fillna(1.0)
    log.info("trade matrix: %d food rows for %d-%d", len(df), y0, y1)
    return df


def load_trade_only() -> pd.DataFrame:
    """Trade partners without a Food Balance Sheet (Japan, Singapore, ...): m49, iso3, name."""
    return pd.read_csv(config.MAPPINGS / "trade_only.csv", comment="#", dtype=str,
                       encoding="utf-8").assign(m49=lambda d: d["m49"].str.zfill(3))


def to_iso3(df: pd.DataFrame) -> pd.DataFrame:
    """M49 -> ISO3 for reporter and partner; rows with an unknown area on either side go
    (regions, historical countries)."""
    m49 = pd.concat([load_countries()[["m49", "iso3"]], load_trade_only()[["m49", "iso3"]]])
    m49 = m49.set_index("m49")["iso3"]
    df = df.assign(reporter=df["reporter"].map(m49), partner=df["partner"].map(m49))
    lost = df["reporter"].isna() | df["partner"].isna()
    if lost.any():
        log.info("trade: %.1f%% of tonnes involve areas outside our country list (dropped)",
                 100 * df.loc[lost, "value"].sum() / df["value"].sum())
    return df[~lost & (df["reporter"] != df["partner"])]


def yearly(df: pd.DataFrame) -> pd.DataFrame:
    """Flows per reporter × partner × group × flow × year: the reporter's own figures, plus mirror
    flows (partners' reports of the opposite flow) where it reported nothing for a flow and year.
    Columns: reporter, partner, group, flow, year, value, primary, source."""
    keys = ["reporter", "partner", "group", "flow", "year"]
    rep = _with_primary(df).groupby(keys, as_index=False)[["value", "primary"]].sum()
    reported = set(rep[["reporter", "flow", "year"]].itertuples(index=False, name=None))

    mirror = rep.rename(columns={"reporter": "partner", "partner": "reporter"})
    mirror["flow"] = mirror["flow"].map(MIRROR)
    gap = [(r, f, y) not in reported for r, f, y in
           mirror[["reporter", "flow", "year"]].itertuples(index=False, name=None)]
    mirror = mirror[gap]
    if len(mirror):
        log.info("trade: mirror flows for %d country-years without own reports",
                 mirror[["reporter", "flow", "year"]].drop_duplicates().shape[0])
    return pd.concat([rep.assign(source="reported"), mirror.assign(source="mirror")],
                     ignore_index=True)


UNDER_FACTOR = 3.0  # partners report more than this times what we would otherwise use ...
UNDER_MIN_T = 20_000  # ... and at least this many tonnes a year ...
UNDER_MAX_BALANCE = 1.5  # ... and no more than this times the country's FBS flow (if it has one)


def fill_underreported(both: pd.DataFrame, years: tuple[int, int],
                       groups: pd.DataFrame | None = None) -> pd.DataFrame:
    """Food groups a country leaves out of its own reports (Australia's sugar exports): over the
    window, when partners report more than UNDER_FACTOR times the flows `yearly` keeps for a
    country × group × flow, at least UNDER_MIN_T a year, and no more than UNDER_MAX_BALANCE times
    the country's FBS flow (`groups`: ssr_groups on the tonnes basis; no limit without a
    balance), their reports of the opposite flow replace them (source "mirror"). The balance
    limit keeps trading hubs (UAE, Switzerland) on their own reports. For the partner lists
    only: the EU-bloc shares keep the per-year rule (methodology, "Trade partners",
    "Under-reported food groups")."""
    both = _with_primary(both[both["year"].between(*years)])
    keys = ["reporter", "group", "flow"]
    rep = both[both["source"] == "reported"]
    mirror = rep.rename(columns={"reporter": "partner", "partner": "reporter"})
    mirror = mirror.assign(flow=mirror["flow"].map(MIRROR), source="mirror")
    used = both.groupby(keys)["primary"].sum()
    theirs = mirror.groupby(keys)["primary"].sum()
    n_years = years[1] - years[0] + 1
    j = pd.concat([used.rename("used"), theirs.rename("theirs")], axis=1).fillna(0.0)
    if groups is not None:
        g = groups[groups["basis"] == "tonnes"].melt(id_vars=["iso3", "group"], value_vars=["imports", "exports"],
                                                     var_name="flow", value_name="balance_kt")
        bal = g.rename(columns={"iso3": "reporter"}).set_index(keys)["balance_kt"]
        j = j.join(bal, how="left")
    else:
        j["balance_kt"] = float("nan")
    fits = j["balance_kt"].isna() | (j["theirs"] / n_years / 1000 <= UNDER_MAX_BALANCE * j["balance_kt"])
    swap = j[(j["theirs"] > UNDER_FACTOR * j["used"]) & (j["theirs"] >= UNDER_MIN_T * n_years) & fits].index
    if not len(swap):
        return both
    log.info("trade: partners' reports replace %d under-reported country-group-flows (%s)", len(swap),
             ", ".join(f"{r} {g} {f}" for r, g, f in swap[:8]))
    hit = both.set_index(keys).index.isin(swap)
    take = mirror.set_index(keys).index.isin(swap)
    return pd.concat([both[~hit], mirror[take]], ignore_index=True)


def _with_primary(df: pd.DataFrame) -> pd.DataFrame:
    """No `primary` column (no conversion factors applied): primary = as traded."""
    return df if "primary" in df else df.assign(primary=df["value"])


def _source_label(s: pd.Series) -> str:
    """reported / mirror when every year agrees, mixed when some years are partners' reports."""
    kinds = set(s)
    return kinds.pop() if len(kinds) == 1 else "mixed"


def average(both: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Yearly flows -> yearly mean over `years` per country × group × flow × partner."""
    both = _with_primary(both[both["year"].between(*years)])
    n_years = years[1] - years[0] + 1
    out = (both.groupby(["reporter", "group", "flow", "partner"], as_index=False)
           .agg(tonnes=("primary", "sum"), source=("source", _source_label)))
    out["tonnes"] /= n_years
    return out.rename(columns={"reporter": "iso3"})


def partners(df: pd.DataFrame, years: tuple[int, int]) -> pd.DataFrame:
    """Raw trade rows -> mean flows per partner over `years`, mirror flows filling gaps."""
    return average(yearly(df), years)


def extra_eu_shares(both: pd.DataFrame) -> pd.DataFrame:
    """For each EU member, food group and year: the share of its imports that come from, and of
    its exports that go to, countries outside the EU. Group "all" covers every food (fallback for
    FBS items outside the groups). Columns: iso3, group, flow, year, share."""
    m = both[both["reporter"].isin(config.EU27)]
    m = pd.concat([m, m.assign(group="all")], ignore_index=True)
    m = m.assign(extra=m["value"].where(~m["partner"].isin(config.EU27), 0.0))
    g = m.groupby(["reporter", "group", "flow", "year"], as_index=False)[["extra", "value"]].sum()
    g = g[g["value"] > 0]
    g["share"] = g["extra"] / g["value"]
    return g.rename(columns={"reporter": "iso3"})[["iso3", "group", "flow", "year", "share"]]

def add_eu_bloc(p: pd.DataFrame) -> pd.DataFrame:
    """EU27 = members' trade with non-members, summed (intra-EU trade is not EU trade)."""
    eu = p[p["iso3"].isin(config.EU27) & ~p["partner"].isin(config.EU27)]
    bloc = (eu.groupby(["group", "flow", "partner"], as_index=False)["tonnes"].sum()
            .assign(iso3=EU_BLOC, source="reported"))
    return pd.concat([p, bloc], ignore_index=True)


def trace_origins(p: pd.DataFrame, fbs: pd.DataFrame) -> pd.DataFrame:
    """Where the food each country buys abroad was grown, as rows (iso3, group, partner = country
    of origin, tonnes), flow "grown".

    Proportional re-export allocation (Kastner et al. 2011): every country sells on an even mix of
    what it has, its own production plus its imports. For one food group, with Z[i, j] the flow
    i -> j and x the amount each country has, A = Z / x (row-wise) and C = diag(P) (I - A)^-1 gives
    C[k, i], how much of country k's production ends up in country i. The origin of j's imports is
    then sum_i C[k, i] / x[i] * Z[i, j].

    Units: bilateral splits come from the trade matrix (product weight), scaled to each importer's
    FBS import total so production and trade are both in FBS primary equivalents. Countries without
    a food balance (Japan, Singapore) keep their trade-matrix totals and count as producing nothing.

    `fbs`: tonnes-basis rows of ssr_groups (iso3, group, production, imports in 1000 t).
    """
    # Fish partners exist for EU members only: tracing needs the whole world's trade.
    imp = p[(p["flow"] == "imports") & (p["iso3"] != EU_BLOC) & (p["group"] != "fish")]
    fbs = fbs.set_index(["group", "iso3"])
    rows = []
    for group, sub in imp.groupby("group"):
        f = fbs.loc[group] if group in fbs.index.get_level_values(0) else pd.DataFrame()
        names = sorted(set(sub["iso3"]) | set(sub["partner"]) | set(f.index))
        idx = {c: i for i, c in enumerate(names)}
        n = len(names)
        z = np.zeros((n, n))
        for j, r in sub.groupby("iso3"):
            if r["tonnes"].sum() <= 0:
                continue
            fbs_m = f["imports"].get(j) if len(f) else None
            total = fbs_m * 1000 if fbs_m is not None and pd.notna(fbs_m) else r["tonnes"].sum()
            z[r["partner"].map(idx).to_numpy(), idx[j]] = total * r["tonnes"].to_numpy() / r["tonnes"].sum()
        prod = np.zeros(n)
        if len(f):
            have = f["production"].fillna(0) * 1000
            prod[[idx[c] for c in have.index]] = have.to_numpy()
        # A country cannot sell more than it has; trade records and balances do not always agree.
        avail = np.maximum(prod + z.sum(axis=0), z.sum(axis=1))
        safe = np.where(avail > 0, avail, 1.0)
        a = z / safe[:, None]
        c = prod[:, None] * np.linalg.inv(np.eye(n) - a)  # c[k, i]: k's production available in i
        share = c / safe[None, :]  # share[k, i]: part of what i has that k grew
        origin = share @ z  # origin[k, j]: k's production in j's imports
        eu = np.array([x in config.EU27 for x in names])
        # The EU as a whole: its members' imports from non-members, traced back, non-EU origins.
        eu_origin = share[:, ~eu] @ z[~eu][:, eu].sum(axis=1)
        for j_name, j in idx.items():
            col = origin[:, j]
            for k in np.nonzero(col > 1e-6)[0]:
                if k != j:
                    rows.append((j_name, group, names[k], col[k]))
        for k in np.nonzero((eu_origin > 1e-6) & ~eu)[0]:
            rows.append((EU_BLOC, group, names[k], eu_origin[k]))
    out = pd.DataFrame(rows, columns=["iso3", "group", "partner", "tonnes"])
    return out.assign(flow="grown", source="traced")


def fbs_window() -> tuple[int, int]:
    """The window of the processed FBS figures, so trade and balances cover the same years."""
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet", columns=["years"])
    y0, y1 = (int(y) for y in groups["years"].iloc[0].split("-"))
    return y0, y1


YEARLY = "trade_yearly.parquet"
FEED_GROUP = "_feed"  # feed items read with the food, not part of any food group
SHARES = "eu_extra_shares.parquet"


def trade_inputs() -> list:
    """Files the interim trade tables are built from."""
    m = config.MAPPINGS
    return [config.RAW / "faostat" / TM_ZIP, config.INTERIM / "fbs.parquet", m / "trade_items.csv",
            m / "trade_only.csv", m / "world.csv", m / "countries.yaml",
            config.INTERIM / comext.YEARLY]


def extract() -> None:
    """Read the trade matrix once for every FBS year: yearly food flows (data/interim) and the
    members' extra-EU shares that compute.py uses for the EU bloc. Runs before compute."""
    if not (config.RAW / "faostat" / TM_ZIP).exists():
        log.warning("no trade matrix; run `atlas download --source faostat` (420 MB)")
        # Outputs from an earlier download would no longer match the balances: do not keep them.
        for name in (YEARLY, SHARES):
            (config.INTERIM / name).unlink(missing_ok=True)
        return
    fbs_years = pd.read_parquet(config.INTERIM / "fbs.parquet", columns=["year"])["year"]
    years = (int(fbs_years.min()), int(fbs_years.max()))
    from . import feed

    groups = load_item_groups()
    # Feed items (cakes, brans, grain) ride along in the same pass, for the EU's feed adjustment.
    extra = {c: FEED_GROUP for c in feed.load_items() if c not in groups}
    raw = to_iso3(read_matrix(years, {**groups, **extra}, load_item_factors()))
    feed.eu_extra_shares(raw).to_parquet(config.INTERIM / feed.EU_EXTRA, index=False)
    both = yearly(raw[raw["group"] != FEED_GROUP])
    both.to_parquet(config.INTERIM / YEARLY, index=False)
    shares = extra_eu_shares(both)
    # Per FBS item where the mapping has one (fruit, meat): a group's share does not fit all its
    # items (bananas come from outside the EU far more than apples). Members' own reports only.
    fbs_item = load_item_fbs()
    own = raw[raw["item_code"].isin(fbs_item) & raw["reporter"].isin(config.EU27)]
    own = own.assign(group=ITEM_KEY + own["item_code"].map(fbs_item))
    per_item = extra_eu_shares(own.groupby(["reporter", "partner", "group", "flow", "year"], as_index=False)["value"].sum())
    shares = pd.concat([shares, per_item[per_item["group"] != "all"]], ignore_index=True)
    # Fish is not in the trade matrix: its extra-EU shares come from Comext (live weight).
    cx = config.INTERIM / comext.YEARLY
    if cx.exists():
        shares = pd.concat([shares, comext.fish_extra_shares(pd.read_parquet(cx))], ignore_index=True)
    shares.to_parquet(config.INTERIM / SHARES, index=False)
    log.info("wrote %s (%d rows) and %s (%d rows)", YEARLY, len(both), SHARES, len(shares))


def run() -> None:
    src = config.INTERIM / YEARLY
    if not src.exists():
        log.warning("no %s; run `atlas build` with the trade matrix downloaded", src)
        (config.PROCESSED / "trade_partners.parquet").unlink(missing_ok=True)
        return
    config.require_fresh(src, trade_inputs())
    years = fbs_window()
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet")
    p = average(fill_underreported(pd.read_parquet(src), years, groups), years)
    cx = config.INTERIM / comext.YEARLY
    if cx.exists():  # EU members' fish partners (the trade matrix has no fish)
        p = pd.concat([p, comext.fish_partners(pd.read_parquet(cx), years)], ignore_index=True)
    bx = config.INTERIM / baci.YEARLY
    if bx.exists():  # everyone else's fish partners
        p = pd.concat([p, baci.fish_partners(pd.read_parquet(bx), years)], ignore_index=True)
    p = add_eu_bloc(p)
    groups = groups[groups["basis"] == "tonnes"][["iso3", "group", "production", "imports"]]
    out = pd.concat([p, trace_origins(p, groups)], ignore_index=True)
    out = out.assign(years=f"{years[0]}-{years[1]}")
    dest = config.PROCESSED / "trade_partners.parquet"
    out.to_parquet(dest, index=False)
    log.info("wrote %s (%d rows)", dest, len(out))

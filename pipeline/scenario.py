"""Scenarios: what a country would lack if a group of countries stopped selling (methodology,
"Scenarios"). The groups are in mappings/scenarios.yaml (Russia and Ukraine, South America, ...).

Per country and food: imports × the share grown in the group (bought from it for fish)
÷ (production + imports), in %: the share of its use, what it has being an even mix; all food
weighted by calories per person.

Output data/processed/scenario.parquet: scenario, iso3, group, lack; web/public/data/scenario.json.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from . import checks, config
from .compute import EU_BLOC

log = logging.getLogger(__name__)

ALL_MIN_KCAL = 0.9  # "all food" needs figures for foods carrying 90% of the groups' calories
OUT = "scenario.parquet"


def load_scenarios() -> dict:
    import yaml

    return yaml.safe_load((config.MAPPINGS / "scenarios.yaml").read_text(encoding="utf-8"))["scenarios"]


def resolve(sellers, partners: pd.DataFrame) -> set:
    """A scenario's `sellers`: a list of ISO3 codes, or a rule (scenarios.yaml)."""
    if sellers == "eu27":
        return set(config.EU27)
    if sellers == "outside_europe":
        from .harmonise import load_countries

        europe = set(load_countries().query("europe")["iso3"])
        return set(partners["partner"].dropna()) - europe
    return set(sellers)


def _prepare(partners: pd.DataFrame, groups: pd.DataFrame, items: pd.DataFrame, products: dict) -> dict:
    """What every seller's figures share: the balances, the traced origins, the weights."""
    g = groups[groups["basis"] == "tonnes"].set_index(["iso3", "group"])
    v = checks.trade_verdicts(partners, groups)
    held = set(zip(v.loc[(v["verdict"] == "withhold") & (v["flow"] == "imports"), "iso3"],
                   v.loc[(v["verdict"] == "withhold") & (v["flow"] == "imports"), "group"], strict=True))
    flow = np.where(partners["group"] == "fish", "imports", "grown")
    p = partners[partners["flow"] == flow]
    tot = p.groupby(["iso3", "group"])["tonnes"].sum()
    by_origin = p.groupby(["partner", "iso3", "group"])["tonnes"].sum()
    item_group = {i: k for k, v in products["groups"].items() for i in v["items"]}
    it = items.assign(group=items["item"].map(item_group)).dropna(subset=["group"])
    kcal = it[it["kcal"] > 0].groupby(["iso3", "group"])["kcal"].sum()
    return {"g": g, "held": held, "tot": tot, "by_origin": by_origin, "kcal": kcal,
            "origins": sorted(set(p["partner"].dropna()))}


def _lack(ctx: dict, sellers: set) -> pd.DataFrame:
    g, held, tot = ctx["g"], ctx["held"], ctx["tot"]
    bo = ctx["by_origin"]
    sel = bo[bo.index.get_level_values("partner").isin(sellers)]
    ru = sel.groupby(level=["iso3", "group"]).sum()
    share = (ru.reindex(tot.index).fillna(0.0) / tot).where(tot > 0)
    # the EU as one is a seller when all its members are
    bloc_sells = set(config.EU27) <= sellers
    rows = []
    for (iso3, group), r in g.iterrows():
        if iso3 in sellers or (iso3 == EU_BLOC and bloc_sells) or group == "all" \
                or str(r.get("flag") or "") != "" or (iso3, group) in held:
            continue
        m, d = r["imports"], r["supply"]
        prod = 0.0 if pd.isna(r["production"]) else max(float(r["production"]), 0.0)
        if pd.isna(d) or d <= 0:
            continue
        if pd.isna(m) or m <= 0:
            lack = 0.0
        else:
            s = share.get((iso3, group))
            if s is None or pd.isna(s):
                continue
            # what it has is an even mix: its use has the same share as production + imports
            lack = 100 * m * s / (prod + m)
        rows.append({"iso3": iso3, "group": group, "lack": lack})
    out = pd.DataFrame(rows, columns=["iso3", "group", "lack"])
    if out.empty:
        return out
    # all food: weighted by calories per person (FBS items in the groups), as the headline
    kcal = ctx["kcal"]
    w = out.assign(p=[kcal.get((i, gr), np.nan) for i, gr in zip(out["iso3"], out["group"], strict=True)])
    w = w[w["p"] > 0]
    allf = (w.assign(x=w["lack"] * w["p"]).groupby("iso3")[["x", "p"]].sum())
    # Only where the foods with a figure carry most of the calories: without Turkey's withheld
    # cereals its "all food" fell from 17% to 3%, the foods it buys most from Russia left out.
    total = kcal.groupby(level="iso3").sum()
    allf = allf[allf["p"] >= ALL_MIN_KCAL * total.reindex(allf.index)]
    allf = (allf["x"] / allf["p"]).rename("lack").reset_index().assign(group="all")
    return pd.concat([out, allf], ignore_index=True)


def compute(partners: pd.DataFrame, groups: pd.DataFrame, items: pd.DataFrame, products: dict,
            sellers=("RUS", "UKR")) -> pd.DataFrame:
    return _lack(_prepare(partners, groups, items, products), resolve(list(sellers), partners))


SELLERS = "scenario_sellers.parquet"  # every country as a scenario of its own
MIN_LACK = 0.05  # per-seller files keep figures from this on; below it, "covered" means 0


def run() -> None:
    from .harmonise import load_products
    from .trade import fbs_window

    src = config.PROCESSED / "trade_partners.parquet"
    dest = config.PROCESSED / OUT
    if not src.exists():
        dest.unlink(missing_ok=True)
        return
    groups = pd.read_parquet(config.PROCESSED / "ssr_groups.parquet")
    items = pd.read_parquet(config.PROCESSED / "ssr_items.parquet")
    if "basis" in items:
        items = items[items["basis"] == "tonnes"]
    partners, products = pd.read_parquet(src), load_products()
    ctx = _prepare(partners, groups, items, products)
    out = pd.concat([_lack(ctx, resolve(sc["sellers"], partners)).assign(scenario=key)
                     for key, sc in load_scenarios().items()], ignore_index=True)
    y0, y1 = fbs_window()
    out.assign(years=f"{y0}-{y1}").to_parquet(dest, index=False)
    # one scenario per seller; "cover" (no seller at all) says where a figure exists
    per = [_lack(ctx, set()).assign(seller="")]
    for c in ctx["origins"]:
        d = _lack(ctx, {c})
        per.append(d[d["lack"] >= MIN_LACK].assign(seller=c))
    pd.concat(per, ignore_index=True).to_parquet(config.PROCESSED / SELLERS, index=False)
    log.info("wrote %s (%d scenarios) and %s (%d sellers)", dest, out["scenario"].nunique(), SELLERS,
             len(ctx["origins"]))


SELLER_DIR = "whatif"  # web/public/data/whatif/<ISO3>.json, fetched when that scenario is chosen


def export() -> None:
    src, dest = config.PROCESSED / OUT, config.WEB_DATA / "scenario.json"
    out_dir = config.WEB_DATA / SELLER_DIR
    if not src.exists():
        dest.unlink(missing_ok=True)
        return
    s = pd.read_parquet(src)
    scen = load_scenarios()
    by: dict = {k: {} for k in scen}
    for r in s.itertuples():
        if r.lack >= MIN_LACK:  # below: 0 where "cover" has the food (as for single sellers)
            by[r.scenario].setdefault(r.iso3, {})[r.group] = round(float(r.lack), 1)
    # every country as a seller: one file each, figures from MIN_LACK on; "cover" lists where a
    # figure exists at all (0 where a country is covered but missing from a seller's file)
    per = pd.read_parquet(config.PROCESSED / SELLERS)
    cover: dict = {}
    for r in per[per["seller"] == ""].itertuples():
        cover.setdefault(r.iso3, []).append(r.group)
    out_dir.mkdir(parents=True, exist_ok=True)
    for f in out_dir.glob("*.json"):
        f.unlink()
    sellers = []
    for c, d in per[per["seller"] != ""].groupby("seller"):
        figs: dict = {}
        for r in d.itertuples():
            figs.setdefault(r.iso3, {})[r.group] = round(float(r.lack), 1)
        (out_dir / f"{c}.json").write_text(json.dumps(figs, separators=(",", ":")), encoding="utf-8")
        sellers.append(c)
    out = {"meta": {"years": s["years"].iloc[0],
                    "basis": "% of domestic supply (tonnes; all food: calorie-weighted) grown in the "
                             "sellers (bought from them for fish); nothing replaces it",
                    "eu_bloc": EU_BLOC, "eu27": list(config.EU27), "min_lack": MIN_LACK,
                    # sellers: ISO3 codes, or the rule ("eu27", "outside_europe") as in scenarios.yaml
                    "scenarios": [{"key": k, "label": v["label"], "food": v.get("food", "all"), "sellers": v["sellers"]}
                                  for k, v in scen.items()],
                    "sellers": sellers, "cover": cover},
           "scenarios": by}
    dest.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    size = sum(f.stat().st_size for f in out_dir.glob("*.json"))
    log.info("wrote %s (%.0f KB) and %d seller files (%.0f KB)", dest, dest.stat().st_size / 1024,
             len(sellers), size / 1024)

"""Scenario: what a country would lack without Russia and Ukraine (methodology, "Scenario").

Per country and food: imports × the share grown in Russia or Ukraine (bought from them for fish)
÷ (production + imports), in %: the share of its use, what it has being an even mix; all food
weighted by calories per person.

Output data/processed/scenario.parquet: iso3, group, lack; web/public/data/scenario.json.
"""

from __future__ import annotations

import json
import logging

import numpy as np
import pandas as pd

from . import checks, config
from .compute import EU_BLOC

log = logging.getLogger(__name__)

PARTNERS = ("RUS", "UKR")
ALL_MIN_KCAL = 0.9  # "all food" needs figures for foods carrying 90% of the groups' calories
OUT = "scenario.parquet"


def compute(partners: pd.DataFrame, groups: pd.DataFrame, items: pd.DataFrame, products: dict) -> pd.DataFrame:
    g = groups[groups["basis"] == "tonnes"].set_index(["iso3", "group"])
    v = checks.trade_verdicts(partners, groups)
    held = set(zip(v.loc[(v["verdict"] == "withhold") & (v["flow"] == "imports"), "iso3"],
                   v.loc[(v["verdict"] == "withhold") & (v["flow"] == "imports"), "group"], strict=True))
    flow = np.where(partners["group"] == "fish", "imports", "grown")
    p = partners[partners["flow"] == flow]
    tot = p.groupby(["iso3", "group"])["tonnes"].sum()
    ru = p[p["partner"].isin(PARTNERS)].groupby(["iso3", "group"])["tonnes"].sum()
    share = (ru.reindex(tot.index).fillna(0.0) / tot).where(tot > 0)
    rows = []
    for (iso3, group), r in g.iterrows():
        if iso3 in PARTNERS or group == "all" or str(r.get("flag") or "") != "" or (iso3, group) in held:
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
    item_group = {i: k for k, v in products["groups"].items() for i in v["items"]}
    it = items.assign(group=items["item"].map(item_group)).dropna(subset=["group"])
    kcal = it[it["kcal"] > 0].groupby(["iso3", "group"])["kcal"].sum()
    w = out.assign(p=[kcal.get((i, gr), np.nan) for i, gr in zip(out["iso3"], out["group"], strict=True)])
    w = w[w["p"] > 0]
    allf = (w.assign(x=w["lack"] * w["p"]).groupby("iso3")[["x", "p"]].sum())
    # Only where the foods with a figure carry most of the calories: without Turkey's withheld
    # cereals its "all food" fell from 17% to 3%, the foods it buys most from Russia left out.
    total = kcal.groupby(level="iso3").sum()
    allf = allf[allf["p"] >= ALL_MIN_KCAL * total.reindex(allf.index)]
    allf = (allf["x"] / allf["p"]).rename("lack").reset_index().assign(group="all")
    return pd.concat([out, allf], ignore_index=True)


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
    out = compute(pd.read_parquet(src), groups, items, load_products())
    y0, y1 = fbs_window()
    out.assign(years=f"{y0}-{y1}").to_parquet(dest, index=False)
    log.info("wrote %s (%d countries)", dest, out["iso3"].nunique())


def export() -> None:
    src, dest = config.PROCESSED / OUT, config.WEB_DATA / "scenario.json"
    if not src.exists():
        dest.unlink(missing_ok=True)
        return
    s = pd.read_parquet(src)
    countries: dict = {}
    for r in s.itertuples():
        countries.setdefault(r.iso3, {})[r.group] = round(float(r.lack), 1)
    out = {"meta": {"partners": list(PARTNERS), "years": s["years"].iloc[0],
                    "basis": "% of domestic supply (tonnes; all food: calorie-weighted) grown in Russia or "
                             "Ukraine (bought from them for fish); nothing replaces it",
                    "eu_bloc": EU_BLOC},
           "countries": countries}
    dest.write_text(json.dumps(out, separators=(",", ":")), encoding="utf-8")
    log.info("wrote %s (%.0f KB)", dest, dest.stat().st_size / 1024)

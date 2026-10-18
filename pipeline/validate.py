"""Invariant checks on everything the site publishes. `atlas validate` runs them after export.

Each check yields findings with a severity:

    block     the release must not go out (a bug in our pipeline, or inputs that do not fit it)
    withhold  one figure is not shown (already applied in the export, listed here for the record)
    warn      shown, but worth a human look before release (listed in the audit report)
    handled   a warning the site deals with by itself (see `resolve`)
    confirmed a warning a review found right (mappings/confirmed_findings.csv)

Findings go to data/processed/validation.parquet and web/public/data/validation.json, which also
records the sha256 of every published data file: the web build (web/scripts/check-data.mjs)
refuses to ship data files that differ from the ones validated here, or any `block` finding.
See docs/methodology.md, "Checks".
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
from dataclasses import asdict, dataclass
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from . import checks, config, jrc
from .compute import EU_BLOC, to_wide
from .harmonise import load_products

log = logging.getLogger(__name__)

BLOCK, WITHHOLD, WARN = "block", "withhold", "warn"
# A warning the site already deals with (handled), or that a review found right (confirmed): listed
# on the audit page for the record, not as an open question.
HANDLED, CONFIRMED = "handled", "confirmed"
PUBLISHED = ["ssr.json", "items.json", "trade.json", "countries.geojson"]

# Tolerances. Exported figures are rounded to 0.1, so sums of rounded parts drift a little.
KT_TOL = 0.5  # kt, for identities between exported components
FAO_ROUNDING_KT = 2.5  # P, M, X, dS and D each rounded to 1 kt by FAO: at most 5 x 0.5 kt per item
REL_TOL = 0.005  # 0.5%, for identities between processed (unrounded) figures
KCAL_RANGE = (1400, 4200)  # kcal/person/day: below or above is not a national average
PROTEIN_RANGE = (25, 160)  # g/person/day
SSR_REVIEW = 1000  # % above which a figure is real but extreme enough to look at
NEG_ITEMS_SHARE = 0.05  # items with negative supply above this share of a group's |supply|
JRC_TOL_PP = 2.0  # percentage points between our JRC-based SSR and the JRC's own
FAO_EU27_TOL = 0.005  # our EU27 production vs FAO's own EU27 row


@dataclass
class Finding:
    check: str
    severity: str
    detail: str
    iso3: str | None = None
    group: str | None = None
    value: float | None = None


def _f(x) -> float | None:
    try:
        x = float(x)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(x) else round(x, 3)


# ------------------------------------------------------------------------------------------------
# processed tables


def check_balance_identity(groups: pd.DataFrame, items: pd.DataFrame) -> list[Finding]:
    """D = P + M - X - dS. FAO rounds each of the five figures of every item to 1 kt, so a group
    of n items as FAO publishes it may miss by up to n x 2.5 kt from rounding alone: beyond that
    is a warning. Rows we build (JRC-replaced items, the EU27 bloc) must satisfy it exactly. Rows
    without trade figures (EU27 fish: FAO's trade records have no fish) are not balances."""
    out = []
    n_items = (items[items["group"].notna() & items["supply"].notna()]
               .groupby(["iso3", "group"]).size())

    def gaps(df):
        lhs = df[["production", "imports", "exports"]].fillna(0)
        rebuilt = lhs["production"] + lhs["imports"] - lhs["exports"] - df["stock_variation"].fillna(0)
        scale = df[["production", "imports", "exports", "supply"]].abs().max(axis=1).clip(lower=1)
        has_trade = df["imports"].notna() | df["exports"].notna()
        return rebuilt, (df["supply"] - rebuilt).abs(), scale, has_trade & df["supply"].notna()

    g = groups[groups["basis"] == "tonnes"]
    rebuilt, gap, scale, ok = gaps(g)
    ours_row = (g["iso3"] == EU_BLOC) | (g.get("source", pd.Series("", index=g.index)) == "jrc_bal")
    rounding = pd.Series([FAO_ROUNDING_KT * n_items.get((i, gr), 1) for i, gr in zip(g["iso3"], g["group"], strict=True)],
                         index=g.index)
    tol = np.maximum(np.maximum(1.0, REL_TOL * scale), np.where(ours_row, 0.0, rounding))
    for _, r in g[ok & (gap > tol)].iterrows():
        ours = r["iso3"] == EU_BLOC or r.get("source") == "jrc_bal"
        out.append(Finding("balance_identity", BLOCK if ours else WARN,
                           f"supply {r['supply']:.0f} kt but P+M-X-dS = {rebuilt.loc[r.name]:.0f} kt"
                           + (" (built by us)" if ours else " (as FAO publishes it)"),
                           r["iso3"], r["group"], _f(gap.loc[r.name])))
    if "jrc_food" in items:
        it = items[items["jrc_food"].notna()]
        rebuilt, gap, scale, ok = gaps(it)
        for _, r in it[ok & (gap > 0.01 + 1e-6 * scale)].iterrows():
            out.append(Finding("balance_identity_jrc", BLOCK,
                               f"{r['item']}: supply {r['supply']:.2f} kt but P+M-X-dS = "
                               f"{rebuilt.loc[r.name]:.2f} kt", r["iso3"], r["group"],
                               _f(gap.loc[r.name])))
    return out


def check_group_sums(items: pd.DataFrame, groups: pd.DataFrame) -> list[Finding]:
    """A group's tonnes are the sum of its items, and every mapped item is counted exactly once."""
    out = []
    products = load_products()["groups"]
    seen: dict[str, str] = {}
    for key, g in products.items():
        for it in g["items"]:
            if it in seen:
                out.append(Finding("item_in_two_groups", BLOCK, f"{it!r} in {seen[it]} and {key}"))
            seen[it] = key
    it = items[items["group"].notna()]
    s = it.groupby(["iso3", "group"])[["production", "imports", "exports", "supply"]].sum(min_count=1)
    t = groups[groups["basis"] == "tonnes"].set_index(["iso3", "group"])
    j = t.join(s, rsuffix="_items", how="left")
    for c in ("production", "imports", "exports", "supply"):
        d = (j[c] - j[f"{c}_items"]).abs()
        bad = j[d > np.maximum(0.05, REL_TOL * j[c].abs())]
        for (iso3, group), r in bad.iterrows():
            out.append(Finding("group_equals_items", BLOCK,
                               f"{c}: group {r[c]:.1f} kt, items sum {r[f'{c}_items']:.1f} kt",
                               iso3, group, _f(r[c])))
    return out


def check_ranges(groups: pd.DataFrame, items: pd.DataFrame, overall: pd.DataFrame) -> list[Finding]:
    out = []
    t = groups[groups["basis"] == "tonnes"]
    for c in ("production", "imports", "exports"):
        for _, r in t[t[c] < -0.05].iterrows():
            out.append(Finding("negative_quantity", BLOCK, f"{c} {r[c]:.1f} kt", r["iso3"],
                               r["group"], _f(r[c])))
    shown = t[t["flag"].fillna("") == ""]
    for _, r in shown[shown["ssr"] > SSR_REVIEW].iterrows():
        out.append(Finding("ssr_extreme", WARN,
                           f"SSR {r['ssr']:.0f}%: produces {r['production']:.0f} kt, uses "
                           f"{r['supply']:.0f} kt", r["iso3"], r["group"], _f(r["ssr"])))
    for _, r in overall.iterrows():
        k, p = r.get("kcal"), r.get("protein")
        if pd.notna(k) and not KCAL_RANGE[0] <= k <= KCAL_RANGE[1]:
            out.append(Finding("kcal_range", WARN, f"{k:.0f} kcal/person/day", r["iso3"], "all", _f(k)))
        if pd.notna(p) and not PROTEIN_RANGE[0] <= p <= PROTEIN_RANGE[1]:
            out.append(Finding("protein_range", WARN, f"{p:.0f} g protein/person/day", r["iso3"],
                               "all", _f(p)))
    # Items with negative supply shrink a group's supply without being visible anywhere.
    neg = items[items["group"].notna() & (items["supply"] < 0)]
    negsum = neg.groupby(["iso3", "group"])["supply"].sum()
    gs = t.set_index(["iso3", "group"])["supply"].abs()
    for (iso3, group), v in negsum.items():
        tot = gs.get((iso3, group))
        if tot and abs(v) > NEG_ITEMS_SHARE * tot and t.set_index(["iso3", "group"]).loc[(iso3, group), "flag"] == "":
            out.append(Finding("negative_items_in_group", WARN,
                               f"items with negative supply ({v:.0f} kt) are {abs(v) / tot:.0%} of "
                               f"the group's {tot:.0f} kt", iso3, group, _f(v)))
    return out


def check_trends(trends: pd.DataFrame) -> list[Finding]:
    """Unusual years (checks.unusual_years): kept in the series, marked in ssr.json for the chart."""
    out = []
    for (iso3, group), s in trends.sort_values("year").groupby(["iso3", "group"]):
        v = {int(y): x for y, x in zip(s["year"], s["ssr"], strict=False)}
        for y in checks.unusual_years(v):
            out.append(Finding("trend_spike", WARN,
                               f"{y}: {v[y]:.0f}% between {v[y - 1]:.0f}% and {v[y + 1]:.0f}% "
                               "(marked as unusual in the chart)", iso3, group, _f(v[y])))
    return out


def check_eu_bloc(groups: pd.DataFrame, items: pd.DataFrame) -> list[Finding]:
    """EU27 production = members' sum; extra-EU trade can't exceed members' total trade; our
    production agrees with FAO's own EU27 row."""
    out = []
    t = groups[groups["basis"] == "tonnes"].set_index(["iso3", "group"])
    if EU_BLOC not in t.index.get_level_values(0):
        return [Finding("eu_bloc_missing", BLOCK, "no EU27 rows in ssr_groups")]
    members = t[t.index.get_level_values(0).isin(config.EU27)].groupby(level="group")
    msum = members[["production", "imports", "exports"]].sum()
    eu = t.loc[EU_BLOC]
    for group, r in eu.iterrows():
        if group not in msum.index or str(r.get("source", "")).startswith("jrc"):
            continue
        p, mp = r["production"], msum.loc[group, "production"]
        if abs(p - mp) > max(0.5, REL_TOL * abs(mp)):
            out.append(Finding("eu_production_sum", BLOCK, f"EU27 {p:.0f} kt, members {mp:.0f} kt",
                               EU_BLOC, group, _f(p)))
        for c in ("imports", "exports"):
            if pd.notna(r[c]) and r[c] > msum.loc[group, c] * (1 + REL_TOL) + 0.5:
                out.append(Finding(f"eu_extra_{c}", BLOCK,
                                   f"extra-EU {c} {r[c]:.0f} kt > members' total {msum.loc[group, c]:.0f} kt",
                                   EU_BLOC, group, _f(r[c])))
    path = config.INTERIM / "FoodBalanceSheets_fao_eu27.parquet"
    if not path.exists():
        out.append(Finding("fao_eu27_missing", WARN, f"no {path.name}: rerun `atlas build`"))
        return out
    fao = pd.read_parquet(path)
    years = groups["years"].iloc[0]
    y0, y1 = (int(y) for y in years.split("-"))
    fw = to_wide(fao[fao["year"].between(y0, y1)].assign(iso3=EU_BLOC))
    fw = fw.groupby("item")["production"].sum() / (y1 - y0 + 1)
    # Item by item, where FAO is the source (JRC items have the JRC's production by design).
    ours = items[(items["iso3"] == EU_BLOC) & items["group"].notna()]
    if "jrc_food" in ours:
        ours = ours[ours["jrc_food"].isna()]
    for _, r in ours.iterrows():
        fp = fw.get(r["item"])
        if fp is None or pd.isna(fp) or fp < 1:
            continue
        # FAO rounds every member and its own EU row to 1 kt: up to 27 x 0.5 kt apart by rounding
        if abs(r["production"] - fp) > FAO_EU27_TOL * fp + 0.5 * len(config.EU27):
            out.append(Finding("eu_production_vs_fao", BLOCK,
                               f"{r['item']}: ours {r['production']:.0f} kt, FAO's EU27 row {fp:.0f} kt",
                               EU_BLOC, r["group"], _f(r["production"])))
    return out


def check_jrc(groups: pd.DataFrame, items: pd.DataFrame) -> list[Finding]:
    """Where we cite the JRC, our ratio should be the JRC's own. True by construction for
    tomatoes, olive oil and wine (its production and apparent use); for dairy the JRC's ratio
    rests on an apparent use the dataset does not derive, so a gap there is a warning, shown in
    the UI next to ours (export: jrc_published_ssr)."""
    out = []
    years = groups["years"].iloc[0]
    window = tuple(int(y) for y in years.split("-"))
    pub = jrc.published_ssr(window)
    if not pub:
        return out
    t = groups[groups["basis"] == "tonnes"].set_index(["iso3", "group"])
    it = items.set_index(["iso3", "item"])
    for (iso3, food), theirs in pub.items():
        if food == "dairy":
            if (iso3, "dairy") not in t.index or t.loc[(iso3, "dairy"), "source"] != "jrc_bal":
                continue
            ours = t.loc[(iso3, "dairy"), "ssr"]
            sev = WARN
        else:
            fbs_items = jrc.FOODS[food][3]
            rows = [it.loc[(iso3, i)] for i in fbs_items if (iso3, i) in it.index]
            if not rows or str(rows[0].get("jrc_food")) != food:
                continue
            p, d = sum(r["production"] for r in rows), sum(r["supply"] for r in rows)
            ours = p / d * 100 if d > 0 else np.nan
            sev = BLOCK
        if pd.notna(ours) and abs(ours - theirs) > JRC_TOL_PP:
            out.append(Finding(f"jrc_ratio_{food}", sev,
                               f"ours {ours:.0f}%, JRC's own {theirs:.0f}%", iso3,
                               "dairy" if food == "dairy" else food, _f(ours)))
    return out


def check_trade(partners: pd.DataFrame, groups: pd.DataFrame) -> list[Finding]:
    out = []
    p = partners
    self_trade = p[p["iso3"] == p["partner"]]
    for _, r in self_trade.iterrows():
        out.append(Finding("trade_self", BLOCK, f"{r['flow']} with itself", r["iso3"], r["group"]))
    neg = p[p["tonnes"] < 0]
    for _, r in neg.iterrows():
        out.append(Finding("trade_negative", BLOCK, f"{r['flow']} {r['tonnes']:.0f} t from "
                           f"{r['partner']}", r["iso3"], r["group"], _f(r["tonnes"])))
    # Trade records (product weight) vs the balance (primary equivalent), against each food group's
    # typical ratio (checks.trade_verdicts): far off is a warning; far above it and above the
    # balance itself is withheld in the export.
    for r in checks.trade_verdicts(p, groups).itertuples():
        if not r.verdict:
            continue
        what = "bought abroad" if r.flow == "imports" else "sold abroad"
        side = "below" if r.ratio < r.typical else "above"
        detail = (f"trade records {r.trade_kt:.0f} kt {what}, food balance {r.balance_kt:.0f} kt "
                  f"(ratio {r.ratio:.2f}, {side} the typical {r.typical:.2f} for {r.group})")
        out.append(Finding("trade_withheld" if r.verdict == "withhold" else "trade_vs_fbs",
                           WITHHOLD if r.verdict == "withhold" else WARN,
                           detail, r.iso3, r.group, _f(r.ratio)))
    return out


def check_usda() -> list[Finding]:
    """FAO against USDA PSD (pipeline/usda.py): large SSR gaps on items with real use. Sources may
    differ legitimately, so these are warnings; the UI shows them next to FAO's figure."""
    from . import usda

    if not usda.OUT.exists():
        return [Finding("usda_missing", WARN, "no usda_comparison.parquet: `atlas download "
                        "--source usda` and `atlas build`")]
    c = pd.read_parquet(usda.OUT)
    out = []
    for _, r in c[c["large_gap"]].iterrows():
        out.append(Finding("usda_gap", WARN,
                           f"{r['item']}: FAO {r['ssr_fao']:.0f}%, USDA {r['ssr_usda']:.0f}% "
                           f"(production {r['production_fao']:.0f} / {r['production_usda']:.0f} kt, "
                           f"use {r['supply_fao']:.0f} / {r['supply_usda']:.0f} kt)",
                           r["iso3"], r["item"], _f(r["gap_pp"])))
    return out


# ------------------------------------------------------------------------------------------------
# published JSON


def _walk_numbers(x, path=""):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from _walk_numbers(v, f"{path}.{k}")
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from _walk_numbers(v, f"{path}[{i}]")
    elif isinstance(x, float):
        yield path, x


def check_published(ssr: dict, items: dict, trade: dict | None) -> list[Finding]:
    """The JSON the browser reads: finite numbers, withheld figures carry nothing usable, every
    cited source exists, trend series aligned, partner shares add up."""
    out = []
    for path, v in _walk_numbers({"ssr": ssr, "items": items, "trade": trade or {}}):
        if not math.isfinite(v):
            out.append(Finding("json_nonfinite", BLOCK, f"{path} = {v}"))
    sources = ssr["meta"]["sources"]
    n_years = len(ssr["meta"]["trend_years"])
    for iso3, c in ssr["countries"].items():
        for group, ind in c.get("indicators", {}).items():
            src = ind.get("source")
            for s in (src or "").split("+"):
                if s and s not in sources:
                    out.append(Finding("unknown_source", BLOCK, f"source {s!r}", iso3, group))
            if group == "all":
                for basis in ("protein", "kcal"):
                    b = ind.get(basis, {})
                    if "withheld" in b and (b.get("ssr") is not None or b.get("share") is not None):
                        out.append(Finding("withheld_leak", BLOCK, f"all/{basis} withheld but "
                                           "exports a share", iso3, group))
                    if "withheld" in b:
                        out.append(Finding("withheld", WITHHOLD, b["withheld"]["reason"], iso3,
                                           f"all/{basis}"))
                continue
            if "withheld" in ind:
                usable = [b for b in ("tonnes", "kcal") if ind.get(b, {}).get("ssr") is not None]
                if usable or "components_kt" in ind:
                    out.append(Finding("withheld_leak", BLOCK,
                                       f"withheld ({ind['withheld']['reason']}) but exports "
                                       f"{usable or 'components_kt'}", iso3, group))
                out.append(Finding("withheld", WITHHOLD, ind["withheld"]["reason"], iso3, group))
                continue
            comp = ind.get("components_kt")
            t = ind.get("tonnes", {})
            if comp and t.get("ssr") is not None and comp.get("supply"):
                ssr_c = comp["production"] / comp["supply"] * 100
                # components are rounded to 0.1 kt: allow for that in the ratio
                tol = 0.06 + 100 * 0.05 * (1 / abs(comp["supply"]) + (comp["production"] or 0)
                                         / comp["supply"] ** 2)
                if abs(ssr_c - t["ssr"]) > max(tol, 0.06):
                    out.append(Finding("ssr_vs_components", BLOCK,
                                       f"ssr {t['ssr']} but production/supply = {ssr_c:.2f}",
                                       iso3, group, t["ssr"]))
            if ind.get("uses_withheld"):
                out.append(Finding("uses_withheld", WITHHOLD, ind["uses_withheld"], iso3, group))
        for group, series in c.get("trend", {}).items():
            if len(series) != n_years:
                out.append(Finding("trend_length", BLOCK, f"{len(series)} points for {n_years} years",
                                   iso3, group))
        for group, ys in c.get("trend_unusual", {}).items():
            if group not in c.get("trend", {}) or not set(ys) <= set(ssr["meta"]["trend_years"]):
                out.append(Finding("trend_unusual_unknown", BLOCK, f"unusual years {ys}", iso3, group))
    if trade:
        # Withheld flows (checks.trade_verdicts) must not be published; imports take "grown" along.
        for iso3, group, flow, *_ in trade["meta"].get("withheld", []):
            for f in (["imports", "grown"] if flow == "imports" else [flow]):
                if f in trade["countries"].get(iso3, {}).get(group, {}):
                    out.append(Finding("trade_withheld_leak", BLOCK, f"{f} withheld but published",
                                       iso3, group))
        # Concentration: within 0..10,000 and at least what the listed partners alone give.
        for iso3, gs in trade.get("concentration", {}).items():
            for group, fl in gs.items():
                for flow, h in fl.items():
                    entry = trade["countries"].get(iso3, {}).get(group, {}).get(flow)
                    # every published figure is rounded to whole tonnes: take the smallest shares the
                    # rounding allows, so this is a strict lower bound even for tiny flows
                    listed = (sum((100 * max(t - 0.5, 0) / (entry[0] + 0.5)) ** 2 for _, t in entry[1])
                              if entry and entry[0] else None)
                    if entry is None or not 0 <= h <= 10_000 or (listed is not None and h < listed - 0.5):
                        out.append(Finding("trade_hhi", BLOCK, f"{flow} HHI {h} (listed partners {listed})",
                                           iso3, group))
        for iso3, gs in trade["countries"].items():
            for group, flows in gs.items():
                for flow, (total, parts) in flows.items():
                    s = sum(t for _, t in parts)
                    # every figure is rounded to whole tonnes
                    if s > total + 0.5 * (len(parts) + 1):
                        out.append(Finding("trade_parts_exceed_total", BLOCK,
                                           f"{flow}: partners {s} t > total {total} t", iso3, group))
                    if any(p == iso3 for p, _ in parts):
                        out.append(Finding("trade_self", BLOCK, f"{flow} lists itself", iso3, group))
    return out


# ------------------------------------------------------------------------------------------------


def resolve(findings: list[Finding], ssr: dict | None, items: pd.DataFrame) -> list[Finding]:
    """Warnings the site deals with by itself become `handled`; reviewed ones `confirmed`.

    trend_spike              the year is drawn apart and named in the year-by-year chart
    jrc_ratio_dairy          the JRC's own ratio is shown next to ours on the sources page
    negative_items_in_group  the parts test (compute.group_tonnes) kept both readings within the
                             withholding threshold, so the figure stands either way
    usda_gap                 shown on the food's page, or too small to move the group's figure by
                             export.USDA_GROUP_PP points
    trade_vs_fbs (below)     the trade page says the records hold under half of the balance
    """
    from .export import USDA_GROUP_PP

    shown_usda = set()
    for iso3, c in (ssr or {}).get("countries", {}).items():
        for ind in c.get("indicators", {}).values():
            shown_usda |= {(iso3, d["item"]) for d in ind.get("usda", [])}
    it = items[items["group"].notna()]
    supply = it.set_index(["iso3", "item"])["supply"]
    group_supply = it.groupby(["iso3", "group"])["supply"].sum()
    group_of = it.drop_duplicates("item").set_index("item")["group"]
    confirmed = {}
    path = config.MAPPINGS / "confirmed_findings.csv"
    if path.exists():
        with path.open(encoding="utf-8") as f:
            import csv

            for r in csv.DictReader(line for line in f if not line.startswith("#")):
                confirmed[(r["check"], r["iso3"], r["group"])] = f"{r['reason']} (reviewed {r['reviewed']})"

    out = []
    for f in findings:
        if f.severity != WARN:
            out.append(f)
            continue
        handled = None
        if f.check == "trend_spike":
            handled = "drawn apart and named in the year-by-year chart"
        elif f.check == "jrc_ratio_dairy":
            ind = (ssr or {}).get("countries", {}).get(f.iso3, {}).get("indicators", {}).get("dairy", {})
            if "jrc_published_ssr" in ind:
                handled = "the Commission's own ratio is shown next to ours on the sources page"
        elif f.check == "negative_items_in_group":
            handled = "both readings within the withholding threshold (parts test)"
        elif f.check == "usda_gap":
            if (f.iso3, f.group) in shown_usda:
                handled = "shown on the food's page"
            else:
                g = group_of.get(f.group)
                gs = group_supply.get((f.iso3, g))
                share = supply.get((f.iso3, f.group), 0) / gs if gs and gs > 0 else 0
                if f.value is not None and share * abs(f.value) < USDA_GROUP_PP:
                    handled = f"cannot move the group's figure by {USDA_GROUP_PP:.0f} points"
        elif f.check == "trade_vs_fbs" and "below" in f.detail and f.group != "all":
            handled = "the trade page says the records hold under half of the balance"
        key = (f.check, f.iso3, f.group)
        if handled:
            out.append(Finding(f.check, HANDLED, f"{f.detail}; {handled}", f.iso3, f.group, f.value))
        elif key in confirmed:
            out.append(Finding(f.check, CONFIRMED, f"{f.detail}; {confirmed[key]}", f.iso3, f.group, f.value))
        else:
            out.append(f)
    return out


def _sha(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(*, write: bool = True) -> list[Finding]:
    P = config.PROCESSED
    groups = pd.read_parquet(P / "ssr_groups.parquet")
    items = pd.read_parquet(P / "ssr_items.parquet")
    overall = pd.read_parquet(P / "ssr_overall.parquet")
    trends = pd.read_parquet(P / "ssr_trends.parquet")
    partners_path = P / "trade_partners.parquet"
    partners = pd.read_parquet(partners_path) if partners_path.exists() else None

    findings: list[Finding] = []
    findings += check_balance_identity(groups, items)
    findings += check_group_sums(items, groups)
    findings += check_ranges(groups, items, overall)
    findings += check_trends(trends)
    findings += check_eu_bloc(groups, items)
    findings += check_jrc(groups, items)
    findings += check_usda()
    if partners is None:
        findings.append(Finding("trade_missing", BLOCK, "no trade_partners.parquet"))
    else:
        findings += check_trade(partners[partners["flow"] != "grown"], groups)

    W = config.WEB_DATA
    load = lambda n: json.loads((W / n).read_text(encoding="utf-8")) if (W / n).exists() else None
    ssr, its, trade = load("ssr.json"), load("items.json"), load("trade.json")
    if ssr is None or its is None:
        findings.append(Finding("published_missing", BLOCK, "ssr.json / items.json not exported"))
    else:
        findings += check_published(ssr, its, trade)

    # A warning about a figure that is withheld anyway (any reason) asks nothing of the reviewer:
    # the audit page lists the figure under "Withheld" already.
    t = groups[groups["basis"] == "tonnes"]
    gone = set(zip(t.loc[t["flag"].fillna("") != "", "iso3"], t.loc[t["flag"].fillna("") != "", "group"],
                   strict=True))
    moot = [f for f in findings if f.severity == WARN and (f.iso3, f.group) in gone]
    if moot:
        log.info("validation: %d warnings about withheld figures dropped", len(moot))
        findings = [f for f in findings if not (f.severity == WARN and (f.iso3, f.group) in gone)]

    findings = resolve(findings, ssr, items)

    # Withholding by the consistency verdicts (checks.py) is applied upstream; count it here.
    counts = pd.Series([f.severity for f in findings]).value_counts().to_dict()
    log.info("validation: %s", counts)
    for f in findings:
        if f.severity == BLOCK:
            log.error("BLOCK %s %s/%s: %s", f.check, f.iso3, f.group, f.detail)

    if write:
        df = pd.DataFrame([asdict(f) for f in findings],
                          columns=["check", "severity", "detail", "iso3", "group", "value"])
        df.to_parquet(P / "validation.parquet", index=False)
        doc = {
            "generated": datetime.now(UTC).isoformat(timespec="seconds"),
            "ok": counts.get(BLOCK, 0) == 0,
            "counts": counts,
            "by_check": df.groupby(["check", "severity"]).size().rename("n").reset_index()
                          .to_dict("records"),
            "files": {n: _sha(W / n) for n in PUBLISHED if (W / n).exists()},
            "thresholds": {"residual_share": checks.RESIDUAL_SHARE, "ssr_review": SSR_REVIEW,
                           "jrc_tol_pp": JRC_TOL_PP, "fao_eu27_tol": FAO_EU27_TOL},
            "findings": [asdict(f) for f in findings if f.severity != WITHHOLD],
        }
        (W / "validation.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    return findings

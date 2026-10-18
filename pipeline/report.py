"""`atlas report`: one HTML page a human reads before every release (data/processed/audit.html).

What is withheld and why, every warning from `atlas validate`, the independent recomputation's
verdict, and the largest changes against the last released data (data/releases/<stamp>/), so a
jump nobody expected is seen before readers see it. `atlas release-snapshot` stores the current
web data as the new baseline once a release has gone out.
"""

from __future__ import annotations

import html
import json
import logging
import shutil
from datetime import UTC, datetime

import pandas as pd

from . import config

log = logging.getLogger(__name__)

RELEASES = config.DATA / "releases"
REPORT = config.PROCESSED / "audit.html"
RECOMPUTE = config.ROOT / "verify" / "recompute_report.json"
TOP_CHANGES = 50


def _figures(ssr: dict) -> dict[tuple[str, str, str], float]:
    """(iso3, group, basis) -> the headline ratio the UI shows."""
    out = {}
    for iso3, c in ssr["countries"].items():
        for group, ind in c.get("indicators", {}).items():
            for basis in ("tonnes", "kcal", "protein"):
                v = ind.get(basis, {}).get("ssr")
                if v is not None:
                    out[(iso3, group, basis)] = v
    return out


def _latest_release() -> dict | None:
    if not RELEASES.exists():
        return None
    stamps = sorted(p for p in RELEASES.iterdir() if (p / "ssr.json").exists())
    if not stamps:
        return None
    return {"stamp": stamps[-1].name,
            "ssr": json.loads((stamps[-1] / "ssr.json").read_text(encoding="utf-8"))}


def changes(old: dict, new: dict) -> pd.DataFrame:
    a, b = _figures(old), _figures(new)
    rows = []
    for key in sorted(set(a) | set(b)):
        x, y = a.get(key), b.get(key)
        if x == y:
            continue
        rows.append({"iso3": key[0], "group": key[1], "basis": key[2], "before": x, "after": y,
                     "change": None if x is None or y is None else y - x})
    df = pd.DataFrame(rows, columns=["iso3", "group", "basis", "before", "after", "change"])
    if df.empty:
        return df
    df["size"] = df["change"].abs().fillna(float("inf"))
    return df.sort_values("size", ascending=False).drop(columns="size")


def _table(df: pd.DataFrame, cols: list[str] | None = None) -> str:
    if df.empty:
        return "<p class='none'>None.</p>"
    df = df[cols] if cols else df
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in df.columns)
    body = "".join(
        "<tr>" + "".join(f"<td>{'' if pd.isna(v) else html.escape(str(round(v, 1) if isinstance(v, float) else v))}</td>"
                         for v in r) + "</tr>"
        for r in df.itertuples(index=False))
    return f"<div class='tw'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def _usda_section() -> str:
    from . import usda

    if not usda.OUT.exists():
        return "<h2>FAO against USDA</h2><p class='bad'>No comparison (download USDA PSD).</p>"
    c = pd.read_parquet(usda.OUT)
    s = usda.summary(c)
    rows = pd.DataFrame(s.pop("by_commodity"))
    return ("<h2>FAO against USDA PSD</h2>"
            f"<p>{s['pairs']} country × commodity pairs with at least 50 kt of use: median SSR gap "
            f"{s['median_gap_pp']} points; {s['share_within_5pp']:.0%} within 5, "
            f"{s['share_within_10pp']:.0%} within 10, {s['share_within_20pp']:.0%} within 20 points. "
            f"Median production ratio FAO/USDA {s['production_ratio_median']}.</p>"
            + _table(rows.sort_values("median", ascending=False)))


COMPARE_MIN_KT = 20  # member-group-flows smaller than this on both sides are not summarised


def _comext_section() -> str:
    from . import comext

    path = config.PROCESSED / comext.COMPARE
    if not path.exists():
        return "<h2>Comext against FAO's trade matrix</h2><p class='bad'>No comparison (download Comext).</p>"
    c = pd.read_parquet(path)
    c = c[(c["comext_kt"] >= COMPARE_MIN_KT) | (c["fao_kt"] >= COMPARE_MIN_KT)]
    r = c["ratio"]
    within = ((r >= 0.9) & (r <= 1.1)).mean()
    by = (c.groupby("group")["ratio"].agg(pairs="size", median="median",
                                          within_20=lambda x: ((x >= 0.8) & (x <= 1.25)).mean())
          .reset_index().sort_values("median"))
    off = c.assign(gap=(c["comext_kt"] - c["fao_kt"]).abs()).sort_values("gap", ascending=False).head(15)
    two = lambda x: f"{x:.2f}"  # ratios near 1 need two decimals
    by[["median", "within_20"]] = by[["median", "within_20"]].map(two)
    off = off.assign(ratio=off["ratio"].map(two))
    return ("<h2>Comext against FAO's trade matrix</h2>"
            f"<p class='note'>EU members' trade {c['years'].iloc[0]}, each group and flow with at least "
            f"{COMPARE_MIN_KT} kt a year on either side, both in the partner lists' basis (methodology, "
            f"\"Comext\"). FAO builds these rows from Comext, so a gap points at a difference in how "
            f"products are mapped, or at FAO's own corrections of a member's figures. "
            f"{len(c)} pairs: median Comext/FAO {r.median():.2f}, {within:.0%} within 10%.</p>"
            + _table(by) + "<p class='note'>Largest gaps in kt:</p>"
            + _table(off[["iso3", "group", "flow", "comext_kt", "fao_kt", "ratio"]]))


def _baci_section() -> str:
    from . import baci

    path = config.PROCESSED / baci.COMPARE
    if not path.exists():
        return "<h2>BACI against FAO's trade matrix</h2><p class='bad'>No comparison (download BACI).</p>"
    c = pd.read_parquet(path)
    c = c[(c["baci_kt"] >= COMPARE_MIN_KT) | (c["fao_kt"] >= COMPARE_MIN_KT)]
    r = c["ratio"]
    two = lambda x: "" if pd.isna(x) else f"{x:.2f}"  # ratios near 1 need two decimals
    by = (c.groupby("group")["ratio"].agg(pairs="size", median="median",
                                          within_20=lambda x: ((x >= 0.8) & (x <= 1.25)).mean())
          .reset_index().sort_values("median"))
    by[["median", "within_20"]] = by[["median", "within_20"]].map(two)
    m = c[c["mirror"]].sort_values("fao_kt", ascending=False)
    off = c.assign(gap=(c["baci_kt"] - c["fao_kt"]).abs()).sort_values("gap", ascending=False).head(15)
    cols = ["iso3", "group", "flow", "baci_kt", "fao_kt", "ratio"]
    return ("<h2>BACI against FAO's trade matrix</h2>"
            f"<p class='note'>Every country's trade {c['years'].iloc[0]}, each group (not fish) and flow "
            f"with at least {COMPARE_MIN_KT} kt a year on either side, both in the partner lists' basis "
            f"(methodology, \"BACI\"); FAO's side as the partner lists use it, mirror flows included. "
            f"{len(c)} pairs: median BACI/FAO {r.median():.2f}, "
            f"{((r >= 0.9) & (r <= 1.1)).mean():.0%} within 10%.</p>"
            + _table(by)
            + f"<p class='note'>Countries whose FAO flows rest partly on partners' reports ({m['iso3'].nunique()}; "
              f"{((m['ratio'] >= 0.9) & (m['ratio'] <= 1.1)).mean():.0%} of their pairs within 10%), "
              "largest flows:</p>"
            + _table(m.head(15).assign(ratio=m.head(15)["ratio"].map(two))[cols])
            + "<p class='note'>Largest gaps in kt:</p>"
            + _table(off.assign(ratio=off["ratio"].map(two))[cols]))


# What each warning tests, its usual cause, and what the site does (reviews of 2026-10-17/18).
CHECK_NOTES = {
    "usda_gap": "FAO's and USDA's figures for one country and commodity put its self-sufficiency far "
                "apart. Different compilations, neither known to be right. Shown on the food's page "
                "when the item is at least 10% of its group or could move the group's figure by 5 "
                "points; the rest cannot move it that much.",
    "trade_vs_fbs": "Trade records far from their food group's typical ratio to the balance. All are "
                    "below it: the balance also counts food contained in processed goods (sugar in "
                    "chocolate and soft drinks, milk in food preparations, wheat gluten in fish feed; fish fed to "
                    "farmed fish as fishmeal, which is not fish in the trade records) "
                    "that the trade records file elsewhere. Records far above it would be withheld.",
    "jrc_ratio_dairy": "The European Commission's own dairy ratio, on a basis its file does not "
                       "document, against ours from its production and trade figures. Expected every "
                       "release; both are shown on the sources page.",
    "negative_items_in_group": "Items with negative supply (re-exports exceeding what FAO counts "
                               "as available) shrink the group's 'uses at home'. Self-sufficiency is "
                               "barely affected where the country produces little of the food.",
    "trend_spike": "A single year far from both neighbours: most likely an error in FAO's figures. "
                   "Kept in the series and drawn apart, named, in the year-by-year chart.",
    "ssr_extreme": "Over 1000% self-sufficient. So far always a real exporter of a food it barely "
                   "uses (Iceland's fish, Ghana's cocoa); check new entries.",
    "balance_identity": "FAO's balance misses production + imports - exports - stock change = "
                        "supply by more than its rounding can explain (2.5 kt per item).",
}


def run() -> None:
    W = config.WEB_DATA
    vpath = W / "validation.json"
    if not vpath.exists():
        raise FileNotFoundError("run `atlas validate` first")
    v = json.loads(vpath.read_text(encoding="utf-8"))
    ssr = json.loads((W / "ssr.json").read_text(encoding="utf-8"))
    findings = pd.read_parquet(config.PROCESSED / "validation.parquet")
    rec = json.loads(RECOMPUTE.read_text(encoding="utf-8")) if RECOMPUTE.exists() else None

    withheld = []
    for iso3, c in ssr["countries"].items():
        for group, ind in c.get("indicators", {}).items():
            bases = [("tonnes", ind)] if group != "all" else [("protein", ind.get("protein", {})),
                                                            ("kcal", ind.get("kcal", {}))]
            for basis, where in bases:
                w = where.get("withheld")
                if w:
                    r = w.get("range") or [None, None]
                    withheld.append({"iso3": iso3, "name": c.get("name"), "group": group, "basis": basis,
                                     "reason": w["reason"], "low": r[0], "high": r[1]})
            if ind.get("uses_withheld"):
                withheld.append({"iso3": iso3, "name": c.get("name"), "group": group, "basis": "tonnes",
                                 "reason": "uses breakdown only", "low": None, "high": None})
    wdf = pd.DataFrame(withheld, columns=["iso3", "name", "group", "basis", "reason", "low", "high"])
    # Trade flows whose records are far above the food balance (checks.trade_verdicts).
    tpath = W / "trade.json"
    tw = json.loads(tpath.read_text(encoding="utf-8"))["meta"].get("withheld", []) if tpath.exists() else []
    names = {k: c.get("name") for k, c in ssr["countries"].items()}
    tdf = pd.DataFrame([{"iso3": i, "name": names.get(i, i), "group": g, "flow": f,
                         "trade_records_kt": t, "food_balance_kt": b} for i, g, f, t, b in tw],
                       columns=["iso3", "name", "group", "flow", "trade_records_kt", "food_balance_kt"])

    rel = _latest_release()
    chg = changes(rel["ssr"], ssr) if rel else pd.DataFrame()
    warn = findings[findings["severity"] == "warn"]
    handled = findings[findings["severity"] == "handled"]
    confirmed = findings[findings["severity"] == "confirmed"]
    block = findings[findings["severity"] == "block"]

    rec_line = ("<p class='bad'>verify/recompute_report.json missing: run verify/recompute.py.</p>"
                if rec is None else
                f"<p class='{'ok' if rec.get('ok') else 'bad'}'>Independent recomputation: "
                f"{rec.get('compared_total', '?')} values compared, "
                f"{rec.get('n_mismatches', '?')} mismatches.</p>")
    sections = [
        (f"<h1>Autonomy Atlas: data audit</h1><p>Generated {datetime.now(UTC):%Y-%m-%d %H:%M} UTC "
         f"for the data window {html.escape(str(ssr['meta']['years']))}. "
         f"Validation {'passed' if v['ok'] else '<b>FAILED</b>'}: "
         f"{html.escape(json.dumps(v['counts']))}.</p>"),
        rec_line,
        "<h2>Blocking findings</h2>" + _table(block, ["check", "iso3", "group", "detail"]),
        _usda_section(),
        _comext_section(),
        _baci_section(),
        f"<h2>Largest changes since the last release{' (' + rel['stamp'] + ')' if rel else ''}</h2>"
        + (_table(chg.head(TOP_CHANGES)) if rel else "<p>No release stored yet "
           "(`atlas release-snapshot` after publishing).</p>"),
        f"<h2>Withheld ({len(wdf)})</h2><p>Not shown on the site; the site explains why.</p>"
        + _table(wdf),
        f"<h2>Withheld trade flows ({len(tdf)})</h2><p>Trade records far above the food balance "
        "(methodology, \"Trade records against the food balance\"): the split by country is not "
        "shown, and for all food the bought or sold total neither.</p>" + _table(tdf),
    ]
    sections.append(f"<h2>Open warnings ({len(warn)})</h2><p>Need a human look before release: fix, "
                    "withhold by review, or confirm in mappings/confirmed_findings.csv.</p>")
    for check, sub in warn.groupby("check"):
        note = CHECK_NOTES.get(check)
        sections.append(f"<h3>{html.escape(check)} ({len(sub)})</h3>"
                        + (f"<p class='note'>{html.escape(note)}</p>" if note else "")
                        + _table(sub.sort_values(["iso3", "group"]), ["iso3", "group", "detail"]))
    for title, df, intro in (
            ("Handled by the site", handled, "Warnings the site deals with by itself; each line says how."),
            ("Confirmed after review", confirmed, "Warnings a review found right as published, with the reason.")):
        sections.append(f"<h2>{title} ({len(df)})</h2><p>{intro}</p>")
        for check, sub in df.groupby("check"):
            note = CHECK_NOTES.get(check)
            sections.append(f"<h3>{html.escape(check)} ({len(sub)})</h3>"
                            + (f"<p class='note'>{html.escape(note)}</p>" if note else "")
                            + _table(sub.sort_values(["iso3", "group"]), ["iso3", "group", "detail"]))
    page = f"""<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Atlas data audit</title>
<style>
:root{{--bg:#fdfcfa;--ink:#23201b;--muted:#57503f;--line:#e3ded4;--head:#efece5;--ok:#2f6f4e;--bad:#a8421f}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#1c1a16;--ink:#f1eee8;--muted:#b5ac98;--line:#3a362f;--head:#2b2823;--ok:#8fcfa8;--bad:#f0937a}}}}
:root[data-theme="dark"]{{--bg:#1c1a16;--ink:#f1eee8;--muted:#b5ac98;--line:#3a362f;--head:#2b2823;--ok:#8fcfa8;--bad:#f0937a}}
html{{background:var(--bg)}}
body{{font:14px/1.45 system-ui,sans-serif;max-width:1100px;margin:24px auto;padding:0 16px;color:var(--ink);background:var(--bg)}}
.tw{{overflow-x:auto;margin:8px 0 24px}}table{{border-collapse:collapse;width:100%}}
th,td{{border-bottom:1px solid var(--line);padding:4px 8px;text-align:left;vertical-align:top}}
th{{background:var(--head);position:sticky;top:0}}.ok{{color:var(--ok)}}.bad{{color:var(--bad);font-weight:600}}.none,.note{{color:var(--muted)}}.note{{max-width:80ch}}
</style>{''.join(sections)}</html>"""
    REPORT.write_text(page, encoding="utf-8")
    log.info("wrote %s (%d withheld, %d trade flows withheld, %d open warnings, %d handled, %d confirmed, "
             "%d changes)", REPORT, len(wdf), len(tdf), len(warn), len(handled), len(confirmed), len(chg))


def snapshot() -> None:
    """Store the published data as the baseline for the next report's "changes"."""
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    dest = RELEASES / stamp
    dest.mkdir(parents=True)
    for name in ("ssr.json", "items.json", "trade.json", "validation.json"):
        if (config.WEB_DATA / name).exists():
            shutil.copy2(config.WEB_DATA / name, dest / name)
    log.info("stored release baseline %s", dest)

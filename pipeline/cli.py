"""`atlas` command line.

    atlas download [--source faostat eurostat boundaries baci crop_calendar] [--force]
    atlas build    [--years 2021 2023]
    atlas export
    atlas all
"""

from __future__ import annotations

import argparse
import logging
import sys

from . import (
    baci,
    comext,
    compute,
    crosswalk,
    download,
    export,
    harmonise,
    manifest,
    regions,
    report,
    seasons,
    trade,
    usda,
    validate,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="atlas", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("download", help="fetch raw source files into data/raw/")
    d.add_argument("--source", nargs="+", choices=sorted(download.ALL),
                   help="default: faostat eurostat boundaries")
    d.add_argument("--force", action="store_true", help="re-download existing files")

    b = sub.add_parser("build", help="harmonise raw files and compute indicators")
    b.add_argument("--years", nargs=2, type=int, metavar=("Y0", "Y1"),
                   help="window, inclusive (default: latest 3 FBS years)")

    sub.add_parser("export", help="write web/public/data/*.json")
    sub.add_parser("crosswalk", help="regenerate mappings/hs_items.csv (HS6 -> food groups)")
    sub.add_parser("validate", help="check processed and published data; exit 1 on a blocking finding")
    sub.add_parser("manifest", help="record sha256 of the raw files as they are now")
    sub.add_parser("report", help="write data/processed/audit.html for review before a release")
    sub.add_parser("release-snapshot", help="store the published data as the next report's baseline")
    a = sub.add_parser("all", help="download + build + export")
    a.add_argument("--years", nargs=2, type=int, metavar=("Y0", "Y1"))

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    years = tuple(args.years) if getattr(args, "years", None) else None
    if args.cmd == "download":
        download.run(args.source, force=args.force)
        manifest.record()
    elif args.cmd == "manifest":
        manifest.record()
    elif args.cmd == "validate":
        return _validate()
    elif args.cmd == "report":
        report.run()
    elif args.cmd == "release-snapshot":
        report.snapshot()
    elif args.cmd == "crosswalk":
        crosswalk.run()
    elif args.cmd == "build":
        manifest.check()
        harmonise.run()
        comext.extract()
        trade.extract()
        compute.run(years=years)
        baci.extract(trade.fbs_window())
        trade.run()
        comext.run_compare(trade.fbs_window())
        comext.run_value(trade.fbs_window())
        baci.run_compare(trade.fbs_window())
        seasons.run()
        regions.run()
        comext.run_months(trade.fbs_window())
        usda.run()
    elif args.cmd == "export":
        export.run()
    elif args.cmd == "all":
        download.run()
        manifest.record()
        harmonise.run()
        comext.extract()
        trade.extract()
        compute.run(years=years)
        baci.extract(trade.fbs_window())
        trade.run()
        comext.run_compare(trade.fbs_window())
        comext.run_value(trade.fbs_window())
        baci.run_compare(trade.fbs_window())
        seasons.run()
        regions.run()
        comext.run_months(trade.fbs_window())
        usda.run()
        export.run()
        return _validate()
    return 0


def _validate() -> int:
    findings = validate.run()
    return 1 if any(f.severity == validate.BLOCK for f in findings) else 0


if __name__ == "__main__":
    sys.exit(main())

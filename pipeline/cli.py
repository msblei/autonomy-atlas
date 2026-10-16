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

from . import compute, download, export, harmonise, trade


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
    elif args.cmd == "build":
        harmonise.run()
        trade.extract()
        compute.run(years=years)
        trade.run()
    elif args.cmd == "export":
        export.run()
    elif args.cmd == "all":
        download.run()
        harmonise.run()
        trade.extract()
        compute.run(years=years)
        trade.run()
        export.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

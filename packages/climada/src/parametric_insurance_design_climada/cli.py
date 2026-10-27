"""Command line of the track → wind → impact pipeline (MAR-73).

From ``packages/climada``::

    pixi run build-eventset --config configs/thesis.yaml
    pixi run build-eventset --config configs/thesis.yaml --overwrite

or ``python -m parametric_insurance_design_climada.cli --help``. It builds the
EventSet with :func:`~parametric_insurance_design_climada.pipeline.build_eventset`,
writes it to ``output`` (refusing to replace an existing EventSet unless
``--overwrite`` is given) and prints its shape, content hash and runtime.
"""

from __future__ import annotations

import argparse
import logging
import sys
from collections.abc import Sequence
from pathlib import Path

from parametric_insurance_design.errors import ParametricInsuranceDesignError
from parametric_insurance_design_climada.config import load_config
from parametric_insurance_design_climada.pipeline import build_eventset
from parametric_insurance_design_climada.tracks import CatalogueFormatError

__all__ = ["main"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the pipeline from the command line.

    Parameters
    ----------
    argv : sequence of str, optional
        Arguments; defaults to ``sys.argv[1:]``.

    Returns
    -------
    int
        0 on success; 1 if the config, the inputs or the output are invalid.
    """
    parser = argparse.ArgumentParser(
        prog="build-eventset",
        description=(
            "Build an EventSet from an IRIS or STORM track catalogue with CLIMADA: "
            "proximity filter, TropCyclone wind at the asset centroids, "
            "ImpactCalc losses."
        ),
    )
    parser.add_argument("--config", type=Path, required=True, help="pipeline YAML")
    parser.add_argument(
        "--catalogue", type=Path, default=None, help="override the config's catalogue"
    )
    parser.add_argument(
        "--output", type=Path, default=None, help="override the config's output"
    )
    parser.add_argument(
        "--overwrite", action="store_true", help="replace an existing EventSet"
    )
    parser.add_argument("--quiet", action="store_true", help="log warnings only")
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    try:
        config = load_config(args.config)
        overrides = {
            key: value.resolve()
            for key, value in (("catalogue", args.catalogue), ("output", args.output))
            if value is not None
        }
        config = config.model_copy(update=overrides)
        result = build_eventset(config)
        written = result.eventset.to_parquet(config.output, overwrite=args.overwrite)
    except (
        ParametricInsuranceDesignError,
        CatalogueFormatError,
        FileExistsError,
        OSError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    es = result.eventset
    print(es)
    print(f"storms in catalogue: {result.n_storms_catalogue:,}")
    print(f"storms within {config.proximity_km:g} km: {result.n_storms_near:,}")
    for storm in result.skipped:
        print(f"skipped {storm.event_id}: {storm.reason}")
    print(f"shape: {es.n_rows:,} rows x {es.n_locations} locations")
    print(f"content_hash: {es.content_hash()}")
    print(f"runtime: {result.seconds:.1f} s")
    print(f"wrote {written}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())

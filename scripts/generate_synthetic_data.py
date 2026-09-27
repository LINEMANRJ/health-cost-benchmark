"""Gera (ou regenera) a base sintética no formato-contrato.

Uso: python scripts/generate_synthetic_data.py [--seed 42] [--start 2022-01] [--end 2024-12] [--clean]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import pandas as pd  # noqa: E402

from hcb.config import load_settings  # noqa: E402
from hcb.ingestion import synthetic  # noqa: E402


def main() -> int:
    settings = load_settings()
    opts = settings.synthetic
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=int(opts.get("seed", 42)))
    parser.add_argument("--start", default=opts.get("start", "2022-01"))
    parser.add_argument("--end", default=opts.get("end", "2024-12"))
    parser.add_argument("--clean", action="store_true", help="Sem problemas de qualidade nem anomalias injetadas")
    parser.add_argument("--output", type=Path, default=settings.raw_file)
    args = parser.parse_args()

    ufs = pd.read_csv(settings.ufs_file, dtype={"uf_codigo_ibge": str})
    result = synthetic.generate(ufs, start=args.start, end=args.end, seed=args.seed,
                                inject_quality_issues=not args.clean, inject_anomalies=not args.clean)
    synthetic.write(result, args.output)
    print(f"{len(result.data):,} linhas escritas em {args.output}")
    print(f"Gabarito de problemas injetados: {len(result.ground_truth)} registros")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Executa o pipeline completo (atalho para `python -m hcb.pipeline`).

Uso: python scripts/run_pipeline.py [--regenerate] [--config caminho.yaml]
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from hcb.pipeline import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

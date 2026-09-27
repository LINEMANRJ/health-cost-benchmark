"""Carregamento e validação da configuração do projeto."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "settings.yaml"


class ConfigError(ValueError):
    """Configuração ausente ou inválida."""


@dataclass(frozen=True)
class Settings:
    raw: dict[str, Any] = field(repr=False)
    root: Path = PROJECT_ROOT

    def path(self, relative: str) -> Path:
        return (self.root / relative).resolve()

    @property
    def source_type(self) -> str:
        return self.raw["source"]["type"]

    @property
    def raw_file(self) -> Path:
        return self.path(self.raw["source"]["raw_file"])

    @property
    def synthetic(self) -> dict[str, Any]:
        return self.raw["source"].get("synthetic", {})

    @property
    def ufs_file(self) -> Path:
        return self.path(self.raw["reference"]["ufs"])

    @property
    def subgroups_file(self) -> Path:
        return self.path(self.raw["reference"]["subgroups"])

    @property
    def processed_dir(self) -> Path:
        return self.path(self.raw["output"]["processed_dir"])

    @property
    def reports_dir(self) -> Path:
        return self.path(self.raw["output"]["reports_dir"])

    @property
    def quality(self) -> dict[str, Any]:
        return self.raw["quality"]

    @property
    def outliers(self) -> dict[str, Any]:
        return self.raw["outliers"]

    @property
    def analysis(self) -> dict[str, Any]:
        return self.raw["analysis"]


_REQUIRED = {
    "source": ["type", "raw_file"],
    "reference": ["ufs", "subgroups"],
    "output": ["processed_dir", "reports_dir"],
    "quality": ["max_rejected_ratio", "min_months"],
    "outliers": ["z_threshold", "min_admissions"],
    "analysis": ["alpha", "pareto_share"],
}
_SOURCES = {"synthetic", "contract_csv"}


def load_settings(path: str | Path | None = None, root: Path | None = None) -> Settings:
    """Lê o YAML de configuração e verifica chaves obrigatórias."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not cfg_path.exists():
        raise ConfigError(f"Arquivo de configuração não encontrado: {cfg_path}")
    try:
        data = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"YAML inválido em {cfg_path}: {exc}") from exc

    missing = [
        f"{section}.{key}"
        for section, keys in _REQUIRED.items()
        for key in keys
        if key not in (data.get(section) or {})
    ]
    if missing:
        raise ConfigError(f"Chaves obrigatórias ausentes na configuração: {', '.join(missing)}")
    if data["source"]["type"] not in _SOURCES:
        raise ConfigError(
            f"source.type deve ser um de {sorted(_SOURCES)}; recebido: {data['source']['type']!r}"
        )
    return Settings(raw=data, root=root or PROJECT_ROOT)

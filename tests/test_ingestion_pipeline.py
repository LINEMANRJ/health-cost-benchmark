import json
import shutil

import pytest
import yaml

from hcb.config import PROJECT_ROOT, ConfigError, load_settings
from hcb.formatting import brl, brl_compact, pct
from hcb.ingestion.tabnet import TabnetParseError, build_contract, parse_tabnet_csv
from hcb.pipeline import main, run


def test_parse_tabnet_export(fixtures_dir):
    df = parse_tabnet_csv(fixtures_dir / "tabnet_valor_0310.csv", "valor_total")
    assert len(df) == 6  # 2 UFs × 3 meses; linha e coluna "Total" descartadas
    ro = df[(df["uf_codigo_ibge"] == "11") & (df["competencia"] == "2024-01")]
    assert ro["valor_total"].iloc[0] == pytest.approx(1234567.89)
    assert df[(df["uf_codigo_ibge"] == "11") & (df["competencia"] == "2024-03")]["valor_total"].isna().all()


def test_build_contract(fixtures_dir, ufs):
    v = parse_tabnet_csv(fixtures_dir / "tabnet_valor_0310.csv", "valor_total")
    q = v.rename(columns={"valor_total": "qtd_internacoes"}).assign(qtd_internacoes=10)
    d = v.rename(columns={"valor_total": "dias_permanencia"}).assign(dias_permanencia=25)
    contract = build_contract(q, v, d, "0310", ufs)
    assert list(contract.columns) == ["competencia", "uf_sigla", "subgrupo_codigo", "qtd_internacoes",
                                      "valor_total", "dias_permanencia"]
    assert set(contract["uf_sigla"]) == {"RO", "AC"}


def test_parse_tabnet_rejects_unknown_layout():
    with pytest.raises(TabnetParseError):
        parse_tabnet_csv("coluna1;coluna2\n1;2", "valor_total")


def test_formatting_ptbr():
    assert brl(1234.5) == "R$ 1.234,50"
    assert brl_compact(2_500_000) == "R$ 2,5 mi"
    assert pct(0.061, signed=True) == "+6,1%"
    assert brl(float("nan")) == "—"


def _write_config(tmp_path, **source):
    cfg = yaml.safe_load((PROJECT_ROOT / "config" / "settings.yaml").read_text(encoding="utf-8"))
    cfg["source"].update(source)
    cfg["source"]["raw_file"] = str(tmp_path / "raw.csv")
    cfg["source"]["synthetic"]["end"] = "2023-06"
    cfg["output"] = {"processed_dir": str(tmp_path / "processed"), "reports_dir": str(tmp_path / "reports")}
    cfg["reference"] = {k: str(PROJECT_ROOT / v) for k, v in cfg["reference"].items()}
    path = tmp_path / "settings.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    return path


def test_pipeline_end_to_end(tmp_path):
    settings = load_settings(_write_config(tmp_path))
    result = run(settings, regenerate=True)
    for path in result.outputs.values():
        assert path.exists(), path
    kpis = json.loads(result.outputs["kpis"].read_text(encoding="utf-8"))
    assert kpis["meses"] == 18
    assert result.quality.rows_quarantined > 0
    assert (tmp_path / "reports" / "quality_report.md").exists()
    assert "SINTÉTICA" in result.outputs["resumo"].read_text(encoding="utf-8")


def test_cli_returns_error_code_when_raw_missing(tmp_path):
    cfg = _write_config(tmp_path, type="contract_csv")
    assert main(["--config", str(cfg)]) == 1


def test_config_validation(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("source: {type: foo, raw_file: x}\n", encoding="utf-8")
    with pytest.raises(ConfigError):
        load_settings(bad)
    with pytest.raises(ConfigError):
        load_settings(tmp_path / "missing.yaml")
    shutil.rmtree(tmp_path, ignore_errors=True)

import pandas as pd
import pytest

from hcb.processing.cleaning import clean, normalize_competencia, parse_number
from hcb.processing.validation import DataQualityError, validate

UFS = {"SP", "RJ", "AC"}
SUBGROUPS = {"0310", "0303"}


@pytest.mark.parametrize(
    "value, expected",
    [("2023-01", "2023-01"), ("2023-1", "2023-01"), ("2023/07", "2023-07"), ("202312", "2023-12"),
     ("2023-13", None), ("jan/2023", None), ("", None), (None, None)],
)
def test_normalize_competencia(value, expected):
    assert normalize_competencia(value) == expected


@pytest.mark.parametrize(
    "value, expected",
    [("1234.56", 1234.56), ("1.234,56", 1234.56), ("-10", -10.0), ("", None), ("abc", None), ("-", None)],
)
def test_parse_number(value, expected):
    assert parse_number(value) == expected


def test_clean_standardizes_and_removes_exact_duplicates(raw_factory):
    raw = raw_factory([{"uf_sigla": " sp "}, {"uf_sigla": "SP"}, {"subgrupo_codigo": "310", "uf_sigla": "RJ"}])
    df, stats = clean(raw)
    assert stats.exact_duplicates_removed == 1
    assert set(df["uf_sigla"]) == {"SP", "RJ"}
    assert set(df["subgrupo_codigo"]) == {"0310"}
    assert df["valor_total"].dtype == "float64"


def _validate(df, **kw):
    params = {"max_rejected_ratio": 0.9, "min_months": 1} | kw
    return validate(df, UFS, SUBGROUPS, **params)


def test_validation_quarantines_each_error_type(raw_factory):
    raw = raw_factory([
        {},                                                   # válida
        {"uf_sigla": "XX", "competencia": "2023-02"},         # UF inválida
        {"valor_total": "", "competencia": "2023-03"},        # valor nulo
        {"valor_total": "-5", "competencia": "2023-04"},      # valor negativo
        {"qtd_internacoes": "0", "competencia": "2023-05"},   # quantidade zero
        {"subgrupo_codigo": "9999", "competencia": "2023-06"},  # subgrupo inválido
        {"competencia": "2023-99"},                           # competência inválida
    ])
    df, _ = clean(raw)
    approved, quarantine, report = _validate(df)
    assert len(approved) == 1
    assert len(quarantine) == 6
    failed = {r.name: r.failed_rows for r in report.rules}
    for rule in ["uf_valida", "valor_preenchido", "valor_nao_negativo", "qtd_positiva",
                 "subgrupo_valido", "competencia_valida"]:
        assert failed[rule] == 1, rule
    assert quarantine["motivo"].str.len().gt(0).all()


def test_conflicting_duplicate_keys_are_quarantined(raw_factory):
    df, _ = clean(raw_factory([{"valor_total": "100"}, {"valor_total": "200"}, {"competencia": "2023-02"}]))
    approved, quarantine, _ = _validate(df)
    assert len(quarantine) == 2 and len(approved) == 1


def test_warning_rules_keep_rows(raw_factory):
    df, _ = clean(raw_factory([{"dias_permanencia": ""}, {"competencia": "2023-02", "valor_total": "10"}]))
    approved, quarantine, report = _validate(df)
    assert len(approved) == 2 and quarantine.empty
    assert report.status == "APROVADO COM ALERTAS"


def test_blocking_when_rejected_ratio_exceeds_limit(raw_factory):
    df, _ = clean(raw_factory([{"uf_sigla": "XX"}, {"competencia": "2023-02"}]))
    with pytest.raises(DataQualityError, match="proporcao_rejeitada"):
        _validate(df, max_rejected_ratio=0.1)


def test_blocking_when_period_too_short(raw_factory):
    df, _ = clean(raw_factory([{}]))
    with pytest.raises(DataQualityError, match="periodo_minimo"):
        _validate(df, min_months=12)


def test_empty_input_raises():
    with pytest.raises(DataQualityError):
        _validate(pd.DataFrame(columns=["competencia"]))


def test_synthetic_issues_are_all_caught(synthetic_result, ufs, subgroups):
    raw = synthetic_result.data.astype(str).replace({"nan": "", "None": ""})
    df, stats = clean(raw)
    approved, quarantine, report = validate(df, set(ufs["uf_sigla"]), set(subgroups["subgrupo_codigo"]))
    truth = synthetic_result.ground_truth["tipo"].value_counts()
    assert stats.exact_duplicates_removed == truth["duplicata"]
    expected_quarantine = truth[["valor_nulo", "valor_negativo", "qtd_zero_com_valor", "uf_invalida"]].sum()
    assert len(quarantine) == expected_quarantine
    assert report.status in {"APROVADO", "APROVADO COM ALERTAS"}

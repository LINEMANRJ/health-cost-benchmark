"""Etapa de validação: regras de qualidade de dados em nível de linha e de conjunto.

- Regras de severidade "erro" enviam a linha para quarentena (não entram nas análises).
- Regras de severidade "alerta" mantêm a linha, mas são reportadas.
- Verificações de conjunto (cobertura temporal, volume rejeitado) podem falhar o pipeline.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from hcb.formatting import pct
from hcb.schema import KEY_COLUMNS

ERROR = "erro"
WARNING = "alerta"


class DataQualityError(RuntimeError):
    """Qualidade dos dados abaixo do mínimo aceitável para análise."""


@dataclass(frozen=True)
class Rule:
    name: str
    description: str
    severity: str
    check: Callable[[pd.DataFrame], pd.Series]  # True = linha VIOLA a regra


@dataclass
class RuleResult:
    name: str
    description: str
    severity: str
    failed_rows: int
    examples: list[dict] = field(default_factory=list)


@dataclass
class DatasetCheck:
    name: str
    description: str
    severity: str
    passed: bool
    detail: str


@dataclass
class QualityReport:
    generated_at: str
    rows_received: int
    rows_approved: int
    rows_quarantined: int
    rejected_ratio: float
    status: str
    rules: list[RuleResult]
    dataset_checks: list[DatasetCheck]

    def to_dict(self) -> dict:
        return asdict(self)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str), encoding="utf-8")


def build_rules(valid_ufs: set[str], valid_subgroups: set[str]) -> list[Rule]:
    def dup_keys(df: pd.DataFrame) -> pd.Series:
        return df.duplicated(subset=KEY_COLUMNS, keep=False) & df["competencia"].notna()

    def unit_cost(df: pd.DataFrame) -> pd.Series:
        # Avaliada só onde valor e quantidade são válidos, para não duplicar erros já reportados.
        valid = (df["qtd_internacoes"] > 0) & (df["valor_total"] >= 0)
        return (df["valor_total"] / df["qtd_internacoes"]).where(valid)

    return [
        Rule("competencia_valida", "Competência presente e no formato AAAA-MM", ERROR,
             lambda d: d["competencia"].isna()),
        Rule("uf_valida", "UF pertence à tabela de referência do IBGE", ERROR,
             lambda d: ~d["uf_sigla"].isin(valid_ufs)),
        Rule("subgrupo_valido", "Subgrupo pertence à tabela de referência SIGTAP do projeto", ERROR,
             lambda d: ~d["subgrupo_codigo"].isin(valid_subgroups)),
        Rule("qtd_preenchida", "Quantidade de internações numérica e preenchida", ERROR,
             lambda d: d["qtd_internacoes"].isna()),
        Rule("qtd_positiva", "Quantidade de internações > 0 (valor sem internação é inconsistente)", ERROR,
             lambda d: d["qtd_internacoes"].notna() & (d["qtd_internacoes"] <= 0)),
        Rule("qtd_inteira", "Quantidade de internações é número inteiro", ERROR,
             lambda d: d["qtd_internacoes"].notna() & (d["qtd_internacoes"] % 1 != 0)),
        Rule("valor_preenchido", "Valor total numérico e preenchido", ERROR,
             lambda d: d["valor_total"].isna()),
        Rule("valor_nao_negativo", "Valor total não negativo", ERROR,
             lambda d: d["valor_total"].notna() & (d["valor_total"] < 0)),
        Rule("chave_unica", "Uma única linha por competência × UF × subgrupo (sem conflito)", ERROR,
             dup_keys),
        Rule("dias_nao_negativo", "Dias de permanência não negativos", ERROR,
             lambda d: d["dias_permanencia"].notna() & (d["dias_permanencia"] < 0)),
        Rule("dias_preenchido", "Dias de permanência preenchidos (necessário p/ custo por dia)", WARNING,
             lambda d: d["dias_permanencia"].isna()),
        Rule("permanencia_plausivel", "Permanência média entre 0,5 e 60 dias", WARNING,
             lambda d: ((d["dias_permanencia"] / d["qtd_internacoes"]).lt(0.5)
                        | (d["dias_permanencia"] / d["qtd_internacoes"]).gt(60))
             & d["qtd_internacoes"].gt(0)),
        Rule("custo_unitario_plausivel", "Custo por internação entre R$ 50 e R$ 500 mil", WARNING,
             lambda d: unit_cost(d).lt(50) | unit_cost(d).gt(500_000)),
    ]


def validate(
    df: pd.DataFrame,
    valid_ufs: set[str],
    valid_subgroups: set[str],
    max_rejected_ratio: float = 0.05,
    min_months: int = 12,
) -> tuple[pd.DataFrame, pd.DataFrame, QualityReport]:
    """Aplica as regras. Retorna (aprovados, quarentena, relatório)."""
    if df.empty:
        raise DataQualityError("Nenhuma linha recebida para validação.")

    rules = build_rules(valid_ufs, valid_subgroups)
    results: list[RuleResult] = []
    error_mask = pd.Series(False, index=df.index)
    reasons = pd.Series("", index=df.index, dtype="object")

    for rule in rules:
        mask = rule.check(df).fillna(False).astype(bool)
        examples = df.loc[mask].head(3).astype(object).where(df.loc[mask].head(3).notna(), None)
        results.append(RuleResult(rule.name, rule.description, rule.severity, int(mask.sum()),
                                  examples.to_dict(orient="records")))
        if rule.severity == ERROR:
            error_mask |= mask
            reasons = reasons.where(~mask, reasons + rule.name + ";")

    quarantine = df.loc[error_mask].assign(motivo=reasons[error_mask].str.rstrip(";"))
    approved = df.loc[~error_mask].copy()
    rejected_ratio = len(quarantine) / len(df)

    months = pd.PeriodIndex(approved["competencia"], freq="M")
    checks = [_check_ratio(rejected_ratio, max_rejected_ratio)]
    checks += _check_period(months, min_months)
    checks.append(_check_uf_coverage(approved, valid_ufs))

    blocking = [c for c in checks if not c.passed and c.severity == ERROR]
    warnings = [c for c in checks if not c.passed] + [r for r in results if r.failed_rows]
    status = "FALHA" if blocking else ("APROVADO COM ALERTAS" if warnings else "APROVADO")

    report = QualityReport(
        generated_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        rows_received=len(df),
        rows_approved=len(approved),
        rows_quarantined=len(quarantine),
        rejected_ratio=round(rejected_ratio, 6),
        status=status,
        rules=results,
        dataset_checks=checks,
    )
    if blocking:
        details = "; ".join(f"{c.name}: {c.detail}" for c in blocking)
        raise DataQualityError(f"Validação bloqueante falhou — {details}")
    return approved.reset_index(drop=True), quarantine.reset_index(drop=True), report


def _check_ratio(ratio: float, limit: float) -> DatasetCheck:
    return DatasetCheck(
        "proporcao_rejeitada",
        f"Proporção de linhas em quarentena ≤ {limit:.1%}",
        ERROR,
        ratio <= limit,
        f"{pct(ratio, 3)} das linhas rejeitadas",
    )


def _check_period(months: pd.PeriodIndex, min_months: int) -> list[DatasetCheck]:
    if len(months) == 0:
        return [DatasetCheck("periodo_minimo", "Há dados aprovados", ERROR, False, "nenhuma linha aprovada")]
    full = pd.period_range(months.min(), months.max(), freq="M")
    present = set(months.unique())
    gaps = [str(p) for p in full if p not in present]
    return [
        DatasetCheck("periodo_minimo", f"Série com pelo menos {min_months} meses", ERROR,
                     len(full) >= min_months, f"{len(full)} meses ({months.min()} a {months.max()})"),
        DatasetCheck("meses_sem_lacuna", "Nenhum mês faltante na série", WARNING,
                     not gaps, "sem lacunas" if not gaps else f"meses faltantes: {', '.join(gaps)}"),
    ]


def _check_uf_coverage(df: pd.DataFrame, valid_ufs: set[str]) -> DatasetCheck:
    missing = sorted(valid_ufs - set(df["uf_sigla"].unique()))
    return DatasetCheck("cobertura_ufs", "Todas as UFs de referência presentes", WARNING,
                        not missing, "todas presentes" if not missing else f"ausentes: {', '.join(missing)}")


def _n(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def report_to_markdown(report: QualityReport) -> str:
    lines = [
        "# Relatório de qualidade dos dados",
        "",
        f"- **Gerado em:** {report.generated_at}",
        f"- **Status:** {report.status}",
        f"- **Linhas recebidas (após remoção de duplicatas exatas):** {_n(report.rows_received)}",
        f"- **Linhas aprovadas:** {_n(report.rows_approved)}",
        f"- **Linhas em quarentena:** {_n(report.rows_quarantined)} ({pct(report.rejected_ratio, 3)})",
        "",
        "## Regras por linha",
        "",
        "| Regra | Descrição | Severidade | Linhas com falha |",
        "|---|---|---|---:|",
    ]
    lines += [f"| `{r.name}` | {r.description} | {r.severity} | {_n(r.failed_rows)} |" for r in report.rules]
    lines += ["", "## Verificações do conjunto", "", "| Verificação | Severidade | Resultado | Detalhe |",
              "|---|---|---|---|"]
    lines += [f"| `{c.name}` | {c.severity} | {'ok' if c.passed else 'falhou'} | {c.detail} |"
              for c in report.dataset_checks]
    return "\n".join(lines) + "\n"

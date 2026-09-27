"""Verificação de fundamentação numérica (grounding) das respostas do agente.

Regra do agente: todo número citado deve vir de uma ferramenta. Este módulo extrai os números
da resposta (formatos brasileiros: "R$ 1.234,56", "6,1%", "35.535.036", "1,2 bi") e verifica se
cada um corresponde, com a tolerância de arredondamento, a algum valor devolvido pelas
ferramentas na mesma resposta. Números não encontrados são sinalizados para o usuário.

É uma checagem conservadora e barata (sem outro modelo): serve como alarme, não como prova.
"""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

_NUMBER = re.compile(
    r"(?P<num>[-+−]?\d{1,3}(?:\.\d{3})+(?:,\d+)?|[-+−]?\d+(?:,\d+)?|[-+−]?\d+\.\d+)"
    r"\s*(?P<suffix>%|\s?(?:bi|bilh(?:ão|ões)|mi|milh(?:ão|ões)|mil)\b)?",
    re.IGNORECASE,
)
_SCALE = {"bi": 1e9, "bilhão": 1e9, "bilhões": 1e9, "mi": 1e6, "milhão": 1e6, "milhões": 1e6, "mil": 1e3}
_PERIOD = re.compile(r"\b\d{4}[-/]\d{2}\b|\b\d{2}/\d{4}\b|\bIC\s?95\b|\bP(?:90|10|25|50|75)\b", re.IGNORECASE)
_CODE = re.compile(r"\b0[345]\d{2}\b|\b0[345]\b")  # códigos SIGTAP


@dataclass(frozen=True)
class Mention:
    text: str
    value: float
    is_percent: bool
    tolerance: float  # meia unidade da última casa exibida, na escala do valor


def _to_float(raw: str) -> tuple[float, int]:
    raw = raw.replace("−", "-")
    if "," in raw:
        int_part, dec = raw.split(",", 1)
        return float(int_part.replace(".", "") + "." + dec), len(dec)
    if re.fullmatch(r"[-+]?\d{1,3}(?:\.\d{3})+", raw):
        return float(raw.replace(".", "")), 0
    if "." in raw:
        return float(raw), len(raw.split(".", 1)[1])
    return float(raw), 0


def extract_numbers(text: str) -> list[Mention]:
    """Extrai menções numéricas relevantes, ignorando anos, competências, códigos e ordinais."""
    cleaned = _CODE.sub(" ", _PERIOD.sub(" ", text))
    cleaned = re.sub(r"\b\d+[ºª°]", " ", cleaned)
    # Janelas metodológicas ("últimos 12 meses", "média móvel de 3 meses") não são resultados.
    cleaned = re.sub(r"\b(?:3|6|12|24)\s+meses\b", " ", cleaned, flags=re.IGNORECASE)
    mentions = []
    for m in _NUMBER.finditer(cleaned):
        value, decimals = _to_float(m.group("num"))
        suffix = (m.group("suffix") or "").strip().lower()
        is_percent = suffix == "%"
        if not is_percent and not suffix and decimals == 0 and (abs(value) < 10 or 1990 <= value <= 2100):
            continue  # contagens pequenas e anos: pouco informativos e ambíguos
        scale = _SCALE.get(suffix, 1.0)
        tolerance = 0.5 * 10 ** (-decimals) * scale
        mentions.append(Mention(m.group(0).strip(), value * scale, is_percent, tolerance))
    return mentions


def _flatten(obj) -> Iterable[float]:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        yield float(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _flatten(v)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            yield from _flatten(v)


def _matches(mention: Mention, source: float) -> bool:
    # Percentuais podem vir como fração (0,061 → 6,1%) ou já em pontos percentuais.
    candidates = (source * 100, source) if mention.is_percent else (source,)
    return any(abs(sign * c - mention.value) <= mention.tolerance + 1e-9
               for c in candidates for sign in (1, -1))


def ungrounded_numbers(answer: str, tool_outputs: Iterable) -> list[str]:
    """Números citados na resposta que não aparecem em nenhuma saída de ferramenta."""
    sources = [v for out in tool_outputs for v in _flatten(out)]
    missing = []
    for mention in extract_numbers(answer):
        if not any(_matches(mention, s) for s in sources):
            missing.append(mention.text)
    return missing

"""
core.py – leitura e limpeza de arquivos (Excel ou CSV).

Tudo aqui é pandas "puro" (sem Streamlit), para poder ser testado separadamente.

Princípios (mantidos da versão anterior):
  * nunca inventar dados nem presumir que uma coluna existe: tudo é detectado a partir do conteúdo;
  * nunca descartar registros em silêncio: o que é ignorado/corrigido é contado e informado;
  * valor ausente (vazio) é diferente de zero.

Convenção de nomes: as funções que já existiam na versão anterior mantêm o nome em inglês
(read_raw, build_table, classify_column...). As funções novas têm nome em português.
"""
from __future__ import annotations

import csv
import io
import re
import unicodedata
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Utilitários de texto e números
# --------------------------------------------------------------------------- #
MISSING_TOKENS = {"", "-", "–", "—", "nan", "none", "null", "n/a", "na", "nd", "n/d", "s/i", "#n/a", "#n/d"}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def norm_text(value) -> str:
    """Texto normalizado para COMPARAR (minúsculas, sem acento, sem pontuação, espaços colapsados)."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return ""
    s = strip_accents(str(value)).lower()
    s = re.sub(r"[^a-z0-9<>]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def clean_label(value):
    """Texto para EXIBIR: tira espaços extras (inclusive espaço não separável). Vazio vira NaN."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return np.nan
    if isinstance(value, (pd.Timestamp,)) or pd.isna(value):
        return value if not pd.isna(value) else np.nan
    s = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
    return np.nan if s.lower() in MISSING_TOKENS else s


def label_str(value) -> str:
    """Converte um valor de categoria em texto (1.0 -> '1')."""
    if isinstance(value, (float, np.floating)) and float(value).is_integer():
        return str(int(value))
    return str(value)


def parse_number(value) -> float:
    """Converte número em formato brasileiro ou internacional (ou já numérico) para float. Não convertível -> NaN."""
    if value is None:
        return np.nan
    if isinstance(value, (bool, np.bool_)):
        return np.nan
    if isinstance(value, (int, float, np.integer, np.floating)):
        return float(value)
    s = str(value).replace("\xa0", " ").strip()
    if s.lower() in MISSING_TOKENS:
        return np.nan
    s = re.sub(r"(?i)r\$|%|\s", "", s)
    if not re.fullmatch(r"[-+]?[\d.,]+", s):
        return np.nan
    has_dot, has_comma = "." in s, "," in s
    if has_dot and has_comma:
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        thou = "." if dec == "," else ","
        s = s.replace(thou, "").replace(dec, ".")
    elif has_comma:
        s = s.replace(",", ".") if s.count(",") == 1 else s.replace(",", "")
    elif has_dot:
        if re.fullmatch(r"[-+]?\d{1,3}(\.\d{3})+", s):  # 1.234 ou 1.234.567 -> milhar
            s = s.replace(".", "")
        elif s.count(".") > 1:
            return np.nan
    try:
        return float(s)
    except ValueError:
        return np.nan


def fmt_num(v, decimals: int = 0, signed: bool = False) -> str:
    """Formata número no padrão brasileiro (1.234,5). Ausente aparece como '—' (nunca como 0)."""
    if v is None or pd.isna(v):
        return "—"
    s = f"{v:+,.{decimals}f}" if signed else f"{v:,.{decimals}f}"
    return s.replace(",", "X").replace(".", ",").replace("X", ".")


# --------------------------------------------------------------------------- #
# Faixa etária
# --------------------------------------------------------------------------- #
# Faixa etária: "< 30 dias", "1 ano", "2 a 4 anos", "100 anos ou mais", "12 a 17 anos"...
AGE_RE = re.compile(
    r"^\s*(<=|>=|<|>|menos de|mais de)?\s*(\d+)\s*(?:(?:a|à|-|e)\s*(\d+)\s*)?"
    r"(dias?|semanas?|meses|mes|mês|anos?)\b(?:\s*ou\s*(mais|menos))?\s*$",
    re.IGNORECASE,
)
_UNIT_DAYS = {"dia": 1, "semana": 7, "mes": 30, "mês": 30, "meses": 30, "ano": 365}


def age_sort_key(label: str):
    """Chave numérica (em dias) para ordenar faixas etárias; None se o texto não parece uma faixa etária."""
    m = AGE_RE.match(str(label))
    if not m:
        return None
    prefix, n1, _n2, unit, suffix = m.groups()
    unit = unit.lower()
    unit = unit[:-1] if unit.endswith("s") and unit not in ("meses", "mes") else unit
    key = int(n1) * _UNIT_DAYS.get(unit, 365)
    if prefix and prefix.strip() in ("<", "<=", "menos de"):
        key -= 0.5  # "< 1 ano" vem antes de "1 ano"
    if suffix and suffix.lower() == "mais":
        key += 0.25
    return float(key)


def faixa_em_anos(label) -> tuple[int, int] | None:
    """
    Intervalo fechado, em anos, de um rótulo como '10 a 14 anos' -> (10, 14) ou '12 anos' -> (12, 12).
    Devolve None quando o rótulo NÃO pode ser lido com segurança (ex.: '10 a 14' sem unidade,
    '15 anos ou mais', '< 1 ano', '6 meses'). Nunca chuta.
    """
    m = AGE_RE.match(str(label))
    if not m:
        return None
    prefix, n1, n2, unit, suffix = m.groups()
    if prefix or suffix:
        return None
    if not unit.lower().startswith("ano"):
        return None
    lo = int(n1)
    hi = int(n2) if n2 else lo
    if hi < lo:
        return None
    return lo, hi


# --------------------------------------------------------------------------- #
# Leitura (Excel e CSV)
# --------------------------------------------------------------------------- #
CSV_LABEL = "(arquivo CSV)"


def is_csv(filename: str) -> bool:
    return str(filename).lower().endswith(".csv")


def list_sheets(data: bytes, filename: str = "") -> list[str]:
    if is_csv(filename):
        return [CSV_LABEL]
    return pd.ExcelFile(io.BytesIO(data)).sheet_names


def _decode_csv(data: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("Não consegui identificar a codificação do CSV (tentei UTF-8 e Windows-1252).")


def _read_csv_raw(data: bytes) -> pd.DataFrame:
    """Lê o CSV como texto, sem cabeçalho e sem converter tipos (igual ao que fazemos com o Excel)."""
    text = _decode_csv(data)
    lines = [ln for ln in text.splitlines()[:20] if ln.strip()]
    if not lines:
        return pd.DataFrame()
    counts = {d: sum(ln.count(d) for ln in lines) for d in (";", ",", "\t", "|")}
    delim = max(counts, key=counts.get)
    if counts[delim] == 0:
        delim = ";"
    rows = [[(c if c.strip() != "" else None) for c in r] for r in csv.reader(io.StringIO(text), delimiter=delim)]
    width = max((len(r) for r in rows), default=0)
    rows = [r + [None] * (width - len(r)) for r in rows]
    return pd.DataFrame(rows, dtype=object)


def read_raw(data: bytes, sheet: str, filename: str = "") -> pd.DataFrame:
    """Lê a planilha crua (sem cabeçalho, sem conversão de tipos). O índice vira o nº da linha no arquivo."""
    if is_csv(filename):
        raw = _read_csv_raw(data)
    else:
        raw = pd.read_excel(io.BytesIO(data), sheet_name=sheet, header=None, dtype=object)
    raw.index = range(1, len(raw) + 1)
    return raw


def _is_number_like(v) -> bool:
    return not pd.isna(parse_number(v))


def guess_header_row(raw: pd.DataFrame, max_scan: int = 20) -> int:
    """Posição (0 = primeira linha da planilha) da linha de cabeçalho mais provável."""
    if raw.empty:
        return 0
    width = int(raw.head(max_scan).notna().sum(axis=1).max())
    for pos in range(min(max_scan, len(raw))):
        row = raw.iloc[pos]
        cells = row.dropna()
        if len(cells) == 0 or len(cells) < 0.6 * width:
            continue
        if all(isinstance(c, str) and not _is_number_like(c) for c in cells):
            return pos
    return 0


@dataclass
class TableInfo:
    header_row_excel: int = 1
    original_headers: dict = field(default_factory=dict)  # nome final -> cabeçalho original
    empty_rows_dropped: int = 0
    empty_cols_dropped: int = 0
    notes: list = field(default_factory=list)


def build_table(raw: pd.DataFrame, header_pos: int) -> tuple[pd.DataFrame, TableInfo]:
    """Monta o DataFrame a partir da linha de cabeçalho escolhida. Só remove linhas/colunas 100% vazias (e informa)."""
    info = TableInfo(header_row_excel=int(raw.index[header_pos]) if len(raw) else 1)
    header_vals = list(raw.iloc[header_pos]) if len(raw) else []
    body = raw.iloc[header_pos + 1:].copy()

    if body.empty:
        all_empty_rows = pd.Series(False, index=body.index)
    else:
        all_empty_rows = body.isna().all(axis=1) | body.apply(lambda r: all(pd.isna(clean_label(x)) for x in r), axis=1)
    info.empty_rows_dropped = int(all_empty_rows.sum())
    body = body[~all_empty_rows]

    names, seen = [], {}
    for i, h in enumerate(header_vals):
        h = clean_label(h)
        original = h
        if isinstance(h, str) and h.startswith("="):  # expressão do BI/Qlik no lugar do nome da coluna
            h = None
        base = h if isinstance(h, str) and h else f"Coluna {i + 1}"
        seen[base] = seen.get(base, 0) + 1
        final = base if seen[base] == 1 else f"{base} ({seen[base]})"
        names.append((final, original, h is None and isinstance(original, str)))
    body.columns = [n[0] for n in names]

    # colunas totalmente vazias
    empty_cols = [c for c in body.columns if body[c].map(clean_label).isna().all()]
    info.empty_cols_dropped = len(empty_cols)
    body = body.drop(columns=empty_cols)

    # colunas cujo cabeçalho era uma fórmula do sistema de origem: nomeia pelo conteúdo
    formula_cols = {final for final, _o, was_formula in names if was_formula and final in body.columns}
    for final, original, _wf in names:
        if final in body.columns:
            info.original_headers[final] = original if isinstance(original, str) else ""
    rename = {}
    for c in formula_cols:
        if classify_column(body[c])["kind"] == "faixa_etaria" and "Faixa etária" not in body.columns and "Faixa etária" not in rename.values():
            rename[c] = "Faixa etária"
            info.notes.append(f"O cabeçalho de '{c}' era uma fórmula do sistema de origem; a coluna foi identificada "
                              f"pelo conteúdo (faixas de idade) e nomeada 'Faixa etária'.")
        else:
            info.notes.append(f"O cabeçalho de '{c}' era uma fórmula do sistema de origem e não pôde ser identificado "
                              f"pelo conteúdo; mantive um nome genérico.")
    if rename:
        body = body.rename(columns=rename)
        info.original_headers = {rename.get(k, k): v for k, v in info.original_headers.items()}
    return body, info


# --------------------------------------------------------------------------- #
# Classificação de colunas
# --------------------------------------------------------------------------- #
KIND_LABELS = {
    "faixa_etaria": "Faixa etária",
    "numerico": "Número",
    "data": "Data",
    "texto": "Texto / categoria",
    "vazia": "Vazia",
}


def classify_column(s: pd.Series) -> dict:
    """Detecta o tipo da coluna pelo conteúdo (e não pelo nome)."""
    cleaned = s.map(clean_label)
    nn = cleaned.dropna()
    out = {"kind": "vazia", "n": 0, "text_numbers": 0, "unparsed": []}
    if nn.empty:
        return out
    out["n"] = len(nn)
    uniq = pd.Series(nn.unique())

    # 1) faixa etária
    is_age = uniq.map(lambda v: isinstance(v, str) and bool(AGE_RE.match(v)))
    if is_age.mean() >= 0.7:
        out["kind"] = "faixa_etaria"
        return out

    # 2) data (datas nativas do Excel ou texto dd/mm/aaaa)
    native_dt = nn.map(lambda v: isinstance(v, (pd.Timestamp, np.datetime64)) or hasattr(v, "year") and hasattr(v, "month"))
    if native_dt.mean() >= 0.9:
        out["kind"] = "data"
        return out

    # 3) número (inclusive número guardado como texto)
    parsed = uniq.map(parse_number)
    if parsed.notna().mean() >= 0.9:
        out["kind"] = "numerico"
        out["text_numbers"] = int(nn.map(lambda v: isinstance(v, str)).sum())
        out["unparsed"] = [str(v) for v in uniq[parsed.isna()].tolist()][:20]
        return out

    # 4) data escrita como texto
    str_vals = uniq[uniq.map(lambda v: isinstance(v, str))]
    if len(str_vals) and str_vals.str.contains(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}").mean() >= 0.9:
        dt = pd.to_datetime(str_vals, dayfirst=True, errors="coerce", format="mixed")
        if dt.notna().mean() >= 0.9:
            out["kind"] = "data"
            return out

    out["kind"] = "texto"
    return out


# --------------------------------------------------------------------------- #
# Sugestão de colunas (só uma SUGESTÃO: a pessoa sempre confirma na tela)
# --------------------------------------------------------------------------- #
# papel -> (palavras que indicam o papel, palavras que o excluem, tipos de conteúdo aceitos)
DICAS = {
    "codigo": (["codigo", "cod", "ibge"], [], ("texto", "numerico")),
    "municipio": (["municipio", "cidade"], ["codigo", "cod", "ibge"], ("texto",)),
    "quantidade": (["quantidade", "qtd", "qtde", "total", "doses aplicadas", "numero de doses", "n de doses"], [], ("numerico",)),
    "populacao": (["populacao", "habitantes", "pop"], [], ("numerico",)),
    "dose": (["dose"], ["quantidade", "qtd", "qtde", "total", "aplicadas", "numero", "n de"], ("texto", "numerico")),
    "faixa_etaria": (["faixa etaria", "idade"], [], ("faixa_etaria", "texto")),
    "vacina": (["vacina", "imunobiologico"], [], ("texto",)),
    "periodo": (["data", "periodo", "competencia", "mes", "ano", "exercicio"], [], ("data", "texto", "numerico")),
    "ano": (["ano", "exercicio"], [], ("numerico", "texto")),
}


def _tem_palavra(nome_norm: str, palavra: str) -> bool:
    if " " in palavra or len(palavra) > 4:
        return palavra in nome_norm
    return palavra in nome_norm.split()


def sugerir_colunas(tipos: dict, papeis: list[str]) -> dict:
    """
    tipos: {nome_da_coluna: tipo_detectado}; papeis: lista de papéis, na ordem de prioridade.
    Devolve {papel: coluna ou None}. Cada coluna é usada em no máximo um papel.
    """
    usados, resultado = set(), {}
    for papel in papeis:
        incluir, excluir, aceitos = DICAS[papel]
        candidatas = []
        for col, tipo in tipos.items():
            nome = norm_text(col)
            if col in usados or tipo not in aceitos:
                continue
            if any(_tem_palavra(nome, e) for e in excluir):
                continue
            if any(_tem_palavra(nome, i) for i in incluir):
                candidatas.append(col)
        if candidatas and papel == "municipio":  # entre várias, prefere a de residência (recomendação do Comitê)
            candidatas.sort(key=lambda c: 0 if "resid" in norm_text(c) else 1)
        resultado[papel] = candidatas[0] if candidatas else None
        if candidatas:
            usados.add(candidatas[0])
    return resultado


def dica_tipo_municipio(texto: str) -> str | None:
    """'residencia' ou 'ocorrencia' se o TEXTO (nome de coluna ou de arquivo) mencionar; senão None. Só uma dica."""
    n = norm_text(texto)
    if "residenc" in n:
        return "residencia"
    if "ocorrenc" in n:
        return "ocorrencia"
    return None


# --------------------------------------------------------------------------- #
# Linhas de "total" e duplicatas
# --------------------------------------------------------------------------- #
TOTAL_WORDS = {"total", "total geral", "geral", "soma", "subtotal", "totais"}


def find_total_rows(df: pd.DataFrame, text_cols: list[str]) -> pd.Series:
    """True nas linhas em que alguma coluna de texto é 'Total', 'Total geral', 'Soma'..."""
    mask = pd.Series(False, index=df.index)
    for c in text_cols:
        if c in df.columns and not pd.api.types.is_numeric_dtype(df[c]) and not pd.api.types.is_datetime64_any_dtype(df[c]):
            mask |= df[c].map(lambda v: norm_text(v) in TOTAL_WORDS)
    return mask


def exact_duplicates(df: pd.DataFrame) -> pd.DataFrame:
    """Linhas totalmente idênticas (todas as colunas). Mostra todas as ocorrências (inclusive a primeira)."""
    if df.empty:
        return df
    return df[df.duplicated(keep=False)]

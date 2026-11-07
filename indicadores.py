"""
indicadores.py – filtros, contagens, cobertura vacinal e validações.

Também é pandas "puro" (sem Streamlit), para poder ser testado separadamente.

Regras que este arquivo cumpre (estão nos testes):
  * valor ausente NUNCA vira zero (soma de tudo-vazio = vazio);
  * cobertura só é calculada com numerador e denominador informados pela pessoa e válidos;
  * percentual acima de 100% é SINALIZADO, nunca cortado em 100%;
  * município sem população, sem doses ou com população zero fica com a situação explicada.
"""
from __future__ import annotations

import re

import numpy as np
import pandas as pd

import core

NAO_INFORMADO = "não informado"

# Textos de situação da cobertura (aparecem na tabela)
S_OK = "Calculada"
S_ACIMA_100 = "Acima de 100% – revisar numerador, denominador e período"
S_SEM_CHAVE = "Município sem identificação para ligar à população"
S_SEM_POP = "População não encontrada para este município"
S_POP_ZERO = "População vazia ou zero"
S_SEM_DOSES = "Sem dados de doses nesta seleção"


# --------------------------------------------------------------------------- #
# 1. Preparar a base de doses (nomes comuns de coluna, tipos corretos)
# --------------------------------------------------------------------------- #
def _texto(s: pd.Series) -> pd.Series:
    """Texto limpo; vazio vira NaN."""
    return s.map(lambda v: np.nan if (not isinstance(v, str) and pd.isna(v)) else core.clean_label(core.label_str(v)))


def _periodo(s: pd.Series, tipo: str) -> tuple[pd.Series, int]:
    """Período como texto. Se a coluna é de data, vira 'AAAA-MM'. Devolve (serie, nº de datas não lidas)."""
    if tipo == "data":
        limpo = s.map(core.clean_label)
        dt = pd.to_datetime(limpo, dayfirst=True, errors="coerce", format="mixed")
        return dt.dt.strftime("%Y-%m"), int((dt.isna() & limpo.notna()).sum())
    return _texto(s), 0


def preparar_base(tabela: pd.DataFrame, colunas: dict, tipos: dict) -> tuple[pd.DataFrame, dict]:
    """
    tabela : a tabela lida do arquivo.
    colunas: {papel: nome da coluna} só com os papéis que EXISTEM
             (municipio, codigo, faixa, dose, vacina, periodo, quantidade).
    Devolve (base, log). O índice da base é o mesmo do arquivo (nº da linha), para poder conferir.
    Texto vazio vira 'não informado' (visível); quantidade vazia continua vazia (NÃO vira zero).
    """
    base = pd.DataFrame(index=tabela.index)
    log: dict = {}
    for papel in ("municipio", "codigo", "faixa", "dose", "vacina"):
        col = colunas.get(papel)
        if col:
            base[papel] = _texto(tabela[col])
            log[papel] = {"coluna": col, "nao_informados": int(base[papel].isna().sum())}
    col = colunas.get("periodo")
    if col:
        base["periodo"], nao_lidas = _periodo(tabela[col], tipos.get(col, "texto"))
        log["periodo"] = {"coluna": col, "nao_informados": int(base["periodo"].isna().sum()), "datas_nao_lidas": nao_lidas}
    col = colunas.get("quantidade")
    if col:
        original = tabela[col]
        vazio = original.map(core.clean_label).isna()
        qtd = original.map(core.parse_number).astype("float64")
        base["quantidade"] = qtd
        log["quantidade"] = {
            "coluna": col, "vazios": int(vazio.sum()), "nao_convertidos": int((qtd.isna() & ~vazio).sum()),
            "zeros": int((qtd == 0).sum()), "negativos": int((qtd < 0).sum()),
        }
    else:
        base["quantidade"] = 1.0  # sem coluna de quantidade: cada linha conta 1
        log["quantidade"] = {"coluna": None}
    for papel in ("municipio", "faixa", "dose", "vacina", "periodo"):
        if papel in base:
            base[papel] = base[papel].fillna(NAO_INFORMADO)
    return base, log


def codigo6(valor) -> str | None:
    """Código IBGE de município com 6 dígitos (aceita 6 ou 7; o 7º é só dígito verificador). Senão, None."""
    if valor is None or (not isinstance(valor, str) and pd.isna(valor)):
        return None
    d = re.sub(r"\D", "", core.label_str(valor))
    return d[:6] if len(d) in (6, 7) else None


def adicionar_chave(df: pd.DataFrame, usar_codigo: bool) -> pd.DataFrame:
    """
    Cria a coluna 'chave', usada para ligar o município da base de doses ao da base de população.
    Pelo código IBGE (6 dígitos) quando os DOIS arquivos têm código; senão, pelo nome (sem acento/maiúscula).
    """
    out = df.copy()
    if usar_codigo:
        out["chave"] = out["codigo"].map(codigo6)
    else:
        out["chave"] = out["municipio"].map(lambda v: None if v == NAO_INFORMADO else (core.norm_text(v) or None))
    return out


# --------------------------------------------------------------------------- #
# 2. Totais, filtros, agrupamento
# --------------------------------------------------------------------------- #
def linhas_de_total(base: pd.DataFrame) -> pd.Series:
    """True nas linhas em que alguma coluna de texto é 'Total', 'Subtotal', 'Soma'... (evita contar em dobro)."""
    cols = [c for c in ("municipio", "faixa", "dose", "vacina", "periodo") if c in base.columns]
    return core.find_total_rows(base, cols)


def aplicar_filtros(df: pd.DataFrame, filtros: dict) -> pd.DataFrame:
    """filtros: {coluna: lista de valores permitidos}. Coluna que não existe é ignorada."""
    mask = pd.Series(True, index=df.index)
    for col, valores in filtros.items():
        if col in df.columns and valores is not None:
            mask &= df[col].isin(valores)
    return df[mask]


def ordenar_rotulos(rotulos) -> list:
    """Ordena faixas etárias pela idade e períodos 'AAAA-MM' em ordem; o resto, em ordem alfabética."""
    rotulos = list(dict.fromkeys(rotulos))
    if rotulos and all(core.age_sort_key(r) is not None for r in rotulos):
        return sorted(rotulos, key=core.age_sort_key)
    return sorted(rotulos, key=lambda r: core.norm_text(r))


def agrupar(df: pd.DataFrame, por: list[str]) -> pd.DataFrame:
    """
    Soma 'quantidade' por categorias. Devolve também quantas linhas entraram e quantas estavam vazias.
    Se TODAS as quantidades do grupo estão vazias, o total é vazio (e não 0).
    """
    soma = lambda s: s.sum(min_count=1)       # noqa: E731
    vazias = lambda s: int(s.isna().sum())    # noqa: E731
    if not por:
        return pd.DataFrame({"linhas": [len(df)], "quantidade": [soma(df["quantidade"])],
                             "quantidade_vazia": [vazias(df["quantidade"])]})
    res = (df.groupby(por, dropna=False, sort=False)
             .agg(linhas=("quantidade", "size"), quantidade=("quantidade", soma), quantidade_vazia=("quantidade", vazias))
             .reset_index())
    # ordem amigável: pela primeira coluna escolhida que seja faixa etária/período; senão alfabética
    ordem = res[por].copy()
    for c in por:
        ordem[c] = ordem[c].map({r: i for i, r in enumerate(ordenar_rotulos(res[c]))})
    return res.loc[ordem.sort_values(por).index].reset_index(drop=True)


# --------------------------------------------------------------------------- #
# 3. Validações
# --------------------------------------------------------------------------- #
def combinacoes_repetidas(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    """Linhas cuja combinação de categorias aparece mais de uma vez (o app SOMA essas linhas)."""
    cols = [c for c in cols if c in df.columns]
    if not cols or df.empty:
        return df.iloc[0:0]
    return df[df.duplicated(subset=cols, keep=False)]


def faixas_sobrepostas(rotulos) -> list[tuple[str, str]]:
    """Pares de faixas etárias (em anos) que se sobrepõem, ex.: '10 a 14 anos' e '12 anos' (possível subtotal)."""
    ivs = [(r, core.faixa_em_anos(r)) for r in dict.fromkeys(rotulos)]
    ivs = [(r, iv) for r, iv in ivs if iv is not None]
    pares = []
    for i in range(len(ivs)):
        for j in range(i + 1, len(ivs)):
            (r1, (a1, b1)), (r2, (a2, b2)) = ivs[i], ivs[j]
            if a1 <= b2 and a2 <= b1:
                pares.append((r1, r2))
    return pares


def faixas_cobrem(rotulos, lo: int = 10, hi: int = 14) -> tuple[bool, str]:
    """
    As faixas escolhidas juntas correspondem EXATAMENTE a lo..hi anos (sem faltar, sobrar ou repetir idade)?
    Devolve (ok, motivo_se_não_ok). Rótulos que não dá para ler com segurança fazem o resultado ser 'não'.
    """
    rotulos = list(dict.fromkeys(rotulos))
    if not rotulos:
        return False, f"Nenhuma faixa etária selecionada (é preciso cobrir {lo} a {hi} anos)."
    itens = []
    for r in rotulos:
        iv = core.faixa_em_anos(r)
        if iv is None:
            return False, (f"Não consegui interpretar «{r}» como faixa em anos completos "
                           f"(ex.: «{lo} a {hi} anos» ou «{lo} anos»).")
        if iv[0] < lo or iv[1] > hi:
            return False, f"A faixa «{r}» inclui idades fora de {lo} a {hi} anos."
        itens.append((iv, r))
    itens.sort()
    proxima = lo
    for (a, b), r in itens:
        if a > proxima:
            return False, f"Faltam idades entre {proxima} e {a - 1} anos nas faixas escolhidas."
        if a < proxima:
            return False, f"A faixa «{r}» repete idades já incluídas em outra faixa escolhida."
        proxima = b + 1
    if proxima != hi + 1:
        return False, f"Faltam idades de {proxima} a {hi} anos nas faixas escolhidas."
    return True, ""


def anos_do_periodo(rotulos) -> set[int]:
    """Anos (4 dígitos) que aparecem nos rótulos de período, ex.: '2024-03' -> {2024}."""
    anos = set()
    for r in rotulos:
        anos.update(int(a) for a in re.findall(r"(?<!\d)((?:19|20)\d{2})(?!\d)", str(r)))
    return anos


def periodos_faltantes(df: pd.DataFrame, periodos: list[str]) -> pd.DataFrame:
    """Para cada município, em quantos dos períodos escolhidos há pelo menos uma linha (e quais faltam)."""
    linhas = []
    for municipio, g in df.groupby("municipio", sort=True):
        presentes = set(g["periodo"].unique())
        faltam = [p for p in periodos if p not in presentes]
        linhas.append({"Município": municipio, "Períodos com dados": len(periodos) - len(faltam),
                       "Períodos escolhidos": len(periodos), "Faltam": ", ".join(faltam) or "—"})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- #
# 4. População (denominador)
# --------------------------------------------------------------------------- #
def preparar_populacao(tabela: pd.DataFrame, colunas: dict) -> tuple[pd.DataFrame, dict]:
    """colunas: {papel: coluna} com municipio, codigo, populacao (obrigatória), ano, faixa (opcionais)."""
    pop = pd.DataFrame(index=tabela.index)
    log: dict = {}
    for papel in ("municipio", "codigo", "faixa", "ano"):
        col = colunas.get(papel)
        if col:
            pop[papel] = _texto(tabela[col])
    original = tabela[colunas["populacao"]]
    vazio = original.map(core.clean_label).isna()
    pop["populacao"] = original.map(core.parse_number).astype("float64")
    log["populacao"] = {"vazios": int(vazio.sum()), "nao_convertidos": int((pop["populacao"].isna() & ~vazio).sum()),
                        "zeros": int((pop["populacao"] == 0).sum()), "negativos": int((pop["populacao"] < 0).sum())}
    for papel in ("municipio", "faixa", "ano"):
        if papel in pop:
            pop[papel] = pop[papel].fillna(NAO_INFORMADO)
    return pop, log


def populacao_por_chave(pop: pd.DataFrame, usar_codigo: bool) -> pd.DataFrame:
    """Soma a população por município (útil quando a faixa 10–14 vem em idades simples). Vazio continua vazio."""
    p = adicionar_chave(pop, usar_codigo)
    p = p[p["chave"].notna()]
    if p.empty:
        return pd.DataFrame(columns=["chave", "populacao"])
    return (p.groupby("chave", sort=False)
              .agg(populacao=("populacao", lambda s: s.sum(min_count=1)))
              .reset_index())


# --------------------------------------------------------------------------- #
# 5. Cobertura
# --------------------------------------------------------------------------- #
def tabela_cobertura(df_sel: pd.DataFrame, doses: list[str], populacao: pd.DataFrame) -> pd.DataFrame:
    """
    df_sel   : base de doses JÁ filtrada por município, faixa etária (10–14), período e vacina, e já com a coluna
               'chave'. NÃO filtrada por dose.
    doses    : categorias de dose que compõem o NUMERADOR (escolhidas pela pessoa, conforme a documentação).
    populacao: DataFrame com 'chave' e 'populacao' (denominador, população-alvo de 10 a 14 anos).
    Cobertura (%) = numerador / denominador × 100. Sem corte em 100%.
    """
    pop = {r.chave: r.populacao for r in populacao.itertuples()}
    ident = df_sel["chave"].where(df_sel["chave"].notna(), "nome:" + df_sel["municipio"].astype(str))
    linhas = []
    for _id, g in df_sel.groupby(ident, sort=False):
        nome = g["municipio"].iloc[0]
        chave = g["chave"].iloc[0]
        q = g.loc[g["dose"].isin(doses), "quantidade"]
        num = q.sum(min_count=1) if len(q) else np.nan
        den = np.nan
        if pd.isna(chave):
            situacao = S_SEM_CHAVE
        elif chave not in pop:
            situacao = S_SEM_POP
        else:
            den = pop[chave]
            if pd.isna(den) or den <= 0:
                situacao, den = S_POP_ZERO, (np.nan if pd.isna(den) else den)
            elif pd.isna(num):
                situacao = S_SEM_DOSES
            else:
                situacao = S_OK
        cob = np.nan
        if situacao == S_OK:
            cob = num / den * 100
            if cob > 100:
                situacao = S_ACIMA_100
        if situacao in (S_SEM_CHAVE, S_SEM_POP, S_POP_ZERO) and pd.isna(num):
            situacao += " · " + S_SEM_DOSES.lower()
        linhas.append({"Município": nome, "Numerador": num, "Denominador (população-alvo)": den,
                       "Cobertura (%)": cob, "Situação": situacao})
    return pd.DataFrame(linhas)


# --------------------------------------------------------------------------- #
# 6. Nome de arquivo
# --------------------------------------------------------------------------- #
def nome_arquivo(*partes: str, extensao: str = "csv") -> str:
    """Nome de arquivo sem acento e sem espaços, ex.: dengue_doses_residencia_2024-01_a_2024-12.csv"""
    limpas = []
    for p in partes:
        s = re.sub(r"[^a-z0-9]+", "-", core.strip_accents(str(p)).lower()).strip("-")
        if s:
            limpas.append(s[:40])
    return "_".join(["dengue"] + limpas) + f".{extensao}"

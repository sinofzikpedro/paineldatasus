"""
Mostra, no terminal, o que há DE VERDADE em um arquivo (Excel ou CSV): abas, colunas, tipos, valores distintos e somas.
Serve para (1) conhecer a base antes de usar o painel e (2) conferir os números do painel com o arquivo original.

Como usar:
    python inspecionar_arquivo.py caminho/do/arquivo.xlsx
    python inspecionar_arquivo.py caminho/do/arquivo.csv

Não altera o arquivo. Não inventa nada: só descreve o que encontra.
"""
import sys

import pandas as pd

import core

MAX_VALORES = 25


def inspecionar(caminho: str) -> None:
    with open(caminho, "rb") as f:
        dados = f.read()
    abas = core.list_sheets(dados, caminho)
    print(f"Arquivo: {caminho}")
    print(f"Abas ({len(abas)}): {', '.join(abas)}")
    for aba in abas:
        print("\n" + "=" * 78)
        print(f"ABA: {aba}")
        bruto = core.read_raw(dados, aba, caminho)
        if bruto.empty:
            print("  (vazia)")
            continue
        pos = core.guess_header_row(bruto)
        tabela, info = core.build_table(bruto, pos)
        print(f"  Cabeçalho detectado na linha {info.header_row_excel}; {len(tabela)} linhas de dados; {tabela.shape[1]} colunas")
        print(f"  Linhas vazias ignoradas: {info.empty_rows_dropped}; colunas vazias ignoradas: {info.empty_cols_dropped}")
        for nota in info.notes:
            print("  NOTA:", nota)
        for col in tabela.columns:
            tipo = core.classify_column(tabela[col])["kind"]
            s = tabela[col]
            vazios = int(s.map(core.clean_label).isna().sum())
            print(f"\n  • {col}   [{core.KIND_LABELS.get(tipo, tipo)}]   vazios: {vazios}")
            if tipo == "numerico":
                n = s.map(core.parse_number)
                print(f"      soma: {core.fmt_num(n.sum(min_count=1), 2)} · mínimo: {core.fmt_num(n.min())} · máximo: {core.fmt_num(n.max())}"
                      f" · zeros: {int((n == 0).sum())} · não convertidos: {int((n.isna() & ~s.map(core.clean_label).isna()).sum())}")
            elif tipo == "data":
                dt = pd.to_datetime(s.map(core.clean_label), dayfirst=True, errors="coerce", format="mixed")
                print(f"      de {dt.min()} até {dt.max()}")
            else:
                valores = pd.Series(s.map(core.clean_label).dropna().map(core.label_str))
                distintos = valores.value_counts()
                print(f"      {len(distintos)} valor(es) distinto(s):")
                for v, qtd in distintos.head(MAX_VALORES).items():
                    print(f"        - {v}  ({qtd} linha(s))")
                if len(distintos) > MAX_VALORES:
                    print(f"        … e mais {len(distintos) - MAX_VALORES}")
        totais = core.find_total_rows(tabela, [c for c in tabela.columns if core.classify_column(tabela[c])["kind"] in ("texto", "faixa_etaria")])
        print(f"\n  Linhas que parecem total/subtotal: {int(totais.sum())}")
        print(f"  Linhas totalmente idênticas: {len(core.exact_duplicates(tabela))}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit("Uso: python inspecionar_arquivo.py caminho/do/arquivo")
    inspecionar(sys.argv[1])

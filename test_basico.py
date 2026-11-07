"""
Testes automáticos. Como rodar (na pasta do projeto):

    python -m unittest discover -s tests -v

ATENÇÃO: os dados abaixo são DADOS DE TESTE inventados, com números fáceis de conferir de cabeça.
Eles existem só para provar que as contas do código estão certas. Não representam nenhum município real
e nunca são usados pelo aplicativo.
"""
import os
import sys
import unittest

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import core            # noqa: E402
import indicadores as ind  # noqa: E402


class TestNumerosETextos(unittest.TestCase):
    def test_parse_number(self):
        self.assertEqual(core.parse_number("1.234"), 1234)          # ponto de milhar
        self.assertEqual(core.parse_number("1.234,5"), 1234.5)      # formato brasileiro
        self.assertEqual(core.parse_number("12,5"), 12.5)
        self.assertEqual(core.parse_number(7), 7)
        self.assertTrue(np.isnan(core.parse_number("abc")))         # não numérico -> vazio, nunca 0
        self.assertTrue(np.isnan(core.parse_number("")))
        self.assertTrue(np.isnan(core.parse_number("-")))

    def test_faixa_em_anos(self):
        self.assertEqual(core.faixa_em_anos("10 a 14 anos"), (10, 14))
        self.assertEqual(core.faixa_em_anos("12 anos"), (12, 12))
        self.assertIsNone(core.faixa_em_anos("15 anos ou mais"))   # aberta: não dá para saber o limite
        self.assertIsNone(core.faixa_em_anos("< 1 ano"))
        self.assertIsNone(core.faixa_em_anos("6 meses"))
        self.assertIsNone(core.faixa_em_anos("Total"))

    def test_codigo6(self):
        self.assertEqual(ind.codigo6("1234567"), "123456")          # 7 dígitos -> tira o verificador
        self.assertEqual(ind.codigo6(123456.0), "123456")
        self.assertIsNone(ind.codigo6("12345"))
        self.assertIsNone(ind.codigo6(np.nan))


class TestFaixaEtaria(unittest.TestCase):
    def test_cobre_exatamente_10_a_14(self):
        self.assertTrue(ind.faixas_cobrem(["10 a 14 anos"])[0])
        self.assertTrue(ind.faixas_cobrem(["10 anos", "11 anos", "12 anos", "13 anos", "14 anos"])[0])
        self.assertTrue(ind.faixas_cobrem(["10 a 11 anos", "12 a 14 anos"])[0])

    def test_nao_cobre(self):
        self.assertFalse(ind.faixas_cobrem([])[0])
        self.assertFalse(ind.faixas_cobrem(["10 a 12 anos"])[0])                 # falta 13 e 14
        self.assertFalse(ind.faixas_cobrem(["5 a 14 anos"])[0])                  # sobra idade
        self.assertFalse(ind.faixas_cobrem(["10 a 14 anos", "14 anos"])[0])      # repete 14
        self.assertFalse(ind.faixas_cobrem(["15 anos ou mais"])[0])
        self.assertFalse(ind.faixas_cobrem(["10 a 14"])[0])                      # sem unidade: não chuta

    def test_sobreposicao(self):
        self.assertEqual(ind.faixas_sobrepostas(["10 a 14 anos", "12 anos", "20 a 29 anos"]), [("10 a 14 anos", "12 anos")])
        self.assertEqual(ind.faixas_sobrepostas(["10 a 14 anos", "15 a 19 anos"]), [])


class TestLeituraCSV(unittest.TestCase):
    def test_csv_ponto_e_virgula_e_acentos_windows(self):
        # DADOS DE TESTE: CSV em Windows-1252 com ';' (formato comum de exportação brasileira)
        conteudo = "Município;Dose;Quantidade\nCidade Teste;1ª Dose;1.250\nCidade Teste;2ª Dose;\n".encode("cp1252")
        raw = core.read_raw(conteudo, core.CSV_LABEL, "teste.csv")
        tabela, info = core.build_table(raw, core.guess_header_row(raw))
        self.assertEqual(list(tabela.columns), ["Município", "Dose", "Quantidade"])
        self.assertEqual(len(tabela), 2)
        self.assertEqual(tabela.iloc[0]["Dose"], "1ª Dose")          # acento preservado
        self.assertEqual(core.classify_column(tabela["Quantidade"])["kind"], "numerico")


# --------------------------------------------------------------------------- #
# Base de teste (inventada): 3 municípios fictícios
# --------------------------------------------------------------------------- #
def base_de_teste():
    tabela = pd.DataFrame({
        "Município de residência": ["Cidade A", "Cidade A", "Cidade B", "Cidade B", "Cidade C", "Cidade C"],
        "Faixa etária": ["10 a 14 anos"] * 6,
        "Dose": ["1ª dose", "2ª dose", "1ª dose", "2ª dose", "1ª dose", "2ª dose"],
        "Quantidade": ["850", "700", "1.200", "", "300", "50"],       # Cidade B: 2ª dose VAZIA (ausente)
    })
    tipos = {c: core.classify_column(tabela[c])["kind"] for c in tabela.columns}
    colunas = {"municipio": "Município de residência", "faixa": "Faixa etária", "dose": "Dose", "quantidade": "Quantidade"}
    base, log = ind.preparar_base(tabela, colunas, tipos)
    return ind.adicionar_chave(base, usar_codigo=False), log


class TestPreparoEAgrupamento(unittest.TestCase):
    def test_ausente_nao_vira_zero(self):
        base, log = base_de_teste()
        self.assertEqual(log["quantidade"]["vazios"], 1)
        self.assertTrue(pd.isna(base.loc[base["municipio"] == "Cidade B", "quantidade"]).sum() == 1)
        tudo_vazio = base[(base["municipio"] == "Cidade B") & (base["dose"] == "2ª dose")]
        g = ind.agrupar(tudo_vazio, ["municipio"])
        self.assertTrue(pd.isna(g.loc[0, "quantidade"]))               # vazio, NÃO zero
        self.assertEqual(g.loc[0, "quantidade_vazia"], 1)

    def test_soma_por_municipio(self):
        base, _ = base_de_teste()
        g = ind.agrupar(base, ["municipio"]).set_index("municipio")
        self.assertEqual(g.loc["Cidade A", "quantidade"], 1550)       # 850 + 700
        self.assertEqual(g.loc["Cidade B", "quantidade"], 1200)       # só a 1ª dose; a 2ª está vazia
        self.assertEqual(g.loc["Cidade C", "quantidade"], 350)

    def test_sem_coluna_quantidade_conta_linhas(self):
        tabela = pd.DataFrame({"Município": ["X", "X", "Y"]})
        base, log = ind.preparar_base(tabela, {"municipio": "Município"}, {"Município": "texto"})
        self.assertIsNone(log["quantidade"]["coluna"])
        g = ind.agrupar(base, ["municipio"]).set_index("municipio")
        self.assertEqual(g.loc["X", "quantidade"], 2)

    def test_linhas_de_total(self):
        tabela = pd.DataFrame({"Município": ["X", "Y", "Total"], "Q": ["1", "2", "3"]})
        base, _ = ind.preparar_base(tabela, {"municipio": "Município", "quantidade": "Q"},
                                    {"Município": "texto", "Q": "numerico"})
        self.assertEqual(list(ind.linhas_de_total(base)), [False, False, True])

    def test_texto_vazio_vira_nao_informado(self):
        tabela = pd.DataFrame({"Município": ["X", None], "Q": ["1", "2"]})
        base, _ = ind.preparar_base(tabela, {"municipio": "Município", "quantidade": "Q"},
                                    {"Município": "texto", "Q": "numerico"})
        self.assertEqual(base.loc[1, "municipio"], ind.NAO_INFORMADO)

    def test_combinacoes_repetidas(self):
        base, _ = base_de_teste()
        extra = pd.concat([base, base.iloc[[0]]])
        self.assertEqual(len(ind.combinacoes_repetidas(extra, ["municipio", "dose"])), 2)
        self.assertEqual(len(ind.combinacoes_repetidas(base, ["municipio", "dose"])), 0)

    def test_periodo_de_data_vira_ano_mes(self):
        tabela = pd.DataFrame({"Data": ["15/03/2024", "02/04/2024", "xx"], "Q": ["1", "1", "1"]})
        base, log = ind.preparar_base(tabela, {"periodo": "Data", "quantidade": "Q"}, {"Data": "data", "Q": "numerico"})
        self.assertEqual(list(base["periodo"]), ["2024-03", "2024-04", ind.NAO_INFORMADO])
        self.assertEqual(log["periodo"]["datas_nao_lidas"], 1)


class TestCobertura(unittest.TestCase):
    def setUp(self):
        self.base, _ = base_de_teste()
        # DADOS DE TESTE: população inventada. Cidade C fica SEM população de propósito.
        self.pop = pd.DataFrame({"chave": ["cidade a", "cidade b"], "populacao": [1000.0, 0.0]})

    def test_conta_certa_e_situacoes(self):
        t = ind.tabela_cobertura(self.base, ["1ª dose"], self.pop).set_index("Município")
        self.assertAlmostEqual(t.loc["Cidade A", "Cobertura (%)"], 85.0)      # 850 / 1000
        self.assertEqual(t.loc["Cidade A", "Situação"], ind.S_OK)
        self.assertTrue(t.loc["Cidade B", "Situação"].startswith(ind.S_POP_ZERO))   # denominador zero
        self.assertTrue(pd.isna(t.loc["Cidade B", "Cobertura (%)"]))               # sem divisão por zero
        self.assertTrue(t.loc["Cidade C", "Situação"].startswith(ind.S_SEM_POP))   # sem população
        self.assertTrue(pd.isna(t.loc["Cidade C", "Cobertura (%)"]))

    def test_acima_de_100_e_sinalizado_e_nao_cortado(self):
        pop = pd.DataFrame({"chave": ["cidade a"], "populacao": [500.0]})
        t = ind.tabela_cobertura(self.base, ["1ª dose"], pop).set_index("Município")
        self.assertAlmostEqual(t.loc["Cidade A", "Cobertura (%)"], 170.0)          # 850 / 500, sem corte
        self.assertEqual(t.loc["Cidade A", "Situação"], ind.S_ACIMA_100)

    def test_dose_ausente_nao_vira_zero(self):
        pop = pd.DataFrame({"chave": ["cidade b"], "populacao": [2000.0]})
        t = ind.tabela_cobertura(self.base, ["2ª dose"], pop).set_index("Município")
        self.assertTrue(pd.isna(t.loc["Cidade B", "Numerador"]))                   # 2ª dose de B está vazia
        self.assertEqual(t.loc["Cidade B", "Situação"], ind.S_SEM_DOSES)
        self.assertTrue(pd.isna(t.loc["Cidade B", "Cobertura (%)"]))               # nunca 0%

    def test_ligacao_por_codigo(self):
        tabela = pd.DataFrame({"Cod": ["1234567", "7654321"], "Mun": ["A", "B"], "Dose": ["1ª", "1ª"], "Q": ["10", "20"]})
        base, _ = ind.preparar_base(tabela, {"codigo": "Cod", "municipio": "Mun", "dose": "Dose", "quantidade": "Q"},
                                    {c: "texto" for c in tabela.columns})
        base = ind.adicionar_chave(base, usar_codigo=True)
        pop_tab = pd.DataFrame({"Cod": ["123456", "765432"], "P": ["100", "100"]})
        pop, _ = ind.preparar_populacao(pop_tab, {"codigo": "Cod", "populacao": "P"})
        pc = ind.populacao_por_chave(pop, usar_codigo=True)
        t = ind.tabela_cobertura(base, ["1ª"], pc).set_index("Município")
        self.assertAlmostEqual(t.loc["A", "Cobertura (%)"], 10.0)
        self.assertAlmostEqual(t.loc["B", "Cobertura (%)"], 20.0)

    def test_populacao_em_idades_simples_e_somada(self):
        tabela = pd.DataFrame({"Mun": ["A"] * 5, "Idade": [f"{i} anos" for i in range(10, 15)], "P": ["10"] * 5})
        pop, _ = ind.preparar_populacao(tabela, {"municipio": "Mun", "faixa": "Idade", "populacao": "P"})
        pc = ind.populacao_por_chave(pop, usar_codigo=False)
        self.assertEqual(pc.loc[0, "populacao"], 50)


class TestPeriodos(unittest.TestCase):
    def test_anos_do_periodo(self):
        self.assertEqual(ind.anos_do_periodo(["2024-01", "2024-02", "2025-01"]), {2024, 2025})
        self.assertEqual(ind.anos_do_periodo(["jan/2024"]), {2024})
        self.assertEqual(ind.anos_do_periodo(["não informado"]), set())

    def test_periodos_faltantes(self):
        df = pd.DataFrame({"municipio": ["A", "A", "B"], "periodo": ["2024-01", "2024-02", "2024-01"]})
        t = ind.periodos_faltantes(df, ["2024-01", "2024-02"]).set_index("Município")
        self.assertEqual(t.loc["A", "Períodos com dados"], 2)
        self.assertEqual(t.loc["B", "Faltam"], "2024-02")


class TestSugestaoDeColunas(unittest.TestCase):
    def test_sugestao(self):
        tipos = {"Município de residência": "texto", "Código IBGE": "numerico", "Dose": "texto",
                 "Quantidade de doses": "numerico", "Faixa etária": "faixa_etaria"}
        s = core.sugerir_colunas(tipos, ["codigo", "municipio", "quantidade", "dose", "faixa_etaria"])
        self.assertEqual(s["codigo"], "Código IBGE")
        self.assertEqual(s["municipio"], "Município de residência")
        self.assertEqual(s["quantidade"], "Quantidade de doses")
        self.assertEqual(s["dose"], "Dose")                 # 'Quantidade de doses' não é a coluna do tipo de dose
        self.assertEqual(s["faixa_etaria"], "Faixa etária")

    def test_nada_encontrado_devolve_none(self):
        s = core.sugerir_colunas({"Coluna 1": "texto"}, ["municipio", "dose"])
        self.assertIsNone(s["municipio"])
        self.assertIsNone(s["dose"])

    def test_dica_residencia(self):
        self.assertEqual(core.dica_tipo_municipio("vacinas_Residência_2024.xlsx"), "residencia")
        self.assertEqual(core.dica_tipo_municipio("Município de ocorrência"), "ocorrencia")
        self.assertIsNone(core.dica_tipo_municipio("Município"))


class TestNomeArquivo(unittest.TestCase):
    def test_nome(self):
        self.assertEqual(ind.nome_arquivo("doses", "Residência", "2024-01 a 2024-12"),
                         "dengue_doses_residencia_2024-01-a-2024-12.csv")


if __name__ == "__main__":
    unittest.main()

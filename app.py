"""
Painel de vacinação contra a dengue – comparação entre municípios.

Como rodar:
    pip install -r requirements.txt
    streamlit run app.py

Como o arquivo está organizado (de cima para baixo, na ordem em que a tela aparece):
    1. Enviar o arquivo de doses e preencher a ficha (fonte, data de extração, critério)
    2. Conferir as colunas (o app SUGERE; você confirma)
    3. Escolher o recorte (município, idade, dose, vacina, período)
    4. Resultados em abas: dados utilizados, gráficos, cobertura, ficha/limitações e download

A lógica de dados fica em core.py (leitura/limpeza) e indicadores.py (contas). Aqui só há a tela.
"""
from __future__ import annotations

import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import core
import indicadores as ind

st.set_page_config(page_title="Vacinação contra a dengue – municípios", page_icon="💉", layout="wide")

NAO_EXISTE = "— não existe no arquivo —"
CORES = ["#0072B2", "#E69F00", "#009E73", "#CC79A7", "#56B4E9", "#D55E00", "#F0E442", "#999999"]  # paleta p/ daltônicos
REFERENCIA_PADRAO = "sao jose dos campos"   # só PRÉ-SELECIONA se existir na base; a pessoa pode trocar

# --------------------------------------------------------------------------- #
# Funções de apoio da tela
# --------------------------------------------------------------------------- #
_VER = tuple(int(x) for x in re.findall(r"\d+", st.__version__)[:2])
_LARGURA_NOVA = _VER >= (1, 50)


def mostrar_tabela(df: pd.DataFrame, **kw):
    """st.dataframe na largura toda, compatível com versões novas e antigas do Streamlit."""
    if _LARGURA_NOVA:
        st.dataframe(df, width="stretch", **kw)
    else:
        st.dataframe(df, use_container_width=True, **kw)


def mostrar_grafico(fig: go.Figure):
    if _LARGURA_NOVA:
        st.plotly_chart(fig, width="stretch")
    else:
        st.plotly_chart(fig, use_container_width=True)


def ou_nao_informado(texto: str) -> str:
    return texto.strip() or ind.NAO_INFORMADO


def csv_bytes(df: pd.DataFrame) -> bytes:
    """CSV para abrir direto no Excel em português: separador ';', decimal ',' e acentos corretos."""
    return df.to_csv(sep=";", decimal=",", index=False).encode("utf-8-sig")


@st.cache_data(show_spinner=False)
def ler_abas(dados: bytes, nome: str):
    return core.list_sheets(dados, nome)


@st.cache_data(show_spinner=False)
def ler_bruto(dados: bytes, aba: str, nome: str):
    return core.read_raw(dados, aba, nome)


@st.cache_data(show_spinner=False)
def ler_tabela(dados: bytes, aba: str, nome: str, linha_cab: int):
    bruto = core.read_raw(dados, aba, nome)
    tabela, info = core.build_table(bruto, linha_cab)
    tipos = {c: core.classify_column(tabela[c])["kind"] for c in tabela.columns}
    return tabela, info, tipos


def falhar(mensagem: str, obrigatorio: bool):
    """Mostra o erro. Se o arquivo é obrigatório, para a página; senão, só segue sem ele (devolve None)."""
    st.error(mensagem)
    if obrigatorio:
        st.stop()
    return None


def carregar_arquivo(chave: str, arquivo, obrigatorio: bool = True) -> dict | None:
    """
    Escolha de aba + linha do cabeçalho + prévia.
    Arquivo obrigatório (doses) que não serve: para a página. Opcional (população): devolve None.
    """
    dados = arquivo.getvalue()
    k = f"{chave}_{arquivo.name}_{len(dados)}"
    try:
        abas = ler_abas(dados, arquivo.name)
    except Exception as e:  # arquivo corrompido, com senha etc.
        return falhar(f"Não consegui abrir «{arquivo.name}» ({e}). Confira se é um Excel ou CSV válido e sem senha.", obrigatorio)
    if not abas:
        return falhar("Este arquivo não tem nenhuma planilha.", obrigatorio)
    aba = abas[0] if len(abas) == 1 else st.selectbox("Planilha a analisar", abas, key=f"aba_{k}")
    try:
        bruto = ler_bruto(dados, aba, arquivo.name)
    except Exception as e:
        return falhar(f"Não consegui ler a planilha «{aba}» ({e}).", obrigatorio)
    if bruto.empty:
        return falhar("A planilha escolhida está vazia.", obrigatorio)
    chute = core.guess_header_row(bruto)
    with st.expander("Opções avançadas: linha do cabeçalho"):
        linha = st.number_input("Linha do arquivo onde estão os nomes das colunas", min_value=1, max_value=len(bruto),
                                value=int(bruto.index[chute]), step=1, key=f"cab_{k}_{aba}",
                                help="Detectada automaticamente. Mude se os nomes das colunas estiverem em outra linha.")
    tabela, info, tipos = ler_tabela(dados, aba, arquivo.name, int(linha) - 1)
    if tabela.empty or tabela.shape[1] == 0:
        return falhar("Não encontrei dados abaixo da linha de cabeçalho escolhida. Ajuste a linha nas opções avançadas.", obrigatorio)
    st.caption(f"{len(tabela)} linhas de dados × {tabela.shape[1]} colunas · cabeçalho na linha {info.header_row_excel}")
    for n in info.notes:
        st.info(n)
    if info.empty_rows_dropped or info.empty_cols_dropped:
        st.warning(f"Ignorei {info.empty_rows_dropped} linha(s) e {info.empty_cols_dropped} coluna(s) totalmente vazias.")
    mostrar_tabela(tabela.head(50))
    return {"nome": arquivo.name, "tabela": tabela, "info": info, "tipos": tipos, "k": f"{k}_{aba}_{linha}"}


def escolher_coluna(rotulo: str, colunas: list[str], sugestao: str | None, key: str, ajuda: str = "") -> str | None:
    """Caixa de seleção de coluna. Devolve o nome da coluna ou None (= 'não existe no arquivo')."""
    opcoes = [NAO_EXISTE] + colunas
    escolha = st.selectbox(rotulo, opcoes, index=opcoes.index(sugestao) if sugestao in opcoes else 0, key=key, help=ajuda or None)
    return None if escolha == NAO_EXISTE else escolha


def texto_periodo(periodos: list[str]) -> str:
    """Resumo legível de uma lista de períodos escolhidos."""
    ordenados = ind.ordenar_rotulos(periodos)
    if not ordenados:
        return ind.NAO_INFORMADO
    return ordenados[0] if len(ordenados) == 1 else f"{ordenados[0]} a {ordenados[-1]} ({len(ordenados)} períodos)"


# --------------------------------------------------------------------------- #
# Cabeçalho (o título final muda depois que o arquivo é lido)
# --------------------------------------------------------------------------- #
titulo_lugar = st.empty()
titulo_lugar.title("💉 Vacinação contra a dengue – comparação entre municípios")
st.markdown(
    "Pergunta que este painel quer ajudar a investigar: "
    "**_como a cobertura da vacinação contra a dengue em São José dos Campos se compara à de municípios "
    "semelhantes no mesmo período?_**"
)
st.info(
    "**O que este painel faz hoje:** mostra as **quantidades** do seu arquivo (doses ou registros) por município, idade, dose e "
    "período. **Cobertura vacinal** só aparece quando todos os dados e definições necessários estiverem confirmados "
    "(veja a aba *Cobertura vacinal*, que lista o que falta). Quantidade de doses **não é** cobertura e **não é** número de pessoas."
)

# --------------------------------------------------------------------------- #
# 1. Arquivo de doses + ficha
# --------------------------------------------------------------------------- #
st.header("1. Enviar o arquivo de doses")
arquivo = st.file_uploader("Arquivo de vacinação (Excel .xlsx/.xls ou CSV)", type=["xlsx", "xls", "csv"], key="up_doses")
if not arquivo:
    st.info("Envie o arquivo para começar. Nenhum dado é preenchido pelo painel: tudo vem do que você enviar.")
    st.stop()
doses_arq = carregar_arquivo("doses", arquivo)

with st.container(border=True):
    st.markdown("**Ficha do arquivo** (o que você sabe sobre ele; aparece nos resultados e no CSV). "
                "Campos em branco aparecem como «não informado».")
    f1, f2 = st.columns(2)
    fonte = f1.text_input("Fonte (de onde veio o arquivo)", key="fonte",
                          help="Ex.: nome do sistema/painel e link. O painel não sabe disso sozinho.")
    extracao = f2.text_input("Data de extração", key="extracao", placeholder="dd/mm/aaaa")
    g1, g2 = st.columns(2)
    dica = core.dica_tipo_municipio(doses_arq["nome"])
    rot_criterio = {"residencia": "Município de residência (onde a pessoa mora)",
                    "ocorrencia": "Município de ocorrência (onde a dose foi aplicada)",
                    "nao_sei": "Não sei / não informado"}
    ordem = ["residencia", "ocorrencia", "nao_sei"]
    criterio = g1.selectbox("A coluna de município deste arquivo é de…", ordem, format_func=rot_criterio.get,
                            index=ordem.index(dica) if dica else 2, key=f"crit_{doses_arq['k']}",
                            help="O painel só sugere pelo nome do arquivo. Confirme na documentação da fonte.")
    if dica:
        g1.caption(f"Sugestão pelo nome do arquivo: {rot_criterio[dica].split(' (')[0]}.")
    unidade_decl = g2.selectbox("Cada número (ou cada linha) deste arquivo representa…",
                                ["doses aplicadas", "pessoas vacinadas", "ainda não sei"], index=2, key=f"un_{doses_arq['k']}",
                                help="Doses e pessoas são coisas diferentes: uma pessoa pode receber mais de uma dose.")
criterio_txt = {"residencia": "residência", "ocorrencia": "ocorrência", "nao_sei": ind.NAO_INFORMADO}[criterio]

# --------------------------------------------------------------------------- #
# 2. Colunas
# --------------------------------------------------------------------------- #
st.header("2. Conferir as colunas")
st.caption("O painel sugere colunas pelo nome e pelo conteúdo. **Confirme ou corrija.** "
           "Se uma informação não existe no arquivo, deixe «não existe» – os filtros dela não aparecerão.")
tipos = doses_arq["tipos"]
nomes_col = list(tipos)
papeis = ["municipio", "codigo", "faixa_etaria", "dose", "vacina", "periodo", "quantidade"]
sug = core.sugerir_colunas(tipos, papeis)
k = doses_arq["k"]
c1, c2, c3 = st.columns(3)
with c1:
    col_mun = escolher_coluna("Município", nomes_col, sug["municipio"], f"c_mun_{k}")
    col_cod = escolher_coluna("Código do município (IBGE)", nomes_col, sug["codigo"], f"c_cod_{k}")
    col_qtd = escolher_coluna("Quantidade (número de doses ou de pessoas)", nomes_col, sug["quantidade"], f"c_qtd_{k}",
                              "Se cada linha já é uma dose/pessoa, escolha «não existe»: o painel contará as linhas.")
with c2:
    col_faixa = escolher_coluna("Idade / faixa etária", nomes_col, sug["faixa_etaria"], f"c_faixa_{k}")
    col_dose = escolher_coluna("Tipo de dose", nomes_col, sug["dose"], f"c_dose_{k}")
with c3:
    col_vac = escolher_coluna("Vacina", nomes_col, sug["vacina"], f"c_vac_{k}")
    col_per = escolher_coluna("Data ou período", nomes_col, sug["periodo"], f"c_per_{k}")

escolhidas = [c for c in (col_mun, col_cod, col_qtd, col_faixa, col_dose, col_vac, col_per) if c]
repetidas = sorted({c for c in escolhidas if escolhidas.count(c) > 1})
if repetidas:
    st.error("A mesma coluna foi escolhida para mais de uma função: " + ", ".join(repetidas) + ". Ajuste para continuar.")
    st.stop()
if col_qtd and tipos[col_qtd] != "numerico":
    st.warning(f"A coluna «{col_qtd}» não parece numérica (tipo detectado: {core.KIND_LABELS.get(tipos[col_qtd])}). "
               "Valores não numéricos serão tratados como **vazios** (não como zero) e contados na qualidade dos dados.")
if criterio != "nao_sei" and col_mun and (core.dica_tipo_municipio(col_mun) not in (None, criterio)):
    st.warning(f"O nome da coluna «{col_mun}» sugere o critério oposto ao que você declarou na ficha. Confira.")

mapa = {"municipio": col_mun, "codigo": col_cod, "faixa": col_faixa, "dose": col_dose, "vacina": col_vac,
        "periodo": col_per, "quantidade": col_qtd}
mapa = {papel: col for papel, col in mapa.items() if col}
base_total, log = ind.preparar_base(doses_arq["tabela"], mapa, tipos)

# Linhas de total/subtotal
eh_total = ind.linhas_de_total(base_total)
ignorar_totais = False
if eh_total.any():
    ignorar_totais = st.checkbox(f"Ignorar {int(eh_total.sum())} linha(s) de total/subtotal para não contar em dobro",
                                 value=True, key=f"tot_{k}")
linhas_ignoradas = base_total[eh_total & ignorar_totais]
base = base_total[~(eh_total & ignorar_totais)]
if base.empty:
    st.error("Não sobrou nenhuma linha de dados depois de ignorar os totais.")
    st.stop()

# Título coerente com os municípios que existem de verdade na base
if "municipio" in base:
    muns_base = ind.ordenar_rotulos(base["municipio"].unique())
    if len(muns_base) <= 3:
        titulo_lugar.title("💉 Vacinação contra a dengue – " + ", ".join(muns_base))
    else:
        titulo_lugar.title(f"💉 Vacinação contra a dengue – {len(muns_base)} municípios na base")
else:
    titulo_lugar.title("💉 Vacinação contra a dengue – município não informado na base")

# --------------------------------------------------------------------------- #
# 3. Recorte
# --------------------------------------------------------------------------- #
st.header("3. Escolher o recorte")
st.caption("Só aparecem filtros de informações que existem no arquivo. O **mesmo recorte** vale para todos os municípios.")
filtros: dict[str, list[str]] = {}
cols_filtro = st.columns(3)
i_col = 0


def filtro_multiselect(papel: str, rotulo: str, padrao_todos: bool = True, limite_padrao: int = 15):
    """Cria um filtro de várias escolhas para a coluna `papel` (se existir)."""
    global i_col
    if papel not in base:
        return None
    opcoes = ind.ordenar_rotulos(base[papel].unique())
    padrao = opcoes if (padrao_todos and len(opcoes) <= limite_padrao) else []
    with cols_filtro[i_col % 3]:
        i_col += 1
        escolha = st.multiselect(f"{rotulo} ({len(opcoes)} na base)", opcoes, default=padrao, key=f"f_{papel}_{k}")
    filtros[papel] = escolha
    return escolha


mun_sel = filtro_multiselect("municipio", "Município(s)")
faixa_sel = filtro_multiselect("faixa", "Idade / faixa etária")
dose_sel = filtro_multiselect("dose", "Tipo de dose")
vac_sel = filtro_multiselect("vacina", "Vacina")
per_sel = filtro_multiselect("periodo", "Período")
for papel, escolha in filtros.items():
    if not escolha:
        st.warning("Escolha pelo menos um valor em cada filtro mostrado acima para ver resultados "
                   "(filtro vazio = nenhum dado selecionado).")
        st.stop()
if not filtros:
    st.info("O arquivo não tem município, idade, dose, vacina nem período identificados: nenhum filtro disponível.")

base_f = ind.aplicar_filtros(base, filtros)
if base_f.empty:
    st.warning("Nenhuma linha atende aos filtros escolhidos.")
    st.stop()
# Para a COBERTURA o filtro de dose não vale: o numerador escolhe as doses por conta própria (aba Cobertura).
base_cob = ind.aplicar_filtros(base, {c: v for c, v in filtros.items() if c != "dose"})

# unidade da quantidade (texto usado nos títulos)
if not col_qtd:
    unidade = "linhas (registros)"
elif unidade_decl == "doses aplicadas":
    unidade = "doses"
elif unidade_decl == "pessoas vacinadas":
    unidade = "pessoas"
else:
    unidade = "quantidade (unidade não confirmada)"

# período descrito (para a ficha, os títulos e o nome do arquivo)
if per_sel:
    periodo_txt = texto_periodo(per_sel)
else:
    periodo_txt = None
if periodo_txt is None:
    periodo_decl = st.text_input("O arquivo não tem coluna de período. Qual período ele cobre? (opcional, mas necessário para cobertura)",
                                 key=f"perdecl_{k}", placeholder="ex.: 2024 (jan a dez)")
    periodo_txt = ou_nao_informado(periodo_decl)
    periodo_declarado = bool(periodo_decl.strip())
else:
    periodo_declarado = True

# --------------------------------------------------------------------------- #
# 4. Resultados
# --------------------------------------------------------------------------- #
st.header("4. Resultados")
tab_dados, tab_graf, tab_cob, tab_ficha, tab_baixar = st.tabs(
    ["📋 Dados utilizados", "📊 Gráficos", "🎯 Cobertura vacinal", "🧾 Ficha e limitações", "⬇️ Baixar"])

# ---- agrupamento escolhido (usado por tabela, gráfico e download) ----
dims_possiveis = [p for p in ("municipio", "dose", "faixa", "vacina", "periodo") if p in base_f]
nomes_dim = {"municipio": "Município", "dose": "Tipo de dose", "faixa": "Faixa etária", "vacina": "Vacina", "periodo": "Período"}

with tab_dados:
    padrao_dims = [p for p in ("municipio", "dose") if p in dims_possiveis]
    por = st.multiselect("Separar a tabela por", dims_possiveis, default=padrao_dims, format_func=nomes_dim.get,
                         key=f"por_{k}")
    resumo = ind.agrupar(base_f, por)
    resumo_vis = resumo.rename(columns={**nomes_dim, "linhas": "Linhas do arquivo usadas",
                                        "quantidade": f"Total – {unidade}", "quantidade_vazia": "Linhas sem quantidade (vazias)"})
    st.markdown(f"**Valores utilizados** · critério de município: **{criterio_txt}** · período: **{periodo_txt}**")
    mostrar_tabela(resumo_vis, hide_index=True)
    st.caption("Célula vazia = **não informado** (não é zero). Isto é uma contagem descritiva, **não é cobertura vacinal**.")
    if not col_qtd:
        st.caption("Sem coluna de quantidade: o total é o **número de linhas** do arquivo.")

    with st.expander("✔️ Totais para conferir no arquivo original"):
        qtd_total = base_f["quantidade"].sum(min_count=1)
        st.markdown(f"- Linhas usadas depois dos filtros: **{len(base_f)}** (de {len(base)} linhas de dados no arquivo)\n"
                    f"- Total geral ({unidade}) nessas linhas: **{core.fmt_num(qtd_total)}**\n"
                    "- Para conferir: no Excel, aplique os mesmos filtros e some a coluna de quantidade. "
                    "Os números devem ser iguais.")

    with st.expander("🧼 Qualidade dos dados"):
        st.markdown(f"- Linhas de dados lidas: **{len(doses_arq['tabela'])}** · linhas vazias ignoradas: "
                    f"**{doses_arq['info'].empty_rows_dropped}** · colunas vazias ignoradas: **{doses_arq['info'].empty_cols_dropped}**")
        st.markdown(f"- Linhas de total/subtotal: **{int(eh_total.sum())}** "
                    f"({'ignoradas' if ignorar_totais else 'mantidas'})")
        if len(linhas_ignoradas):
            mostrar_tabela(linhas_ignoradas)
        for papel, info_col in log.items():
            nome_p = {"municipio": "Município", "codigo": "Código", "faixa": "Faixa etária", "dose": "Dose", "vacina": "Vacina",
                      "periodo": "Período", "quantidade": "Quantidade"}[papel]
            if papel == "quantidade":
                if info_col.get("coluna"):
                    st.markdown(f"- **{nome_p}**: {info_col['vazios']} vazio(s) (ausente ≠ zero), {info_col['nao_convertidos']} "
                                f"valor(es) não numérico(s) (viraram vazio), {info_col['zeros']} zero(s) informado(s), "
                                f"{info_col['negativos']} negativo(s).")
                    if info_col["negativos"]:
                        st.warning("Há quantidades negativas. Verifique no arquivo original (podem ser estornos ou erros).")
            else:
                extra = f", {info_col['datas_nao_lidas']} data(s) não lida(s)" if info_col.get("datas_nao_lidas") else ""
                st.markdown(f"- **{nome_p}**: {info_col['nao_informados']} linha(s) sem valor (aparecem como «não informado»){extra}.")
        outras = [c for c in ("municipio", "faixa", "dose", "vacina", "periodo") if c in base]
        rep = ind.combinacoes_repetidas(base_f, outras)
        st.markdown(f"- Linhas com a **mesma combinação** de município/faixa/dose/vacina/período: **{len(rep)}** "
                    + ("→ o painel **soma** essas linhas. Confirme se isso faz sentido (pode ser duplicidade)." if len(rep) else ""))
        if len(rep):
            mostrar_tabela(rep)
        dup_exatas = core.exact_duplicates(base_f)
        st.markdown(f"- Linhas **totalmente idênticas**: **{len(dup_exatas)}** (nada foi apagado).")
        if "faixa" in base_f:
            sobrep = ind.faixas_sobrepostas(base_f["faixa"].unique())
            if sobrep:
                st.warning("Faixas etárias que se sobrepõem (possível mistura de total com subtotal): "
                           + "; ".join(f"«{a}» e «{b}»" for a, b in sobrep))
        if "periodo" in base_f and "municipio" in base_f:
            falt = ind.periodos_faltantes(base_f, ind.ordenar_rotulos(per_sel or base_f["periodo"].unique()))
            st.markdown("- Períodos com dados em cada município:")
            mostrar_tabela(falt, hide_index=True)
            if (falt["Períodos com dados"] < falt["Períodos escolhidos"]).any():
                st.warning("Há município(s) sem dados em alguns períodos escolhidos. Comparar totais assim pode enganar.")
        if "municipio" in base_f and base_f["municipio"].eq(ind.NAO_INFORMADO).any():
            st.warning("Há linhas sem município informado.")

with tab_graf:
    if "municipio" not in base_f:
        st.info("Sem coluna de município, não há gráfico comparativo entre municípios. "
                "O gráfico por outra categoria aparece abaixo, se você escolher categorias em «Dados utilizados».")
    eixo = "municipio" if "municipio" in base_f else (por[0] if por else None)
    cor_por = next((p for p in por if p != eixo), None)
    if eixo is None:
        st.info("Escolha ao menos uma categoria em «Dados utilizados» para ver o gráfico.")
    else:
        grupos = [eixo] + ([cor_por] if cor_por else [])
        g = ind.agrupar(base_f, grupos)
        fig = go.Figure()
        if cor_por:
            for i, (nome, parte) in enumerate(g.groupby(cor_por, sort=False)):
                fig.add_bar(x=parte[eixo], y=parte["quantidade"], name=str(nome), marker_color=CORES[i % len(CORES)])
            fig.update_layout(barmode="group", legend_title_text=nomes_dim[cor_por])
        else:
            fig.add_bar(x=g[eixo], y=g["quantidade"], marker_color=CORES[0], showlegend=False)
        fig.update_layout(
            title=f"Total de {unidade} por {nomes_dim[eixo].lower()} – critério: {criterio_txt}; período: {periodo_txt}",
            yaxis_title=f"{unidade} (contagem – não é cobertura)", xaxis_title=None, height=460, margin=dict(t=70, b=40))
        mostrar_grafico(fig)
        st.caption("Contagem absoluta: municípios maiores tendem a ter números maiores. "
                   "Sem a população-alvo (denominador), **não dá para comparar municípios por esta contagem**. "
                   "Barras ausentes = sem dado (não é zero).")

# ---- Cobertura: checklist + cálculo ----
cobertura_resultados: dict[str, pd.DataFrame] = {}
with tab_cob:
    st.markdown(
        "**Cobertura vacinal = pessoas vacinadas ÷ população-alvo × 100.** Para calcular, o painel precisa que **você confirme** "
        "cada item abaixo. Enquanto algum item estiver pendente, o cálculo **não é feito** (para não gerar um número errado)."
    )
    pendencias: list[str] = []

    # 1. residência
    if criterio != "residencia":
        pendencias.append("Município **de residência**: na ficha (passo 1) o critério declarado é "
                          f"**{criterio_txt}**. A cobertura dos moradores exige dados por residência; o painel não troca um pelo outro.")
    # 2. município identificado
    if "municipio" not in base_f:
        pendencias.append("Coluna com o **nome do município** não identificada no arquivo de doses (passo 2).")
    # 3. idade 10-14
    if "faixa" in base_f:
        ok_idade, motivo_idade = ind.faixas_cobrem(faixa_sel or [])
        if not ok_idade:
            pendencias.append(f"**Idade 10 a 14 anos**: {motivo_idade} Escolha, no filtro de idade (passo 3), as faixas que juntas "
                              "formam exatamente 10 a 14 anos.")
    else:
        pendencias.append("**Idade**: o arquivo de doses não tem coluna de faixa etária. Não dá para garantir que as doses são de 10 a 14 anos.")
    # 4. período
    if not per_sel and not periodo_declarado:
        pendencias.append("**Período**: o arquivo não tem coluna de período e você não declarou qual período ele cobre (passo 3).")
    # 5. dose
    if "dose" not in base_f:
        pendencias.append("**Tipo de dose**: o arquivo não tem coluna de dose. Sem ela não dá para separar primeira dose de esquema completo.")

    st.subheader("Definição do numerador (pessoas vacinadas)")
    doses_primeira, doses_completo = [], []
    confirma_pessoas = False
    if "dose" in base_f:
        opcoes_dose = ind.ordenar_rotulos(base["dose"].unique())
        st.caption("Escolha, **conforme a documentação da fonte**, quais categorias de dose da sua base representam cada indicador. "
                   "O painel **não presume** que «2ª dose» seja esquema completo.")
        d1, d2 = st.columns(2)
        doses_primeira = d1.multiselect("Categoria(s) = **primeira dose**", opcoes_dose, key=f"d1_{k}")
        doses_completo = d2.multiselect("Categoria(s) = **esquema completo**", opcoes_dose, key=f"d2_{k}")
        fonte_def = st.text_input("Onde está a definição dessas categorias? (documento, link ou página)", key=f"defdose_{k}")
        confirma_def = st.checkbox("Confirmo que as categorias acima seguem a definição da fonte indicada.", key=f"cdef_{k}")
        confirma_pessoas = st.checkbox(
            "Confirmo que, nas categorias escolhidas, cada quantidade/linha equivale a **uma pessoa** diferente "
            "(uma pessoa não é contada duas vezes no mesmo indicador).", key=f"cpes_{k}")
        comuns = set(doses_primeira) & set(doses_completo)
        if comuns:
            pendencias.append("Categorias de dose repetidas nos dois indicadores: " + ", ".join(sorted(comuns)) + ".")
        if not doses_primeira and not doses_completo:
            pendencias.append("**Definição de dose**: escolha as categorias de primeira dose e/ou de esquema completo.")
        else:
            if not fonte_def.strip() or not confirma_def:
                pendencias.append("**Definição de dose**: indique a fonte da definição e confirme (acima).")
            if not confirma_pessoas:
                pendencias.append("**Pessoas × doses**: confirme que a quantidade das categorias escolhidas conta pessoas diferentes.")
            for rot, lista in (("primeira dose", doses_primeira), ("esquema completo", doses_completo)):
                if len(lista) > 1:
                    st.warning(f"Você somou mais de uma categoria em «{rot}». Isso só é correto se **cada pessoa aparece em uma só** "
                               "dessas categorias.")
    if unidade_decl == "ainda não sei":
        pendencias.append("**Unidade da quantidade**: na ficha (passo 1) a unidade está como «ainda não sei».")

    st.subheader("Denominador (população de 10 a 14 anos)")
    pop_chave = pd.DataFrame(columns=["chave", "populacao"])
    usar_codigo = False
    pop_fonte = pop_ref = ""
    ano_pop = None
    arq_pop = st.file_uploader("Arquivo de população-alvo (Excel ou CSV): município e população de 10 a 14 anos",
                               type=["xlsx", "xls", "csv"], key="up_pop",
                               help="O painel não traz população embutida. Você precisa fornecer uma fonte oficial.")
    if arq_pop is None:
        pendencias.append("**População de 10 a 14 anos por município e ano**: nenhum arquivo enviado. "
                          "O painel não inventa nem usa população total no lugar da população-alvo.")
    else:
        pop_arq = carregar_arquivo("pop", arq_pop, obrigatorio=False)
    if arq_pop is not None and pop_arq is None:
        pendencias.append("**População**: o arquivo enviado não pôde ser lido (veja a mensagem de erro acima).")
    if arq_pop is not None and pop_arq is not None:
        tp = pop_arq["tipos"]
        np_cols = list(tp)
        sp = core.sugerir_colunas(tp, ["codigo", "municipio", "populacao", "ano", "faixa_etaria"])
        kp = pop_arq["k"]
        p1, p2, p3 = st.columns(3)
        with p1:
            pc_mun = escolher_coluna("Município", np_cols, sp["municipio"], f"p_mun_{kp}")
            pc_cod = escolher_coluna("Código do município (IBGE)", np_cols, sp["codigo"], f"p_cod_{kp}")
        with p2:
            pc_pop = escolher_coluna("População", np_cols, sp["populacao"], f"p_pop_{kp}")
            pc_ano = escolher_coluna("Ano", np_cols, sp["ano"], f"p_ano_{kp}")
        with p3:
            pc_faixa = escolher_coluna("Idade / faixa etária", np_cols, sp["faixa_etaria"], f"p_faixa_{kp}")
        pop_fonte = st.text_input("Fonte da população (órgão, tabela, link)", key=f"popfonte_{kp}")
        pop_ref = st.text_input("Data/ano de referência da população", key=f"popref_{kp}")
        sel_pop = [c for c in (pc_mun, pc_cod, pc_pop, pc_ano, pc_faixa) if c]
        if len(sel_pop) != len(set(sel_pop)):
            pendencias.append("População: a mesma coluna foi escolhida para mais de uma função.")
        elif not pc_pop:
            pendencias.append("População: escolha a coluna com o número de habitantes.")
        elif not (pc_mun or pc_cod):
            pendencias.append("População: escolha a coluna de município ou de código.")
        else:
            map_pop = {"municipio": pc_mun, "codigo": pc_cod, "populacao": pc_pop, "ano": pc_ano, "faixa": pc_faixa}
            pop_df, log_pop = ind.preparar_populacao(pop_arq["tabela"], {p: c for p, c in map_pop.items() if c})
            if log_pop["populacao"]["nao_convertidos"] or log_pop["populacao"]["vazios"]:
                st.warning(f"População: {log_pop['populacao']['vazios']} vazio(s) e {log_pop['populacao']['nao_convertidos']} "
                           "valor(es) não numérico(s) (tratados como ausentes, não como zero).")
            if log_pop["populacao"]["zeros"] or log_pop["populacao"]["negativos"]:
                st.warning(f"População: {log_pop['populacao']['zeros']} zero(s) e {log_pop['populacao']['negativos']} negativo(s). "
                           "Esses municípios ficarão sem cobertura calculada.")
            # ano
            ano_ok = True
            if "ano" in pop_df:
                anos = ind.ordenar_rotulos(pop_df["ano"].unique())
                ano_pop = st.selectbox("Ano da população a usar", anos, key=f"anopop_{kp}")
                pop_df = pop_df[pop_df["ano"] == ano_pop]
            else:
                ano_txt = st.text_input("A população não tem coluna de ano. Qual o ano de referência? (ex.: 2024)", key=f"anotxt_{kp}")
                ano_pop = ano_txt.strip() or None
                if not ano_pop:
                    pendencias.append("População: informe o ano de referência.")
                    ano_ok = False
            # idade da população
            idade_pop_ok = True
            if "faixa" in pop_df:
                faixas_pop = ind.ordenar_rotulos(pop_df["faixa"].unique())
                faixas_pop_sel = st.multiselect("Faixas etárias da população a usar (devem formar 10 a 14 anos)", faixas_pop,
                                                key=f"faixapop_{kp}")
                idade_pop_ok, motivo_pop = ind.faixas_cobrem(faixas_pop_sel)
                if not idade_pop_ok:
                    pendencias.append(f"**População – idade**: {motivo_pop}")
                else:
                    pop_df = pop_df[pop_df["faixa"].isin(faixas_pop_sel)]
            else:
                idade_pop_ok = st.checkbox("Confirmo que esta população é **somente a de 10 a 14 anos** (não a população total).",
                                           key=f"conf1014_{kp}")
                if not idade_pop_ok:
                    pendencias.append("**População – idade**: confirme que o arquivo traz a população de 10 a 14 anos.")
            if not pop_fonte.strip():
                pendencias.append("População: informe a fonte.")
            if not pop_ref.strip():
                pendencias.append("População: informe a data/ano de referência.")
            dup_pop = core.exact_duplicates(pop_df)
            if len(dup_pop):
                st.warning(f"Há {len(dup_pop)} linhas idênticas na população. O painel soma linhas do mesmo município; confira se não há duplicidade.")
            usar_codigo = bool(col_cod and pc_cod)
            if not usar_codigo and not pc_mun:
                pendencias.append("**Ligação município × população**: não há código IBGE nos dois arquivos nem nome do município na "
                                  "população. Não há como saber qual população é de qual município.")
            else:
                pop_chave = ind.populacao_por_chave(pop_df, usar_codigo)
                if pop_chave.empty and ano_ok and idade_pop_ok:
                    pendencias.append("**População**: nenhuma linha utilizável depois do ano e da idade escolhidos.")
                st.caption("Ligação município × população feita " + (
                    "pelo **código IBGE (6 primeiros dígitos)**." if usar_codigo
                    else "pelo **nome** do município (sem acento/maiúscula). Com código nos dois arquivos, fica mais seguro."))

    # compatibilidade de período entre doses e população
    anos_doses = ind.anos_do_periodo(per_sel or [periodo_txt])
    if ano_pop and anos_doses and str(ano_pop).strip().isdigit() and int(str(ano_pop).strip()) not in anos_doses:
        st.warning(f"**Períodos diferentes:** a população é de {ano_pop}, mas o período das doses cita {sorted(anos_doses)}. "
                   "Cobertura calculada assim mistura períodos – avalie antes de interpretar.")
    elif ano_pop and not anos_doses:
        st.warning("Não consegui identificar o ano do período das doses para comparar com o ano da população. Confira manualmente.")

    st.subheader("Municípios comparados")
    ref_mun = None
    criterio_comp = ""
    if "municipio" in base_cob:
        muns_sel = ind.ordenar_rotulos(base_cob["municipio"].unique())
        padrao_ref = next((m for m in muns_sel if core.norm_text(m) == REFERENCIA_PADRAO), None)
        opcoes_ref = ["(escolher)"] + muns_sel
        ref_mun = st.selectbox("Município de referência", opcoes_ref,
                               index=opcoes_ref.index(padrao_ref) if padrao_ref else 0, key=f"ref_{k}")
        if ref_mun == "(escolher)":
            ref_mun = None
        if padrao_ref is None:
            st.caption("São José dos Campos não está entre os municípios selecionados na base.")
        criterio_comp = st.text_area(
            "Critério usado por você para escolher os municípios de comparação (aparece no resultado)", key=f"critcomp_{k}",
            placeholder="Ex.: municípios da mesma região, com população de 10 a 14 anos próxima… (o painel NÃO escolhe por você)")
        if ref_mun is None:
            pendencias.append("**Município de referência**: escolha um (acima).")
        if len(muns_sel) < 2:
            pendencias.append("**Comparação**: selecione pelo menos um município além do de referência no filtro do passo 3.")
        if not criterio_comp.strip():
            pendencias.append("**Critério de semelhança** dos municípios de comparação: descreva-o acima (o painel não o define).")
    else:
        pendencias.append("Sem coluna de município, não há comparação entre municípios.")

    tem_indicador = bool(doses_primeira) or bool(doses_completo)
    st.subheader("O que falta para calcular a cobertura")
    pendencias_gerais = [p for p in dict.fromkeys(pendencias)]
    if pendencias_gerais:
        for p in pendencias_gerais:
            st.markdown(f"- ❌ {p}")
        st.error("Cobertura **não calculada**: há itens pendentes. Resolva a lista acima. "
                 "Enquanto isso, as abas «Dados utilizados» e «Gráficos» continuam valendo como análise descritiva.")
    else:
        st.success("Todos os itens foram confirmados por você. A cobertura abaixo usa **exatamente** as definições informadas.")

    if not pendencias_gerais and tem_indicador:
        sel_cob = ind.adicionar_chave(base_cob, usar_codigo)
        for nome_ind, lista in (("Primeira dose", doses_primeira), ("Esquema completo", doses_completo)):
            if not lista:
                continue
            tabela_cob = ind.tabela_cobertura(sel_cob, lista, pop_chave)
            tabela_cob.insert(0, "Indicador", nome_ind)
            tabela_cob["Categorias de dose no numerador"] = ", ".join(lista)
            cobertura_resultados[nome_ind] = tabela_cob
            st.subheader(f"Cobertura – {nome_ind.lower()}")
            st.markdown(f"**Numerador:** {unidade} nas categorias «{', '.join(lista)}» (pessoas, conforme sua confirmação). "
                        f"**Denominador:** população de 10 a 14 anos, ano {ano_pop}, fonte: {pop_fonte}. "
                        f"**Período das doses:** {periodo_txt}. **Critério:** residência.")
            mostrar_tabela(tabela_cob.drop(columns=["Indicador", "Categorias de dose no numerador"]), hide_index=True,
                           column_config={"Cobertura (%)": st.column_config.NumberColumn(format="%.1f"),
                                          "Numerador": st.column_config.NumberColumn(format="%d"),
                                          "Denominador (população-alvo)": st.column_config.NumberColumn(format="%d")})
            if (tabela_cob["Situação"] == ind.S_ACIMA_100).any():
                st.warning("Há cobertura **acima de 100%**: o resultado foi mantido, mas é preciso revisar numerador, denominador e período.")
            if (tabela_cob["Situação"] != ind.S_OK).any():
                st.warning("Algum município não teve cobertura calculada. Veja a coluna «Situação» – células vazias não são zero.")
            plot = tabela_cob.dropna(subset=["Cobertura (%)"])
            if not plot.empty:
                fig = go.Figure(go.Bar(x=plot["Município"], y=plot["Cobertura (%)"], marker_color=CORES[0],
                                       text=plot["Cobertura (%)"].map(lambda v: core.fmt_num(v, 1) + "%"), textposition="outside"))
                fig.update_layout(title=f"Cobertura – {nome_ind.lower()} (10 a 14 anos, residência, {periodo_txt})",
                                  yaxis_title="Cobertura (%)", xaxis_title=None, height=420, margin=dict(t=70, b=40))
                mostrar_grafico(fig)
        st.caption("Diferenças entre municípios **não indicam, por si só, melhor ou pior gestão**: dependem de qualidade dos dados, "
                   "população estimada, momento da extração e outros fatores.")

# ---- Ficha e limitações ----
with tab_ficha:
    st.markdown("### Ficha dos dados")
    ficha = pd.DataFrame([
        ("Arquivo de doses", doses_arq["nome"]),
        ("Fonte", ou_nao_informado(fonte)),
        ("Data de extração", ou_nao_informado(extracao)),
        ("Critério do município", criterio_txt),
        ("Período selecionado", periodo_txt),
        ("Unidade da quantidade", unidade),
        ("Municípios selecionados", ", ".join(ind.ordenar_rotulos(base_f["municipio"].unique())) if "municipio" in base_f else ind.NAO_INFORMADO),
        ("Faixas etárias selecionadas", ", ".join(ind.ordenar_rotulos(base_f["faixa"].unique())) if "faixa" in base_f else ind.NAO_INFORMADO),
        ("Tipos de dose selecionados", ", ".join(ind.ordenar_rotulos(base_f["dose"].unique())) if "dose" in base_f else ind.NAO_INFORMADO),
        ("Vacina", ", ".join(ind.ordenar_rotulos(base_f["vacina"].unique())) if "vacina" in base_f else ind.NAO_INFORMADO),
        ("População (fonte)", ou_nao_informado(pop_fonte)),
        ("População (referência)", ou_nao_informado(pop_ref)),
        ("Critério de escolha dos municípios de comparação", ou_nao_informado(criterio_comp)),
    ], columns=["Item", "Valor"])
    mostrar_tabela(ficha, hide_index=True)
    st.markdown("### Limitações")
    st.markdown(
        "- Os dados vêm **do arquivo que você enviou**; o painel não verifica se estão corretos nem atualizados.\n"
        "- Quantidade de **doses não é** quantidade de **pessoas**; só vale como pessoas se você confirmar (aba Cobertura).\n"
        "- **Distribuição percentual de doses não é cobertura vacinal.**\n"
        "- Dados por **residência** e por **ocorrência** respondem a perguntas diferentes e **não são misturados**.\n"
        "- «2ª dose» **não é** automaticamente «esquema completo»: depende da definição da fonte.\n"
        "- Sistemas de informação podem ter atraso de registro e correções posteriores: compare apenas extrações da mesma data.\n"
        "- Linhas de total só são reconhecidas se tiverem palavras como «Total», «Subtotal» ou «Soma».\n"
        "- Diferenças entre municípios **não demonstram**, por si só, melhor ou pior gestão."
    )

# ---- Baixar ----
with tab_baixar:
    st.markdown("Os CSVs usam **«;» como separador e «,» como decimal** (abrem direto no Excel em português). "
                "Células vazias = **não informado** (não é zero).")
    meta = {"Fonte": ou_nao_informado(fonte), "Data de extração": ou_nao_informado(extracao),
            "Critério do município": criterio_txt, "Período": periodo_txt, "Unidade": unidade}
    saida = resumo_vis.copy()
    for nome_meta, valor in meta.items():
        saida[nome_meta] = valor
    st.download_button("⬇️ Baixar tabela de valores utilizados (CSV)", data=csv_bytes(saida), mime="text/csv",
                       file_name=ind.nome_arquivo("doses", criterio_txt, periodo_txt))
    if cobertura_resultados:
        cob = pd.concat(cobertura_resultados.values(), ignore_index=True)
        cob["Fonte das doses"] = ou_nao_informado(fonte)
        cob["Data de extração"] = ou_nao_informado(extracao)
        cob["Critério do município"] = criterio_txt
        cob["Período das doses"] = periodo_txt
        cob["Ano da população"] = ou_nao_informado(str(ano_pop or ""))
        cob["Fonte da população"] = ou_nao_informado(pop_fonte)
        cob["Referência da população"] = ou_nao_informado(pop_ref)
        cob["Município de referência"] = ref_mun or ind.NAO_INFORMADO
        cob["Critério de escolha dos comparados"] = ou_nao_informado(criterio_comp)
        st.download_button("⬇️ Baixar cobertura vacinal (CSV)", data=csv_bytes(cob), mime="text/csv",
                           file_name=ind.nome_arquivo("cobertura-10-14-anos", criterio_txt, periodo_txt))
    else:
        st.info("O arquivo de cobertura só fica disponível quando a cobertura puder ser calculada (veja a aba «Cobertura vacinal»).")

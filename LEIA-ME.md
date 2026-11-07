# Painel de vacinação contra a dengue – comparação entre municípios

Objetivo futuro do painel: ajudar a investigar

> *Como a cobertura da vacinação contra a dengue em São José dos Campos se compara à de municípios semelhantes no mesmo período?*

## O que o painel faz hoje (e o que ele se recusa a fazer)

**Faz sempre (análise descritiva):** lê seu arquivo de doses (Excel ou CSV), deixa você confirmar as colunas, filtra por município, idade, dose, vacina e período (só os que existem no arquivo), mostra a tabela com os valores usados, um gráfico por município e baixa o resultado em CSV.

**Faz só quando você confirma tudo (cobertura):** calcula *primeira dose* e *esquema completo* separadamente, por município, como `numerador ÷ população de 10 a 14 anos × 100`. Se faltar qualquer item, **não calcula** e mostra na aba **🎯 Cobertura vacinal** a lista do que falta.

**Nunca faz:** tratar doses como pessoas sem você confirmar; chamar distribuição percentual de "cobertura"; supor que "2ª dose" = esquema completo; misturar residência com ocorrência; escolher municípios "semelhantes"; usar população total no lugar da de 10 a 14 anos; transformar dado ausente em zero; cortar percentual em 100%.

## Como rodar

```bash
pip install -r requirements.txt
streamlit run app.py
```

O Streamlit 1.40 em diante exige Python 3.9 ou mais novo. O código foi testado aqui apenas com Python 3.13.

## Como usar (passo a passo)

1. **Enviar o arquivo de doses** e preencher a ficha: fonte, data de extração, se o município da base é de *residência* ou *ocorrência*, e se cada número é *dose* ou *pessoa*. O que ficar em branco aparece como «não informado».
2. **Conferir as colunas.** O painel sugere pelo nome e pelo conteúdo; você corrige. Se algo não existe no arquivo, escolha «não existe» e os filtros daquilo somem.
3. **Escolher o recorte** (município, idade, dose, vacina, período). O mesmo recorte vale para todos os municípios.
4. **Ver os resultados** nas abas: dados utilizados · gráficos · cobertura vacinal · ficha e limitações · baixar.

Para a cobertura você ainda precisa: enviar um arquivo de **população de 10 a 14 anos por município** (com fonte e ano), escolher quais categorias de dose são *primeira dose* e *esquema completo* (conforme a documentação da fonte), confirmar que a quantidade conta pessoas diferentes, escolher o município de referência e **escrever o critério** com que você escolheu os municípios de comparação.

## Arquivos do projeto

| Arquivo | Para que serve |
|---|---|
| `app.py` | A tela (Streamlit). Só mostra e pergunta; quase não tem conta. |
| `core.py` | Ler Excel/CSV, limpar texto e número, detectar tipo de coluna, sugerir colunas. |
| `indicadores.py` | As contas: filtros, somas, validações e cobertura. |
| `inspecionar_arquivo.py` | Mostra no terminal o que há num arquivo (abas, colunas, valores, somas). |
| `tests/test_basico.py` | Testes automáticos. |
| `versao_anterior/` | Cópia do `app.py` e `core.py` antigos (comparador A × B), para você consultar. |

## Principais mudanças (em linguagem simples)

- **Antes:** comparava dois arquivos Excel entre si (A × B) e mostrava diferenças. **Agora:** olha *municípios* dentro de um arquivo e, quando possível, calcula cobertura.
- **Mantido:** leitura de Excel com detecção do cabeçalho, limpeza de números no formato brasileiro (`1.234,5`), a regra "vazio não é zero", detecção de linhas de total, aviso de duplicidades.
- **Novo:** leitura de CSV; filtros que só aparecem se a coluna existir; ficha com fonte/extração/período; lista de pendências para a cobertura; CSV de saída com nome coerente e com a ficha repetida em cada linha.
- **Removido** (por não ajudar a responder a pergunta): comparação registro a registro e mapeamento de colunas entre dois arquivos. Está guardado em `versao_anterior/`.
- O título da página agora usa os municípios que **realmente aparecem** no arquivo (antes dizia "Taubaté" fixo).

## Como testar

```bash
python -m unittest discover -s tests -v
```

Os testes usam **dados de teste inventados** (cidades "A", "B", "C"), com números fáceis de conferir de cabeça, por exemplo: 850 doses ÷ população 1.000 = 85,0%; população zero → cobertura não calculada; dose vazia → continua vazia (nunca 0).

**Conferir com seus arquivos reais** (não depende dos testes automáticos):

1. `python inspecionar_arquivo.py seu_arquivo.xlsx` mostra abas, colunas, valores distintos e a soma de cada coluna numérica (a soma inclui linhas de total, se houver).
2. No painel, abra *Dados utilizados → Totais para conferir no arquivo original*. No Excel, aplique os mesmos filtros e some a coluna de quantidade: os números devem ser iguais.

## Funcionalidades NÃO implementadas (e por quê)

| O que | Motivo |
|---|---|
| Escolha automática de municípios "semelhantes" | Você não aprovou nenhum critério. O painel só aceita a escolha manual e registra o critério que você escrever. |
| População embutida / busca automática de população | Não foi fornecida nem confirmada nenhuma fonte; o painel não inventa valores. Você envia o arquivo. |
| Tabela pronta de "o que é esquema completo" por vacina | Depende da documentação da fonte e da vacina; você escolhe e cita a fonte. |
| Conexão direta com sistemas públicos (API) | Nenhum endpoint foi informado nem verificado. |
| Mais de um arquivo de doses ao mesmo tempo (residência + ocorrência juntos) | Para não misturar critérios, cada análise usa um arquivo por vez. Rode uma vez para cada critério. |
| Ajuste por idade fora de 10–14 / outros públicos | Fora do escopo recomendado pelo Comitê. |

## O que NÃO foi verificado

- **Seus arquivos reais não foram vistos:** só o código chegou, sem a amostra da base. Por isso o painel não assume nenhuma coluna; tudo é detectado no upload e confirmado por você. Nomes de coluna e valores de dose reais podem exigir ajuste na sugestão automática (`DICAS` em `core.py`).
- **O app foi executado apenas com um substituto simples do Streamlit** (para percorrer o código de ponta a ponta com dados de teste), não com o Streamlit de verdade, que não está instalado no ambiente de desenvolvimento. A aparência, os gráficos e o comportamento real dos botões e abas **ainda precisam ser conferidos por você** ao rodar `streamlit run app.py`.
- Só foi usado `pandas` 3.0.5 nos testes.

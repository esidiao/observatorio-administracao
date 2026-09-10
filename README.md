# Observatório Nacional da Formação em Administração

Site estático data-driven com indicadores de acesso territorial, qualidade e absorção
profissional dos cursos de Administração no Brasil.

Terceiro de uma família de projetos irmãos — e independentes:
[Observatório Nacional da Formação Farmacêutica](https://github.com/esidiao/observatorio-formacao-farmaceutica)
e [Observatório Nacional da Formação em Fonoaudiologia](https://github.com/esidiao/observatorio-fonoaudiologia).
Compartilham o método e o design system; não compartilham código, dados nem dependências.

## O que este observatório mede

| | Administração (Censo 2024) | Fonoaudiologia, para escala |
|---|---:|---:|
| Registros no Censo, rótulo CINE exato | **19.205** | 939 |
| UFs com oferta presencial | **27** de 27 | 24 |
| Municípios com oferta presencial | **688** | 83 |
| Municípios com polo de EaD | **3.085** | 618 |
| Polos de EaD (registros) | **17.011** | 793 |
| Vagas presenciais | **372.698** | 17.028 |
| Vagas EaD (atribuídas à UF-sede) | **752.523** | 12.876 |
| Capacidade total | **1.125.221** | 29.904 |
| Participação da EaD | **66,9%** | 43,1% |
| Matrículas | **652.934** | 22.996 |
| Concluintes | **76.889** | 2.027 |
| IES distintas | **1.386** | 129 |
| Cursos avaliados | **1.805** (CPC 2022) | 74 (CPC 2023) |

### A manchete é um contraste, não um número

A oferta presencial de Administração chega a **688 municípios — 12,3% do país**. Os polos
de EaD chegam a **3.085 — 55,4%**. É a mesma formação alcançando dois territórios de
tamanhos muito diferentes, e a distância entre esses dois números é o assunto deste
observatório.

Diferente do observatório de Fonoaudiologia, aqui **não há estado sem curso presencial**:
as 27 unidades da federação têm oferta. A tensão territorial é outra.

### E é uma manchete que precisa de uma ressalva em toda página

**Dois terços da capacidade do país são de cursos a distância cujas vagas o Censo registra
na sede da mantenedora, não onde o aluno estuda.** Não é lacuna de dado: é o significado
do número. Todo total que soma presencial e EaD descreve onde a vaga foi *ofertada*.

Este é o cuidado central do projeto, e ele é diferente do que os dois observatórios
anteriores exigiam. Lá as lacunas eram grandes e visíveis, e o risco era preenchê-las.
Aqui os números são enormes e quase completos — 27 UFs, 1.805 cursos avaliados, IDD em
todos eles — e o risco passa a ser **tratar como sólido o que é apenas volumoso**.

### Administração pública fica de fora

É rótulo CINE separado (3.530 registros no Censo 2024) e área de avaliação separada no
CPC 2022 (65 cursos). Fica fora deste recorte **por decisão de escopo declarada**, não por
ausência de dado.

O recorte usa **igualdade exata** sobre o rótulo CINE normalizado, nunca substring. Medido:
buscar `administra` acrescentaria 4.905 registros — 25% a mais, em silêncio.

| Rótulo capturado por substring | Registros |
|---|---:|
| Administração pública | 3.530 |
| Programas interdisciplinares abrangendo negócios, administração e direito | 1.367 |
| Programas abrangendo negócios, administração e direito em processo de definição da classificação | 8 |

## Estrutura

```
/etl                        Scripts ETL (Python): extração, índices, pipeline
/data                       Dados versionados: nacional.json, _proveniencia.json
/etl/dados                  Recortes brutos — NÃO versionados (ver .gitignore)
/site                       Gerador estático (Python/Jinja2) + templates + assets
/site/marca.py              Gera o SVG e os seis PNGs da marca
/site/dist                  Site gerado — NÃO versionar
/tests                      Portão de qualidade (GO) + integridade + verificador de fontes
/.github/workflows/ci.yml   CI: valida -> constrói -> publica
```

## Fontes

| Indicador | Fonte | Acesso |
|---|---|---|
| Oferta, vagas, matrículas, polos | Censo da Educação Superior 2024 (INEP) | HTTPS, ZIP lido por `Range` |
| CPC, IDD, ENADE, perfil docente | **CPC 2022** (INEP), área ADMINISTRAÇÃO | HTTPS |
| Administradores com vínculo formal | RAIS 2024 (MTE), CBO 2002 família **2521** | FTP `ftp.mtps.gov.br` |
| Empresas atuantes e pessoal ocupado | CEMPRE 2024 (IBGE), **agregado 9509**, nível N6 | API SIDRA |
| População e municípios | IBGE (agregado 6579; API de localidades) | HTTPS |

### O ciclo do CPC é 2022, não 2023

Administração **não** está no CPC 2023 — aquele é o ciclo da saúde e das engenharias, o
mesmo que avaliou Fonoaudiologia. Está no ciclo 2022: 1.805 cursos em 27 UFs, 1.724 com
CPC contínuo e 1.805 com IDD (cobertura praticamente total), 82.636 concluintes
participantes, 1.602 presenciais e 203 EaD.

Três diferenças de formato entre os dois ciclos, todas medidas, todas capazes de quebrar
um extrator escrito para 2023:

1. o nome do arquivo é minúsculo — `cpc_2022.xlsx`; com `CPC_2022.xlsx` o servidor responde
   404, e é fácil concluir dali que o ciclo não existe;
2. a aba chama-se `CPC 2022`, com espaço, e não `CPC_2022` com sublinhado;
3. as colunas vêm com espaço à esquerda (`' Ano'`, `' Área de Avaliação'`) — nos dois ciclos.

Por isso o extrator **procura** o nome do arquivo e o nome da aba entre candidatos, com
sondagem de três estados, em vez de montá-los com uma f-string.

### Por que dois indicadores de absorção, e não um

O ICON de Farmácia é `municípios com Farmácia Popular / municípios com oferta`. O ICAF de
Fonoaudiologia é `municípios com fonoaudiólogo no SUS`. Os dois medem uma rede pública
identificável, e **nenhum dos dois transfere**: o administrador não atua numa rede pública,
atua na economia inteira.

A pergunta equivalente — "onde existe economia formal que absorve quem se forma?" — tem
duas metades que nenhuma fonte única responde:

* **quem já foi absorvido** — RAIS, vínculos formais ativos em 31/12 na família CBO 2521.
  Produz o **IAP**: fração dos municípios da UF com ao menos um administrador
  formalmente empregado;
* **o tamanho do mercado** — CEMPRE, empresas e outras organizações atuantes e pessoal
  ocupado, por município. É o denominador que torna o IAP interpretável.

São publicados separadamente. Fundi-los num índice único exigiria um peso arbitrário entre
"tem administrador empregado" e "tem economia formal" — e peso arbitrário é estimativa
disfarçada. Foi a mesma decisão tomada no observatório de Fonoaudiologia.

### O que a investigação das fontes mediu — e corrigiu

**O CEMPRE não para em 2021.** O agregado 1685 do SIDRA para: o próprio título diz "série
encerrada em 2021". Mas a série continua no **agregado 9509**, com as mesmas oito
variáveis, o mesmo nível N6 e períodos de 2022 a 2024. Há dado municipal de 2024 — o mesmo
ano do Censo. Não há defasagem a declarar; há um agregado sucessor a usar. O verificador
semanal de fontes procura por sucessores justamente por causa disto: um agregado encerrado
envelhece em silêncio, e a limitação falsa sobreviveria por anos.

**A RAIS é viável, e cara.** Medido na edição 2024: 3,63 GB em sete arquivos `.7z`, por
região, com razão de expansão de **7,3×** — cerca de 27 GB. O formato `.7z` não é lido pela
biblioteca padrão do Python e, por ser arquivo sólido LZMA, **também não é lido por
intervalo de bytes**: todo o truque de `rede.ZipRemoto` é inútil aqui. Por isso a extração
processa uma região por vez, apaga cada uma antes da seguinte, e exige `--tmp` num disco
com espaço.

**A edição da RAIS é a que casa com o ano do CEMPRE, não a mais recente.** Em 09/09/2026 já
existe a RAIS de ano-base 2025, completa. Ela não é adotada: a densidade publicada é RAIS
sobre CEMPRE, e um quociente com numerador de 2025 e denominador de 2024 não mede nada que
se possa nomear. A edição nova aparece como novidade na verificação semanal — que é onde
uma edição nova deve aparecer. Se os anos divergirem, `administradores_por_mil_ocupados`
sai nulo e a limitação é declarada.

## Rodar localmente

```bash
pip install -r requirements.txt
```

### Gerar o site

```bash
python site/build.py
```

O site sai em `site/dist/`. Medido: **3.126 páginas em 14 segundos**, 46 MB — sendo 3.090
páginas de município, uma para cada município com curso presencial ou polo. A decisão de
gerar todas foi tomada depois de medir, não antes.

### Portões de qualidade (GO)

```bash
python etl/indices.py --autoteste
python site/estatistica.py
python site/catalogo.py
```

Conferem, respectivamente: as fórmulas dos índices contra um estado sintético calculado à
mão; Spearman, valor de p e regressão múltipla contra casos de resultado conhecido; e a
coerência interna do catálogo de indicadores.

### Testes

```bash
python tests/test_catalogo.py
python tests/test_validacao.py
python tests/test_check_fontes.py
python tests/test_acessibilidade.py   # depois de `python site/build.py`
```

Rodam como script ou sob `pytest`, se você o tiver instalado.

A auditoria de acessibilidade não é decorativa: este projeto herdou o design system dos
observatórios anteriores e **trocou a paleta inteira**. Trocar paleta é a maneira mais
fácil de reprovar em contraste sem que nada quebre na tela — o site continua bonito e
continua ilegível para parte dos leitores. O teste mede os pares que existem de fato no
CSS, confere que a escala sequencial é monotônica e verifica no HTML gerado o que só ele
prova: `caption` e `scope` nas tabelas, `alt` nas imagens, e a ordem das folhas de estilo.

## Atualizar os dados

```bash
python etl/pipeline.py --check-only               # só verifica se as fontes mudaram
python etl/pipeline.py --ano 2024 --tmp D:/_rais  # extrai, calcula, valida, publica
python etl/pipeline.py --ano 2024 --pular-rais    # sem a RAIS; o IAP fica nulo
python etl/pipeline.py --so-riqueza               # só a guarda de riqueza
python etl/serie.py --anos 2023 2024              # série histórica
```

A extração da RAIS leva perto de uma hora e precisa de cerca de **11 GB livres** no
diretório apontado por `--tmp` — o pico é o maior arquivo de região descompactado (SP, por
volta de 8 GB). O extrator confere o espaço antes de começar e aborta com a mensagem certa
em vez de encher o disco. Os agregados de cada região ficam em cache em
`etl/dados/rais_<ano>/`, então reprocessar depois de uma interrupção é instantâneo.

O pipeline encadeia extração -> índices -> enriquecimento -> **conferência de riqueza** ->
validação, e só grava se tudo passar. A conferência de riqueza compara o número de campos
por UF com o que está em `git show HEAD` e aborta se o novo resultado for mais pobre —
guarda que existe porque, no projeto de Farmácia, republicar por um caminho parcial
derrubou 33 dos 51 campos com todos os testes verdes: nenhum teste checava *presença* de
campo.

## Publicação

O deploy é **automático**: todo push na `main` que passar pelos portões vai ao ar no
GitHub Pages.

> **Uma vez por repositório, à mão:** *Settings → Pages → Build and deployment → Source:
> **GitHub Actions***. Não dá para automatizar. Criar um site do Pages exige permissão de
> administração do repositório, que o `GITHUB_TOKEN` do workflow não tem e que
> `permissions:` não sabe conceder — `pages: write` autoriza publicar num site existente,
> não criá-lo. Sem esse clique, o job `publicar` falha com *Resource not accessible by
> integration*, e o `validar` continua passando normalmente.

É uma escolha com consequência conhecida — um commit de texto republica o site. O que a
torna aceitável é que nada passa pelos portões por acidente: portão GO das fórmulas,
testes de integridade contra as âncoras do Censo e do CPC, guarda de riqueza. Um conjunto
pela metade falha antes de chegar ao Pages, e o site no ar continua sendo o último que
passou.

Para republicar sem commit novo, ou para rodar só a validação, use
**Actions → CI → Run workflow**:

| Ação | O que faz |
|---|---|
| `publicar` | valida e republica no GitHub Pages |
| `so-validar` | roda portões, testes e build; não publica |
| `verificar-fontes` | só checa se INEP, MTE ou IBGE publicaram edição nova |

A verificação de fontes também roda sozinha toda segunda-feira e abre issue quando
encontra edição nova — ou quando a verificação fica **indeterminada**, que é diferente de
não ter novidade.

## Princípio inegociável

Nenhum indicador é estimado, interpolado ou preenchido por analogia. Sem fonte oficial
para um recorte, o valor é `null` e aparece como **"sem dados"** — nunca zero, nunca média
plausível. Todo número carrega proveniência: fonte, ano e data de extração.

Há uma exceção declarada, e ela é uma medida, não um preenchimento: `administradores_rais`
vale **0** quando a RAIS varreu o município e não encontrou nenhum vínculo. Ali o zero é o
que a fonte encontrou. Município que a fonte não alcançou continua `null`.

## Autoria e direitos

**Edson Sidião de Souza Júnior** — sidiao@i9educar.com ·
[Lattes](http://lattes.cnpq.br/9464330669014306)
Farmacêutico, Mestre e Doutor em Medicina Tropical (UFG), avaliador *ad hoc*
INEP/MEC há mais de quinze anos.

O autor **não é administrador**. O que ele traz é competência em avaliação e regulação do
ensino superior, que independe do curso; o que ele não traz é a leitura de quem exerce a
profissão. Correções de método, de interpretação e de recorte vindas de administradores,
docentes e entidades da área são bem-vindas e serão creditadas.

© 2026, todos os direitos reservados sobre a obra autoral (Leis 9.610/1998 e
9.609/1998). Os **dados primários** são públicos e pertencem ao INEP, ao Ministério do
Trabalho e Emprego e ao IBGE; os **indicadores calculados** são liberados para reúso com
citação.

Termos completos, forma de citação e registro de anterioridade em
[`DIREITOS.md`](DIREITOS.md). Ver também [`SECURITY.md`](SECURITY.md) e a
página de aviso legal do site.

"""
etl/extrair_absorcao.py
Absorção profissional: onde existe economia formal que emprega administradores.

Uso:
    python etl/extrair_absorcao.py                    # CEMPRE + RAIS
    python etl/extrair_absorcao.py --pular-rais       # só CEMPRE (rápido)
    python etl/extrair_absorcao.py --tmp D:\\_rais     # onde descompactar a RAIS

Saída: data/absorcao.json — por município (código IBGE de 6 dígitos).

POR QUE O ICON DE FARMÁCIA E O ICAF DE FONOAUDIOLOGIA NÃO TRANSFEREM
---------------------------------------------------------------------
O ICON de Farmácia é `municípios com Farmácia Popular / municípios com oferta`.
O ICAF de Fonoaudiologia é `municípios com vínculo de fonoaudiólogo no SUS`.
Os dois medem uma rede pública identificável, e nenhum dos dois serve aqui: o
administrador não atua numa rede pública, atua na economia inteira. A pergunta
equivalente é "onde existe atividade econômica formal que absorve quem se
forma?", e ela tem duas metades que nenhuma fonte única responde.

DUAS FONTES, DUAS PERGUNTAS, NENHUMA FUSÃO
-------------------------------------------
  RAIS (Ministério do Trabalho) — QUEM JÁ FOI ABSORVIDO
      Vínculos formais ativos em 31/12 com CBO 2002 da família 2521
      (Administradores). Municipal. É o análogo direto do CBO 2238 que o
      observatório de Fonoaudiologia usou para a força de trabalho no SUS.
      Produz o IAP: fração dos municípios da UF com ao menos um administrador
      formalmente empregado.

  CEMPRE / Cadastro Central de Empresas (IBGE) — O TAMANHO DO MERCADO
      Empresas e outras organizações atuantes e pessoal ocupado total, por
      município. Dá o denominador que torna o IAP interpretável: um município
      sem administrador formal e com trinta empresas não é o mesmo caso que um
      município sem administrador formal e com trezentas.

As duas são publicadas separadamente, cada uma com sua escala. Fundi-las num
índice único exigiria um peso arbitrário entre "tem administrador empregado" e
"tem economia formal" — e peso arbitrário é estimativa disfarçada. Foi a mesma
decisão tomada no observatório de Fonoaudiologia entre força de trabalho e rede
especializada.

O QUE A INVESTIGAÇÃO DA FONTE MEDIU, E CORRIGIU
------------------------------------------------
1. O CEMPRE NÃO PARA EM 2021. O agregado 1685 do SIDRA para mesmo em 2021 —
   o próprio título diz "série encerrada em 2021". Mas a série continua no
   agregado 9509, com os mesmos oito indicadores, o mesmo nível N6 e períodos
   2022 a 2024. Ou seja: há dado municipal de 2024, o MESMO ano do Censo. Não
   há defasagem a declarar; há um agregado sucessor a usar. Medido: 5.570
   municípios com valor, resposta em 1,3 s.

2. A RAIS É VIÁVEL, MAS NÃO É LEVE, E O CUSTO É DE FORMATO. Medido em
   09/09/2026, na edição 2024 (publicada em 18/05/2026):
       · 8 arquivos `.7z` somando 3,77 GB — por REGIÃO, não por UF;
       · razão de expansão medida de 7,3x, o que dá cerca de 27 GB;
       · `.7z` não é lido pela biblioteca padrão do Python e, por ser um
         arquivo sólido LZMA, também não é lido por intervalo de bytes — todo
         o truque de `rede.ZipRemoto` é inútil aqui. Exige `py7zr` e o arquivo
         inteiro em disco.
   Por isso a extração processa UMA região por vez e apaga cada uma antes de
   passar à seguinte, e por isso `--tmp` existe: o pico é o maior arquivo
   descompactado (SP, cerca de 8 GB) e ele não cabe em qualquer disco.

3. A LISTAGEM DO FTP VEM EM LATIN-1. `ftplib` decodifica em UTF-8 por padrão e
   estoura em UnicodeDecodeError antes de listar qualquer coisa. `FTP.encoding`
   tem de ser trocado ANTES do login.

4. HÁ EDIÇÃO DA RAIS MAIS NOVA QUE O CENSO, E ELA NÃO É ADOTADA SOZINHA.
   Em 09/09/2026 o FTP já publica a RAIS de ano-base 2025 (13/05/2026),
   completa: as sete regiões e o cadastro de estabelecimentos. Mesmo assim o
   padrão deste extrator é a edição que CASA COM O ANO DO CEMPRE, e não a mais
   recente. A razão é aritmética, não conservadorismo: a densidade publicada é
   `administradores RAIS / pessoal ocupado CEMPRE`, e um quociente cujo
   numerador é de 2025 e cujo denominador é de 2024 não mede nada que se possa
   nomear. Enquanto o CEMPRE parar em 2024, a RAIS lida aqui é a de 2024.
   A edição nova não é ignorada: ela aparece como NOVIDADE na verificação
   semanal de fontes, que é onde uma edição nova deve aparecer — não numa
   troca silenciosa de ano no meio de um ciclo.

   Os diretórios "2023 Parcial" e "2024 Parcial" existem no mesmo lugar e são
   edições incompletas. O filtro só aceita nomes de quatro dígitos, o que os
   exclui pela forma, não por lista.

NEM TODO CÓDIGO DA RAIS É UM MUNICÍPIO
---------------------------------------
O arquivo `RAIS_VINC_PUB_NI` é o dos vínculos sem unidade da federação
identificada, e neles o município vem como `999999`. Medido na edição 2024: 39
administradores ativos nessa condição. Eles são reais — só não têm onde ser
postos no mapa.

Ficam FORA do conjunto municipal e são declarados na proveniência como
`administradores_sem_municipio`. Deixá-los no conjunto inflaria a contagem de
"municípios com administrador" em um município que não existe; descartá-los em
silêncio faria o total nacional não fechar com a fonte. Nenhuma das duas.

MUNICÍPIO AUSENTE DA FONTE NÃO É MUNICÍPIO COM ZERO
----------------------------------------------------
O CEMPRE devolve 5.570 municípios; o IBGE reconhece 5.571 desde a instalação de
Boa Esperança do Norte (MT) em 01/01/2025. O município que não está na fonte sai
com `None`, não com 0 — dizer "zero empresas" sobre um município que a pesquisa
sequer visitou é inventar dado. Já um município que a RAIS visitou e no qual não
há nenhum administrador vinculado sai com 0, porque aí o zero é a medida.

E há o caso simétrico, que a extração de 2024 encontrou: Boa Esperança do Norte
(MT), código 510183, ESTÁ na RAIS e NÃO está no CEMPRE. Ele sai com contagem de
administradores e sem contagem de empresas — cada campo com o que sua fonte
sabe, e nenhum campo preenchido pelo outro.
"""
import argparse
import csv
import json
import os
import shutil
import socket
import sys
import time
from collections import defaultdict
from datetime import date
from ftplib import FTP
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rede import ler_json  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DADOS = REPO / "etl" / "dados"
DATA = REPO / "data"

# --------------------------------------------------------------------------- #
# CEMPRE — IBGE/SIDRA
# --------------------------------------------------------------------------- #

# 1685 é a série encerrada em 2021; 9509 é a continuação, 2022 a 2024, com as
# mesmas variáveis e o mesmo nível municipal. O código do agregado é parâmetro
# porque ele MUDA quando o IBGE fecha e reabre a série — foi o que aconteceu
# aqui, e uma constante fixa envelheceria em silêncio.
AGREGADO_CEMPRE = 9509
VAR_EMPRESAS = 367          # Número de empresas e outras organizações atuantes
VAR_PESSOAL = 707           # Pessoal ocupado total
API_CEMPRE = ("https://servicodados.ibge.gov.br/api/v3/agregados/{agregado}/"
              "periodos/{periodo}/variaveis/{variaveis}?localidades=N6[all]")
API_META = "https://servicodados.ibge.gov.br/api/v3/agregados/{agregado}/metadados"


def _valor(bruto):
    """Texto do SIDRA -> int, ou None. '-', '...' e 'X' são ausência, não zero."""
    texto = str(bruto or "").strip().replace(".", "")
    if texto.lstrip("-").isdigit():
        return int(texto)
    return None


def extrair_cempre(agregado=AGREGADO_CEMPRE, periodo="-1"):
    """{codigo6: {empresas, pessoal_ocupado}} mais os metadados da consulta."""
    meta = ler_json(API_META.format(agregado=agregado))
    url = API_CEMPRE.format(agregado=agregado, periodo=periodo,
                            variaveis=f"{VAR_EMPRESAS}|{VAR_PESSOAL}")
    print(f"[CEMPRE] agregado {agregado} — {meta['nome'][:70]}...")
    inicio = time.time()
    blocos = ler_json(url, timeout=300)

    por_municipio = defaultdict(dict)
    ano = None
    for bloco in blocos:
        chave = ("empresas" if int(bloco["id"]) == VAR_EMPRESAS
                 else "pessoal_ocupado")
        for serie in bloco["resultados"][0]["series"]:
            codigo = str(serie["localidade"]["id"])[:6]
            for periodo_serie, bruto in serie["serie"].items():
                ano = periodo_serie
                por_municipio[codigo][chave] = _valor(bruto)

    print(f"[CEMPRE] {len(por_municipio)} municípios, ano {ano}, "
          f"em {time.time() - inicio:.1f}s")
    metadados = {
        "fonte": "Cadastro Central de Empresas — CEMPRE (IBGE)",
        "agregado": agregado,
        "agregado_nome": meta["nome"],
        "variaveis": {VAR_EMPRESAS: "Número de empresas e outras organizações "
                                    "atuantes",
                      VAR_PESSOAL: "Pessoal ocupado total"},
        "nivel": "N6 (município)",
        "ano": ano,                       # do RETORNO, não do calendário
        "periodicidade": meta["periodicidade"],
        "municipios_na_fonte": len(por_municipio),
        "url": url,
        "extraido_em": date.today().isoformat(),
    }
    return dict(por_municipio), metadados


# --------------------------------------------------------------------------- #
# RAIS — Ministério do Trabalho e Emprego
# --------------------------------------------------------------------------- #

HOST_RAIS = "ftp.mtps.gov.br"
DIR_RAIS = "/pdet/microdados/RAIS/{ano}"

# Família 2521 da CBO 2002 — Administradores. O filtro é por PREFIXO de família,
# não pelo código de ocupação: se a CBO abrir uma ocupação nova na família, ela
# entra sozinha. Os códigos efetivamente encontrados são registrados na
# proveniência, para que a afirmação "só existe 252105" seja um dado medido em
# cada edição e não uma suposição herdada.
FAMILIA_CBO = "2521"

COL_CBO = "CBO 2002 Ocupação"
COL_MUNICIPIO = "Município - "
COL_ATIVO = "Vínculo Ativo"

# `csv` do arquivo da RAIS: separador VÍRGULA (não ponto e vírgula, como no
# INEP), aspas duplas, latin-1. Campos longos existem.
csv.field_size_limit(1 << 24)


def _ftp():
    """
    Conexão FTP anônima com a codificação certa.

    `encoding` tem de ser trocada ANTES do login: a saudação e a resposta do
    USER já vêm em latin-1, e a decodificação padrão em UTF-8 estoura em
    UnicodeDecodeError antes de a sessão existir.
    """
    f = FTP(HOST_RAIS, timeout=300)
    f.encoding = "latin-1"
    f.login()
    return f


def listar_edicoes_rais():
    """Anos disponíveis no diretório da RAIS, do mais recente para o mais antigo."""
    f = _ftp()
    try:
        f.cwd("/pdet/microdados/RAIS")
        nomes = f.nlst()
    finally:
        f.close()
    anos = sorted((n for n in nomes if n.isdigit() and len(n) == 4), reverse=True)
    return anos


def _arquivos_da_edicao(ano):
    f = _ftp()
    try:
        f.cwd(DIR_RAIS.format(ano=ano))
        f.voidcmd("TYPE I")
        nomes = [n for n in f.nlst() if n.upper().endswith(".7Z")
                 and "VINC" in n.upper()]
        tamanhos = {}
        for nome in nomes:
            try:
                tamanhos[nome] = f.size(nome)
            except Exception:                                  # noqa: BLE001
                tamanhos[nome] = None
    finally:
        f.close()
    return sorted(nomes), tamanhos


def _baixar_ftp(ano, nome, destino):
    f = _ftp()
    try:
        f.cwd(DIR_RAIS.format(ano=ano))
        f.voidcmd("TYPE I")
        baixado = [0]
        marco = [0]
        inicio = time.time()

        # Progresso por MARCO acumulado, e sem retorno de carro. Duas correções
        # medidas na primeira execução: o socket entrega blocos bem menores que
        # o `blocksize` pedido, então uma condição do tipo
        # `baixado % 64MB < 1MB` dispara em quase todo bloco e encheu o log com
        # dezenas de milhares de linhas; e, com a saída redirecionada para
        # arquivo, "\r" não apaga a linha anterior — só empilha lixo.
        PASSO = 128 << 20

        def escrever(bloco, saida):
            saida.write(bloco)
            baixado[0] += len(bloco)
            if baixado[0] // PASSO > marco[0]:
                marco[0] = baixado[0] // PASSO
                print(f"      {baixado[0] / 1048576:.0f} MB", flush=True)

        with open(destino, "wb") as saida:
            f.retrbinary(f"RETR {nome}", lambda b: escrever(b, saida),
                         blocksize=1 << 20)
        print(f"      {baixado[0] / 1048576:.0f} MB em "
              f"{time.time() - inicio:.0f}s")
    finally:
        # `close()`, não `quit()`: a mesma razão do DATASUS em rede.py — não
        # vale esperar diálogo de despedida de um servidor ocupado.
        f.close()
    return baixado[0]


def _espaco_livre(caminho):
    return shutil.disk_usage(str(caminho)).free


def _varrer_regiao(caminho_csv):
    """Conta vínculos ativos da família CBO por município. Devolve (mapa, códigos, total)."""
    por_municipio = defaultdict(int)
    codigos_vistos = defaultdict(int)
    linhas = 0
    with open(caminho_csv, encoding="latin-1", newline="") as fh:
        leitor = csv.DictReader(fh, delimiter=",")
        colunas = leitor.fieldnames or []
        try:
            col_cbo = next(c for c in colunas if c.startswith(COL_CBO))
            col_mun = next(c for c in colunas if c.startswith(COL_MUNICIPIO))
            col_ativo = next(c for c in colunas if COL_ATIVO in c)
        except StopIteration:
            raise SystemExit(
                f"[ERRO] colunas esperadas não encontradas em {caminho_csv.name}. "
                f"Procurados: {COL_CBO!r}, {COL_MUNICIPIO!r}, {COL_ATIVO!r}. "
                f"Presentes: {colunas}")
        for linha in leitor:
            linhas += 1
            cbo = (linha[col_cbo] or "").strip()
            if not cbo.startswith(FAMILIA_CBO):
                continue
            codigos_vistos[cbo] += 1
            if (linha[col_ativo] or "").strip() != "1":
                continue
            por_municipio[(linha[col_mun] or "").strip()] += 1
    return dict(por_municipio), dict(codigos_vistos), linhas


def extrair_rais(ano, tmp):
    """
    {codigo6: administradores} mais metadados. Uma região por vez, apagando
    cada arquivo antes da seguinte — o pico de disco é o maior arquivo sozinho.

    O agregado de cada região fica em cache em etl/dados/rais_<ano>/, então
    reprocessar depois de uma interrupção é instantâneo. É a mesma estratégia
    que o observatório de Fonoaudiologia usou no CNES, pelo mesmo motivo: a
    parte cara é a rede, e ela não deve ser repetida por causa de um ajuste na
    agregação.
    """
    try:
        import py7zr
    except ImportError:
        raise SystemExit(
            "[ERRO] py7zr não está instalado, e os microdados da RAIS são "
            "publicados em .7z — formato que a biblioteca padrão do Python não "
            "lê. `pip install -r requirements.txt`, ou rode com --pular-rais "
            "para publicar sem o indicador (ele fica nulo, não zero).")

    tmp = Path(tmp)
    tmp.mkdir(parents=True, exist_ok=True)
    cache = DADOS / f"rais_{ano}"
    cache.mkdir(parents=True, exist_ok=True)

    nomes, tamanhos = _arquivos_da_edicao(ano)
    if not nomes:
        raise SystemExit(f"[ERRO] nenhum arquivo de vínculos na RAIS {ano}.")
    maior = max((t for t in tamanhos.values() if t), default=0)
    # 7,3x foi a razão medida; 9x dá margem para uma região que comprima pior.
    necessario = maior * 9 + maior
    livre = _espaco_livre(tmp)
    print(f"[RAIS] {len(nomes)} arquivos, "
          f"{sum(t or 0 for t in tamanhos.values()) / 1e9:.2f} GB comprimidos")
    print(f"[RAIS] pico estimado em {tmp}: {necessario / 1e9:.1f} GB; "
          f"livre: {livre / 1e9:.1f} GB")
    if livre < necessario:
        raise SystemExit(
            f"[ERRO] espaço insuficiente em {tmp}. O maior arquivo tem "
            f"{maior / 1e9:.2f} GB comprimidos e expande cerca de 7,3x. "
            f"Aponte --tmp para um disco com pelo menos "
            f"{necessario / 1e9:.0f} GB livres.")

    total = defaultdict(int)
    codigos = defaultdict(int)
    linhas_total = 0
    regioes = []

    for nome in nomes:
        parcial = cache / f"{nome}.json"
        if parcial.exists():
            print(f"[RAIS] {nome}: agregado em cache")
            guardado = json.loads(parcial.read_text(encoding="utf-8"))
        else:
            arquivo = tmp / nome
            print(f"[RAIS] {nome} ({(tamanhos.get(nome) or 0) / 1e6:.0f} MB)")
            if not arquivo.exists():
                _baixar_ftp(ano, nome, arquivo)
            destino = tmp / f"_ext_{nome}"
            if destino.exists():
                shutil.rmtree(destino, ignore_errors=True)
            inicio = time.time()
            with py7zr.SevenZipFile(arquivo) as z:
                z.extractall(path=str(destino))
            print(f"      descomprimido em {time.time() - inicio:.0f}s")
            membros = sorted(destino.glob("*"))
            if len(membros) != 1:
                raise SystemExit(
                    f"[ERRO] {nome} tem {len(membros)} membros; era esperado 1: "
                    f"{[m.name for m in membros]}")
            inicio = time.time()
            mapa, vistos, linhas = _varrer_regiao(membros[0])
            print(f"      {linhas:,} vínculos varridos em "
                  f"{time.time() - inicio:.0f}s; "
                  f"{sum(mapa.values()):,} administradores ativos".replace(",", "."))
            guardado = {"municipios": mapa, "codigos_cbo": vistos,
                        "linhas": linhas}
            parcial.write_text(json.dumps(guardado, ensure_ascii=False),
                               encoding="utf-8", newline="\n")
            # Apagar ANTES da próxima região: sem isto o pico vira a soma de
            # todas elas, e a conferência de espaço acima passa a mentir.
            shutil.rmtree(destino, ignore_errors=True)
            arquivo.unlink(missing_ok=True)

        for codigo, n in guardado["municipios"].items():
            total[codigo] += n
        for codigo, n in guardado["codigos_cbo"].items():
            codigos[codigo] += n
        linhas_total += guardado["linhas"]
        regioes.append(nome)

    metadados = {
        "fonte": "RAIS — Relação Anual de Informações Sociais "
                 "(Ministério do Trabalho e Emprego)",
        "ano": ano,                        # do DIRETÓRIO lido, não do calendário
        "ftp": f"ftp://{HOST_RAIS}{DIR_RAIS.format(ano=ano)}",
        "recorte": f"CBO 2002, família {FAMILIA_CBO} (Administradores), "
                   "vínculos ativos em 31/12",
        "codigos_cbo_encontrados": dict(sorted(codigos.items())),
        "arquivos": regioes,
        "vinculos_varridos": linhas_total,
        "administradores_ativos": sum(total.values()),
        "municipios_com_administrador": len(
            [c for c, n in total.items() if n > 0]),
        "extraido_em": date.today().isoformat(),
    }
    return dict(total), metadados


# --------------------------------------------------------------------------- #

def main():
    p = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ano-rais", type=int, default=None,
                   help="edição da RAIS (padrão: a que casa com o ano do CEMPRE)")
    p.add_argument("--agregado-cempre", type=int, default=AGREGADO_CEMPRE)
    p.add_argument("--periodo-cempre", default="-1",
                   help="período do SIDRA; -1 é o mais recente")
    p.add_argument("--tmp", default=str(DADOS / "_rais_tmp"),
                   help="diretório de trabalho para descompactar a RAIS")
    p.add_argument("--pular-rais", action="store_true",
                   help="não extrai a RAIS; o IAP fica nulo e a proveniência diz")
    p.add_argument("--pular-cempre", action="store_true")
    p.add_argument("--saida", default=str(DATA / "absorcao.json"))
    args = p.parse_args()

    municipios = defaultdict(dict)
    metadados = {}

    if not args.pular_cempre:
        cempre, meta = extrair_cempre(args.agregado_cempre, args.periodo_cempre)
        metadados["cempre"] = meta
        for codigo, valores in cempre.items():
            municipios[codigo].update(valores)
    else:
        print("[ABSORCAO] CEMPRE pulado; empresas e pessoal ocupado ficam nulos.")

    if not args.pular_rais:
        ano = args.ano_rais
        if ano is None:
            edicoes = listar_edicoes_rais()
            if not edicoes:
                raise SystemExit("[ERRO] nenhuma edição da RAIS listada no FTP.")
            ano_cempre = (metadados.get("cempre") or {}).get("ano")
            if ano_cempre and str(ano_cempre) in edicoes:
                ano = int(ano_cempre)
                mais_novas = [e for e in edicoes if e > str(ano_cempre)]
                print(f"[RAIS] edições disponíveis: {', '.join(edicoes[:6])}")
                print(f"[RAIS] usando {ano} — o ano do CEMPRE. A densidade "
                      "publicada é RAIS sobre CEMPRE; anos diferentes nos dois "
                      "lados do quociente não medem nada.")
                if mais_novas:
                    print(f"[RAIS] atenção: já existe edição mais recente "
                          f"({', '.join(mais_novas)}). Ela NÃO é adotada aqui; "
                          "é a verificação semanal de fontes que a reporta como "
                          "novidade, e a troca acontece quando o CEMPRE "
                          "acompanhar.")
            else:
                ano = int(edicoes[0])
                print(f"[RAIS] edições disponíveis: {', '.join(edicoes[:6])} — "
                      f"usando {ano} (não há edição do ano do CEMPRE)")
        rais, meta = extrair_rais(ano, args.tmp)
        ano_cempre = (metadados.get("cempre") or {}).get("ano")
        meta["ano_cempre_pareado"] = ano_cempre
        meta["anos_casam"] = bool(ano_cempre and str(ano_cempre) == str(ano))
        metadados["rais"] = meta
        for codigo, n in rais.items():
            municipios[codigo]["administradores_rais"] = n
        # Um município que a RAIS varreu e onde não há administrador vinculado
        # vale 0 — aqui o zero É a medida. Quem não foi varrido fica sem chave,
        # e o consolidador o publica como "sem dados".
        for codigo in municipios:
            municipios[codigo].setdefault("administradores_rais", 0)
    else:
        print("[ABSORCAO] RAIS pulada; o IAP fica nulo e a proveniência diz isso.")

    # Códigos que não são município. O IBGE inicia todo código de município
    # pelo código da UF, então o prefixo de dois dígitos basta para separá-los —
    # sem precisar de uma lista de 5.571 códigos que envelheceria junto.
    PREFIXOS_UF = {"11", "12", "13", "14", "15", "16", "17", "21", "22", "23",
                   "24", "25", "26", "27", "28", "29", "31", "32", "33", "35",
                   "41", "42", "43", "50", "51", "52", "53"}
    sem_municipio = {c: v for c, v in municipios.items()
                     if str(c)[:2] not in PREFIXOS_UF}
    for codigo in sem_municipio:
        del municipios[codigo]
    if sem_municipio:
        total_sem = sum(v.get("administradores_rais") or 0
                        for v in sem_municipio.values())
        print(f"[ABSORCAO] {total_sem} vínculo(s) sem município identificado "
              f"(códigos {sorted(sem_municipio)}) — fora do conjunto municipal, "
              "declarados na proveniência.")
        if "rais" in metadados:
            metadados["rais"]["administradores_sem_municipio"] = total_sem
            metadados["rais"]["codigos_sem_municipio"] = sorted(sem_municipio)
            # A contagem de municípios com administrador é recontada sobre o
            # conjunto já limpo: publicada com o 999999 dentro, ela afirmaria a
            # existência de um município a mais no país.
            metadados["rais"]["municipios_com_administrador"] = sum(
                1 for v in municipios.values()
                if v.get("administradores_rais"))

    saida = {
        "metadados": {
            **metadados,
            "chave": "código IBGE de município com 6 dígitos, sem verificador",
            "gerado_em": date.today().isoformat(),
        },
        "municipios": dict(municipios),
    }
    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(args.saida).write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"[ABSORCAO] {len(municipios)} municípios -> {args.saida}")


if __name__ == "__main__":
    main()

"""
site/build.py
Gerador do site estático do Observatório Nacional da Formação em Administração.

Uso:
    python site/build.py
    python site/build.py --dados data/nacional.json --out site/dist

Lê `data/nacional.json` e `data/municipios/*.json` e escreve HTML estático,
sem servidor e sem build de front-end.

O QUE É CALCULADO AQUI E NÃO NO NAVEGADOR
------------------------------------------
Correlações, regressões e normalizações saem prontas do build, em JSON embutido
na página. Duas razões: o resultado fica igual para todo leitor, e fica
auditável — quem quiser conferir uma correlação lê o mesmo número que o CI
gerou, não um valor recalculado por uma versão de navegador qualquer.

O ÍNDICE SINTÉTICO É A EXCEÇÃO: seus pesos são ajustáveis pelo leitor, então o
build entrega os valores NORMALIZADOS e o navegador recompõe. Normalizar no
cliente é que seria errado — a escala mudaria conforme o filtro aplicado.
"""
import argparse
import csv
import hashlib
import io
import json
import shutil
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import catalogo  # noqa: E402
import estatistica  # noqa: E402
import planilha  # noqa: E402

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    sys.exit("Instale jinja2: pip install jinja2")

RAIZ = Path(__file__).resolve().parent.parent

NOMES_UF = {
    "AC": "Acre", "AL": "Alagoas", "AM": "Amazonas", "AP": "Amapá",
    "BA": "Bahia", "CE": "Ceará", "DF": "Distrito Federal",
    "ES": "Espírito Santo", "GO": "Goiás", "MA": "Maranhão",
    "MG": "Minas Gerais", "MS": "Mato Grosso do Sul", "MT": "Mato Grosso",
    "PA": "Pará", "PB": "Paraíba", "PE": "Pernambuco", "PI": "Piauí",
    "PR": "Paraná", "RJ": "Rio de Janeiro", "RN": "Rio Grande do Norte",
    "RO": "Rondônia", "RR": "Roraima", "RS": "Rio Grande do Sul",
    "SC": "Santa Catarina", "SE": "Sergipe", "SP": "São Paulo",
    "TO": "Tocantins",
}

CODIGO_IBGE = {
    "RO": "11", "AC": "12", "AM": "13", "RR": "14", "PA": "15", "AP": "16",
    "TO": "17", "MA": "21", "PI": "22", "CE": "23", "RN": "24", "PB": "25",
    "PE": "26", "AL": "27", "SE": "28", "BA": "29", "MG": "31", "ES": "32",
    "RJ": "33", "SP": "35", "PR": "41", "SC": "42", "RS": "43", "MS": "50",
    "MT": "51", "GO": "52", "DF": "53",
}

# Indicadores oferecidos na matriz de correlação.
#
# Lista curta de propósito: cruzar os 60 indicadores daria mais de 1.700 pares,
# dos quais dezenas passariam de p<0,05 só pelo número de tentativas.
# Correlação em massa não é análise, é pesca.
#
# `E` fica de fora, embora seja indicador central do site: E = 1 − ICT, por
# definição. O par ICT×E devolvia rho = -1,000 com p < 0,001 e encabeçava a
# lista ordenada por força — uma identidade algébrica ocupando o lugar da
# descoberta mais forte do observatório. Nenhum par aqui pode ser derivação
# aritmética de outro.
EIXOS_CORRELACAO = [
    "ICT", "IAF", "IAP", "administradores_por_mil_ocupados",
    "empresas_por_mil_hab", "CPC_cont", "IDD", "ENADE_cont",
    "vagas_total", "vagas_por_100k", "pct_ead", "HHI_mantenedora",
    "cobertura_municipal", "taxa_conclusao", "pct_doc_doutores",
    "pct_rede_publica", "populacao",
]

# Componentes do índice sintético, com peso inicial. O leitor ajusta os pesos;
# a composição é declarada aqui para ficar explícita no código e na página.
COMPONENTES_INDICE = [
    {"key": "E", "peso": 25, "rotulo": "Equidade territorial"},
    {"key": "IAF", "peso": 25, "rotulo": "Adequação formativa"},
    {"key": "IAP", "peso": 20, "rotulo": "Absorção profissional"},
    {"key": "administradores_por_mil_ocupados", "peso": 15,
     "rotulo": "Densidade de administradores"},
    {"key": "vagas_por_100k", "peso": 15, "rotulo": "Densidade de vagas"},
]


# --------------------------------------------------------------------------- #
# Utilidades
# --------------------------------------------------------------------------- #

def slug(texto):
    """
    Nome de arquivo seguro a partir do nome do município.

    Mantém o apóstrofo fora do nome do arquivo. `Olho d'Água` e
    `Santa Bárbara d'Oeste` existem de verdade, e um apóstrofo num caminho ou
    dentro de uma string JS quebra silenciosamente — a página gera, o link
    aparece, e o clique não faz nada.
    """
    import unicodedata
    s = unicodedata.normalize("NFD", str(texto or "").upper())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    saida = []
    for ch in s:
        saida.append(ch if ch.isalnum() else "_")
    return "_".join(filter(None, "".join(saida).split("_")))


def numero_ptbr(valor, casas=0):
    """
    Formata para pt-BR: ponto como separador de milhar, vírgula decimal.

    Ausência devolve o texto "sem dados", não string vazia e muito menos zero.
    Um template que imprime `0` para ausência transforma lacuna em afirmação, e
    a afirmação é falsa.
    """
    if valor is None:
        return "sem dados"
    if isinstance(valor, str):
        return valor
    texto = f"{valor:,.{casas}f}"
    return texto.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def mediana(valores):
    limpos = sorted(v for v in valores if v is not None)
    if not limpos:
        return None
    meio = len(limpos) // 2
    if len(limpos) % 2:
        return limpos[meio]
    return (limpos[meio - 1] + limpos[meio]) / 2


def _json(valor):
    """
    Serializa para embutir em <script>. Fecha a porta do `</script>` injetado.

    `json.dumps` sozinho deixa passar a sequência `</script>` dentro de uma
    string de dado, que encerra o bloco no meio e quebra a página inteira.
    """
    texto = json.dumps(valor, ensure_ascii=False)
    return texto.replace("</", "<\\/")


def normalizar(valores, maior_melhor):
    """
    Min-max para 0..100 sobre os valores presentes. Ausente continua ausente.

    Uma UF sem o indicador NÃO recebe 0 nem a média: recebe None e sai do
    índice sintético, que passa a declarar sobre quantos componentes foi
    calculado. Substituir ausência por zero colocaria as UFs não avaliadas no
    fundo do ranking como se tivessem sido medidas e tivessem ido mal.
    """
    presentes = [v for v in valores if v is not None]
    if len(presentes) < 2:
        return [None] * len(valores)
    menor, maior = min(presentes), max(presentes)
    if maior == menor:
        return [None if v is None else 50.0 for v in valores]
    saida = []
    for v in valores:
        if v is None:
            saida.append(None)
            continue
        escala = (v - menor) / (maior - menor) * 100
        saida.append(round(escala if maior_melhor else 100 - escala, 2))
    return saida


# --------------------------------------------------------------------------- #
# Análises
# --------------------------------------------------------------------------- #

def matriz_correlacao(ufs, eixos):
    siglas = sorted(ufs)
    series = {k: [ufs[s].get(k) for s in siglas] for k in eixos}
    celulas = []
    for i, a in enumerate(eixos):
        for b in eixos[i + 1:]:
            rho, p, n = estatistica.spearman(series[a], series[b])
            if rho is None:
                continue
            celulas.append({
                "a": a, "b": b,
                "rotulo_a": catalogo.POR_CHAVE[a]["sigla"],
                "rotulo_b": catalogo.POR_CHAVE[b]["sigla"],
                "rho": round(rho, 4),
                "p": round(p, 5) if p is not None else None,
                "n": n,
                "significativo": bool(p is not None and p < 0.05),
            })
    celulas.sort(key=lambda c: -abs(c["rho"]))
    return celulas


def regressoes(ufs):
    """
    Duas regressões declaradas, não uma varredura.

    Escolher o modelo depois de olhar os resultados é a forma mais fácil de
    achar significância onde não há. As duas perguntas abaixo foram formuladas
    antes de rodar qualquer coisa.
    """
    siglas = sorted(ufs)

    def serie(k):
        return [ufs[s].get(k) for s in siglas]

    modelos = []
    m = estatistica.regressao(
        serie("IAF"),
        [serie("E"), serie("CPC_cont"), serie("pct_doc_doutores")],
        ["Equidade", "CPC contínuo", "% Doutores"])
    if m:
        m["pergunta"] = ("O que explica a adequação formativa de um estado: "
                         "distribuição territorial, qualidade avaliada ou "
                         "titulação docente?")
        m["resposta"] = "IAF"
        modelos.append(m)

    m = estatistica.regressao(
        serie("IAP"),
        [serie("vagas_por_100k"), serie("cobertura_municipal"),
         serie("empresas_por_mil_hab")],
        ["Vagas / 100 mil", "Cobertura municipal", "Empresas / mil hab."])
    if m:
        m["pergunta"] = ("A absorção de administradores pelo mercado formal "
                         "acompanha a capacidade formativa do estado, ou o "
                         "tamanho da economia?")
        m["resposta"] = "IAP"
        modelos.append(m)
    return modelos


def indice_sintetico(ufs):
    siglas = sorted(ufs)
    normalizados = {}
    for comp in COMPONENTES_INDICE:
        key = comp["key"]
        maior_melhor = catalogo.POR_CHAVE[key]["dir"] != "menor"
        valores = normalizar([ufs[s].get(key) for s in siglas], maior_melhor)
        normalizados[key] = dict(zip(siglas, valores))
    return {
        "componentes": COMPONENTES_INDICE,
        "normalizados": normalizados,
        "ufs": siglas,
    }


# --------------------------------------------------------------------------- #
# Exportações
# --------------------------------------------------------------------------- #

def exportar_csv(ufs):
    colunas = ["uf", "nome"] + [i["key"] for i in catalogo.INDICADORES]
    buffer = io.StringIO()
    escritor = csv.writer(buffer, delimiter=";", lineterminator="\n")
    escritor.writerow(colunas)
    for sigla in sorted(ufs):
        d = ufs[sigla]
        linha = [sigla, NOMES_UF.get(sigla, sigla)]
        for key in colunas[2:]:
            valor = d.get(key)
            # Vazio, não zero. Um CSV que preenche ausência com 0 propaga a
            # mentira para toda planilha que o abrir.
            linha.append("" if valor is None else valor)
        escritor.writerow(linha)
    return buffer.getvalue()


# --------------------------------------------------------------------------- #
# Build
# --------------------------------------------------------------------------- #

def construir(caminho_dados, saida, templates):
    problemas = catalogo.validar()
    if problemas:
        raise SystemExit("[BUILD] catálogo inconsistente:\n  - "
                         + "\n  - ".join(problemas))

    nacional = json.loads(Path(caminho_dados).read_text(encoding="utf-8"))
    meta = nacional["metadados"]
    ufs = nacional["ufs"]

    dir_municipios = Path(caminho_dados).parent / "municipios"
    municipios = {}
    if dir_municipios.exists():
        for arquivo in sorted(dir_municipios.glob("*.json")):
            lista = json.loads(arquivo.read_text(encoding="utf-8"))["municipios"]
            # O slug é calculado UMA vez, aqui, e viaja com o registro. O nome
            # do arquivo e o link do mapa passam a sair da mesma string; se
            # fossem derivados em dois lugares, "Santa Bárbara d'Oeste" daria
            # dois resultados diferentes e o clique cairia em 404.
            for m in lista:
                m["slug"] = slug(m["nome"])
            municipios[arquivo.stem.upper()] = lista

    serie = {}
    caminho_serie = Path(caminho_dados).parent / "serie.json"
    if caminho_serie.exists():
        serie = json.loads(caminho_serie.read_text(encoding="utf-8"))

    saida = Path(saida)
    # Apaga o dist inteiro: municípios que saíram dos dados numa reingestão
    # deixariam páginas órfãs, ainda linkadas pelo mapa e ainda indexáveis.
    if saida.exists():
        shutil.rmtree(saida)
    saida.mkdir(parents=True)
    shutil.copytree(Path(templates).parent / "static", saida / "static")

    # O catálogo vira JS aqui, a partir da MESMA estrutura que alimenta os
    # templates. É isto que impede um indicador de existir no glossário e
    # faltar na formatação.
    (saida / "static" / "js" / "indicadores.js").write_text(
        catalogo.para_js(), encoding="utf-8", newline="\n")

    env = Environment(loader=FileSystemLoader(str(templates)),
                      autoescape=select_autoescape(["html"]))
    env.filters["json"] = _json
    env.filters["slug"] = slug
    env.filters["numero"] = numero_ptbr

    com_oferta = {s: d for s, d in ufs.items() if d.get("tem_oferta_presencial")}
    sem_oferta = sorted(s for s in ufs if not ufs[s].get("tem_oferta_presencial"))

    def soma(campo, fonte=None):
        return sum((fonte or ufs)[s].get(campo) or 0 for s in (fonte or ufs))

    populacao = soma("populacao")
    vagas_total = soma("vagas_total")
    panorama = {
        "n_ufs": len(ufs),
        "n_ufs_com_oferta": len(com_oferta),
        "ufs_sem_oferta": sem_oferta,
        "vagas_total": vagas_total,
        "vagas_presencial": soma("vagas_presencial"),
        "vagas_ead": soma("vagas_ead"),
        "pct_ead": round(100 * soma("vagas_ead") / vagas_total, 1) if vagas_total else None,
        "municipios_total": soma("municipios_total"),
        "municipios_oferta": soma("municipios_oferta"),
        "municipios_deserto": soma("municipios_total") - soma("municipios_oferta"),
        "polos_registros": soma("ead_polos_registros"),
        "polos_municipios": soma("ead_polos_municipios"),
        "matriculas": soma("matriculas"),
        "concluintes": soma("concluintes"),
        "populacao": populacao,
        "vagas_por_100k": round(100_000 * vagas_total / populacao, 1) if populacao else None,
        "ict_mediana": mediana([d.get("ICT") for d in ufs.values()]),
        "iaf_mediana": mediana([d.get("IAF") for d in ufs.values()]),
        "cursos_avaliados": sum(d.get("n_cursos_avaliados") or 0 for d in ufs.values()),
        "municipios_so_ead": soma("municipios_so_ead"),
        "municipios_com_administrador": soma("municipios_com_administrador"),
        "administradores_rais": soma("administradores_rais"),
        "empresas_atuantes": soma("empresas_atuantes"),
        "pessoal_ocupado": soma("pessoal_ocupado"),
        "ano_censo": meta.get("ano_censo"),
    }

    # A manchete deste observatório é o CONTRASTE entre os dois alcances, e ela
    # é derivada aqui, dos dados, para que nenhum template precise digitar
    # número nenhum. `pct_*` ficam nulos se o denominador não vier — não zero:
    # "0% dos municípios" seria uma afirmação, e não haveria fonte para ela.
    total_municipios = panorama["municipios_total"] or 0
    panorama["pct_municipios_oferta"] = (
        round(100 * panorama["municipios_oferta"] / total_municipios, 1)
        if total_municipios else None)
    panorama["pct_municipios_polo"] = (
        round(100 * panorama["polos_municipios"] / total_municipios, 1)
        if total_municipios else None)
    panorama["pct_municipios_com_administrador"] = (
        round(100 * panorama["municipios_com_administrador"] / total_municipios, 1)
        if total_municipios and panorama["municipios_com_administrador"] else None)
    panorama["administradores_por_mil_ocupados"] = (
        round(1000 * panorama["administradores_rais"] / panorama["pessoal_ocupado"], 2)
        if panorama["pessoal_ocupado"] and panorama["administradores_rais"] else None)

    correlacoes = matriz_correlacao(ufs, EIXOS_CORRELACAO)
    modelos = regressoes(ufs)
    indice = indice_sintetico(ufs)

    comum = {
        "meta": meta,
        "panorama": panorama,
        "nomes_uf": NOMES_UF,
        "catalogo": catalogo.INDICADORES,
        "categorias": catalogo.CATEGORIAS,
        "gerado_em": date.today().isoformat(),
    }

    def render(template, destino, **contexto):
        html = env.get_template(template).render(**comum, **contexto)
        caminho = saida / destino
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_text(html, encoding="utf-8", newline="\n")

    ordenadas = sorted(ufs.items(), key=lambda kv: -(kv[1].get("vagas_total") or 0))

    render("index.html.j2", "index.html", depth="",
           ufs=ufs, ufs_ordenadas=ordenadas, ufs_json=_json(ufs),
           serie_json=_json(serie))

    for sigla, d in sorted(ufs.items()):
        lista = municipios.get(sigla, [])
        render("uf.html.j2", f"uf/{sigla}.html", depth="../",
               sigla=sigla, nome_uf=NOMES_UF.get(sigla, sigla), d=d,
               uf_json=_json(d), codigo_ibge=CODIGO_IBGE.get(sigla, ""),
               municipios=lista, municipios_json=_json(lista),
               ufs_json=_json(ufs))
    print(f"[BUILD] {len(ufs)} páginas de UF")

    n_mun = 0
    for sigla, lista in sorted(municipios.items()):
        for m in lista:
            render("municipio.html.j2",
                   f"municipio/{sigla}/{m['slug']}.html", depth="../../",
                   sigla=sigla, nome_uf=NOMES_UF.get(sigla, sigla),
                   m=m, m_json=_json(m), d=ufs.get(sigla, {}))
            n_mun += 1
    print(f"[BUILD] {n_mun} páginas de município")

    render("comparar.html.j2", "comparar.html", depth="",
           ufs=ufs, ufs_json=_json(ufs))
    render("correlacoes.html.j2", "correlacoes.html", depth="",
           correlacoes=correlacoes, correlacoes_json=_json(correlacoes),
           modelos=modelos, ufs_json=_json(ufs),
           eixos=EIXOS_CORRELACAO)
    render("indice.html.j2", "indice.html", depth="",
           indice=indice, indice_json=_json(indice), ufs_json=_json(ufs))
    render("glossario.html.j2", "glossario.html", depth="")
    render("serie.html.j2", "serie.html", depth="",
           serie=serie, serie_json=_json(serie))
    render("autor.html.j2", "autor.html", depth="")
    render("aviso-legal.html.j2", "aviso-legal.html", depth="")
    render("offline.html.j2", "offline.html", depth="")

    # Dados abertos: o site publica o que consome.
    (saida / "dados").mkdir(exist_ok=True)
    shutil.copy(caminho_dados, saida / "dados" / "nacional.json")
    (saida / "dados" / "indicadores.csv").write_text(
        exportar_csv(ufs), encoding="utf-8-sig", newline="\n")
    xlsx = planilha.gerar(saida / "dados" / "observatorio-administracao.xlsx",
                          Path(caminho_dados).parent, NOMES_UF)
    print(f"[BUILD] planilha XLSX ({xlsx.stat().st_size // 1024} KB)")
    for nome in ("_proveniencia.json", "qualidade.json", "absorcao.json",
                 "registro_autoral.json"):
        origem = Path(caminho_dados).parent / nome
        if origem.exists():
            shutil.copy(origem, saida / "dados" / nome)
    print("[BUILD] dados abertos em dados/")

    escrever_pwa(saida, panorama)
    print(f"[BUILD] -> {saida}")
    return saida


# Arquivos que o service worker guarda de saída. Declarados aqui em cima
# porque servem a duas coisas: a lista que o SW pré-carrega E o cálculo da
# chave do cache.
ESSENCIAIS_CACHE = [
    "index.html", "comparar.html", "correlacoes.html", "indice.html",
    "glossario.html", "serie.html", "offline.html", "manifest.json",
    "static/css/style.css", "static/js/app.js", "static/js/indicadores.js",
    "static/js/xlsx.js",
    "static/fonts/fonts.css",
]


def escrever_pwa(saida, panorama):
    manifesto = {
        # `id` fixa a identidade do app entre instalações. Sem ele, mudar
        # start_url faz o sistema tratar como OUTRO aplicativo e o usuário
        # termina com dois ícones do mesmo site.
        "id": "/observatorio-administracao/",
        "name": "Observatório Nacional da Formação em Administração",
        "short_name": "Obs. Adm",
        "lang": "pt-BR",
        "dir": "ltr",
        "start_url": "./index.html",
        "scope": "./",
        "display": "standalone",
        "display_override": ["standalone", "minimal-ui", "browser"],
        "orientation": "any",
        "background_color": "#FBFAF8",
        "theme_color": "#3B2A4A",
        "categories": ["education", "government", "business"],
        "description": "Indicadores de acesso territorial, qualidade e "
                       "absorção profissional dos cursos de Administração no "
                       "Brasil, a partir do Censo da Educação Superior, do "
                       "CPC, da RAIS e do CEMPRE.",
        "icons": [
            {"src": "static/img/icon-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "any"},
            {"src": "static/img/icon-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "any"},
            # `maskable` separado do `any`: declarar os dois no mesmo ícone faz
            # o Android recortar a arte que não tem zona de segurança.
            {"src": "static/img/icon-maskable-192.png", "sizes": "192x192",
             "type": "image/png", "purpose": "maskable"},
            {"src": "static/img/icon-maskable-512.png", "sizes": "512x512",
             "type": "image/png", "purpose": "maskable"},
        ],
        "shortcuts": [
            {"name": "Comparar estados", "short_name": "Comparar",
             "url": "./comparar.html",
             "icons": [{"src": "static/img/icon-192.png", "sizes": "192x192"}]},
            {"name": "Índice e ranking", "short_name": "Índice",
             "url": "./indice.html",
             "icons": [{"src": "static/img/icon-192.png", "sizes": "192x192"}]},
            {"name": "Glossário dos indicadores", "short_name": "Glossário",
             "url": "./glossario.html",
             "icons": [{"src": "static/img/icon-192.png", "sizes": "192x192"}]},
        ],
    }

    (saida / "manifest.json").write_text(
        json.dumps(manifesto, ensure_ascii=False, indent=2),
        encoding="utf-8", newline="\n")

    # A chave do cache é o RESUMO DO CONTEÚDO dos arquivos cacheados, não a
    # data do build.
    #
    # A primeira versão usava `date.today()`, e o defeito apareceu na primeira
    # verificação no navegador: dois builds no mesmo dia compartilham a chave,
    # então o service worker seguiu servindo o CSS anterior. A página carregou
    # sem estilo nenhum, com o arquivo novo em disco, correto e ignorado.
    # Chave por data é a granularidade errada: responde "que dia é hoje?"
    # quando a pergunta é "esses bytes mudaram?".
    resumo = hashlib.sha256()
    for relativo in ESSENCIAIS_CACHE:
        caminho = saida / relativo
        if caminho.exists():
            resumo.update(caminho.read_bytes())
    versao = f"adm-{panorama.get('ano_censo')}-{resumo.hexdigest()[:12]}"
    essenciais_js = json.dumps(["./"] + ["./" + x for x in ESSENCIAIS_CACHE])
    (saida / "sw.js").write_text(f"""/* Service worker do Observatório.
   Cache-first para estáticos, rede-primeiro para as páginas.

   A chave do cache é o ano do Censo mais o RESUMO DO CONTEÚDO dos arquivos
   essenciais — nunca a data do build. Dois builds no mesmo dia dividiriam uma
   chave por data, e o leitor recorrente continuaria recebendo o conteúdo
   anterior: o site pareceria atualizado sem estar. */
const CACHE = '{versao}';
const ESSENCIAIS = {essenciais_js};

self.addEventListener('install', e => {{
  e.waitUntil(caches.open(CACHE).then(c => c.addAll(ESSENCIAIS)).then(() => self.skipWaiting()));
}});

self.addEventListener('activate', e => {{
  e.waitUntil(caches.keys().then(chaves =>
    Promise.all(chaves.filter(k => k !== CACHE).map(k => caches.delete(k)))
  ).then(() => self.clients.claim()));
}});

self.addEventListener('fetch', e => {{
  if (e.request.method !== 'GET') return;
  const url = new URL(e.request.url);
  if (url.origin !== self.location.origin) return;

  const estatico = /\\.(css|js|woff2|png|svg|jpg|webp|json)$/.test(url.pathname)
                   && !url.pathname.includes('/dados/');
  if (estatico) {{
    /* Busca SO no cache da versao corrente, nao em `caches.match` global.
       O global varre TODOS os caches, inclusive o da versao anterior que o
       `activate` ainda nao apagou — e numa janela de poucos segundos apos o
       deploy a pagina carregava o CSS velho junto com o HTML novo. O sintoma
       foi a pagina de autoria sem estilo algum, com o arquivo novo publicado
       e correto no servidor. */
    e.respondWith(caches.open(CACHE).then(c => c.match(e.request)).then(r => r || fetch(e.request).then(resp => {{
      const copia = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, copia));
      return resp;
    }})));
    return;
  }}
  /* Rede primeiro para as páginas, com dois níveis de queda: a própria página
     em cache e, se nem isso houver, a página offline. Sem o segundo nível o
     leitor sem conexão recebe o erro cru do navegador, que não diz o que ainda
     funciona. */
  e.respondWith(
    fetch(e.request).then(resp => {{
      const copia = resp.clone();
      caches.open(CACHE).then(c => c.put(e.request, copia));
      return resp;
    }}).catch(() => caches.open(CACHE).then(c => c.match(e.request).then(
      r => r || (e.request.mode === 'navigate'
                 /* Tambem do cache da versao corrente, e nao de `caches.match`
                    global. Era a ultima linha do arquivo que ainda consultava o
                    global: logo depois de um deploy, ela serviria a pagina
                    offline da versao ANTERIOR — com o cabecalho e o rodape
                    velhos — para quem perdesse a conexao naquela janela. */
                 ? c.match('./offline.html')
                 : undefined))))
  );
}});
""", encoding="utf-8", newline="\n")
    print("[BUILD] PWA: manifest.json + sw.js")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--dados", default=str(RAIZ / "data" / "nacional.json"))
    p.add_argument("--out", default=str(RAIZ / "site" / "dist"))
    p.add_argument("--templates", default=str(RAIZ / "site" / "templates"))
    args = p.parse_args()
    construir(Path(args.dados), Path(args.out), Path(args.templates))


if __name__ == "__main__":
    main()

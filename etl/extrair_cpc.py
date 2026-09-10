"""
etl/extrair_cpc.py
Extrai do CPC (INEP) os indicadores de qualidade dos cursos de Administração:
CPC, ENADE, IDD, perfil docente e as dimensões avaliadas pelos estudantes.

Uso:
    python etl/extrair_cpc.py
    python etl/extrair_cpc.py --area ADMINISTRAÇÃO --ciclo 2022

Saída: data/qualidade.json (por curso e agregado por UF).

O CICLO É 2022, NÃO 2023
------------------------
Administração NÃO está no CPC 2023 — aquele é o ciclo da saúde e das
engenharias, o mesmo que avaliou Fonoaudiologia. Administração está no ciclo
2022: 1.805 cursos avaliados em 27 UFs, 1.724 com CPC contínuo e 1.805 com IDD,
82.636 concluintes participantes, 1.602 presenciais e 203 EaD.

Cobertura de IDD praticamente total, ao contrário de Fonoaudiologia — onde 6 de
74 cursos ficavam sem. Isso NÃO torna o conjunto completo: 81 cursos ficam sem
CPC contínuo, e um curso sem CPC continua sendo um curso sem CPC.

TRÊS DIFERENÇAS DE FORMATO ENTRE O CICLO 2022 E O 2023
-------------------------------------------------------
Medidas, não supostas. Todas as três quebram um extrator escrito para 2023:

  1. O NOME DO ARQUIVO É MINÚSCULO: `.../resultados/2022/cpc_2022.xlsx`.
     Com `CPC_2022.xlsx` o servidor responde 404 — e é fácil concluir dali que
     o ciclo não existe, quando o que não existe é aquele nome.

  2. A ABA CHAMA-SE `CPC 2022`, COM ESPAÇO, e não `CPC_2022` com sublinhado
     como em 2023. Montar o nome da aba com f"CPC_{ciclo}" quebra.

  3. AS COLUNAS VÊM COM ESPAÇO À ESQUERDA (' Ano', ' Área de Avaliação') —
     em 2022 e também em 2023. Busca por nome exato dá KeyError; por nome
     normalizado, não. Por isso `_coluna()`.

As 39 colunas são idênticas entre os dois ciclos, então o resto do extrator
serve sem adaptação. Nome de arquivo e nome de aba são PROCURADOS entre
candidatos, com sondagem de três estados — nunca montados por uma f-string só.

TRÊS CASAS DECIMAIS, PONDERADO POR CONCLUINTES PARTICIPANTES
-------------------------------------------------------------
As médias por UF são ponderadas pelo número de concluintes participantes, e
arredondadas com TRÊS casas. Com duas, nenhuma UF reproduz o valor publicado —
um curso com 4 participantes e outro com 180 movem a terceira casa, e a
diferença aparece exatamente onde alguém vai conferir.

O COMPONENTE Q DO IAF USA CPC (FAIXA), NÃO O CONTÍNUO
------------------------------------------------------
`q_qualidade` espera conceitos na escala 1 a 5, porque calcula (v−1)/4. O CPC
contínuo vai de 0 a 5 e produziria componente negativo para os cursos abaixo de
1. As faixas de ENADE e IDD não vêm nesta planilha, e derivá-las dos contínuos
seria reconstruir número que o INEP não publicou — então Q usa só o CPC em
faixa. ENADE contínuo, IDD, docentes e dimensões são publicados como
indicadores próprios, não dobrados dentro do Q.
"""
import argparse
import csv
import json
import re
import unicodedata
from datetime import date
from pathlib import Path

import pandas as pd

from rede import baixar, sondar

REPO = Path(__file__).parent.parent
DADOS = REPO / "etl" / "dados"
DATA = REPO / "data"

BASE_CPC = ("https://download.inep.gov.br/educacao_superior/indicadores/"
            "resultados/{ciclo}/")

# O INEP não é consistente na caixa do nome entre ciclos: 2023 publica
# `CPC_2023.xlsx`; 2022 publica `cpc_2022.xlsx`. Procurar entre candidatos custa
# uma sondagem e evita a conclusão errada de que o ciclo não foi publicado.
NOMES_CPC = ("cpc_{ciclo}.xlsx", "CPC_{ciclo}.xlsx",
             "cpc{ciclo}.xlsx", "CPC{ciclo}.xlsx")

# Mesma história para a aba: 2022 usa espaço, 2023 usa sublinhado.
ABAS_CPC = ("CPC {ciclo}", "CPC_{ciclo}", "CPC{ciclo}")


def normalizar(texto):
    s = unicodedata.normalize("NFD", str(texto or "").strip().upper())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"\s+", " ", s)


def _coluna(colunas, *trechos):
    """Acha a coluna cujo nome normalizado contém todos os trechos."""
    alvos = [normalizar(t) for t in trechos]
    for original in colunas:
        norm = normalizar(original)
        if all(a in norm for a in alvos):
            return original
    return None


def _num(serie):
    """Texto -> número, com vírgula decimal e vazio virando NaN."""
    return pd.to_numeric(
        serie.astype(str).str.strip().str.replace(",", ".", regex=False),
        errors="coerce")


def baixar_planilha(ciclo, forcar=False):
    """
    Baixa a planilha do ciclo, procurando o nome entre os candidatos conhecidos.

    Distingue os três estados de cada candidato. Só afirma que o ciclo não foi
    publicado quando TODOS responderam 404 confirmado; se algum ficou
    indeterminado, aborta pedindo nova tentativa em vez de concluir ausência a
    partir de falha de rede.
    """
    destino = DADOS / f"cpc_{ciclo}.xlsx"
    if destino.exists() and not forcar:
        print(f"[CPC] usando cópia local {destino.name}")
        return destino, _url_registrada(ciclo) or BASE_CPC.format(ciclo=ciclo)

    indeterminados = []
    for molde in NOMES_CPC:
        nome = molde.format(ciclo=ciclo)
        url = BASE_CPC.format(ciclo=ciclo) + nome
        existe, detalhe = sondar(url)
        if existe:
            print(f"[CPC] encontrado: {url}")
            baixar(url, destino)
            (DADOS / f"_cpc_{ciclo}.url").write_text(url, encoding="utf-8", newline="\n")
            return destino, url
        if existe is None:
            indeterminados.append(f"{nome} ({detalhe})")
            print(f"[CPC] {nome}: INDETERMINADO ({detalhe})")
        else:
            print(f"[CPC] {nome}: 404 confirmado")

    if indeterminados:
        raise SystemExit(
            f"[ERRO] nenhum candidato do CPC {ciclo} foi confirmado, e "
            f"{len(indeterminados)} ficaram INDETERMINADOS: {indeterminados}. "
            "Indeterminado não é ausente — tente de novo em vez de concluir "
            "que o ciclo não existe.")
    raise SystemExit(
        f"[ERRO] CPC {ciclo} confirmadamente ausente: todos os nomes "
        f"candidatos ({', '.join(NOMES_CPC)}) responderam 404.")


def _url_registrada(ciclo):
    caminho = DADOS / f"_cpc_{ciclo}.url"
    return caminho.read_text(encoding="utf-8").strip() if caminho.exists() else None


def _abrir_aba(caminho, ciclo):
    """
    Lê a aba do ciclo, procurando entre as grafias conhecidas.

    A mensagem de erro lista as abas REALMENTE presentes: quando o INEP mudar a
    grafia de novo, quem rodar isto descobre o nome novo pela mensagem, em vez
    de por tentativa e erro.
    """
    import openpyxl
    livro = openpyxl.load_workbook(caminho, read_only=True)
    presentes = list(livro.sheetnames)
    livro.close()

    normalizadas = {normalizar(a).replace("_", " "): a for a in presentes}
    for molde in ABAS_CPC:
        chave = normalizar(molde.format(ciclo=ciclo)).replace("_", " ")
        if chave in normalizadas:
            aba = normalizadas[chave]
            print(f"[CPC] aba: {aba!r}")
            return pd.read_excel(caminho, sheet_name=aba, dtype=str)
    raise SystemExit(
        f"[ERRO] nenhuma aba do ciclo {ciclo} encontrada. "
        f"Candidatos: {[m.format(ciclo=ciclo) for m in ABAS_CPC]}. "
        f"Abas presentes na planilha: {presentes}")


def carregar(caminho, area, ciclo):
    bruto = _abrir_aba(caminho, ciclo)
    bruto.columns = [str(c).strip() for c in bruto.columns]
    cols = list(bruto.columns)

    mapa = {
        "area": _coluna(cols, "AREA", "AVALIACAO"),
        "cod_area": _coluna(cols, "CODIGO", "AREA"),
        "cod_ies": _coluna(cols, "CODIGO", "IES"),
        "nome_ies": _coluna(cols, "NOME", "IES"),
        "sigla_ies": _coluna(cols, "SIGLA", "IES"),
        "categoria": _coluna(cols, "CATEGORIA", "ADMINISTRATIVA"),
        "cod_curso": _coluna(cols, "CODIGO", "CURSO"),
        "modalidade": _coluna(cols, "MODALIDADE"),
        "cod_mun": _coluna(cols, "CODIGO", "MUNICIPIO"),
        "municipio": _coluna(cols, "MUNICIPIO", "CURSO"),
        "uf": _coluna(cols, "SIGLA", "UF"),
        "concluintes": _coluna(cols, "CONCLUINTES", "PARTICIPANTES"),
        "enade_cont": _coluna(cols, "CONCEITO ENADE", "CONTINUO"),
        "idd": _coluna(cols, "NOTA PADRONIZADA", "IDD"),
        "cpc_cont": _coluna(cols, "CPC", "CONTINUO"),
        "cpc_faixa": _coluna(cols, "CPC", "FAIXA"),
        "mestres": _coluna(cols, "NOTA BRUTA", "MESTRES"),
        "doutores": _coluna(cols, "NOTA BRUTA", "DOUTORES"),
        "regime": _coluna(cols, "NOTA BRUTA", "REGIME"),
        "dim_didatica": _coluna(cols, "NOTA BRUTA", "DIDATICO"),
        "dim_infra": _coluna(cols, "NOTA BRUTA", "INFRAESTRUTURA"),
        "dim_oportunidade": _coluna(cols, "NOTA BRUTA", "OPORTUNIDADE"),
    }
    faltando = [k for k, v in mapa.items() if v is None]
    if faltando:
        raise SystemExit(
            f"[ERRO] colunas não localizadas na planilha: {faltando}\n"
            f"Colunas disponíveis: {cols}")

    df = bruto[[v for v in mapa.values()]].copy()
    df.columns = list(mapa)

    alvo = normalizar(area)
    df = df[df["area"].map(normalizar) == alvo].copy()
    if df.empty:
        disponiveis = sorted({normalizar(a) for a in bruto[mapa["area"]].dropna()})
        raise SystemExit(
            f"[ERRO] área {area!r} não encontrada. Match é EXATO, não substring.\n"
            f"Áreas com trecho parecido: "
            f"{[a for a in disponiveis if alvo.split()[0][:4] in a]}")

    for col in ("concluintes", "enade_cont", "idd", "cpc_cont", "cpc_faixa",
                "mestres", "doutores", "regime",
                "dim_didatica", "dim_infra", "dim_oportunidade"):
        df[col] = _num(df[col])
    return df


def vagas_por_curso(ano_censo, slug="administracao"):
    """CO_CURSO -> vagas, lido do recorte do Censo já extraído."""
    caminho = DADOS / f"curso_{slug}_{ano_censo}.csv"
    if not caminho.exists():
        print(f"[CPC] {caminho.name} ausente — vagas_avaliadas ficará nulo. "
              "Rode etl/extrair_censo.py antes para preencher.")
        return {}
    vagas = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            codigo = (linha.get("CO_CURSO") or "").strip()
            bruto = (linha.get("QT_VG_TOTAL") or "").strip()
            if codigo and bruto.lstrip("-").isdigit():
                vagas[codigo] = vagas.get(codigo, 0) + int(bruto)
    return vagas


def _ponderada(grupo, coluna, casas=3, fator=1.0):
    """
    Média ponderada por concluintes participantes, `casas` decimais.

    Cursos sem valor na coluna saem da conta — não entram como zero. Um curso
    sem IDD não é um curso com IDD zero, e a diferença muda o ranking da UF.
    """
    sub = grupo.dropna(subset=[coluna])
    if sub.empty:
        return None
    pesos = sub["concluintes"].fillna(0)
    if pesos.sum() > 0:
        valor = float((sub[coluna] * pesos).sum() / pesos.sum())
    else:
        valor = float(sub[coluna].mean())
    return round(valor * fator, casas)


def agregar(df, vagas, ciclo, url, area):
    cursos = []
    for _, linha in df.iterrows():
        codigo = str(linha["cod_curso"]).strip()
        cursos.append({
            "cod_curso": codigo,
            "cod_ies": str(linha["cod_ies"]).strip(),
            "ies": linha["nome_ies"],
            "sigla_ies": linha["sigla_ies"],
            "categoria": linha["categoria"],
            "modalidade": linha["modalidade"],
            "uf": linha["uf"],
            "municipio": linha["municipio"],
            "cod_municipio": str(linha["cod_mun"]).strip(),
            "concluintes_participantes": _ou_nulo(linha["concluintes"], int),
            "CPC_faixa": _ou_nulo(linha["cpc_faixa"], int),
            "CPC_cont": _ou_nulo(linha["cpc_cont"], lambda v: round(v, 3)),
            "ENADE_cont": _ou_nulo(linha["enade_cont"], lambda v: round(v, 3)),
            "IDD": _ou_nulo(linha["idd"], lambda v: round(v, 3)),
            "vagas": vagas.get(codigo),
        })

    ufs = {}
    for uf, grupo in df.groupby("uf"):
        codigos = {str(c).strip() for c in grupo["cod_curso"]}
        avaliadas = [vagas[c] for c in codigos if c in vagas]
        ufs[str(uf).strip().upper()] = {
            "n_cursos_avaliados": int(len(grupo)),
            "n_com_cpc": int(grupo["cpc_cont"].notna().sum()),
            "n_com_idd": int(grupo["idd"].notna().sum()),
            "concluintes_participantes": int(grupo["concluintes"].fillna(0).sum()),
            # Q do IAF vem daqui: escala 1 a 5.
            "CPC": _ponderada(grupo, "cpc_faixa"),
            "CPC_cont": _ponderada(grupo, "cpc_cont"),
            "ENADE_cont": _ponderada(grupo, "enade_cont"),
            "IDD": _ponderada(grupo, "idd"),
            # perfil docente: as notas brutas são proporções 0 a 1.
            "pct_doc_mestres": _ponderada(grupo, "mestres", casas=1, fator=100),
            "pct_doc_doutores": _ponderada(grupo, "doutores", casas=1, fator=100),
            "pct_doc_regime_integral": _ponderada(grupo, "regime", casas=1, fator=100),
            # dimensões avaliadas pelos estudantes: notas brutas 0 a 5.
            "dim_didatico_pedagogica": _ponderada(grupo, "dim_didatica"),
            "dim_infraestrutura": _ponderada(grupo, "dim_infra"),
            "dim_oportunidade_formacao": _ponderada(grupo, "dim_oportunidade"),
            # vagas em cursos avaliados: componente V do IAF.
            "vagas_avaliadas": sum(avaliadas) if avaliadas else None,
            "cursos_sem_vagas_no_censo": sorted(c for c in codigos if c not in vagas),
        }

    return {
        "metadados": {
            "fonte": "Conceito Preliminar de Curso (INEP)",
            "url": url,
            "ciclo": ciclo,                 # do ARQUIVO, não do calendário
            "area_avaliacao": area,
            "match": "igualdade sobre o rótulo normalizado, nunca substring",
            "ponderacao": "média ponderada por concluintes participantes, 3 casas",
            "componente_q_do_iaf": "CPC (Faixa), escala 1 a 5",
            "cursos_avaliados": len(cursos),
            "ufs_avaliadas": len(ufs),
            "extraido_em": date.today().isoformat(),
        },
        "ufs": ufs,
        "cursos": cursos,
    }


def _ou_nulo(valor, conversor):
    if valor is None or pd.isna(valor):
        return None
    return conversor(float(valor))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--ciclo", default="2022")
    p.add_argument("--area", default="ADMINISTRAÇÃO")
    p.add_argument("--ano-censo", type=int, default=2024)
    p.add_argument("--slug", default="administracao")
    p.add_argument("--forcar-download", action="store_true")
    p.add_argument("--saida", default=str(DATA / "qualidade.json"))
    args = p.parse_args()

    caminho, url = baixar_planilha(args.ciclo, args.forcar_download)
    df = carregar(caminho, args.area, args.ciclo)
    print(f"[CPC] {len(df)} cursos de {args.area} no ciclo {args.ciclo}; "
          f"{df['uf'].nunique()} UFs")
    print(f"[CPC] com CPC contínuo: {int(df['cpc_cont'].notna().sum())}; "
          f"com IDD: {int(df['idd'].notna().sum())}")

    vagas = vagas_por_curso(args.ano_censo, args.slug)
    saida = agregar(df, vagas, args.ciclo, url, args.area)

    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(args.saida).write_text(
        json.dumps(saida, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    print(f"[CPC] -> {args.saida}")

    sem_vagas = sum(len(u["cursos_sem_vagas_no_censo"]) for u in saida["ufs"].values())
    if sem_vagas:
        print(f"[CPC] atenção: {sem_vagas} cursos avaliados sem correspondência "
              "de vagas no Censo (curso extinto ou código alterado). "
              "Ficam fora de vagas_avaliadas, não entram como zero.")


if __name__ == "__main__":
    main()

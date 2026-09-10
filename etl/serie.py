"""
etl/serie.py
Série histórica: compara edições do Censo da Educação Superior.

Uso:
    python etl/serie.py --anos 2023 2024
    python etl/serie.py --anos 2021 2022 2023 2024

Saída: data/serie.json  (Brasil e por UF, só com campos comparáveis)

POR QUE DÁ PARA VOLTAR NO TEMPO SEM GAMBIARRA
----------------------------------------------
O INEP reclassificou as edições antigas na CINE e as republicou, então
`NO_CINE_ROTULO` existe em todas — e o match EXATO de rótulo, que é a regra do
projeto inteiro, vale para trás sem adaptação. Em Administração isso importa
ainda mais: o rótulo exato tem 19.205 registros no Censo 2024, e uma busca por
substring somaria 4.905 de outros três rótulos. Errar o recorte num ano só
inventaria uma variação que nunca existiu.

CONTAGEM DE DISTINTOS NÃO SE SOMA
----------------------------------
`n_ies` conta instituições DISTINTAS. Somar as contagens por UF para chegar ao
número do país conta cada instituição uma vez por estado em que ela atua — e em
Administração, onde as grandes mantenedoras de EaD operam no país inteiro, isso
dá 3.024 contra as 1.386 reais. Mais que o dobro, sem nenhum sinal na tela.

Por isso `agregar_ano` guarda um conjunto NACIONAL de `CO_IES` e a linha do
Brasil o usa. As demais colunas continuam somas porque são de fato aditivas: um
município pertence a uma UF só, um registro de polo também, e vaga, matrícula e
concluinte idem.

POUCOS CAMPOS, DE PROPÓSITO
---------------------------
A série guarda apenas o que é comparável entre edições. Campos de perfil e
qualidade mudam de definição, de cobertura e até de existência entre anos; um
gráfico que os empilha lado a lado descreve mudança de metodologia como se
fosse mudança do mundo. O que sobra — vagas, matrículas, concluintes,
municípios com oferta, polos, IES — mantém o mesmo significado.

CADA ANO É LIDO E DESCARTADO
-----------------------------
O ZIP de cada edição é lido remotamente por intervalo de bytes, agregado, e o
agregado (poucos KB) é o que fica em disco. Guardar os cadastros completos de
quatro edições custaria mais de um giga para produzir um arquivo de 60 KB.
"""
import argparse
import csv
import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from extrair_censo import URL_CENSO, normalizar  # noqa: E402
from rede import ZipRemotoHTTP, sondar  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
DADOS = REPO / "etl" / "dados"
DATA = REPO / "data"

DIM_PRESENCIAL, DIM_POLO, DIM_SEDE = "1", "2", "3"

# Campos que significam a mesma coisa em todas as edições.
CAMPOS = [
    "vagas_presencial", "vagas_ead", "vagas_total",
    "n_cursos_presencial", "n_ies",
    "municipios_oferta", "ead_polos_registros", "ead_polos_municipios",
    "matriculas", "concluintes",
]

csv.field_size_limit(1 << 24)


def inteiro(valor):
    texto = (valor or "").strip()
    return int(texto) if texto.lstrip("-").isdigit() else 0


def agregar_ano(ano, rotulo="Administração"):
    """Lê a edição `ano` remotamente e devolve o agregado por UF."""
    cache = DADOS / f"serie_{ano}.json"
    if cache.exists():
        guardado = json.loads(cache.read_text(encoding="utf-8"))
        # Cache de formato antigo (só o mapa de UFs) é descartado em vez de
        # remendado: ele não tem como saber a contagem nacional de IES, e
        # deduzi-la das partes é exatamente o erro que esta correção existe
        # para eliminar.
        if isinstance(guardado, dict) and "ufs" in guardado:
            print(f"[SERIE] {ano}: usando agregado em cache")
            return guardado
        print(f"[SERIE] {ano}: cache em formato antigo, sem a contagem "
              "nacional de IES — relendo a edição")

    url = URL_CENSO.format(ano=ano)
    existe, detalhe = sondar(url)
    if existe is False:
        print(f"[SERIE] {ano}: confirmadamente não publicado — ano pulado.")
        return None
    if existe is None:
        print(f"[SERIE] {ano}: INDETERMINADO ({detalhe}). "
              "Ano pulado sem afirmar que não existe.")
        return None

    z = ZipRemotoHTTP(url)
    alvo = z.localizar("cadastro_cursos", ".csv") or z.localizar("curso", ".csv")
    alvo_ies = z.localizar("_ies_", ".csv") or z.localizar("ies", ".csv")
    if not alvo or not alvo_ies:
        print(f"[SERIE] {ano}: membros esperados não encontrados no ZIP — pulado.")
        return None

    print(f"[SERIE] {ano}: lendo {alvo.rsplit('/', 1)[-1]} ...")

    uf_sede = {}
    with z.membro_arquivo(alvo_ies) as f:
        for linha in csv.DictReader(f, delimiter=";"):
            codigo = (linha.get("CO_IES") or "").strip()
            sigla = (linha.get("SG_UF_IES") or "").strip().upper()
            if codigo and sigla:
                uf_sede[codigo] = sigla

    alvo_norm = normalizar(rotulo)
    ufs = defaultdict(lambda: {
        "vagas_presencial": 0, "vagas_ead": 0, "n_cursos_presencial": 0,
        "ead_polos_registros": 0, "matriculas": 0, "concluintes": 0,
        "_ies": set(), "_mun_oferta": set(), "_mun_polo": set(),
    })
    ies_nacional = set()
    lidas = casadas = 0

    with z.membro_arquivo(alvo) as f:
        for linha in csv.DictReader(f, delimiter=";"):
            lidas += 1
            if normalizar(linha.get("NO_CINE_ROTULO")) != alvo_norm:
                continue
            casadas += 1
            dimensao = (linha.get("TP_DIMENSAO") or "").strip()
            cod_ies = (linha.get("CO_IES") or "").strip()
            sigla = (linha.get("SG_UF") or "").strip().upper() or None
            vagas = inteiro(linha.get("QT_VG_TOTAL"))
            cod_mun = (linha.get("CO_MUNICIPIO") or "").strip()

            if dimensao == DIM_SEDE:
                sigla = uf_sede.get(cod_ies)
            if not sigla:
                continue
            d = ufs[sigla]
            d["_ies"].add(cod_ies)
            ies_nacional.add(cod_ies)
            d["matriculas"] += inteiro(linha.get("QT_MAT"))
            d["concluintes"] += inteiro(linha.get("QT_CONC"))

            if dimensao == DIM_PRESENCIAL:
                d["vagas_presencial"] += vagas
                d["n_cursos_presencial"] += 1
                d["_mun_oferta"].add(cod_mun)
            elif dimensao == DIM_SEDE:
                d["vagas_ead"] += vagas
            elif dimensao == DIM_POLO:
                d["ead_polos_registros"] += 1
                d["_mun_polo"].add(cod_mun)

    saida = {}
    for sigla, d in ufs.items():
        saida[sigla] = {
            "vagas_presencial": d["vagas_presencial"],
            "vagas_ead": d["vagas_ead"],
            "vagas_total": d["vagas_presencial"] + d["vagas_ead"],
            "n_cursos_presencial": d["n_cursos_presencial"],
            "n_ies": len(d["_ies"]),
            "municipios_oferta": len(d["_mun_oferta"]),
            "ead_polos_registros": d["ead_polos_registros"],
            "ead_polos_municipios": len(d["_mun_polo"]),
            "matriculas": d["matriculas"],
            "concluintes": d["concluintes"],
        }

    agregado = {
        "ufs": saida,
        "nacional": {
            "n_ies": len(ies_nacional),
            "registros": casadas,
        },
    }
    print(f"[SERIE] {ano}: {lidas} linhas, {casadas} do rótulo exato, "
          f"{len(saida)} UFs, {len(ies_nacional)} IES distintas no país")
    DADOS.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(agregado, ensure_ascii=False, indent=1),
                     encoding="utf-8", newline="\n")
    return agregado


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--anos", nargs="+", type=int, default=[2023, 2024])
    p.add_argument("--rotulo", default="Administração")
    p.add_argument("--saida", default=str(DATA / "serie.json"))
    args = p.parse_args()

    por_ano = {}
    for ano in sorted(args.anos):
        agregado = agregar_ano(ano, args.rotulo)
        if agregado:
            por_ano[str(ano)] = agregado

    if len(por_ano) < 2:
        raise SystemExit(
            "[SERIE] menos de duas edições disponíveis; a série não é gerada. "
            "Uma série de um ponto não é série, e publicar uma seria sugerir "
            "comparação onde não há.")

    anos = sorted(por_ano)
    siglas = sorted({s for ano in anos for s in por_ano[ano]["ufs"]})

    ufs = {}
    for sigla in siglas:
        ufs[sigla] = {ano: por_ano[ano]["ufs"].get(sigla) for ano in anos}

    brasil = {}
    for ano in anos:
        por_uf = por_ano[ano]["ufs"]
        brasil[ano] = {campo: sum((por_uf.get(s) or {}).get(campo) or 0
                                  for s in siglas)
                       for campo in CAMPOS}
        # A única coluna que NÃO é soma. Ver o cabeçalho deste arquivo.
        brasil[ano]["n_ies"] = por_ano[ano]["nacional"]["n_ies"]

    saida = {
        "metadados": {
            "fonte": "Censo da Educação Superior (INEP)",
            "curso": args.rotulo,
            "match": "igualdade sobre o rótulo CINE normalizado",
            "observacao": (
                "Somente campos com significado estável entre edições. Campos "
                "de perfil e qualidade mudam de definição entre anos e não "
                "entram na série."
            ),
            "n_ies_no_brasil": (
                "Contagem de instituições DISTINTAS no país, não a soma das "
                "contagens por UF. Uma instituição que atua em vários estados "
                "entraria uma vez por estado na soma."
            ),
            "gerado_em": date.today().isoformat(),
        },
        "anos": anos,
        "campos": CAMPOS,
        "brasil": brasil,
        "ufs": ufs,
    }
    Path(args.saida).parent.mkdir(parents=True, exist_ok=True)
    Path(args.saida).write_text(json.dumps(saida, ensure_ascii=False, indent=1),
                                encoding="utf-8", newline="\n")
    print(f"[SERIE] {len(anos)} edições ({', '.join(anos)}) -> {args.saida}")
    for campo in ("vagas_total", "matriculas", "concluintes"):
        antes, depois = brasil[anos[0]][campo], brasil[anos[-1]][campo]
        variacao = (depois - antes) / antes * 100 if antes else None
        marca = f"{variacao:+.1f}%" if variacao is not None else "—"
        print(f"[SERIE]   {campo}: {antes} -> {depois} ({marca})")


if __name__ == "__main__":
    main()

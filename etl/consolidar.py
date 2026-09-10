"""
etl/consolidar.py
Junta as fontes num único conjunto publicável e aplica os índices.

Uso:
    python etl/consolidar.py

Entrada:  data/bruto.json      (Censo, de ingestao.py)
          data/qualidade.json  (CPC 2022, de extrair_cpc.py)
          data/absorcao.json   (RAIS + CEMPRE, de extrair_absorcao.py)
Saída:    data/nacional.json
          data/municipios/<UF>.json
          data/_proveniencia.json

A ORDEM IMPORTA
---------------
`ingestao.py` produz `vagas_presencial` e `vagas_ead`; só depois disso faz
sentido calcular `pct_ead`, `HHI` sobre a capacidade total e o ICT. Rodar o
consolidador antes da ingestão grava `None` em cadeia sem reclamar de nada — o
arquivo fica com as chaves certas e os valores vazios, e nenhum teste de
integridade repara, porque as chaves existem.

FONTE AUSENTE NÃO VIRA ZERO
---------------------------
Se `absorcao.json` não existir, os campos de absorção ficam `None` e o conjunto
sai marcado com a fonte faltando na proveniência. O que não acontece é o IAP
virar 0,0 — isso afirmaria que nenhum município do país emprega administrador,
uma afirmação forte sustentada por um arquivo que não foi lido.

E TAMBÉM: MUNICÍPIO FORA DA FONTE NÃO É MUNICÍPIO COM ZERO
-----------------------------------------------------------
O CEMPRE traz 5.570 municípios; o IBGE reconhece 5.571 desde a instalação de
Boa Esperança do Norte (MT). O município que a pesquisa não visitou sai com
`None` em empresas e pessoal ocupado, e fica de fora do denominador de qualquer
razão que os use. Já `administradores_rais` vale 0 quando a RAIS varreu o
município e não encontrou nenhum vínculo: ali o zero é a medida.
"""
import argparse
import json
from collections import defaultdict
from datetime import date
from pathlib import Path

from indices import aplicar

REPO = Path(__file__).parent.parent
DATA = REPO / "data"


def _ler(caminho, obrigatorio=True):
    caminho = Path(caminho)
    if caminho.exists():
        return json.loads(caminho.read_text(encoding="utf-8"))
    if obrigatorio:
        raise SystemExit(f"[ERRO] {caminho} ausente — rode o passo anterior do pipeline.")
    print(f"[CONSOLIDAR] {caminho.name} ausente; os campos dessa fonte ficam nulos.")
    return None


def juntar_qualidade(ufs, qualidade):
    """Copia os indicadores de qualidade do CPC para cada UF."""
    campos = ("n_cursos_avaliados", "n_com_cpc", "n_com_idd",
              "concluintes_participantes", "CPC", "CPC_cont", "ENADE_cont",
              "IDD", "pct_doc_mestres", "pct_doc_doutores",
              "pct_doc_regime_integral", "dim_didatico_pedagogica",
              "dim_infraestrutura", "dim_oportunidade_formacao",
              "vagas_avaliadas")
    por_uf = (qualidade or {}).get("ufs", {})
    for sigla, d in ufs.items():
        q = por_uf.get(sigla, {})
        for campo in campos:
            d[campo] = q.get(campo)
        # UF com oferta e sem nenhum curso avaliado seria caso real, não erro.
        # No CPC 2022 de Administração isso não acontece — as 27 UFs têm curso
        # avaliado —, mas a marca continua sendo calculada em vez de presumida:
        # a próxima edição não deve nada à esta.
        d["tem_avaliacao"] = bool(q)
    return ufs


def juntar_absorcao(ufs, municipios_por_uf, absorcao):
    """
    Agrega a absorção por UF e anexa aos municípios.

    A junção é pelo código IBGE de 6 DÍGITOS. O Censo usa 7 (com verificador),
    a RAIS e o CEMPRE usam 6. Junta-se pelos seis primeiros — nunca por nome,
    que tem grafia divergente entre as bases e homônimos entre UFs.
    """
    # Os campos da fonte, nomeados UMA vez só. Repetir a lista no ramo do "sem
    # fonte" foi o que, no observatório de Fonoaudiologia, fez um campo sumir do
    # conjunto em vez de sair nulo — e campo ausente não aparece como "sem
    # dados": some da página inteira, sem alarme nenhum.
    CAMPOS_UF = ("municipios_com_administrador", "administradores_rais",
                 "administradores_por_100k", "empresas_atuantes",
                 "pessoal_ocupado", "empresas_por_mil_hab",
                 "municipios_no_cempre")
    CAMPOS_MUN = ("administradores_rais", "empresas_atuantes",
                  "pessoal_ocupado")

    if not absorcao:
        for d in ufs.values():
            for campo in CAMPOS_UF:
                d[campo] = None
        for lista in municipios_por_uf.values():
            for m in lista:
                for campo in CAMPOS_MUN:
                    m[campo] = None
        return ufs, municipios_por_uf

    por_municipio = absorcao["municipios"]
    tem_rais = "rais" in absorcao.get("metadados", {})
    tem_cempre = "cempre" in absorcao.get("metadados", {})

    # O código IBGE começa pelo código da UF, então dois dígitos bastam para
    # agregar sem precisar de tabela de-para de município.
    codigo_uf = {
        "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
        "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
        "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
        "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
        "51": "MT", "52": "GO", "53": "DF",
    }

    com_admin = defaultdict(int)
    administradores = defaultdict(int)
    empresas = defaultdict(int)
    ocupados = defaultdict(int)
    no_cempre = defaultdict(int)

    for codigo, m in por_municipio.items():
        uf = codigo_uf.get(str(codigo)[:2])
        if not uf:
            continue
        n = m.get("administradores_rais")
        if n:
            com_admin[uf] += 1
        if n is not None:
            administradores[uf] += n
        if m.get("empresas") is not None:
            empresas[uf] += m["empresas"]
            no_cempre[uf] += 1
        if m.get("pessoal_ocupado") is not None:
            ocupados[uf] += m["pessoal_ocupado"]

    for sigla, d in ufs.items():
        d["municipios_com_administrador"] = com_admin.get(sigla, 0) if tem_rais else None
        d["administradores_rais"] = administradores.get(sigla) if tem_rais else None
        d["administradores_por_100k"] = (
            round(100_000 * administradores[sigla] / d["populacao"], 1)
            if tem_rais and administradores.get(sigla) and d.get("populacao")
            else None)
        d["empresas_atuantes"] = empresas.get(sigla) if tem_cempre else None
        d["pessoal_ocupado"] = ocupados.get(sigla) if tem_cempre else None
        d["municipios_no_cempre"] = no_cempre.get(sigla, 0) if tem_cempre else None
        d["empresas_por_mil_hab"] = (
            round(1000 * empresas[sigla] / d["populacao"], 1)
            if tem_cempre and empresas.get(sigla) and d.get("populacao")
            else None)

    for uf, lista in municipios_por_uf.items():
        for m in lista:
            fonte = por_municipio.get(str(m["codigo"])[:6], {})
            m["administradores_rais"] = fonte.get("administradores_rais")
            m["empresas_atuantes"] = fonte.get("empresas")
            m["pessoal_ocupado"] = fonte.get("pessoal_ocupado")

    return ufs, municipios_por_uf


def proveniencia(bruto, qualidade, absorcao):
    meta_abs = (absorcao or {}).get("metadados", {})
    meta_rais = meta_abs.get("rais") or {}
    fontes = {
        "censo": {
            "presente": True,
            **(bruto["metadados"].get("proveniencia_censo") or {}),
        },
        "cpc": ({"presente": True, **qualidade["metadados"]} if qualidade
                else {"presente": False,
                      "motivo": "data/qualidade.json não gerado"}),
        "rais": ({"presente": True, **meta_abs["rais"]} if "rais" in meta_abs
                 else {"presente": False,
                       "motivo": "RAIS não extraída; o IAP fica nulo"}),
        "cempre": ({"presente": True, **meta_abs["cempre"]}
                   if "cempre" in meta_abs
                   else {"presente": False,
                         "motivo": "CEMPRE não extraído"}),
        # As fontes do IBGE também declaram `presente`, como as demais. Sem o
        # campo, elas ficam de fora de qualquer varredura que pergunte "quais
        # fontes faltaram?" — e uma fonte que nunca aparece na resposta é uma
        # fonte que ninguém percebe ter sumido.
        "ibge_municipios": {"presente": True,
                            **(bruto["metadados"].get("municipios_ibge") or {})},
        "ibge_populacao": {"presente": True,
                           **(bruto["metadados"].get("populacao_ibge") or {})},
    }
    return {
        "gerado_em": date.today().isoformat(),
        "fontes": fontes,
        "limitacoes_conhecidas": [
            "Dois terços da capacidade nacional são de cursos a distância, e as "
            "vagas de EaD estão registradas na UF-SEDE DA MANTENEDORA, não onde "
            "o aluno estuda. Todo número de vagas que inclui EaD descreve onde a "
            "vaga foi OFERTADA, não onde ela é ocupada.",
            "Administração pública é rótulo CINE separado (3.530 registros no "
            "Censo 2024) e área de avaliação separada no CPC 2022 (65 cursos). "
            "Está FORA deste recorte, por decisão de escopo declarada — não por "
            "ausência de dado.",
            "A avaliação de Administração é do ciclo CPC 2022, não 2023: 2023 é "
            "o ciclo da saúde e das engenharias. Comparar estes conceitos com os "
            "de um curso avaliado em 2023 é comparar edições diferentes do "
            "mesmo instrumento.",
            "81 dos 1.805 cursos avaliados não têm CPC contínuo. Ficam sem "
            "conceito, não com conceito zero.",
            "O CEMPRE traz 5.570 municípios; o IBGE reconhece 5.571 desde a "
            "instalação de Boa Esperança do Norte (MT) em 01/01/2025. O "
            "município ausente da fonte fica sem dado, não com zero.",
            "Os vínculos da RAIS são vínculos, não pessoas: quem tem dois "
            "empregos formais como administrador conta duas vezes. Os "
            "microdados públicos não permitem desduplicar por pessoa, e "
            "estimar a desduplicação seria inventar o número que falta.",
        ] + ([
            f"A RAIS lida é de {meta_rais.get('ano')} e o CEMPRE, de "
            f"{meta_rais.get('ano_cempre_pareado')}. Como as duas edições não "
            "coincidem, a densidade de administradores por mil ocupados não é "
            "publicada."
        ] if meta_rais and not meta_rais.get("anos_casam", True) else []),
    }


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--bruto", default=str(DATA / "bruto.json"))
    p.add_argument("--qualidade", default=str(DATA / "qualidade.json"))
    p.add_argument("--absorcao", default=str(DATA / "absorcao.json"))
    p.add_argument("--saida", default=str(DATA / "nacional.json"))
    args = p.parse_args()

    bruto = _ler(args.bruto)
    qualidade = _ler(args.qualidade, obrigatorio=False)
    absorcao = _ler(args.absorcao, obrigatorio=False)

    ufs = bruto["ufs"]
    municipios = bruto["municipios"]

    juntar_qualidade(ufs, qualidade)
    juntar_absorcao(ufs, municipios, absorcao)
    aplicar(ufs)

    # A densidade de administradores e o quociente RAIS/CEMPRE. Se as duas
    # fontes forem de anos diferentes, o quociente é anulado AQUI, depois de
    # calculado, em vez de nunca ser calculado: assim a regra fica num lugar só
    # e é visível. Um numerador de 2025 sobre um denominador de 2024 não mede
    # nada que se possa nomear, e um número sem nome é pior que uma lacuna.
    meta_rais = ((absorcao or {}).get("metadados") or {}).get("rais") or {}
    if meta_rais and not meta_rais.get("anos_casam", True):
        for d in ufs.values():
            d["administradores_por_mil_ocupados"] = None
        print(f"[CONSOLIDAR] RAIS {meta_rais.get('ano')} e CEMPRE "
              f"{meta_rais.get('ano_cempre_pareado')} são de anos diferentes: "
              "a densidade por mil ocupados fica nula, não aproximada.")

    metadados = dict(bruto["metadados"])
    metadados["proveniencia"] = proveniencia(bruto, qualidade, absorcao)
    nacional = {"metadados": metadados, "ufs": ufs}

    Path(args.saida).write_text(
        json.dumps(nacional, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    campos = len(next(iter(ufs.values())))
    print(f"[CONSOLIDAR] {len(ufs)} UFs, {campos} campos por UF -> {args.saida}")

    destino_mun = DATA / "municipios"
    destino_mun.mkdir(parents=True, exist_ok=True)
    total = 0
    for uf, lista in municipios.items():
        (destino_mun / f"{uf}.json").write_text(
            json.dumps({"uf": uf, "municipios": lista},
                       ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        total += len(lista)
    print(f"[CONSOLIDAR] {total} municípios em {len(municipios)} arquivos "
          f"-> {destino_mun}")

    (DATA / "_proveniencia.json").write_text(
        json.dumps(metadados["proveniencia"], ensure_ascii=False, indent=2),
        encoding="utf-8", newline="\n")
    print(f"[CONSOLIDAR] proveniência -> data/_proveniencia.json")

    faltando = [n for n, f in metadados["proveniencia"]["fontes"].items()
                if isinstance(f, dict) and f.get("presente") is False]
    if faltando:
        print(f"[CONSOLIDAR] ATENÇÃO: fontes ausentes: {faltando}. "
              "Os indicadores correspondentes estão nulos, não zerados.")


if __name__ == "__main__":
    main()

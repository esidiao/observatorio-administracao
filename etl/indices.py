"""
etl/indices.py
Fórmulas canônicas do Observatório Nacional da Formação em Administração
e o portão GO.

Uso:
    python etl/indices.py --autoteste
    python etl/indices.py --dados data/bruto.json --qualidade etl/qualidade_uf.csv \
                          --saida data/nacional.json

TODA FUNÇÃO AQUI DEVOLVE None QUANDO FALTA INSUMO
--------------------------------------------------
Nunca 0, nunca média, nunca valor de outra UF. `None` atravessa o pipeline até
virar "sem dados" na tela. Zero é uma afirmação — "não há nenhum" — e afirmar
isso sem fonte é inventar dado.

A TENTAÇÃO AQUI É DIFERENTE DA DE FONOAUDIOLOGIA
-------------------------------------------------
Lá as lacunas eram grandes e visíveis: 24 UFs com oferta presencial, 74 cursos
avaliados, três estados sem curso nenhum. O risco era preencher o vazio.

Aqui os números são enormes e quase completos — 27 de 27 UFs com oferta
presencial, 1.805 cursos avaliados, IDD em todos eles — e o risco vira o
oposto: tratar como sólido o que é apenas volumoso. Dois terços da capacidade
do país são de cursos a distância cujas vagas estão registradas na SEDE DA
MANTENEDORA, não onde o aluno está. Nenhum índice daqui conserta isso; o que
eles podem fazer é não esconder. Por isso `vagas_total` e tudo que deriva dela
carregam a marca de origem até a tela.

O portão GO (`--autoteste`) roda antes de qualquer publicação, no CI, contra
uma UF sintética cujos valores foram calculados à mão. É sintética de propósito:
um caso real amarra o teste à edição do Censo e o transforma em teste de dados
quando ele deveria testar fórmula.
"""
import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).parent.parent


# --------------------------------------------------------------------------- #
# TERRITÓRIO
# --------------------------------------------------------------------------- #

def ict(vagas_capital, vagas_total, mun_oferta, mun_total):
    """
    Índice de Concentração Territorial. 0 a 1, MENOR é melhor.

        ICT = ½·(vagas_capital / vagas_total) + ½·(1 − mun_oferta / mun_total)

    Metade mede concentração na capital, metade mede vazio no interior. Uma UF
    com todas as vagas na capital e um só município com oferta tende a 1.
    """
    if not vagas_total or not mun_total:
        return None
    if vagas_capital is None or mun_oferta is None:
        return None
    return 0.5 * (vagas_capital / vagas_total) + 0.5 * (1 - mun_oferta / mun_total)


def equidade(valor_ict):
    """E = 1 − ICT. 0 a 1, MAIOR é melhor."""
    return None if valor_ict is None else 1 - valor_ict


# --------------------------------------------------------------------------- #
# QUALIDADE
# --------------------------------------------------------------------------- #

def q_qualidade(cc, enade, idd):
    """
    Componente de qualidade, 0 a 1: média de (nota − 1) / 4 sobre os conceitos
    DISPONÍVEIS. Conceitos INEP vão de 1 a 5.

    A média ignora os ausentes em vez de tratá-los como zero. Um conceito
    ausente não é um conceito ruim: somar zero no lugar puniria a lacuna como se
    fosse desempenho medido.

    Em Administração a lacuna não está no IDD — o CPC 2022 traz IDD para os
    1.805 cursos avaliados. Está no CPC contínuo, ausente em 81 deles. É o
    contrário de Fonoaudiologia, onde faltava o IDD em 6 de 74; a regra é a
    mesma justamente por não depender de qual conceito falta.
    """
    partes = [(v - 1) / 4 for v in (cc, enade, idd) if v is not None]
    return sum(partes) / len(partes) if partes else None


def iaf(cc, enade, idd, vagas_avaliadas, vagas_total, valor_ict):
    """
    Índice de Adequação Formativa. 0 a 100, MAIOR é melhor.

        IAF = 100 · média(Q, V, E)

    Q = qualidade dos conceitos; V = fração das vagas em cursos avaliados;
    E = equidade territorial (1 − ICT).

    Devolve None se qualquer um dos três faltar: um IAF calculado sobre dois
    terços dos componentes não é comparável com um calculado sobre três, e
    publicá-los na mesma coluna produziria um ranking sem sentido.
    """
    if not vagas_total or valor_ict is None or vagas_avaliadas is None:
        return None
    q = q_qualidade(cc, enade, idd)
    if q is None:
        return None
    v = vagas_avaliadas / vagas_total
    e = equidade(valor_ict)
    return round(100 * (q + v + e) / 3, 1)


# --------------------------------------------------------------------------- #
# CONCENTRAÇÃO DE MERCADO
# --------------------------------------------------------------------------- #

def hhi(vagas_por_agente):
    """
    Herfindahl-Hirschman: Σ(sᵢ²) sobre as fatias de vagas. 0 a 1.

    Serve tanto para IES quanto para MANTENEDORA — e a diferença entre as duas
    é o ponto. Um grupo educacional opera várias IES; medir só por IES esconde
    o grupo. No observatório de Farmácia, calcular a mantenedora apenas sobre o
    presencial deu 0,06 para SP contra 0,36 do valor real: a concentração vinha
    justamente dos grandes grupos EaD, que só aparecem quando a capacidade da
    UF inclui a EaD atribuída à UF-sede.
    """
    if not vagas_por_agente:
        return None
    total = sum(vagas_por_agente.values())
    if total <= 0:
        return None
    return round(sum((v / total) ** 2 for v in vagas_por_agente.values()), 4)


def cr(vagas_por_agente, n):
    """CR_n: soma das n maiores fatias. 0 a 1."""
    if not vagas_por_agente:
        return None
    total = sum(vagas_por_agente.values())
    if total <= 0:
        return None
    maiores = sorted(vagas_por_agente.values(), reverse=True)[:n]
    return round(sum(maiores) / total, 4)


# --------------------------------------------------------------------------- #
# ABSORÇÃO PROFISSIONAL — duas fontes, duas perguntas, nenhuma fusão
# --------------------------------------------------------------------------- #
#
# O ICON de Farmácia (municípios com Farmácia Popular sobre municípios com
# oferta) e o ICAF de Fonoaudiologia (municípios com fonoaudiólogo no SUS) medem
# uma rede pública identificável. Nenhum dos dois transfere: o administrador não
# atua numa rede pública, atua na economia inteira.
#
# A pergunta equivalente — "onde existe economia formal que absorve quem se
# forma?" — tem duas metades. A RAIS responde quem JÁ foi absorvido; o CEMPRE
# responde qual é o tamanho do mercado que poderia absorver. Fundi-las num
# índice só exigiria um peso arbitrário entre "tem administrador empregado" e
# "tem economia formal", e peso arbitrário é estimativa disfarçada. Ficam
# separadas, cada uma com sua escala.


def iap(mun_com_administrador, mun_total):
    """
    Índice de Absorção Profissional. Fração dos municípios da UF com ao menos
    um vínculo formal ativo de administrador (RAIS, CBO 2002 família 2521).
    0 a 1, MAIOR é melhor.

    Zero é resultado legítimo AQUI, e só aqui: a RAIS varre todos os
    estabelecimentos formais do município, então "nenhum administrador
    vinculado" é medida, não lacuna. Município que a fonte não varreu chega
    como None e continua None.
    """
    if not mun_total or mun_com_administrador is None:
        return None
    return round(mun_com_administrador / mun_total, 4)


def densidade_por_mil_ocupados(administradores, pessoal_ocupado):
    """
    Administradores formais por mil ocupados na economia formal da UF.
    RAIS sobre CEMPRE, ambos municipais e do mesmo ano.

    É o número que torna o IAP interpretável. Uma UF pode ter administrador em
    quase todo município e ainda assim uma densidade baixíssima — são perguntas
    diferentes, e por isso são dois indicadores, não um.
    """
    if not pessoal_ocupado or administradores is None:
        return None
    return round(1000 * administradores / pessoal_ocupado, 2)


# --------------------------------------------------------------------------- #
# PORTÃO GO — autoteste contra UF sintética
# --------------------------------------------------------------------------- #

# UF sintética. Os números foram escolhidos para que cada valor esperado seja
# verificável de cabeça, sem rodar o código:
#   ICT  = ½·(600/1000) + ½·(1 − 5/25)  = 0,30 + 0,40 = 0,700
#   E    = 0,300
#   Q    = média[(3−1)/4 ×3]            = 0,500
#   V    = 500/1000                     = 0,500
#   IAF  = 100·(0,5 + 0,5 + 0,3)/3      = 43,3
#   HHI  = 0,4² + 0,3² + 0,2² + 0,1²    = 0,300
#   CR2  = (400+300)/1000               = 0,700
#   IAP  = 18/25                        = 0,720
#   dens = 1000·900/300000              = 3,00
SINTETICA = {
    "uf": "ZZ",
    "vagas_total": 1000,
    "vagas_capital": 600,
    "municipios_total": 25,
    "municipios_oferta": 5,
    "CC": 3.0,
    "ENADE": 3.0,
    "IDD": 3.0,
    "vagas_avaliadas": 500,
    "vagas_por_ies": {"A": 400, "B": 300, "C": 200, "D": 100},
    "vagas_por_mantenedora": {"Grupo1": 500, "Grupo2": 500},
    "municipios_com_administrador": 18,
    "administradores_rais": 900,
    "pessoal_ocupado": 300000,
}

CANONICO = {
    "ICT": 0.700,
    "E": 0.300,
    "IAF": 43.3,
    "HHI": 0.300,
    "HHI_mantenedora": 0.500,
    "CR2": 0.700,
    "CR10": 1.000,
    "IAP": 0.720,
    "administradores_por_mil_ocupados": 3.00,
}
TOLERANCIA = 0.001


def _calcular_sintetica():
    d = SINTETICA
    v_ict = ict(d["vagas_capital"], d["vagas_total"],
                d["municipios_oferta"], d["municipios_total"])
    return {
        "ICT": round(v_ict, 3),
        "E": round(equidade(v_ict), 3),
        "IAF": iaf(d["CC"], d["ENADE"], d["IDD"],
                   d["vagas_avaliadas"], d["vagas_total"], v_ict),
        "HHI": hhi(d["vagas_por_ies"]),
        "HHI_mantenedora": hhi(d["vagas_por_mantenedora"]),
        "CR2": cr(d["vagas_por_ies"], 2),
        "CR10": cr(d["vagas_por_ies"], 10),
        "IAP": iap(d["municipios_com_administrador"], d["municipios_total"]),
        "administradores_por_mil_ocupados": densidade_por_mil_ocupados(
            d["administradores_rais"], d["pessoal_ocupado"]),
    }


def _testar_ausencias():
    """
    Segunda metade do portão: ausência tem de propagar como None, nunca como 0.

    Sem isso, uma UF sem CPC apareceria com IAF 0 — indistinguível de uma UF
    avaliada e péssima — e o ranking colocaria as não-avaliadas no fundo como
    se fosse mérito medido.
    """
    casos = [
        ("IAF sem nenhum conceito",
         iaf(None, None, None, 500, 1000, 0.5), None),
        ("IAF sem vagas avaliadas",
         iaf(3.0, 3.0, 3.0, None, 1000, 0.5), None),
        ("IAF com ICT ausente",
         iaf(3.0, 3.0, 3.0, 500, 1000, None), None),
        ("Q ignora conceito ausente, não zera",
         q_qualidade(3.0, 3.0, None), 0.5),
        ("ICT sem municípios com oferta",
         ict(600, 1000, None, 25), None),
        ("IAP sem contagem de municípios",
         iap(None, 25), None),
        ("IAP com contagem zero é 0, não None",
         iap(0, 25), 0.0),
        ("densidade sem administradores",
         densidade_por_mil_ocupados(None, 300000), None),
        ("densidade sem pessoal ocupado (não divide por zero)",
         densidade_por_mil_ocupados(900, 0), None),
        ("densidade com zero administradores é 0, não None",
         densidade_por_mil_ocupados(0, 300000), 0.0),
        ("HHI sem agentes",
         hhi({}), None),
        ("HHI com total zero",
         hhi({"A": 0}), None),
    ]
    ok = True
    print("\n=== AUSÊNCIAS (None nunca vira 0) ===")
    for rotulo, obtido, esperado in casos:
        passou = obtido == esperado
        ok = ok and passou
        print(f"  {'OK    ' if passou else 'FALHOU'}  {rotulo}: "
              f"obtido={obtido!r} esperado={esperado!r}")
    return ok


def autoteste():
    calculado = _calcular_sintetica()
    ok = True
    print("=== PORTÃO GO — UF sintética ===")
    for nome, esperado in CANONICO.items():
        obtido = calculado[nome]
        passou = obtido is not None and abs(obtido - esperado) <= TOLERANCIA
        ok = ok and passou
        print(f"  {'OK    ' if passou else 'FALHOU'}  {nome}: "
              f"calculado={obtido}  esperado={esperado}")

    ok = _testar_ausencias() and ok

    if ok:
        print("\n[PASSOU] Fórmulas conferem. Pode prosseguir.")
        return 0
    print("\n[FALHOU] Portão GO reprovou. Corrigir antes de publicar.", file=sys.stderr)
    return 1


# --------------------------------------------------------------------------- #
# APLICAÇÃO SOBRE OS DADOS REAIS
# --------------------------------------------------------------------------- #

def _num(valor):
    """Texto -> float, com vazio virando None. Vírgula decimal aceita."""
    if valor is None:
        return None
    texto = str(valor).strip().replace(",", ".")
    if texto == "" or texto.upper() in {"NA", "N/A", "-", "NULL", "NONE"}:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


def carregar_qualidade(caminho):
    """
    CSV com UF, CC, ENADE, IDD, vagas_avaliadas.
    Célula vazia = sem dado, e continua sem dado até a saída.
    """
    qualidade = {}
    with open(caminho, encoding="utf-8") as f:
        for linha in csv.DictReader(f):
            uf = (linha.get("UF") or "").strip().upper()
            if not uf:
                continue
            qualidade[uf] = {k: _num(linha.get(k))
                             for k in ("CC", "ENADE", "IDD", "vagas_avaliadas")}
    return qualidade


def aplicar(ufs, qualidade=None):
    """
    Acrescenta os índices a cada UF do dicionário, in place. Devolve-o.

    O componente Q do IAF vem de `CPC` — a média ponderada da FAIXA do CPC,
    escala 1 a 5 — e de mais nada. `ENADE_cont` e `IDD` estão no dado e são
    publicados como indicadores próprios, mas não entram no Q: ambos vêm em
    escala contínua 0 a 5, e (v−1)/4 sobre um contínuo abaixo de 1 devolve
    componente negativo. Misturar as duas escalas dentro da mesma média produz
    um índice que ninguém consegue reproduzir a partir dos números publicados.
    """
    qualidade = qualidade or {}
    for sigla, d in ufs.items():
        q = qualidade.get(sigla, {})
        v_ict = ict(d.get("vagas_capital"), d.get("vagas_total"),
                    d.get("municipios_oferta"), d.get("municipios_total"))
        d["ICT"] = None if v_ict is None else round(v_ict, 4)
        e = equidade(v_ict)
        d["E"] = None if e is None else round(e, 4)
        for chave in ("CPC", "ENADE_cont", "IDD", "vagas_avaliadas"):
            if d.get(chave) is None:
                d[chave] = q.get(chave)
        d["IAF"] = iaf(d.get("CPC"), None, None,
                       d.get("vagas_avaliadas"), d.get("vagas_total"), v_ict)
        d["IAP"] = iap(d.get("municipios_com_administrador"),
                       d.get("municipios_total"))
        d["administradores_por_mil_ocupados"] = densidade_por_mil_ocupados(
            d.get("administradores_rais"), d.get("pessoal_ocupado"))
    return ufs


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--autoteste", action="store_true",
                   help="roda o portão GO e sai com 0 (passou) ou 1 (falhou)")
    p.add_argument("--dados", help="JSON com {'ufs': {...}}")
    p.add_argument("--qualidade", help="CSV de qualidade por UF")
    p.add_argument("--saida", help="JSON de saída")
    args = p.parse_args()

    if args.autoteste or not args.dados:
        sys.exit(autoteste())

    with open(args.dados, encoding="utf-8") as f:
        dados = json.load(f)
    qualidade = carregar_qualidade(args.qualidade) if args.qualidade else {}
    aplicar(dados["ufs"], qualidade)

    saida = args.saida or args.dados
    with open(saida, "w", encoding="utf-8") as f:
        json.dump(dados, f, ensure_ascii=False, indent=1)
    print(f"[INDICES] {len(dados['ufs'])} UFs -> {saida}")


if __name__ == "__main__":
    main()

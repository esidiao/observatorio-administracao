"""
tests/test_validacao.py
Integridade do conjunto publicado, contra âncoras conhecidas.

As âncoras foram apuradas no Censo 2024 e no CPC 2022, lendo os arquivos
originais do INEP, e conferidas contra o recorte bruto. Servem como teste de
REGRESSÃO: se o pipeline passar a produzir outra coisa, o mais provável é
defeito no pipeline, não notícia nos dados. Uma edição nova do Censo muda os
números de propósito — e aí estas constantes mudam junto, num commit que diz
isso.

O RISCO AQUI É O OPOSTO DO DE UM CURSO PEQUENO
-----------------------------------------------
No observatório de Fonoaudiologia as lacunas eram grandes e visíveis, e os
testes existiam sobretudo para impedir que fossem preenchidas. Administração
tem oferta nas 27 unidades da federação, 1.805 cursos avaliados e IDD em todos
eles: quase nada fica em branco, e a tentação passa a ser tratar como sólido o
que é apenas volumoso. Por isso os testes daqui insistem em três coisas que
número grande nenhum resolve — a separação das camadas da EaD, a exatidão do
rótulo CINE e a diferença entre ausência e zero.

Roda como script ou sob pytest.
"""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DATA = REPO / "data"
DADOS_BRUTOS = REPO / "etl" / "dados"

CENSO = 2024
CICLO_CPC = "2022"

# ------------------------------------------------------------------ âncoras
REGISTROS_CENSO = 19205           # rótulo CINE EXATO "Administração"
UFS_COM_PRESENCIAL = 27
MUNICIPIOS_COM_OFERTA = 688
VAGAS_PRESENCIAL = 372698
VAGAS_EAD = 752523
CAPACIDADE_TOTAL = 1125221
PCT_EAD = 66.9
POLOS_REGISTROS = 17011
POLOS_MUNICIPIOS = 3085
MUNICIPIOS_COM_OFERTA_OU_POLO = 3090
MATRICULAS = 652934
CONCLUINTES = 76889

IES_DISTINTAS = 1386              # no país, não a soma das contagens por UF

CURSOS_AVALIADOS = 1805
UFS_AVALIADAS = 27
CURSOS_COM_CPC = 1724
CURSOS_SEM_CPC = 81
CURSOS_COM_IDD = 1805
CONCLUINTES_PARTICIPANTES = 82636

# Registros que uma busca por SUBSTRING "administra" acrescentaria, por rótulo.
# Estão aqui para que a exclusão de Administração pública seja uma decisão
# TESTADA, e não um efeito colateral de como o filtro foi escrito.
VIZINHOS_CINE = {
    "Administração pública": 3530,
    "Programas interdisciplinares abrangendo negócios, administração e direito": 1367,
    "Programas abrangendo negócios, administração e direito em processo de "
    "definição da classificação": 8,
}
REGISTROS_A_MAIS_POR_SUBSTRING = 4905

MUNICIPIOS_BRASIL = 5571          # IBGE, desde a instalação de Boa Esperança
MUNICIPIOS_MT = 142               # do Norte (MT) em 01/01/2025


def _ler(nome):
    caminho = DATA / nome
    if not caminho.exists():
        raise SystemExit(
            f"[ERRO] {caminho} ausente. Rode o pipeline antes dos testes.")
    return json.loads(caminho.read_text(encoding="utf-8"))


def _soma(ufs, campo):
    return sum(d.get(campo) or 0 for d in ufs.values())


# ------------------------------------------------------------------ território

def test_27_ufs_presentes():
    ufs = _ler("nacional.json")["ufs"]
    assert len(ufs) == 27, f"esperado 27 UFs, veio {len(ufs)}"


def test_ufs_com_presencial():
    """
    As 27 têm curso presencial — e o teste continua olhando o SINALIZADOR, não
    presumindo o resultado.

    Administração é um dos poucos cursos em que nenhum estado fica de fora.
    Isso não autoriza tratar `tem_oferta_presencial` como sempre verdadeiro: se
    numa edição futura um estado perder a oferta, ele precisa aparecer no
    conjunto com os indicadores dependentes nulos, e não sumir do mapa. É por
    isso que a checagem de baixo existe mesmo com a lista vazia hoje.
    """
    ufs = _ler("nacional.json")["ufs"]
    com = [u for u, d in ufs.items() if d.get("tem_oferta_presencial")]
    sem = sorted(u for u, d in ufs.items() if not d.get("tem_oferta_presencial"))
    assert len(com) == UFS_COM_PRESENCIAL, (
        f"esperado {UFS_COM_PRESENCIAL} UFs com oferta presencial, "
        f"veio {len(com)} (sem oferta: {sem})")
    for sigla in sem:
        assert ufs[sigla]["municipios_total"] > 0, (
            f"{sigla} sem oferta presencial foi mantida, mas sem contagem de "
            "municípios — o estado precisa aparecer cinza, não vazio")


def test_contagem_de_municipios_do_ibge():
    ufs = _ler("nacional.json")["ufs"]
    total = _soma(ufs, "municipios_total")
    assert total == MUNICIPIOS_BRASIL, (
        f"esperado {MUNICIPIOS_BRASIL} municípios, veio {total}. "
        "Se o IBGE instalou ou extinguiu município, a mudança é real — "
        "atualize a âncora num commit que explique.")
    assert ufs["MT"]["municipios_total"] == MUNICIPIOS_MT, (
        f"MT deveria ter {MUNICIPIOS_MT} municípios, "
        f"veio {ufs['MT']['municipios_total']}")


def test_municipios_com_oferta():
    ufs = _ler("nacional.json")["ufs"]
    total = _soma(ufs, "municipios_oferta")
    assert total == MUNICIPIOS_COM_OFERTA, (
        f"esperado {MUNICIPIOS_COM_OFERTA}, veio {total}")


def test_contraste_entre_presencial_e_polo():
    """
    A manchete do observatório é a distância entre os dois alcances.

    688 municípios com curso presencial contra 3.085 com polo. Se algum dia os
    dois números convergirem, ou o país mudou ou o pipeline parou de separar as
    camadas — e nos dois casos alguém precisa olhar antes de publicar.
    """
    ufs = _ler("nacional.json")["ufs"]
    oferta = _soma(ufs, "municipios_oferta")
    polo = _soma(ufs, "ead_polos_municipios")
    assert polo == POLOS_MUNICIPIOS, f"municípios com polo: veio {polo}"
    assert polo > 4 * oferta, (
        f"polos em {polo} municípios contra oferta presencial em {oferta} — "
        "a proporção esperada é de mais de quatro para um")


def test_uniao_de_municipios_publicados():
    """Toda página municipal gerada precisa vir de um município do conjunto."""
    arquivos = sorted((DATA / "municipios").glob("*.json"))
    assert len(arquivos) == 27, (
        f"esperado 27 arquivos de município, veio {len(arquivos)}")
    codigos = set()
    for arquivo in arquivos:
        for m in json.loads(arquivo.read_text(encoding="utf-8"))["municipios"]:
            codigos.add(str(m["codigo"]))
    assert len(codigos) == MUNICIPIOS_COM_OFERTA_OU_POLO, (
        f"esperado {MUNICIPIOS_COM_OFERTA_OU_POLO} municípios com oferta ou "
        f"polo, veio {len(codigos)}")


# ------------------------------------------------------------------ capacidade

def test_vagas_presenciais_e_ead():
    """
    As duas camadas da EaD, somadas separadamente.

    Somar QT_VG_TOTAL por SG_UF sem separar sede de polo devolve vagas EaD
    zeradas — e o resultado parece plausível, que é o que torna o erro caro.
    Em Administração ele custaria dois terços da capacidade do país.
    """
    ufs = _ler("nacional.json")["ufs"]
    presencial = _soma(ufs, "vagas_presencial")
    ead = _soma(ufs, "vagas_ead")
    total = _soma(ufs, "vagas_total")
    assert presencial == VAGAS_PRESENCIAL, (
        f"vagas presenciais: esperado {VAGAS_PRESENCIAL}, veio {presencial}")
    assert ead == VAGAS_EAD, f"vagas EaD: esperado {VAGAS_EAD}, veio {ead}"
    assert total == CAPACIDADE_TOTAL, (
        f"capacidade total: esperado {CAPACIDADE_TOTAL}, veio {total}")
    assert ead > 0, ("vagas EaD zeradas — sintoma clássico de somar as linhas "
                     "de polo em vez das de sede")


def test_participacao_da_ead():
    ufs = _ler("nacional.json")["ufs"]
    pct = round(100 * _soma(ufs, "vagas_ead") / _soma(ufs, "vagas_total"), 1)
    assert pct == PCT_EAD, f"participação da EaD: esperado {PCT_EAD}%, veio {pct}%"


def test_polos_ead():
    ufs = _ler("nacional.json")["ufs"]
    registros = _soma(ufs, "ead_polos_registros")
    assert registros == POLOS_REGISTROS, (
        f"registros de polo: esperado {POLOS_REGISTROS}, veio {registros}")


def test_fluxo():
    ufs = _ler("nacional.json")["ufs"]
    assert _soma(ufs, "matriculas") == MATRICULAS, (
        f"matrículas: esperado {MATRICULAS}, veio {_soma(ufs, 'matriculas')}")
    assert _soma(ufs, "concluintes") == CONCLUINTES, (
        f"concluintes: esperado {CONCLUINTES}, veio {_soma(ufs, 'concluintes')}")


def test_concentracao_por_mantenedora_nunca_e_menor_que_por_ies():
    """
    Invariante algébrico, não valor de edição.

    Agrupar instituições sob a mesma mantenedora só pode SOMAR fatias, e somar
    fatias só pode aumentar o Herfindahl. Se `HHI_mantenedora` sair menor que
    `HHI`, o agrupamento está errado — tipicamente porque as duas contas foram
    feitas sobre universos de vagas diferentes.
    """
    ufs = _ler("nacional.json")["ufs"]
    problemas = []
    for sigla, d in ufs.items():
        if d.get("HHI") is None or d.get("HHI_mantenedora") is None:
            continue
        # Tolerância de um passo do arredondamento de quatro casas.
        if d["HHI_mantenedora"] < d["HHI"] - 0.0001:
            problemas.append(
                f"{sigla}: HHI_mantenedora {d['HHI_mantenedora']} < HHI {d['HHI']}")
    assert not problemas, "\n  - ".join(problemas)


def test_concentracao_e_calculada_sobre_a_capacidade_total():
    """
    Refaz o HHI de mantenedora de SP a partir do recorte bruto, incluindo a EaD.

    É reimplementação independente de propósito: o teste não chama o código do
    pipeline, refaz a conta do zero e compara. Calcular a concentração só sobre
    o presencial descreve outro mercado — no observatório de Farmácia a
    diferença em SP foi de 0,06 para 0,36.

    Pulado quando `etl/dados/` não está presente: os recortes brutos não são
    versionados, e um teste que falha por falta de insumo vira ruído no CI.
    """
    cursos = DADOS_BRUTOS / f"curso_administracao_{CENSO}.csv"
    ies_csv = DADOS_BRUTOS / f"ies_{CENSO}.csv"
    if not (cursos.exists() and ies_csv.exists()):
        print("          (pulado: etl/dados/ ausente — recorte bruto não versionado)")
        return

    csv.field_size_limit(1 << 24)
    mantenedora, uf_sede = {}, {}
    with open(ies_csv, encoding="utf-8") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            codigo = (linha.get("CO_IES") or "").strip()
            if not codigo:
                continue
            mantenedora[codigo] = ((linha.get("CO_MANTENEDORA") or "").strip()
                                   or (linha.get("NO_MANTENEDORA") or "").strip()
                                   or f"IES:{codigo}")
            uf_sede[codigo] = (linha.get("SG_UF_IES") or "").strip().upper() or None

    vagas = defaultdict(int)
    with open(cursos, encoding="utf-8") as f:
        for linha in csv.DictReader(f, delimiter=";"):
            dim = (linha.get("TP_DIMENSAO") or "").strip()
            if dim not in ("1", "3"):
                continue
            bruto = (linha.get("QT_VG_TOTAL") or "").strip()
            if not bruto.lstrip("-").isdigit() or int(bruto) <= 0:
                continue
            cod_ies = (linha.get("CO_IES") or "").strip()
            sigla = (uf_sede.get(cod_ies) if dim == "3"
                     else (linha.get("SG_UF") or "").strip().upper())
            if sigla != "SP":
                continue
            vagas[mantenedora.get(cod_ies, f"IES:{cod_ies}")] += int(bruto)

    total = sum(vagas.values())
    esperado = round(sum((v / total) ** 2 for v in vagas.values()), 4)
    publicado = _ler("nacional.json")["ufs"]["SP"]["HHI_mantenedora"]
    assert abs(publicado - esperado) <= 0.0001, (
        f"HHI_mantenedora de SP: publicado {publicado}, recalculado sobre a "
        f"capacidade total {esperado}")


# ------------------------------------------------------------- série histórica

def test_ies_no_brasil_nao_e_soma_das_contagens_por_uf():
    """
    Contagem de DISTINTOS não se soma.

    Uma instituição que atua em cinco UFs entra cinco vezes na soma das
    contagens estaduais. Em Administração, onde as grandes mantenedoras de EaD
    operam no país inteiro, a soma dá 3.024 contra as 1.386 instituições reais
    — mais que o dobro, e sem nenhum sinal na tela.

    O teste confere as duas pontas: o valor publicado tem de bater com a
    contagem de distintos, E tem de ser menor que a soma. A segunda metade é o
    que garante que o teste ainda serve para alguma coisa: se um dia a soma e o
    distinto coincidirem, o primeiro assert passaria por acaso.
    """
    caminho = DATA / "serie.json"
    if not caminho.exists():
        print("          (pulado: data/serie.json ausente — rode etl/serie.py)")
        return
    serie = json.loads(caminho.read_text(encoding="utf-8"))
    ano = serie["anos"][-1]
    publicado = serie["brasil"][ano]["n_ies"]
    soma = sum((d.get(ano) or {}).get("n_ies") or 0 for d in serie["ufs"].values())
    assert publicado == IES_DISTINTAS, (
        f"IES distintas no Brasil em {ano}: esperado {IES_DISTINTAS}, "
        f"veio {publicado}")
    assert publicado < soma, (
        f"o valor publicado ({publicado}) coincide com a soma das UFs "
        f"({soma}) — ou o país mudou, ou a correção foi desfeita")


def test_serie_reproduz_o_total_do_pipeline():
    """
    A série lê o Censo por um caminho independente do pipeline principal.

    Se os dois discordarem no ano que ambos cobrem, um deles está errado — e a
    coincidência é a única prova barata de que a separação sede/polo foi feita
    igual nos dois lugares.
    """
    caminho = DATA / "serie.json"
    if not caminho.exists():
        print("          (pulado: data/serie.json ausente)")
        return
    serie = json.loads(caminho.read_text(encoding="utf-8"))
    if str(CENSO) not in serie["brasil"]:
        print(f"          (pulado: a série não cobre {CENSO})")
        return
    b = serie["brasil"][str(CENSO)]
    assert b["vagas_presencial"] == VAGAS_PRESENCIAL, (
        f"série: vagas presenciais {b['vagas_presencial']} != {VAGAS_PRESENCIAL}")
    assert b["vagas_ead"] == VAGAS_EAD, (
        f"série: vagas EaD {b['vagas_ead']} != {VAGAS_EAD}")
    assert b["municipios_oferta"] == MUNICIPIOS_COM_OFERTA
    assert b["ead_polos_registros"] == POLOS_REGISTROS


# ------------------------------------------------------------- recorte CINE

def test_recorte_usa_rotulo_exato():
    """
    O número de linhas do recorte é a prova de que o match foi por igualdade.

    Uma busca por substring "administra" traria 4.905 registros a mais — 25% de
    acréscimo silencioso, vindo de três rótulos que são outras áreas. Nenhum
    erro apareceria na tela.
    """
    prov = _ler("_proveniencia.json")["fontes"]["censo"]
    assert prov.get("rotulo_cine") == "Administração", (
        f"rótulo do recorte: {prov.get('rotulo_cine')!r}")
    assert prov.get("linhas_curso") == REGISTROS_CENSO, (
        f"esperado {REGISTROS_CENSO} registros do rótulo exato, "
        f"veio {prov.get('linhas_curso')}")
    assert sum(VIZINHOS_CINE.values()) == REGISTROS_A_MAIS_POR_SUBSTRING, (
        "a própria tabela de vizinhos não fecha — corrija a âncora")


# ------------------------------------------------------------------- qualidade

def test_qualidade_cpc():
    q = _ler("qualidade.json")
    assert q["metadados"]["ciclo"] == CICLO_CPC, (
        f"ciclo do CPC: esperado {CICLO_CPC} (Administração não está no de "
        f"2023), veio {q['metadados']['ciclo']}")
    assert len(q["cursos"]) == CURSOS_AVALIADOS, (
        f"esperado {CURSOS_AVALIADOS} cursos avaliados, veio {len(q['cursos'])}")
    assert len(q["ufs"]) == UFS_AVALIADAS
    com_cpc = sum(1 for c in q["cursos"] if c["CPC_cont"] is not None)
    com_idd = sum(1 for c in q["cursos"] if c["IDD"] is not None)
    assert com_cpc == CURSOS_COM_CPC, (
        f"com CPC: esperado {CURSOS_COM_CPC}, veio {com_cpc}")
    assert com_idd == CURSOS_COM_IDD, (
        f"com IDD: esperado {CURSOS_COM_IDD}, veio {com_idd}")
    participantes = sum(u["concluintes_participantes"] for u in q["ufs"].values())
    assert participantes == CONCLUINTES_PARTICIPANTES, (
        f"concluintes participantes: esperado {CONCLUINTES_PARTICIPANTES}, "
        f"veio {participantes}")


def test_curso_sem_cpc_fica_nulo_e_nao_zero():
    """
    81 dos 1.805 cursos avaliados não têm CPC contínuo.

    Precisam sair `None`. Zero colocaria esses cursos — e as UFs que os abrigam
    — no fundo de qualquer ranking de qualidade como se tivessem sido medidos e
    tivessem ido mal. A cobertura quase total do IDD não muda isso: um conjunto
    quase completo continua tendo o buraco que tem.
    """
    q = _ler("qualidade.json")
    sem_cpc = [c for c in q["cursos"] if c["CPC_cont"] is None]
    assert len(sem_cpc) == CURSOS_SEM_CPC, (
        f"esperado {CURSOS_SEM_CPC} cursos sem CPC contínuo, veio {len(sem_cpc)}")
    zerados = [c["cod_curso"] for c in q["cursos"] if c["CPC_cont"] == 0]
    assert not zerados, f"cursos com CPC contínuo igual a zero: {zerados[:5]}"


# ------------------------------------------------------------------- absorção

def test_absorcao_respeita_a_diferenca_entre_zero_e_ausencia():
    """
    Aqui o zero É medida — e só aqui.

    A RAIS varre todos os estabelecimentos formais do município, então "nenhum
    administrador vinculado" é o que a fonte encontrou. Já o município que a
    fonte não alcançou tem de sair `None`. O teste confere as duas pontas e não
    exige que a RAIS esteja presente: sem ela, tudo fica nulo, que é o
    comportamento correto de fonte ausente.
    """
    ufs = _ler("nacional.json")["ufs"]
    fontes = _ler("_proveniencia.json")["fontes"]
    tem_rais = fontes.get("rais", {}).get("presente")

    if not tem_rais:
        for sigla, d in ufs.items():
            assert d.get("IAP") is None, (
                f"{sigla}.IAP = {d['IAP']} sem a RAIS na proveniência — "
                "fonte ausente tem de produzir nulo, nunca zero")
        return

    problemas = []
    for sigla, d in ufs.items():
        iap = d.get("IAP")
        if iap is None:
            problemas.append(f"{sigla}: sem IAP com a RAIS presente")
            continue
        if not 0 <= iap <= 1:
            problemas.append(f"{sigla}: IAP {iap} fora de 0..1")
        if d.get("municipios_com_administrador") is None:
            problemas.append(f"{sigla}: contagem de municípios ausente")
    assert not problemas, "\n  - ".join(problemas)


def test_densidade_so_existe_com_as_duas_fontes_do_mesmo_ano():
    """
    A densidade é RAIS sobre CEMPRE. Anos diferentes nos dois lados do
    quociente não medem nada que se possa nomear, e um número sem nome é pior
    que uma lacuna.
    """
    ufs = _ler("nacional.json")["ufs"]
    fontes = _ler("_proveniencia.json")["fontes"]
    rais = fontes.get("rais", {})
    cempre = fontes.get("cempre", {})
    casam = bool(rais.get("presente") and cempre.get("presente")
                 and str(rais.get("ano")) == str(cempre.get("ano")))
    problemas = []
    for sigla, d in ufs.items():
        valor = d.get("administradores_por_mil_ocupados")
        if not casam and valor is not None:
            problemas.append(
                f"{sigla}: densidade {valor} com RAIS {rais.get('ano')} e "
                f"CEMPRE {cempre.get('ano')} — anos que não casam")
        if casam and d.get("pessoal_ocupado") and valor is None:
            problemas.append(f"{sigla}: densidade nula com as duas fontes")
    assert not problemas, "\n  - ".join(problemas)


# ------------------------------------------------------- princípio inegociável

def test_ausencia_nunca_e_zero():
    """
    Varre o conjunto atrás de zeros que deveriam ser nulos.

    Regra: se a UF não tem oferta presencial, os índices que dependem dela não
    podem ter valor numérico. `None` chega à tela como "sem dados"; `0` chega
    como afirmação.
    """
    ufs = _ler("nacional.json")["ufs"]
    problemas = []
    for sigla, d in ufs.items():
        if d.get("tem_oferta_presencial"):
            continue
        for campo in ("ICT", "E", "IAF", "HHI", "HHI_mantenedora", "CR2", "CR10"):
            if d.get(campo) is not None:
                problemas.append(f"{sigla}.{campo} = {d[campo]} (deveria ser None)")
    assert not problemas, "valores numéricos onde deveria haver ausência:\n  - " \
                          + "\n  - ".join(problemas)


def test_iaf_so_existe_com_os_tres_componentes():
    ufs = _ler("nacional.json")["ufs"]
    problemas = []
    for sigla, d in ufs.items():
        tem_tudo = (d.get("CPC") is not None
                    and d.get("vagas_avaliadas") is not None
                    and d.get("ICT") is not None)
        if d.get("IAF") is not None and not tem_tudo:
            problemas.append(f"{sigla}: IAF={d['IAF']} sem os três componentes")
        if d.get("IAF") is None and tem_tudo:
            problemas.append(f"{sigla}: componentes completos mas IAF nulo")
    assert not problemas, "\n  - ".join(problemas)


def test_percentuais_dentro_da_faixa():
    ufs = _ler("nacional.json")["ufs"]
    problemas = []
    for sigla, d in ufs.items():
        for campo, valor in d.items():
            if campo.startswith("pct_") and valor is not None:
                if not 0 <= valor <= 100:
                    problemas.append(f"{sigla}.{campo} = {valor}")
    assert not problemas, ("percentuais fora de 0..100:\n  - "
                           + "\n  - ".join(problemas))


# ---------------------------------------------------------------- proveniência

def test_proveniencia_vem_do_arquivo():
    """
    O ano do Censo tem de vir do arquivo lido, não do calendário.

    Derivar `ano - 1` da data de hoje rotula o Censo 2024 como 2025 durante todo
    o ano seguinte, e o erro só aparece muito depois, num gráfico de série.
    """
    meta = _ler("nacional.json")["metadados"]
    assert meta["ano_censo"] == CENSO
    prov = meta["proveniencia"]["fontes"]["censo"]
    assert prov.get("ano_censo") == CENSO
    assert prov.get("md5_publicado"), "sem md5 publicado pelo INEP na proveniência"
    assert str(CENSO) in prov.get("membro_cursos", ""), (
        "o membro lido não confere com o ano declarado")


def test_limitacoes_declaradas():
    """O que não foi medido precisa estar escrito, não subentendido."""
    prov = _ler("_proveniencia.json")
    texto = " ".join(prov["limitacoes_conhecidas"]).lower()
    exigidas = {
        "mantenedora": "o registro das vagas de EaD na sede da mantenedora",
        "administração pública": "a exclusão de Administração pública do recorte",
        "2022": "o ciclo do CPC",
        "cempre": "a cobertura do CEMPRE",
        "vínculos": "a contagem de vínculos e não de pessoas na RAIS",
    }
    faltando = [motivo for chave, motivo in exigidas.items() if chave not in texto]
    assert not faltando, "limitações não declaradas: " + "; ".join(faltando)


def main():
    testes = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    falhas = 0
    for teste in testes:
        try:
            teste()
            print(f"  OK      {teste.__name__}")
        except AssertionError as e:
            falhas += 1
            print(f"  FALHOU  {teste.__name__}: {e}")
    print(f"\n{len(testes) - falhas}/{len(testes)} testes de integridade passaram.")
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(main())

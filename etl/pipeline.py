"""
etl/pipeline.py
Orquestrador: verifica fontes, extrai, calcula, confere e só então publica.

Uso:
    python etl/pipeline.py --check-only        # só verifica frescor das fontes
    python etl/pipeline.py --ano 2024          # pipeline completo
    python etl/pipeline.py --ano 2024 --pular-rais

A ORDEM NÃO É NEGOCIÁVEL
------------------------
    extrair_censo -> ingestao -> extrair_cpc -> extrair_absorcao -> consolidar

`ingestao` produz `vagas_presencial` e `vagas_ead`; só depois disso faz sentido
`consolidar` calcular pct_ead, HHI sobre a capacidade total e o ICT. Invertido,
o consolidador grava `None` em cadeia sem reclamar de nada: o arquivo sai com as
chaves certas e os valores vazios, e nenhum teste de integridade repara, porque
as chaves existem.

A GUARDA DE RIQUEZA
-------------------
`conferir_riqueza()` compara o número de campos por UF com o que está em
`git show HEAD` e ABORTA se o resultado novo for mais pobre.

Ela existe por um caso concreto do observatório de Farmácia: republicar por um
caminho parcial derrubou 33 dos 51 campos por UF, com todos os testes verdes —
porque nenhum teste checava PRESENÇA de campo. Aqui o risco é o mesmo com outra
cara: rodar com `--pular-rais` produz um conjunto que passa em tudo e chega ao
site com a seção de absorção inteira em branco. O site continuou no ar, bonito,
com dois terços das páginas vazias, e ninguém notou por semanas.

TRÊS ESTADOS POR FONTE, NUNCA DOIS
-----------------------------------
publicada / confirmadamente ausente / indeterminado. Tratar falha de rede como
"sem novidade" silencia o alerta inteiro — no projeto de Farmácia isso regrediu
duas vezes. Aqui `rede.sondar` nunca devolve booleano puro, o que torna o erro
difícil de cometer por acidente.
"""
import argparse
import json
import os
import subprocess
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from rede import sondar  # noqa: E402

REPO = Path(__file__).resolve().parent.parent
ETL = REPO / "etl"
DATA = REPO / "data"

URL_CENSO = ("https://download.inep.gov.br/microdados/"
             "microdados_censo_da_educacao_superior_{ano}.zip")

# O CPC não tem UM nome de arquivo: 2023 é `CPC_2023.xlsx`, 2022 é
# `cpc_2022.xlsx`. Sondar um nome só e concluir "não publicado" a partir do 404
# é como se perde uma edição inteira — foi assim que o ciclo 2022, que é o de
# Administração, quase ficou de fora deste projeto.
from extrair_cpc import BASE_CPC, NOMES_CPC  # noqa: E402

HOST_RAIS = "ftp.mtps.gov.br"
DIR_RAIS = "/pdet/microdados/RAIS"
API_AGREGADOS = "https://servicodados.ibge.gov.br/api/v3/agregados"

# Fontes cuja publicação NÃO é verificável automaticamente hoje, com o motivo
# concreto. Ficam declaradas para que a limitação apareça no relatório semanal
# em vez de virar um silêncio que passa por "tudo em dia".
FONTES_SEM_SONDAGEM = {
    "e_mec": (
        "e-MEC não expõe API pública nem URL de arquivo estável; o portal é "
        "renderizado por JavaScript e não há endpoint documentado."
    ),
}


def _github_output(chave, valor):
    caminho = os.environ.get("GITHUB_OUTPUT", "")
    if caminho:
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"{chave}={valor}\n")


def _rodar(script, *args):
    comando = [sys.executable, str(ETL / script), *map(str, args)]
    print(f"\n[PIPELINE] $ {' '.join(comando[1:])}")
    resultado = subprocess.run(comando, cwd=str(ETL))
    if resultado.returncode != 0:
        raise SystemExit(f"[PIPELINE] {script} falhou "
                         f"(código {resultado.returncode}). Nada foi publicado.")


# --------------------------------------------------------------------------- #
# Verificação de frescor
# --------------------------------------------------------------------------- #

def _serie_anual(rotulo, url_padrao, ano_atual, ano_limite):
    """Procura edição mais recente que `ano_atual`. Devolve (novidades, indeterminados)."""
    novidades, indeterminados = [], []
    if not ano_atual:
        return novidades, ["{}: ano corrente desconhecido".format(rotulo)]
    for ano in range(int(ano_atual) + 1, ano_limite + 1):
        existe, detalhe = sondar(url_padrao.format(ano=ano))
        if existe:
            novidades.append(f"{rotulo} {ano}")
            print(f"[CHECK] NOVIDADE: {rotulo} {ano} publicado (atual: {ano_atual}).")
        elif existe is None:
            indeterminados.append(f"{rotulo} {ano} ({detalhe})")
            print(f"[CHECK] INDETERMINADO: {rotulo} {ano} não verificável ({detalhe}).")
        else:
            print(f"[CHECK] {rotulo} {ano}: confirmadamente não publicado (404).")
    return novidades, indeterminados


def _serie_cpc(ciclo_atual, ano_limite):
    """
    Procura ciclo mais recente do CPC, testando TODOS os nomes de arquivo.

    Um 404 num nome não é ausência do ciclo: o INEP alterna a caixa do nome
    entre edições. O ciclo só é dado por não publicado quando todos os
    candidatos respondem 404 confirmado; se algum ficou indeterminado, o ano
    inteiro entra como indeterminado.
    """
    novidades, indeterminados = [], []
    if not ciclo_atual:
        return novidades, ["CPC: ciclo corrente desconhecido"]

    for ano in range(int(ciclo_atual) + 1, ano_limite + 1):
        houve_indeterminado = []
        encontrado = False
        for molde in NOMES_CPC:
            nome = molde.format(ciclo=ano)
            existe, detalhe = sondar(BASE_CPC.format(ciclo=ano) + nome)
            if existe:
                novidades.append(f"CPC {ano} ({nome})")
                print(f"[CHECK] NOVIDADE: CPC {ano} publicado como {nome} "
                      f"(atual: {ciclo_atual}).")
                encontrado = True
                break
            if existe is None:
                houve_indeterminado.append(f"{nome}: {detalhe}")
        if encontrado:
            continue
        if houve_indeterminado:
            indeterminados.append(f"CPC {ano} ({'; '.join(houve_indeterminado)})")
            print(f"[CHECK] INDETERMINADO: CPC {ano} não verificável.")
        else:
            print(f"[CHECK] CPC {ano}: nenhum dos nomes candidatos existe (404).")
    return novidades, indeterminados


def _edicao_rais(ano_atual):
    """
    Verifica a RAIS pela EDIÇÃO disponível no FTP.

    Os diretórios "AAAA Parcial" são edições incompletas e ficam de fora pela
    forma do nome — só quatro dígitos entram. A edição adotada pelo pipeline é
    a que casa com o ano do CEMPRE, não a mais nova; então uma edição mais nova
    aparece aqui como NOTÍCIA, que é onde ela deve aparecer.
    """
    from ftplib import FTP

    try:
        f = FTP(HOST_RAIS, timeout=120)
        # latin-1 ANTES do login: a saudação já vem acentuada e a decodificação
        # padrão em UTF-8 estoura antes de a sessão existir.
        f.encoding = "latin-1"
        f.login()
        f.cwd(DIR_RAIS)
        nomes = f.nlst()
        f.close()
    except Exception as e:                                     # noqa: BLE001
        return [], [f"RAIS ({type(e).__name__}) — não foi possível listar o FTP"]

    anos = sorted(n for n in nomes if n.isdigit() and len(n) == 4)
    if not anos:
        return [], ["RAIS (nenhuma edição encontrada — layout mudou?)"]
    if not ano_atual:
        return [], ["RAIS (proveniência sem ano registrado)"]

    mais_novas = [a for a in anos if int(a) > int(ano_atual)]
    if mais_novas:
        print(f"[CHECK] NOVIDADE: RAIS {mais_novas[-1]} disponível "
              f"(em uso: {ano_atual}).")
        return [f"RAIS {mais_novas[-1]}"], []
    print(f"[CHECK] RAIS: {ano_atual} continua sendo a mais recente.")
    return [], []


def _agregado_cempre(agregado_atual, ano_atual):
    """
    Verifica o CEMPRE por DOIS caminhos, porque um só não basta.

    O agregado em uso pode ganhar período novo — caso fácil. Mas o IBGE também
    ENCERRA um agregado e abre outro: a série que ia até 2021 no agregado 1685
    continua no 9509, com as mesmas variáveis e o mesmo nível municipal. Quem
    só olhasse o 1685 concluiria para sempre que o CEMPRE parou em 2021, e
    publicaria essa afirmação como limitação conhecida. Ela seria falsa.

    Por isso a segunda checagem varre a lista de agregados do IBGE atrás de
    qualquer agregado do CEMPRE cujo período final seja posterior ao ano em
    uso.
    """
    from rede import ler_json

    novidades, indeterminados = [], []
    try:
        meta = ler_json(f"{API_AGREGADOS}/{agregado_atual}/metadados")
    except Exception as e:                                     # noqa: BLE001
        return [], [f"CEMPRE {agregado_atual} ({type(e).__name__})"]

    fim = (meta.get("periodicidade") or {}).get("fim")
    if ano_atual and fim and int(fim) > int(ano_atual):
        novidades.append(f"CEMPRE {fim} (agregado {agregado_atual})")
        print(f"[CHECK] NOVIDADE: agregado {agregado_atual} chegou a {fim} "
              f"(em uso: {ano_atual}).")

    try:
        todos = ler_json(API_AGREGADOS)
    except Exception as e:                                     # noqa: BLE001
        indeterminados.append(
            f"CEMPRE — lista de agregados ({type(e).__name__}); não foi "
            "possível conferir se a série migrou para outro agregado")
        return novidades, indeterminados

    sucessores = []
    for pesquisa in todos:
        if "cadastro central de empresas" not in (pesquisa.get("nome") or "").lower():
            continue
        for ag in pesquisa.get("agregados", []):
            if int(ag["id"]) == int(agregado_atual):
                continue
            try:
                m = ler_json(f"{API_AGREGADOS}/{ag['id']}/metadados")
            except Exception:                                  # noqa: BLE001
                continue
            f = (m.get("periodicidade") or {}).get("fim")
            niveis = (m.get("nivelTerritorial") or {}).get("Administrativo") or []
            if f and ano_atual and int(f) > int(ano_atual) and "N6" in niveis:
                sucessores.append(f"{ag['id']} (até {f})")

    if sucessores:
        novidades.append("CEMPRE — agregado sucessor: " + ", ".join(sucessores))
        print(f"[CHECK] NOVIDADE: agregado(s) do CEMPRE com período mais "
              f"recente e nível municipal: {', '.join(sucessores)}")
    elif not novidades:
        print(f"[CHECK] CEMPRE: {ano_atual} continua sendo o mais recente.")
    return novidades, indeterminados


def verificar_fontes():
    prov = {}
    caminho = DATA / "_proveniencia.json"
    if caminho.exists():
        prov = json.loads(caminho.read_text(encoding="utf-8")).get("fontes", {})

    ano_limite = date.today().year
    novidades, indeterminados = [], []

    ano_censo = (prov.get("censo") or {}).get("ano_censo")
    n, i = _serie_anual("Censo da Educação Superior", URL_CENSO, ano_censo, ano_limite)
    novidades += n
    indeterminados += i

    ciclo_cpc = (prov.get("cpc") or {}).get("ciclo")
    n, i = _serie_cpc(ciclo_cpc, ano_limite)
    novidades += n
    indeterminados += i

    ano_rais = (prov.get("rais") or {}).get("ano")
    n, i = _edicao_rais(ano_rais)
    novidades += n
    indeterminados += i

    cempre = prov.get("cempre") or {}
    n, i = _agregado_cempre(cempre.get("agregado"), cempre.get("ano"))
    novidades += n
    indeterminados += i

    print()
    for nome, motivo in FONTES_SEM_SONDAGEM.items():
        print(f"[CHECK] SEM SONDAGEM: {nome} — {motivo}")

    print()
    if novidades:
        print(f"[CHECK] {len(novidades)} fonte(s) com edição nova: "
              f"{', '.join(novidades)}")
    else:
        print("[CHECK] nenhuma edição nova encontrada.")
    if indeterminados:
        print(f"[CHECK] {len(indeterminados)} verificação(ões) INDETERMINADA(s): "
              f"{', '.join(indeterminados)}")
        print("[CHECK] indeterminado NÃO é ausente. Reveja manualmente antes de "
              "concluir que nada mudou.")

    _github_output("fontes_novas", "true" if novidades else "false")
    _github_output("fontes_novas_detalhe", "; ".join(novidades))
    _github_output("fontes_indeterminadas", "true" if indeterminados else "false")
    _github_output("fontes_indeterminadas_detalhe", "; ".join(indeterminados))
    return novidades, indeterminados


# --------------------------------------------------------------------------- #
# Guarda de riqueza
# --------------------------------------------------------------------------- #

def _versao_anterior(caminho_relativo):
    """Conteúdo do arquivo em HEAD, ou None se não houver (repo novo, arquivo novo)."""
    try:
        saida = subprocess.run(
            ["git", "show", f"HEAD:{caminho_relativo}"],
            cwd=str(REPO), capture_output=True, text=True, encoding="utf-8")
        if saida.returncode != 0:
            return None
        return json.loads(saida.stdout)
    except Exception:                                          # noqa: BLE001
        return None


def conferir_riqueza(tolerancia=0):
    """
    Compara a riqueza do conjunto novo com a do publicado em HEAD.

    Aborta se alguma UF perder campos. Não é um teste de valor — é um teste de
    PRESENÇA, que é justamente o que os testes de integridade não fazem: eles
    conferem os campos que conhecem, e um campo que sumiu não é conferido por
    ninguém.
    """
    atual_caminho = DATA / "nacional.json"
    if not atual_caminho.exists():
        raise SystemExit("[RIQUEZA] data/nacional.json não existe — nada a conferir.")

    atual = json.loads(atual_caminho.read_text(encoding="utf-8"))
    anterior = _versao_anterior("data/nacional.json")

    campos_atuais = {u: set(d) for u, d in atual["ufs"].items()}
    n_atual = len(next(iter(campos_atuais.values())))

    if anterior is None:
        print(f"[RIQUEZA] sem versão anterior em HEAD; registrando "
              f"{n_atual} campos por UF como linha de base.")
        return True

    campos_antes = {u: set(d) for u, d in anterior["ufs"].items()}
    problemas = []

    ufs_perdidas = sorted(set(campos_antes) - set(campos_atuais))
    if ufs_perdidas:
        problemas.append(f"UFs que sumiram do conjunto: {ufs_perdidas}")

    for uf, antes in campos_antes.items():
        agora = campos_atuais.get(uf)
        if agora is None:
            continue
        perdidos = sorted(antes - agora)
        if len(perdidos) > tolerancia:
            problemas.append(f"{uf}: perdeu {len(perdidos)} campo(s): {perdidos}")

    n_antes = len(next(iter(campos_antes.values())))
    print(f"[RIQUEZA] campos por UF: {n_antes} em HEAD -> {n_atual} agora")

    if problemas:
        print("[RIQUEZA] FALHOU:", file=sys.stderr)
        for p in problemas:
            print("  -", p, file=sys.stderr)
        raise SystemExit(
            "[RIQUEZA] o conjunto novo é mais pobre que o publicado. "
            "Isso quase sempre significa que um passo do pipeline não rodou. "
            "Nada foi publicado.")

    ganhos = n_atual - n_antes
    if ganhos > 0:
        print(f"[RIQUEZA] OK — {ganhos} campo(s) a mais que a versão publicada.")
    else:
        print("[RIQUEZA] OK — nenhum campo perdido.")
    return True


# --------------------------------------------------------------------------- #

def executar(ano, pular_rais=False, tmp=None):
    _rodar("extrair_censo.py", "--ano", ano)
    _rodar("ingestao.py", "--ano", ano)
    _rodar("extrair_cpc.py", "--ano-censo", ano)
    args = ["--tmp", tmp] if tmp else []
    if pular_rais:
        args.append("--pular-rais")
        print("\n[PIPELINE] RAIS pulada por pedido; o IAP ficará nulo e a "
              "proveniência dirá isso.")
    _rodar("extrair_absorcao.py", *args)
    _rodar("consolidar.py")
    _rodar("registro_autoral.py")

    print("\n[PIPELINE] portão de qualidade")
    _rodar("indices.py", "--autoteste")

    print("\n[PIPELINE] conferência de riqueza")
    conferir_riqueza()

    print("\n[PIPELINE] testes")
    for teste in ("test_catalogo.py", "test_validacao.py",
                  "test_check_fontes.py", "test_acessibilidade.py"):
        caminho = REPO / "tests" / teste
        if not caminho.exists():
            continue
        resultado = subprocess.run([sys.executable, str(caminho)], cwd=str(REPO))
        if resultado.returncode != 0:
            raise SystemExit(f"[PIPELINE] {teste} falhou. Nada foi publicado.")

    print("\n[PIPELINE] tudo passou. Rode `python site/build.py` para gerar o site.")


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--check-only", action="store_true",
                   help="só verifica se as fontes têm edição nova")
    p.add_argument("--ano", type=int, default=2024, help="ano do Censo")
    p.add_argument("--tmp", help="diretório de trabalho para descompactar a RAIS")
    p.add_argument("--pular-rais", action="store_true",
                   help="não reextrai a RAIS (demorada); o IAP fica nulo")
    p.add_argument("--so-riqueza", action="store_true",
                   help="roda apenas a conferência de riqueza")
    args = p.parse_args()

    if args.check_only:
        verificar_fontes()
        return
    if args.so_riqueza:
        conferir_riqueza()
        return
    executar(args.ano, args.pular_rais, args.tmp)


if __name__ == "__main__":
    main()

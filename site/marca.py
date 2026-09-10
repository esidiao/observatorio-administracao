# -*- coding: utf-8 -*-
"""site/marca.py
Gera a marca do Observatório Nacional da Formação em Administração.

Uso:
    python site/marca.py

Fica no repositório porque a marca é obra do projeto e precisa ser
reproduzível: o SVG e os seis PNGs saem todos daqui, e regerá-los depois de
mexer na paleta é uma linha de comando, não um trabalho de desenho.

O desenho é um organograma de dois níveis: um nó de comando acima, três nós
subordinados abaixo, ligados por hastes. É o símbolo mais reconhecível da
área — e, ao contrário de barras de gráfico, não se confunde com o ícone de
qualquer outro painel de dados.

Os três nós de baixo usam as três cores institucionais, na mesma lógica com que
o observatório de Fonoaudiologia usou três arcos: a marca carrega a paleta.

SVG e PNG são desenhados a partir da MESMA geometria, declarada uma vez em
`NOS` e `HASTES`. Desenhar duas vezes é como o ícone e o favicon divergem.
"""
import pathlib

from PIL import Image, ImageDraw

DESTINO = pathlib.Path(__file__).resolve().parent / "static" / "img"

FUNDO = "#3B2A4A"
CLARO = "#FBFAF8"
MID = "#6C5B9E"
WARM = "#C8892B"

# Geometria em unidades de um viewBox 64x64.
RAIO_CAIXA = 12
NO_TOPO = (23, 10, 41, 22)          # x0, y0, x1, y1
NOS_BASE = [
    ((8, 42, 22, 54), CLARO),
    ((25, 42, 39, 54), MID),
    ((42, 42, 56, 54), WARM),
]
TRONCO = (32, 22, 32, 33)           # desce do nó de topo
BARRA = (15, 33, 49, 33)            # barra horizontal que distribui
HASTES = [(15, 33, 15, 42), (32, 33, 32, 42), (49, 33, 49, 42)]
ESPESSURA = 3
RAIO_NO = 3


def svg():
    partes = [
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img"'
        ' aria-label="Observatório Nacional da Formação em Administração">',
        f'  <rect width="64" height="64" rx="{RAIO_CAIXA}" fill="{FUNDO}"/>',
        '  <!-- Organograma de dois níveis: um nó de comando, três subordinados.',
        '       Os três de baixo carregam as cores institucionais. -->',
        f'  <g stroke="{CLARO}" stroke-width="{ESPESSURA}" stroke-linecap="round">',
        f'    <path d="M{TRONCO[0]} {TRONCO[1]}V{TRONCO[3]}"/>',
        f'    <path d="M{BARRA[0]} {BARRA[1]}H{BARRA[2]}"/>',
    ]
    for x0, y0, x1, y1 in HASTES:
        partes.append(f'    <path d="M{x0} {y0}V{y1}"/>')
    partes.append('  </g>')
    x0, y0, x1, y1 = NO_TOPO
    partes.append(f'  <rect x="{x0}" y="{y0}" width="{x1 - x0}" '
                  f'height="{y1 - y0}" rx="{RAIO_NO}" fill="{CLARO}"/>')
    for (x0, y0, x1, y1), cor in NOS_BASE:
        partes.append(f'  <rect x="{x0}" y="{y0}" width="{x1 - x0}" '
                      f'height="{y1 - y0}" rx="{RAIO_NO}" fill="{cor}"/>')
    partes.append('</svg>')
    return "\n".join(partes) + "\n"


def png(lado, maskable=False):
    """
    Desenha em 8x e reduz: o Pillow não tem antialias em `rectangle` nem em
    `line`, e sem a supersamostragem as hastes de 3 unidades saem serrilhadas
    justamente no tamanho em que o ícone é mais visto.
    """
    escala = 8
    n = lado * escala
    img = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    u = n / 64  # uma unidade do viewBox em pixels

    # `maskable` tem zona de segurança: o Android recorta um círculo de 80% da
    # área. O conteúdo é encolhido para caber nela e o fundo vai até a borda,
    # sem cantos arredondados — quem arredonda é o sistema.
    if maskable:
        d.rectangle([0, 0, n, n], fill=FUNDO)
        margem = 0.10
    else:
        d.rounded_rectangle([0, 0, n - 1, n - 1], radius=RAIO_CAIXA * u, fill=FUNDO)
        margem = 0.0

    def px(x, y):
        if not margem:
            return x * u, y * u
        centro = 32
        return ((centro + (x - centro) * (1 - 2 * margem)) * u,
                (centro + (y - centro) * (1 - 2 * margem)) * u)

    largura = max(1, round(ESPESSURA * u * (1 - 2 * margem)))
    for x0, y0, x1, y1 in [TRONCO, BARRA] + HASTES:
        d.line([px(x0, y0), px(x1, y1)], fill=CLARO, width=largura)

    # Ponta arredondada nas junções, à mão. O `line` do Pillow não tem
    # `stroke-linecap`, então o encontro da barra horizontal com as hastes
    # verticais deixa um degrau de meia espessura — visível justamente no
    # tamanho de favicon. O SVG resolve isso com stroke-linecap="round"; aqui
    # é um círculo do diâmetro da haste em cada extremidade.
    r = largura / 2
    for x, y in [(TRONCO[0], TRONCO[1]), (TRONCO[2], TRONCO[3]),
                 (BARRA[0], BARRA[1]), (BARRA[2], BARRA[3])] +                 [(h[0], h[1]) for h in HASTES] + [(h[2], h[3]) for h in HASTES]:
        cx, cy = px(x, y)
        d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=CLARO)

    for (x0, y0, x1, y1), cor in [(NO_TOPO, CLARO)] + NOS_BASE:
        a, b = px(x0, y0)
        c, e = px(x1, y1)
        d.rounded_rectangle([a, b, c, e],
                            radius=RAIO_NO * u * (1 - 2 * margem), fill=cor)

    return img.resize((lado, lado), Image.LANCZOS)


(DESTINO / "favicon.svg").write_text(svg(), encoding="utf-8", newline="\n")
png(32).save(DESTINO / "favicon-32.png")
png(180).save(DESTINO / "favicon-180.png")
png(192).save(DESTINO / "icon-192.png")
png(512).save(DESTINO / "icon-512.png")
png(192, maskable=True).save(DESTINO / "icon-maskable-192.png")
png(512, maskable=True).save(DESTINO / "icon-maskable-512.png")
print("marca gerada:")
for f in sorted(DESTINO.glob("*")):
    if f.name != "autor.jpg":
        print(f"  {f.name:26s} {f.stat().st_size:>7} bytes")

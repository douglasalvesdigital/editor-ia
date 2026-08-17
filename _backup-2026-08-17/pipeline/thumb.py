"""Gera a capa (thumb) a partir de um quadro do bruto.

O quadro sai do material ORIGINAL, nao do proxy: capa e imagem parada, onde
resolucao aparece. O proxy tem 720px na maior dimensao e ficaria borrado no
feed.

Uso como modulo:
    thumb.gerar(edl, destino, t=3.5, texto="linha 1\\nlinha 2", ...)
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

FONTES = Path.home() / "AppData/Local/Microsoft/Windows/Fonts"
SISTEMA = Path("C:/Windows/Fonts")

# proporcao -> (largura, altura) na saida
FORMATOS = {
    "9:16": (1080, 1920),   # story / reels
    "4:5": (1080, 1350),    # feed do instagram
    "1:1": (1080, 1080),    # quadrado
}

ROSA = (210, 48, 137)
LARANJA = (238, 134, 86)
BRANCO = (255, 255, 255)
GRAFITE = (18, 18, 18)

# Presets de capa. Cada um e um conjunto coerente de fonte, caixa, alinhamento
# e tratamento da palavra de enfase — trocar so a fonte, sem trocar o resto,
# costuma piorar em vez de melhorar.
PRESETS = {
    "ili": {
        # Copia da estrutura dos cards de 03_grafismos: linha de apoio em
        # Funnel Medium e a ULTIMA linha em Trirong Bold Italic, bem maior,
        # tudo minusculo, alinhado a esquerda, branco puro e sem contorno.
        # A enfase aqui nao e cor — e tipografia e escala.
        "rotulo": "ili",
        "fonte": "FunnelDisplay-Medium.ttf",
        "fonte_enfase": "Trirong-BoldItalic.ttf",
        "corpo": 0.040, "entrelinha": 1.45, "caixa_alta": False,
        "alinhar": "esquerda", "enfase": "ultima_linha",
        "escala_enfase": 1.62, "margem_base": 0.175,
        "scrim": 0.85, "vinheta": False, "barra": False,
    },
    "impacto": {
        "rotulo": "Impacto",
        "fonte": "FunnelDisplay-ExtraBold.ttf",
        "corpo": 0.070, "entrelinha": 1.06, "caixa_alta": True,
        "alinhar": "esquerda", "enfase": "marca",     # fundo solido na palavra
        "scrim": 0.82, "vinheta": True, "barra": False,
    },
    "destaque": {
        "rotulo": "Destaque",
        "fonte": "FunnelDisplay-Bold.ttf",
        "corpo": 0.062, "entrelinha": 1.12, "caixa_alta": True,
        "alinhar": "esquerda", "enfase": "cor",       # so a palavra colorida
        "scrim": 0.72, "vinheta": False, "barra": False,
    },
    "faixa": {
        "rotulo": "Faixa",
        "fonte": "FunnelDisplay-Bold.ttf",
        "corpo": 0.054, "entrelinha": 1.18, "caixa_alta": True,
        "alinhar": "esquerda", "enfase": "nenhuma",
        "scrim": 0.0, "vinheta": False, "barra": True,  # bloco de cor atras
    },
    "editorial": {
        "rotulo": "Editorial",
        "fonte": "FunnelDisplay-Medium.ttf",
        "fonte_enfase": "Trirong-BoldItalic.ttf",     # o par tipografico da ili
        "corpo": 0.056, "entrelinha": 1.20, "caixa_alta": False,
        "alinhar": "esquerda", "enfase": "italico",
        "scrim": 0.70, "vinheta": True, "barra": False,
    },
    "limpo": {
        "rotulo": "Limpo",
        "fonte": "FunnelDisplay-SemiBold.ttf",
        "corpo": 0.040, "entrelinha": 1.16, "caixa_alta": True,
        "alinhar": "centro", "enfase": "cor",
        "scrim": 0.35, "vinheta": False, "barra": False,
    },
}


def _fonte(nome: str, tamanho: int) -> ImageFont.FreeTypeFont:
    """Procura a fonte instalada; cai pra padrao em vez de quebrar a geracao."""
    for pasta in (FONTES, SISTEMA):
        caminho = pasta / nome
        if caminho.exists():
            return ImageFont.truetype(str(caminho), tamanho)
    return ImageFont.load_default(tamanho)


def _hex_rgb(h: str, padrao=LARANJA) -> tuple[int, int, int]:
    h = (h or "").strip().lstrip("#")
    if len(h) != 6:
        return padrao
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore
    except ValueError:
        return padrao


def extrair_quadro(video: Path, t: float, destino: Path, duracao: float = 0.0) -> Path:
    """Tira um quadro no instante t.

    -ss depois do -i: seek preciso. Numa capa, pegar o quadro errado significa
    olho fechado ou boca aberta no meio da palavra.

    Pedir um instante alem do fim nao devolve erro do ffmpeg — ele so nao
    escreve arquivo nenhum, e quem quebrava era o PIL adiante, com um
    FileNotFoundError que nao dizia nada. Aqui o tempo e limitado ao material e,
    se ainda assim nada sair, cai pro primeiro quadro.
    """
    if duracao > 0:
        t = min(max(0.0, t), max(0.0, duracao - 0.05))
    else:
        t = max(0.0, t)

    def tentar(instante: float) -> bool:
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video),
                        "-ss", f"{instante:.3f}", "-frames:v", "1", str(destino)],
                       capture_output=True)
        return destino.exists() and destino.stat().st_size > 0

    if tentar(t) or tentar(0.0):
        return destino
    raise RuntimeError(f"não consegui tirar um quadro de {video.name}")


def _enquadrar(im: Image.Image, larg: int, alt: int) -> Image.Image:
    """Preenche o formato sem distorcer: escala pelo lado que falta e corta o
    excedente pelo centro."""
    escala = max(larg / im.width, alt / im.height)
    novo = im.resize((max(1, round(im.width * escala)),
                      max(1, round(im.height * escala))), Image.LANCZOS)
    x = (novo.width - larg) // 2
    y = (novo.height - alt) // 2
    return novo.crop((x, y, x + larg, y + alt))


def _scrim(im: Image.Image, posicao: str, forca: float) -> Image.Image:
    """Gradiente escuro atras do texto.

    Sem isso a tipografia branca some sobre ceu claro — que e exatamente o caso
    dos brutos gravados perto da janela.
    """
    if forca <= 0:
        return im
    larg, alt = im.size
    camada = Image.new("L", (1, alt), 0)
    px = camada.load()
    for y in range(alt):
        p = y / max(1, alt - 1)
        if posicao == "topo":
            v = (1 - p) ** 1.6
        elif posicao == "centro":
            v = 1 - abs(p - 0.5) * 2
        else:
            v = p ** 1.6
        px[0, y] = int(255 * forca * max(0.0, min(1.0, v)))
    mascara = camada.resize((larg, alt))
    escuro = Image.new("RGB", (larg, alt), (8, 8, 8))
    return Image.composite(escuro, im, mascara).convert("RGB")


def _quebrar(texto: str, fonte, larg_max: int, desenho) -> list[str]:
    """Quebra por largura real do texto, respeitando quebras que o autor pos."""
    linhas: list[str] = []
    for bruta in texto.splitlines():
        palavras = bruta.split()
        if not palavras:
            continue
        atual = palavras[0]
        for p in palavras[1:]:
            teste = f"{atual} {p}"
            if desenho.textlength(teste, font=fonte) <= larg_max:
                atual = teste
            else:
                linhas.append(atual)
                atual = p
        linhas.append(atual)
    return linhas


def _vinheta(im: Image.Image, forca: float = 0.35) -> Image.Image:
    """Escurece as quatro bordas. Segura o olho no centro e dá profundidade."""
    larg, alt = im.size
    mascara = Image.new("L", (larg, alt), 0)
    d = ImageDraw.Draw(mascara)
    passos = 26
    for i in range(passos):
        p = i / passos
        v = int(255 * forca * (p ** 2.2))
        margem_x = int(larg * 0.5 * (1 - p))
        margem_y = int(alt * 0.5 * (1 - p))
        d.rectangle([margem_x, margem_y, larg - margem_x, alt - margem_y], outline=v, width=2)
    escuro = Image.new("RGB", (larg, alt), (0, 0, 0))
    return Image.composite(escuro, im, mascara.filter(
        __import__("PIL.ImageFilter", fromlist=["GaussianBlur"]).GaussianBlur(40)))


def gerar(edl: dict, destino: Path, t: float, texto: str = "",
          formato: str = "9:16", posicao: str = "base",
          cor: str = "#EE8656", destacar: str = "",
          preset: str = "impacto", scrim: float | None = None,
          look: bool = False, estilo: str = "") -> Path:
    """Monta a capa e grava em `destino` (.jpg ou .png)."""
    cfg = dict(PRESETS.get(preset) or PRESETS["impacto"])
    fonte_video = Path(edl["fonte"])
    larg, alt = FORMATOS.get(formato, FORMATOS["9:16"])
    realce = _hex_rgb(cor)

    tmp = destino.parent / "_quadro_capa.png"
    extrair_quadro(fonte_video, t, tmp, duracao=float(edl.get("duracao") or 0))
    im = Image.open(tmp).convert("RGB")
    tmp.unlink(missing_ok=True)
    im = _enquadrar(im, larg, alt)

    if look:  # mesmo tratamento do video, pra capa nao destoar do conteudo
        from PIL import ImageEnhance
        im = ImageEnhance.Color(im).enhance(0.55)
        im = ImageEnhance.Contrast(im).enhance(1.06)

    tem_texto = bool(texto.strip())
    forca_scrim = cfg["scrim"] if scrim is None else scrim
    if tem_texto and forca_scrim > 0 and not cfg["barra"]:
        im = _scrim(im, posicao, forca_scrim)
    if cfg["vinheta"]:
        im = _vinheta(im)

    if not tem_texto:
        return _salvar(im, destino)

    d = ImageDraw.Draw(im)
    margem = round(larg * 0.072)
    corpo = round(alt * cfg["corpo"])
    nome_fonte = cfg["fonte"]
    conteudo = texto.upper() if cfg["caixa_alta"] else texto

    # O modo ili nao trabalha com "palavra destacada": ele separa a fala em
    # linha de apoio + fecho, e o fecho ganha outra fonte e outro corpo. Cada
    # linha que o autor escreveu vira uma linha de verdade — nao ha requebra.
    if cfg["enfase"] == "ultima_linha":
        linhas_txt = [l.strip() for l in texto.splitlines() if l.strip()]
        if not linhas_txt:
            return _salvar(im, destino)
        f_apoio = _fonte(nome_fonte, corpo)
        corpo_enf = round(corpo * cfg.get("escala_enfase", 1.6))
        f_fecho = _fonte(cfg["fonte_enfase"], corpo_enf)

        # encolhe se a mais larga nao couber
        while corpo > 18:
            larguras = [d.textlength(l, font=(f_fecho if i == len(linhas_txt) - 1 else f_apoio))
                        for i, l in enumerate(linhas_txt)]
            if max(larguras) <= larg - margem * 2:
                break
            corpo = int(corpo * 0.93)
            corpo_enf = round(corpo * cfg.get("escala_enfase", 1.6))
            f_apoio = _fonte(nome_fonte, corpo)
            f_fecho = _fonte(cfg["fonte_enfase"], corpo_enf)

        alturas = [round(corpo_enf * 1.12) if i == len(linhas_txt) - 1
                   else round(corpo * cfg["entrelinha"])
                   for i in range(len(linhas_txt))]
        bloco = sum(alturas)
        if posicao == "topo":
            y = round(alt * 0.085)
        elif posicao == "centro":
            y = (alt - bloco) // 2
        else:
            y = alt - bloco - round(alt * cfg.get("margem_base", 0.12))

        for i, linha in enumerate(linhas_txt):
            ultima = i == len(linhas_txt) - 1
            d.text((margem, y), linha, font=(f_fecho if ultima else f_apoio), fill=BRANCO)
            y += alturas[i]
        return _salvar(im, destino)

    f = _fonte(nome_fonte, corpo)
    linhas = _quebrar(conteudo, f, larg - margem * 2, d)
    while len(linhas) > 4 and corpo > 24:     # cabe em 4 linhas ou diminui
        corpo = int(corpo * 0.92)
        f = _fonte(nome_fonte, corpo)
        linhas = _quebrar(conteudo, f, larg - margem * 2, d)

    f_enf = _fonte(cfg.get("fonte_enfase", nome_fonte), corpo)
    altura_linha = round(corpo * cfg["entrelinha"])
    bloco = altura_linha * len(linhas)
    pad = round(corpo * 0.34)

    if posicao == "topo":
        y0 = round(alt * 0.085)
    elif posicao == "centro":
        y0 = (alt - bloco) // 2
    else:
        y0 = alt - bloco - round(alt * 0.11)

    # bloco de cor atras do texto inteiro (preset faixa)
    if cfg["barra"]:
        d.rectangle([0, y0 - pad, larg, y0 + bloco + pad], fill=realce)

    alvo = destacar.strip().lower()
    contorno = 0 if cfg["barra"] else max(2, round(corpo * 0.055))
    y = y0

    for linha in linhas:
        largura_linha = d.textlength(linha, font=f)
        if cfg["alinhar"] == "centro":
            x = (larg - largura_linha) / 2
        else:
            x = margem

        for i, palavra in enumerate(linha.split()):
            eh_alvo = bool(alvo) and alvo in palavra.lower()
            fonte_p = f_enf if (eh_alvo and cfg["enfase"] == "italico") else f

            # O espaco anda ANTES e fora da palavra. Medir " PALAVRA" junto
            # fazia o retangulo do destaque comecar no espaco e terminar por
            # cima da palavra seguinte — saia "DINHEIRONA" com o fundo torto.
            if i:
                x += d.textlength(" ", font=f)
            w = d.textlength(palavra, font=fonte_p)

            if eh_alvo and cfg["enfase"] == "marca":
                # Fundo solido na palavra-chave: le mesmo em thumb pequena.
                # O retangulo tem que seguir a caixa REAL do glifo. Estimar a
                # partir de `y` e da entrelinha punha a marca por cima da linha
                # de cima, com a palavra vazando por baixo — o PIL desenha a
                # partir da caixa da fonte (com ascender/descender), nao da
                # altura das maiusculas.
                cx0, cy0, cx1, cy1 = fonte_p.getbbox(palavra)
                folga_x = pad * 0.34
                folga_y = pad * 0.28
                d.rectangle([x + cx0 - folga_x, y + cy0 - folga_y,
                             x + cx1 + folga_x, y + cy1 + folga_y], fill=realce)
                d.text((x, y), palavra, font=fonte_p, fill=GRAFITE)
            else:
                cor_p = BRANCO
                if eh_alvo and cfg["enfase"] in ("cor", "italico"):
                    cor_p = realce
                if cfg["barra"]:
                    cor_p = BRANCO if eh_alvo else GRAFITE
                d.text((x, y), palavra, font=fonte_p, fill=cor_p,
                       stroke_width=contorno, stroke_fill=(0, 0, 0))
            x += w
        y += altura_linha

    return _salvar(im, destino)


def _salvar(im: Image.Image, destino: Path) -> Path:
    destino.parent.mkdir(parents=True, exist_ok=True)
    if destino.suffix.lower() in (".jpg", ".jpeg"):
        im.save(destino, quality=92, subsampling=0)
    else:
        im.save(destino)
    return destino

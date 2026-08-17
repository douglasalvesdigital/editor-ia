"""EDL -> legenda ASS na timeline de saida, com a identidade da ili.

SRT nao guarda estilo, entao a legenda queimada sai em ASS. Os tempos seguem a
mesma regra do export_srt: cada palavra e reposicionada pra timeline ja cortada.

Cor em ASS e &HAABBGGRR — BGR invertido, nao RGB. Errar isso troca rosa por azul.
"""

from __future__ import annotations

from pathlib import Path

BRANCO = "&H00FFFFFF"
ROSA = "&H008930D2"      # #D23089
LARANJA = "&H005686EE"   # #EE8656
PRETO = "&H00000000"
CAIXA = "&H40202020"     # cinza escuro translucido, fundo da headline stacked

# A headline pede peso e largura — a referencia usa uma condensada pesada em
# caixa alta. Funnel Display Bold e o que existe instalado e mais se aproxima.
HL_FONTE = "Funnel Display Bold"

ESTILOS = {
    "ili-frase": {
        # o padrao da referencia: 2-4 palavras por vez, com uma delas realcada.
        # palavra solta obriga o olho a saltar rapido demais e cansa.
        "rotulo": "frase curta com ênfase",
        "fonte": "Funnel Display SemiBold",
        "tamanho": 74,
        "cor": BRANCO,
        "realce": LARANJA,
        "modo": "frase",
        "por_bloco": 3,
    },
    "ili-palavra": {
        "rotulo": "uma palavra por vez",
        "fonte": "Funnel Display SemiBold",
        "tamanho": 104,
        "cor": BRANCO,
        "realce": LARANJA,
        "modo": "palavra",
    },
    "ili-bloco": {
        "rotulo": "frase em bloco",
        "fonte": "Funnel Display SemiBold",
        "tamanho": 62,
        "cor": BRANCO,
        "realce": ROSA,
        "modo": "bloco",
    },
}

# Palavras curtas de ligacao nunca recebem o realce — destacar "de" ou "que"
# so polui. O realce e pra substantivo/verbo que carrega a frase.
LIGACAO = {
    "a", "o", "as", "os", "e", "é", "de", "da", "do", "das", "dos", "em", "no",
    "na", "nos", "nas", "um", "uma", "que", "se", "por", "com", "pra", "para",
    "ao", "à", "mais", "seu", "sua", "eu", "você", "voce", "ele", "ela", "tem",
}


def hex_para_ass(hexa: str) -> str:
    """#RRGGBB -> &H00BBGGRR. O ASS guarda a cor invertida; passar RGB direto
    troca laranja por azul sem dar erro nenhum, o que torna o bug dificil de ver.
    """
    h = (hexa or "").strip().lstrip("#")
    if len(h) != 6:
        return LARANJA
    try:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}".upper().replace("&H00", "&H00")
    except ValueError:
        return LARANJA


def _ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600); m = int(t % 3600 // 60)
    s = t % 60
    return f"{h:d}:{m:02d}:{s:05.2f}"


def _palavras_na_saida(edl: dict) -> list[dict]:
    ativos = sorted([t for t in edl["takes"] if t.get("ativo", True)], key=lambda t: t["ini"])
    saida, deslocamento = [], 0.0
    for t in ativos:
        for w in t.get("palavras", []):
            if w["fim"] < t["ini"] or w["ini"] > t["fim"]:
                continue
            saida.append({
                "t": w["t"],
                "ini": max(0.0, w["ini"] - t["ini"]) + deslocamento,
                "fim": max(0.0, min(w["fim"], t["fim"]) - t["ini"]) + deslocamento,
            })
        deslocamento += t["fim"] - t["ini"]
    return saida


def _limpar(p: str) -> str:
    return p.strip().strip(".,!?;:").lower()


def esc(t: str) -> str:
    """Neutraliza a sintaxe do ASS dentro do texto falado.

    `{` abre bloco de override e `\\` inicia comando: se a transcricao trouxer
    qualquer um dos dois, o libass engole o trecho sem reclamar e a legenda
    aparece furada. Isso vale para TODO texto vindo do ASR — os overrides que a
    gente mesmo monta sao concatenados depois, ja escapados.
    """
    return (t.replace("\\", "\\\\")
             .replace("{", "\\{")
             .replace("}", "\\}")
             .replace("\n", " ")
             .strip())


def _eventos_headline(texto: str, modo: str, dur: float, altura: int) -> list[str]:
    """Headline fixa no topo, nas duas versoes da referencia.

    outline  — texto vazado, so contorno grosso, sem caixa
    stacked  — caixa escura arredondada atras das duas linhas

    Em ASS nao existe caixa com canto arredondado: a stacked usa BorderStyle=3
    (caixa opaca no tamanho do texto), que e o mais proximo e nao exige
    desenhar retangulo a mao.
    """
    if not texto.strip():
        return []
    linhas = [esc(l).upper() for l in texto.strip().splitlines() if l.strip()]
    if not linhas:
        return []
    corpo = "\\N".join(linhas)   # \N e quebra de linha do ASS, depois do escape
    estilo = "hl_stacked" if modo == "stacked" else "hl_outline"
    return [f"Dialogue: 1,{_ts(0)},{_ts(dur)},{estilo},,0,0,0,,{corpo}"]


def gerar(edl: dict, destino: Path, estilo: str = "ili-palavra",
          largura: int = 1080, altura: int = 1920,
          headline: str = "", headline_modo: str = "outline",
          cor: str = "", caixa_alta: bool = False,
          altura_legenda: float = 0.20) -> Path:
    cfg = dict(ESTILOS.get(estilo) or ESTILOS["ili-palavra"])
    if cor:
        cfg["realce"] = hex_para_ass(cor)
    palavras = _palavras_na_saida(edl)

    # Os tamanhos sao pensados pra 1080x1920. Em ASS eles sao absolutos em
    # PlayRes, entao num bruto de 1728x3072 uma fonte 84 sai minuscula: tem que
    # escalar junto com a altura.
    escala = altura / 1920
    corpo = max(18, round(cfg["tamanho"] * escala))
    contorno = max(2, round(4 * escala))
    margem_lat = round(80 * escala)
    hl = max(20, round(66 * escala))
    # 11% da base punha a legenda atras da UI do Instagram (botoes e texto
    # do post). 20% e o piso seguro pra story/reels.
    margem_baixo = int(altura * max(0.08, min(0.45, altura_legenda)))
    dur_total = sum(t["fim"] - t["ini"]
                    for t in edl["takes"] if t.get("ativo", True))

    cabecalho = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {largura}
PlayResY: {altura}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, OutlineColour, BackColour, Bold, Italic, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: base,{cfg['fonte']},{corpo},{cfg['cor']},{PRETO},{PRETO},0,0,1,{contorno},0,2,{margem_lat},{margem_lat},{margem_baixo},1
Style: realce,{cfg['fonte']},{corpo},{cfg['realce']},{PRETO},{PRETO},0,0,1,{contorno},0,2,{margem_lat},{margem_lat},{margem_baixo},1
Style: hl_outline,{HL_FONTE},{hl},{BRANCO},{PRETO},{PRETO},1,0,1,{contorno+2},0,8,{margem_lat},{margem_lat},{int(altura*0.07)},1
Style: hl_stacked,{HL_FONTE},{hl},{BRANCO},{CAIXA},{CAIXA},1,0,3,{max(6,round(14*escala))},0,8,{margem_lat},{margem_lat},{int(altura*0.07)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # "nenhuma" ainda passa por aqui quando ha headline: gera o topo e pula as
    # legendas, em vez de devolver arquivo vazio
    modo = "nenhuma" if estilo == "nenhuma" else cfg["modo"]
    # A caixa da legenda e escolha de estilo, nao regra: minuscula pesa menos na
    # imagem e e o padrao da referencia na legenda palavra-a-palavra.
    caixa = (lambda s: s.upper()) if caixa_alta else (lambda s: s.lower())
    linhas = _eventos_headline(headline, headline_modo, dur_total, altura)

    if modo == "nenhuma":
        pass

    elif modo == "palavra":
        for i, w in enumerate(palavras):
            fim = w["fim"]
            if i + 1 < len(palavras):
                # encosta na proxima pra legenda nao piscar entre palavras
                fim = min(palavras[i + 1]["ini"], w["fim"] + 0.25)
            fim = max(fim, w["ini"] + 0.12)
            est = "realce" if (_vale_realce(w["t"]) and i % 4 == 0) else "base"
            linhas.append(_dialogo(w["ini"], fim, est, caixa(esc(w["t"]))))

    elif modo == "frase":
        for grupo in _agrupar(palavras, cfg.get("por_bloco", 3)):
            ini = grupo[0]["ini"]
            fim = max(grupo[-1]["fim"] + 0.08, ini + 0.3)
            # inline: so a palavra que carrega a frase muda de cor, o resto
            # fica branco. Trocar a cor de tudo tira o sentido do realce.
            alvo = _melhor_realce(grupo)
            partes = []
            for w in grupo:
                t = caixa(esc(w["t"]))
                partes.append(f"{{\\c{cfg['realce']}}}{t}{{\\c{cfg['cor']}}}"
                              if w is alvo else t)
            linhas.append(_dialogo(ini, fim, "base", " ".join(partes)))

    else:  # bloco corrido
        bloco: list[dict] = []
        for w in palavras:
            bloco.append(w)
            largo = len(" ".join(x["t"] for x in bloco)) > 34
            longo = bloco[-1]["fim"] - bloco[0]["ini"] > 3.0
            if largo or longo:
                linhas.append(_dialogo(bloco[0]["ini"], bloco[-1]["fim"] + 0.15, "base",
                                       " ".join(caixa(esc(w["t"])) for w in bloco)))
                bloco = []
        if bloco:
            linhas.append(_dialogo(bloco[0]["ini"], bloco[-1]["fim"] + 0.15, "base",
                                   " ".join(caixa(esc(w["t"])) for w in bloco)))

    destino.write_text(cabecalho + "\n".join(linhas) + "\n", encoding="utf-8")
    return destino


def _dialogo(ini: float, fim: float, estilo: str, texto: str) -> str:
    return f"Dialogue: 0,{_ts(ini)},{_ts(fim)},{estilo},,0,0,0,,{texto}"


def _vale_realce(p: str) -> bool:
    limpo = _limpar(p)
    return limpo not in LIGACAO and len(limpo) > 3


def _agrupar(palavras: list[dict], n: int) -> list[list[dict]]:
    """Quebra em grupos de ate n palavras, respeitando pausa maior no meio."""
    grupos, atual = [], []
    for i, w in enumerate(palavras):
        atual.append(w)
        proxima_longe = (i + 1 < len(palavras)
                         and palavras[i + 1]["ini"] - w["fim"] > 0.45)
        if len(atual) >= n or proxima_longe or i == len(palavras) - 1:
            grupos.append(atual)
            atual = []
    return grupos


def _melhor_realce(grupo: list[dict]) -> dict | None:
    """A palavra mais longa que nao seja ligacao — costuma ser a que importa."""
    candidatas = [w for w in grupo if _vale_realce(w["t"])]
    if not candidatas:
        return None
    return max(candidatas, key=lambda w: len(_limpar(w["t"])))

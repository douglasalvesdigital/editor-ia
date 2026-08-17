"""Validacao ponta a ponta: exercita o pipeline todo e conta o que quebrou.

    python testes/validar.py <pasta_edit>

Nao depende do servidor — chama os modulos direto, pra isolar a logica do HTTP.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import traceback
from pathlib import Path

RAIZ = Path(__file__).parent.parent
sys.path.insert(0, str(RAIZ))

from pipeline import export_ass, export_srt, export_xml, render, repeticoes  # noqa: E402

falhas: list[str] = []
passou = 0


def checar(nome: str, condicao: bool, detalhe: str = "") -> None:
    global passou
    if condicao:
        passou += 1
        print(f"  ok   {nome}")
    else:
        falhas.append(f"{nome}: {detalhe}")
        print(f"  FALHA {nome}  {detalhe}")


def probe(p: Path) -> dict:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=width,height,codec_type", "-of", "json", str(p)],
        capture_output=True, text=True)
    if r.returncode != 0:
        return {}
    d = json.loads(r.stdout)
    v = next((s for s in d.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in d.get("streams", []) if s.get("codec_type") == "audio"), {})
    return {"dur": float(d.get("format", {}).get("duration") or 0),
            "larg": v.get("width"), "alt": v.get("height"), "tem_audio": bool(a)}


def duracao_esperada(edl: dict) -> float:
    return sum(t["fim"] - t["ini"] for t in edl["takes"] if t.get("ativo", True))


# ---------------------------------------------------------------- unidade

def testar_cor():
    print("\n[cor ASS: RGB -> BGR]")
    casos = {"#00FF91": "&H0091FF00", "#EE8656": "&H005686EE",
             "#FFFFFF": "&H00FFFFFF", "#000000": "&H00000000"}
    for hexa, esperado in casos.items():
        obtido = export_ass.hex_para_ass(hexa)
        checar(f"{hexa} -> {esperado}", obtido == esperado, f"veio {obtido}")
    # entradas ruins nao podem explodir
    for ruim in ("", "xyz", "#12", None, "#GGGGGG"):
        try:
            export_ass.hex_para_ass(ruim)
            checar(f"cor invalida {ruim!r} nao quebra", True)
        except Exception as e:
            checar(f"cor invalida {ruim!r} nao quebra", False, repr(e))


def testar_repeticoes():
    print("\n[deteccao de repeticao]")
    base = lambda i, ini, fim, txt: {
        "id": i, "ini": ini, "fim": fim, "ini_orig": ini, "fim_orig": fim,
        "texto": txt, "ativo": True, "palavras": []}

    # retake classico: mesmo comeco, ultima e a boa
    t = [base(1, 0, 3, "E o pior é que dá pra fazer ajustes"),
         base(2, 4, 9, "E o pior é que dá pra virar esse jogo com ajustes que ninguém vê")]
    repeticoes.marcar(t)
    checar("retake por prefixo: fica o ultimo", (not t[0]["ativo"]) and t[1]["ativo"],
           f"{[x['ativo'] for x in t]}")

    # contencao: o segundo engloba o primeiro mas comeca diferente
    t = [base(1, 0, 4, "a gente montou um diagnóstico que analisa seu site"),
         base(2, 5, 11, "Aqui na ili a gente montou um diagnóstico que analisa seu site")]
    repeticoes.marcar(t)
    checar("retake por contencao", (not t[0]["ativo"]) and t[1]["ativo"],
           f"{[x['ativo'] for x in t]}")

    # NAO pode agrupar frases diferentes que so compartilham ligacao
    t = [base(1, 0, 4, "Você já deu uma olhada no seu site"),
         base(2, 5, 10, "Quer ver como ele cuida da sua marca")]
    repeticoes.marcar(t)
    checar("frases distintas continuam ativas", t[0]["ativo"] and t[1]["ativo"],
           f"{[x['ativo'] for x in t]}")

    # fala legitima com "deixa eu" nao pode virar descarte
    t = [base(1, 0, 5, "Mas deixa eu te perguntar uma coisa. E as redes sociais?")]
    repeticoes.marcar(t)
    checar("'deixa eu' nao e descartado", t[0]["ativo"], t[0].get("motivo", ""))

    # idempotencia: rodar duas vezes da o mesmo resultado
    t = [base(1, 0, 3, "E o pior é que dá pra fazer"),
         base(2, 4, 9, "E o pior é que dá pra fazer isso tudo agora")]
    repeticoes.marcar(t)
    a = [x["ativo"] for x in t]
    repeticoes.marcar(t)
    checar("marcar e idempotente", a == [x["ativo"] for x in t])


def testar_srt_offsets(edl: dict, tmp: Path):
    print("\n[SRT na timeline de saida]")
    alvo = export_srt.gerar(edl, tmp / "t.srt")
    txt = alvo.read_text(encoding="utf-8")
    checar("SRT nao vazio", len(txt) > 20)

    import re
    tempos = re.findall(r"(\d\d):(\d\d):(\d\d),(\d\d\d) --> (\d\d):(\d\d):(\d\d),(\d\d\d)", txt)
    checar("SRT tem blocos", len(tempos) > 0)
    if tempos:
        seg = lambda g: int(g[0])*3600 + int(g[1])*60 + int(g[2]) + int(g[3])/1000
        inis = [seg(t[:4]) for t in tempos]
        fins = [seg(t[4:]) for t in tempos]
        checar("SRT em ordem crescente", inis == sorted(inis))
        checar("SRT sem bloco invertido", all(f > i for i, f in zip(inis, fins)))
        dur = duracao_esperada(edl)
        checar("SRT nao passa da duracao final", max(fins) <= dur + 1.5,
               f"max {max(fins):.2f} vs dur {dur:.2f}")


def testar_ass_escape(tmp: Path):
    print("\n[ASS com texto perigoso]")
    # chaves e barras sao sintaxe de override no ASS; se vazarem, some texto
    edl = {"takes": [{"id": 1, "ini": 0, "fim": 3, "ativo": True, "texto": "x",
                      "palavras": [{"t": "{teste}", "ini": 0.0, "fim": 0.5},
                                   {"t": "a\\b", "ini": 0.6, "fim": 1.0},
                                   {"t": "acentuação", "ini": 1.1, "fim": 1.6}]}],
           "info": {}}
    for estilo in ("ili-frase", "ili-palavra", "ili-bloco"):
        try:
            alvo = export_ass.gerar(edl, tmp / f"e_{estilo}.ass", estilo, 1080, 1920)
            conteudo = alvo.read_text(encoding="utf-8")
            linhas_dialogo = [l for l in conteudo.splitlines() if l.startswith("Dialogue")]
            checar(f"{estilo}: gerou dialogos", len(linhas_dialogo) > 0)
            checar(f"{estilo}: chave crua nao vaza",
                   "{teste}" not in conteudo, "texto com { } entrou sem escapar")
        except Exception as e:
            checar(f"{estilo}: nao quebra com texto perigoso", False, repr(e))


def testar_xml(edl: dict, tmp: Path):
    print("\n[XML do Premiere]")
    import xml.etree.ElementTree as ET
    alvo = export_xml.gerar(edl, tmp / "s.xml")
    try:
        arvore = ET.parse(alvo)
        checar("XML e bem formado", True)
    except ET.ParseError as e:
        return checar("XML e bem formado", False, str(e))

    raiz = arvore.getroot()
    itens = raiz.findall(".//video/track/clipitem")
    ativos = [t for t in edl["takes"] if t.get("ativo", True)]
    checar("um clipitem por take ativo", len(itens) == len(ativos),
           f"{len(itens)} vs {len(ativos)}")

    # a timeline tem que ser contigua: end de um == start do proximo
    starts = [int(i.findtext("start")) for i in itens]
    ends = [int(i.findtext("end")) for i in itens]
    checar("timeline contigua", all(e == s for e, s in zip(ends, starts[1:])),
           f"starts={starts} ends={ends}")
    checar("comeca no frame 0", starts and starts[0] == 0)
    checar("in/out dentro do bruto",
           all(int(i.findtext("in")) < int(i.findtext("out")) for i in itens))
    checar("pathurl aponta pro bruto",
           raiz.findtext(".//pathurl", "").endswith(Path(edl["fonte"]).name.replace(" ", "%20"))
           or Path(edl["fonte"]).name in raiz.findtext(".//pathurl", ""))


def testar_render(edl: dict, tmp: Path):
    print("\n[render mp4]")
    dur = duracao_esperada(edl)
    info = edl.get("info", {})

    combos = [
        ("limpa sem nada", dict(tipo="limpa")),
        ("limpa + zoom", dict(tipo="limpa", zoom=True)),
        ("dividida", dict(tipo="dividida")),
        ("dividida2", dict(tipo="dividida2")),
        ("cor ili", dict(tipo="limpa", look={"saturacao": 0.55, "contraste": 1.06, "sombras": 0.045})),
    ]
    for nome, kw in combos:
        alvo = tmp / f"r_{nome.replace(' ','_')}.mp4"
        try:
            render.gerar(edl, alvo, tmp, **kw)
        except Exception as e:
            checar(f"render {nome}", False, repr(e))
            continue
        p = probe(alvo)
        checar(f"render {nome}: gerou", bool(p))
        if p:
            checar(f"render {nome}: duracao ~{dur:.1f}s",
                   abs(p["dur"] - dur) < 1.0, f"veio {p['dur']:.2f}")
            checar(f"render {nome}: tem audio", p["tem_audio"])
            checar(f"render {nome}: resolucao preservada",
                   p["larg"] == info.get("largura") and p["alt"] == info.get("altura"),
                   f"{p['larg']}x{p['alt']}")

    # legenda + headline queimadas
    ass = export_ass.gerar(edl, tmp / "leg.ass", "ili-frase",
                           info.get("largura") or 1080, info.get("altura") or 1920,
                           headline="LINHA UM\nLINHA DOIS", headline_modo="stacked",
                           cor="#00FF91")
    alvo = tmp / "r_legenda.mp4"
    try:
        render.gerar(edl, alvo, tmp, legenda=ass)
        p = probe(alvo)
        checar("render com legenda: gerou", bool(p))
        checar("render com legenda: duracao", p and abs(p["dur"] - dur) < 1.0,
               f"{p.get('dur')}")
    except Exception as e:
        checar("render com legenda", False, repr(e))

    # nao pode sobrar pasta temporaria nem arquivo intermediario
    restos = [p.name for p in tmp.glob("segmentos-*")]
    checar("limpou os segmentos", not restos, str(restos))
    sobra = [p.name for p in tmp.glob("_*.mp4")]
    checar("nao deixou intermediario", not sobra, str(sobra))

    # o zoom precisa MESMO mudar a imagem, nao so nao dar erro
    sem = tmp / "z_sem.mp4"
    com = tmp / "z_com.mp4"
    render.gerar(edl, sem, tmp, zoom=False)
    render.gerar(edl, com, tmp, zoom=True)
    if len(ativos_de(edl)) >= 2:
        t_meio = ponto_no_segundo_take(edl)
        a, b = tmp / "za.png", tmp / "zb.png"
        for src, img in ((sem, a), (com, b)):
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-ss", f"{t_meio:.2f}",
                            "-i", str(src), "-frames:v", "1", str(img)], check=False)
        checar("zoom altera a imagem do 2o take",
               a.exists() and b.exists() and a.read_bytes() != b.read_bytes(),
               "frames identicos — punch-in nao aplicou")


def ativos_de(edl: dict) -> list:
    return sorted([t for t in edl["takes"] if t.get("ativo", True)], key=lambda t: t["ini"])


def ponto_no_segundo_take(edl: dict) -> float:
    """Instante, na timeline de saida, no meio do 2o take — que e onde o
    punch-in alternado deve estar ligado."""
    at = ativos_de(edl)
    return (at[0]["fim"] - at[0]["ini"]) + (at[1]["fim"] - at[1]["ini"]) / 2


def brilho(img: Path) -> float:
    from PIL import Image, ImageStat
    return ImageStat.Stat(Image.open(img).convert("L")).mean[0]


def quadro(video: Path, t: float, destino: Path) -> Path:
    # -ss DEPOIS do -i: seek preciso. Antes do -i ele volta pro keyframe e a
    # medicao pega o quadro errado.
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video),
                    "-ss", f"{t:.3f}", "-frames:v", "1", str(destino)], check=False)
    return destino


def brilhos_da_janela(video: Path, ini: float, fim: float, tmp: Path) -> list[float]:
    """Brilho de CADA quadro entre ini e fim, decodificando em sequencia.

    Seek nao serve aqui: num arquivo vindo de concat os timestamps tem
    descontinuidade, e `-ss` devolve o mesmo quadro para instantes diferentes —
    o que fazia um unico quadro de flash ser contado tres vezes. `select` +
    `-vsync 0` entrega os quadros reais, um a um.
    """
    saida = tmp / "_janela"
    if saida.exists():
        shutil.rmtree(saida)
    saida.mkdir(parents=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video),
                    "-vf", f"select='between(t,{ini:.3f},{fim:.3f})'",
                    "-vsync", "0", "-q:v", "3", str(saida / "q%03d.png")], check=False)
    from PIL import Image, ImageStat
    return [ImageStat.Stat(Image.open(p).convert("L")).mean[0]
            for p in sorted(saida.glob("q*.png"))]


def testar_efeitos(edl: dict, tmp: Path):
    print("\n[flash e zoom animado]")
    at = ativos_de(edl)
    if len(at) < 2:
        return print("  (precisa de 2 takes ativos, pulando)")
    emenda = at[0]["fim"] - at[0]["ini"]

    base = tmp / "e_base.mp4"
    fl = tmp / "e_flash.mp4"
    an = tmp / "e_anim.mp4"
    render.gerar(edl, base, tmp)
    render.gerar(edl, fl, tmp, flash=True)
    render.gerar(edl, an, tmp, zoom_animado=True)

    janela = (max(0.0, emenda - 0.20), emenda + 0.30)
    com = brilhos_da_janela(fl, *janela, tmp)
    sem = brilhos_da_janela(base, *janela, tmp)
    checar("extraiu quadros da emenda", len(com) > 4 and len(sem) > 4,
           f"com={len(com)} sem={len(sem)}")
    if not com or not sem:
        return

    pico_com, pico_sem = max(com), max(sem)
    piso = min(com)
    checar(f"flash clareia a emenda ({piso:.0f} -> {pico_com:.0f})",
           pico_com > piso + 40, "sem clarao")
    checar(f"sem flash a emenda nao clareia (base {pico_sem:.0f})",
           pico_sem < pico_com - 30, f"base {pico_sem:.0f} vs flash {pico_com:.0f}")

    # nao pode saturar: branco puro na emenda le como falha de player
    checar(f"flash nao estoura (pico {pico_com:.0f})", pico_com < 245,
           "saturou em branco puro")
    afetados = sum(1 for b in com if b > piso + 15)
    checar(f"flash curto ({afetados} quadro(s) afetado(s))",
           1 <= afetados <= 4, "flash longo demais ou ausente")

    # o zoom animado precisa se acumular: diferenca cresce ao longo do take
    from PIL import Image, ImageChops, ImageStat
    def dif(t: float) -> float:
        a = Image.open(quadro(an, t, tmp / "qa.png")).convert("L")
        b = Image.open(quadro(base, t, tmp / "qb.png")).convert("L")
        if a.size != b.size:
            return 999.0
        return ImageStat.Stat(ImageChops.difference(a, b)).mean[0]

    d_cedo, d_tarde = dif(0.3), dif(max(0.6, emenda - 0.4))
    checar(f"zoom animado se acumula ({d_cedo:.1f} -> {d_tarde:.1f})",
           d_tarde > d_cedo + 3, "escala nao muda ao longo do take")


def testar_dividida_com_broll(edl: dict, tmp: Path):
    print("\n[tela dividida com b-roll]")
    ref = tmp / "ref_teste.png"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "gradients=s=1080x960:c0=0x1a3a5c:c1=0x0d1b2a:d=1",
                    "-frames:v", "1", str(ref)], check=True)
    info = edl.get("info", {})
    for tipo in ("dividida", "dividida2"):
        alvo = tmp / f"d_{tipo}.mp4"
        try:
            render.gerar(edl, alvo, tmp, tipo=tipo, referencias=[ref], flash=True)
        except Exception as e:
            checar(f"{tipo} com b-roll", False, repr(e))
            continue
        p = probe(alvo)
        checar(f"{tipo} com b-roll: gerou", bool(p))
        checar(f"{tipo}: resolucao preservada",
               p.get("larg") == info.get("largura") and p.get("alt") == info.get("altura"),
               f"{p.get('larg')}x{p.get('alt')}")
        checar(f"{tipo}: manteve audio", p.get("tem_audio"))
        checar(f"{tipo}: duracao",
               abs(p.get("dur", 0) - duracao_esperada(edl)) < 1.2, f"{p.get('dur')}")

    # a metade com b-roll tem que ser diferente da versao sem b-roll
    sem = tmp / "d_sem.mp4"
    render.gerar(edl, sem, tmp, tipo="dividida")
    a = quadro(tmp / "d_dividida.mp4", 1.0, tmp / "dr1.png")
    b = quadro(sem, 1.0, tmp / "dr2.png")
    checar("b-roll muda a metade de apoio", a.read_bytes() != b.read_bytes())


def testar_capa(edl: dict, tmp: Path):
    print("\n[capa]")
    from PIL import Image, ImageStat
    from pipeline import thumb

    esperado = {"9:16": (1080, 1920), "4:5": (1080, 1350), "1:1": (1080, 1080)}
    for fmt, (w, h) in esperado.items():
        alvo = tmp / f"capa_{fmt.replace(':','x')}.jpg"
        try:
            thumb.gerar(edl, alvo, t=1.0, texto="teste de capa", formato=fmt)
        except Exception as e:
            checar(f"capa {fmt}", False, repr(e))
            continue
        im = Image.open(alvo)
        checar(f"capa {fmt}: {w}x{h}", im.size == (w, h), f"veio {im.size}")

    # sem texto nao pode escurecer nada
    limpa = thumb.gerar(edl, tmp / "capa_limpa.jpg", t=1.0, texto="", scrim=0.9)
    com = thumb.gerar(edl, tmp / "capa_scrim.jpg", t=1.0, texto="chamada", scrim=0.9)
    faixa = lambda p: ImageStat.Stat(
        Image.open(p).convert("L").crop((0, 1200, 1080, 1500))).mean[0]
    checar(f"scrim escurece o fundo ({faixa(limpa):.0f} -> {faixa(com):.0f})",
           faixa(com) < faixa(limpa) - 10, "scrim nao aplicou")

    # texto comprido tem que caber, nao vazar
    longo = thumb.gerar(edl, tmp / "capa_longa.jpg", t=1.0,
                        texto="uma chamada bem longa que precisa quebrar em varias "
                              "linhas sem estourar o quadro de jeito nenhum")
    checar("texto longo nao quebra a geracao", longo.exists())

    # quadro fora da duracao nao pode explodir
    try:
        thumb.gerar(edl, tmp / "capa_fim.jpg", t=edl["duracao"] + 60, texto="fim")
        checar("instante alem do fim nao quebra", True)
    except Exception as e:
        checar("instante alem do fim nao quebra", False, repr(e))

    # cor invalida cai no padrao em vez de estourar
    try:
        thumb.gerar(edl, tmp / "capa_cor.jpg", t=1.0, texto="x", cor="zzz")
        checar("cor invalida na capa nao quebra", True)
    except Exception as e:
        checar("cor invalida na capa nao quebra", False, repr(e))

    checar("nao deixou quadro temporario",
           not (tmp / "_quadro_capa.png").exists())


def testar_trilha(edl: dict, tmp: Path):
    print("\n[trilha com ducking]")
    voz = tmp / "tv.mp4"
    mus = tmp / "tm.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y",
                    "-f", "lavfi", "-i", "color=c=black:s=320x320:d=6:r=30",
                    "-f", "lavfi", "-i", "sine=frequency=1000:duration=6",
                    "-filter_complex", "[1:a]volume='if(lt(t,3),1,0)':eval=frame[a]",
                    "-map", "0:v", "-map", "[a]", "-c:v", "libx264",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", str(voz)], check=True)
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi",
                    "-i", "sine=frequency=220:duration=8", "-c:a", "aac", str(mus)], check=True)

    mix = tmp / "tmix.mp4"
    render._mixar_trilha(voz, mus, mix, 0.22)
    checar("mix gerado", mix.exists())

    def nivel220(ini: float) -> float:
        r = subprocess.run(["ffmpeg", "-hide_banner", "-ss", str(ini), "-t", "1.5",
                            "-i", str(mix), "-af",
                            "bandpass=f=220:width_type=h:w=30,volumedetect",
                            "-f", "null", "-"], capture_output=True, text=True)
        import re
        m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", r.stderr)
        return float(m.group(1)) if m else 0.0

    com_voz, sem_voz = nivel220(0.5), nivel220(4.0)
    checar(f"trilha abaixa durante a fala ({com_voz:.1f} vs {sem_voz:.1f} dB)",
           sem_voz - com_voz > 4.0, "ducking fraco ou ausente")

    total = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(mix), "-af",
                            "volumedetect", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    import re
    m = re.search(r"mean_volume:\s*(-?[\d.]+) dB", total)
    checar("mix nao ficou mudo", m and float(m.group(1)) > -50,
           f"mean {m.group(1) if m else '?'} dB")


def testar_bordas(edl: dict, tmp: Path):
    print("\n[casos de borda]")
    vazio = json.loads(json.dumps(edl))
    for t in vazio["takes"]:
        t["ativo"] = False
    for nome, fn in (("render", lambda: render.gerar(vazio, tmp / "v.mp4", tmp)),
                     ("xml", lambda: export_xml.gerar(vazio, tmp / "v.xml"))):
        try:
            fn()
            checar(f"{nome} sem take ativo avisa em vez de gerar lixo", False,
                   "gerou sem erro")
        except ValueError:
            checar(f"{nome} sem take ativo avisa em vez de gerar lixo", True)
        except Exception as e:
            checar(f"{nome} sem take ativo: erro claro", False, repr(e))

    # um take so
    um = json.loads(json.dumps(edl))
    manteve = False
    for t in um["takes"]:
        if t["ativo"] and not manteve:
            manteve = True
        else:
            t["ativo"] = False
    try:
        alvo = render.gerar(um, tmp / "um.mp4", tmp)
        checar("render com um take so", probe(alvo).get("dur", 0) > 0.3)
    except Exception as e:
        checar("render com um take so", False, repr(e))

    # headline vazia nao pode criar evento fantasma
    a = export_ass.gerar(edl, tmp / "h0.ass", "ili-frase", 1080, 1920, headline="   ")
    checar("headline em branco nao vira evento",
           "hl_outline" not in a.read_text(encoding="utf-8").split("[Events]")[1])


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    pasta = Path(sys.argv[1]).resolve()
    edl = json.loads((pasta / "edl.json").read_text(encoding="utf-8"))
    tmp = RAIZ / "testes" / "_saida"
    tmp.mkdir(parents=True, exist_ok=True)

    print(f"projeto: {edl['nome']}  ({edl['duracao']:.1f}s, {len(edl['takes'])} takes, "
          f"corte {duracao_esperada(edl):.1f}s)")

    testar_cor()
    testar_repeticoes()
    testar_srt_offsets(edl, tmp)
    testar_ass_escape(tmp)
    testar_xml(edl, tmp)
    testar_render(edl, tmp)
    testar_efeitos(edl, tmp)
    testar_dividida_com_broll(edl, tmp)
    testar_capa(edl, tmp)
    testar_trilha(edl, tmp)
    testar_bordas(edl, tmp)

    print(f"\n{'='*54}\n{passou} passaram, {len(falhas)} falharam")
    for f in falhas:
        print(f"  - {f}")
    return 1 if falhas else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        traceback.print_exc()
        sys.exit(2)

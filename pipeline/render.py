"""EDL -> mp4.

Duas etapas de proposito:
1. extrai cada take reencodando (corte preciso em qualquer frame, nao so em
   keyframe) e aplica fade de 30ms nas pontas do audio;
2. junta com concat -c copy, sem reencodar de novo.

Fazer tudo num filtergraph unico obrigaria a reencodar o material inteiro toda
vez que algo mudasse. E sem os fades, cada emenda estala.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

FADE = 0.03


def _rodar(cmd: list[str]) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-1200:])


def _filtro_cor(look: dict | None) -> str:
    """Monta o tratamento de cor. Aceita um .cube ou ajuste parametrico.

    O projeto da ili pede imagem escura e dessaturada, e isso nao deu pra fazer
    por script no Premiere — a API publica nao adiciona efeitos. No render por
    ffmpeg e uma linha de filtro.
    """
    if not look:
        return ""
    partes = []
    cube = look.get("cube")
    if cube:
        caminho = Path(cube).as_posix().replace(":", "\\:")
        partes.append(f"lut3d='{caminho}'")
    sat = look.get("saturacao")
    contraste = look.get("contraste")
    brilho = look.get("brilho")
    if sat is not None or contraste is not None or brilho is not None:
        eq = []
        if sat is not None:
            eq.append(f"saturation={sat}")
        if contraste is not None:
            eq.append(f"contrast={contraste}")
        if brilho is not None:
            eq.append(f"brightness={brilho}")
        partes.append("eq=" + ":".join(eq))
    if look.get("sombras"):   # leve lift nas sombras, como no look da marca
        partes.append(f"curves=all='0/{look['sombras']} 0.5/0.5 1/1'")
    return ",".join(partes)


def _par(n: int) -> int:
    """H.264 nao aceita dimensao impar — 1727x3071 derruba o encoder."""
    return n - (n % 2)


def _filtro_zoom(fator: float, larg: int, alt: int) -> str:
    """Punch-in estatico: recorta e reescala de volta ao tamanho original.

    Alternar takes com e sem punch-in cria a leitura de duas cameras, que e o
    que disfarca o jump cut de um plano so. Usar `crop` fixo evita o tremor do
    zoompan, que recalcula em inteiro a cada frame e vibra.

    As contas sao feitas aqui em Python, com as bordas forcadas a numero par, e
    o scale volta ao tamanho ORIGINAL exato. Deixar o ffmpeg calcular
    `scale=iw*1.12` produzia 1727x3071 e quebrava o encode.
    """
    if fator <= 1.0 or larg <= 0 or alt <= 0:
        return ""
    cl, ca = _par(int(larg / fator)), _par(int(alt / fator))
    if cl < 2 or ca < 2:
        return ""
    x, y = _par((larg - cl) // 2), _par((alt - ca) // 2)
    return f"crop={cl}:{ca}:{x}:{y},scale={_par(larg)}:{_par(alt)}:flags=lanczos"


def _filtro_zoom_animado(sentido: int, dur: float, larg: int, alt: int,
                         fator: float = 1.10, fps: float = 30.0) -> str:
    """Zoom que se move ao longo do take (in num corte, out no seguinte).

    Diferente do punch-in estatico, aqui a escala varia quadro a quadro. Usa
    `zoompan` com `s=` na resolucao exata e o fps real do material — sem isso
    ele reamostra pra 25fps e o take sai fora de sincronia com o audio.

    O `d=1` faz cada quadro de entrada virar um de saida; sem isso o zoompan
    congela a imagem e repete o mesmo frame.
    """
    if sentido == 0 or dur <= 0:
        return ""
    larg, alt = _par(larg), _par(alt)
    quadros = max(2, int(dur * fps))
    passo = (fator - 1.0) / quadros
    if sentido > 0:      # in: comeca aberto e fecha
        z = f"min(1+{passo:.6f}*on,{fator})"
    else:                # out: comeca fechado e abre
        z = f"max({fator}-{passo:.6f}*on,1)"
    return (f"zoompan=z='{z}':d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
            f":s={larg}x{alt}:fps={fps}")


def _filtro_flash(dur: float, forca: float = 0.35) -> str:
    """Clarao curto na emenda.

    `fade:color=white` estoura pro branco puro no primeiro quadro, e o olho le
    isso como falha de player, nao como transicao — foi o que aconteceu na
    primeira versao. Aqui a imagem so LEVANTA de brilho e volta, sem saturar:
    a `forca` e quanto ela sobe (0,35 ~ um terço), decaindo em ~2 quadros.

    setpts zera o relogio do segmento: com `-ss` antes do `-i` o PTS continua
    contando do ponto de origem no bruto, e um `st=0` apontaria pra instante
    que ja passou — sem isso o efeito nao aparece, e sem erro nenhum.
    """
    d = min(0.07, max(0.04, dur / 30))
    rampa = f"if(lt(t,{d:.3f}),{forca:.3f}*(1-t/{d:.3f}),0)"
    return f"setpts=PTS-STARTPTS,eq=brightness='{rampa}':eval=frame"


def _meia_tela(larg: int, alt: int) -> str:
    """Recorta o miolo do quadro e encaixa em metade da altura, sem esticar."""
    meia = _par(alt // 2)
    return (f"crop=iw:ih/2:0:ih/4,scale={larg}:{meia}:force_original_aspect_ratio=increase,"
            f"crop={larg}:{meia}")


def _filtro_dividida(tipo: str, larg: int, alt: int) -> str:
    """Tela dividida SEM material de apoio: a outra metade vira faixa lisa.

    E o caso degradado. Quando ha imagem de referencia, a composicao passa por
    `_cmd_dividida_com_imagem`, porque ai precisa de um segundo input e o `-vf`
    sozinho nao da conta.

    dividida  — video embaixo, faixa em cima
    dividida2 — video em cima, faixa embaixo
    """
    if tipo not in ("dividida", "dividida2"):
        return ""
    larg, alt = _par(larg), _par(alt)
    meia = _par(alt // 2)
    base = _meia_tela(larg, alt)
    if tipo == "dividida":
        return f"{base},pad={larg}:{alt}:0:{meia}:color=#101010"
    return f"{base},pad={larg}:{alt}:0:0:color=#101010"


def _filtro_complexo_dividida(tipo: str, larg: int, alt: int, antes: str) -> str:
    """Tela dividida com b-roll na outra metade.

    E o que a referencia faz de verdade: "tela dividida com a imagem de
    referencia em cima, imagem embaixo". Faixa lisa era leitura minha errada.

    `antes` sao os filtros que ja vinham na cadeia (cor, zoom) e precisam
    continuar valendo pro video antes de ele virar meia tela.
    """
    larg, alt = _par(larg), _par(alt)
    meia = _par(alt // 2)
    cadeia = f"{antes}," if antes else ""
    v = f"[0:v]{cadeia}{_meia_tela(larg, alt)}[v]"
    ref = (f"[1:v]scale={larg}:{meia}:force_original_aspect_ratio=increase,"
           f"crop={larg}:{meia},setsar=1[ref]")
    ordem = "[ref][v]" if tipo == "dividida" else "[v][ref]"
    return f"{v};{ref};{ordem}vstack=inputs=2[vout]"


def _mixar_trilha(entrada: Path, trilha: Path, saida: Path, volume: float) -> None:
    """Poe a trilha por baixo da voz, com ducking de verdade.

    Baixar o volume da musica no olho nao resolve: em trecho falado ela ainda
    briga com a voz, e no silencio fica baixa demais. O `sidechaincompress` usa
    a propria voz como chave e abaixa a musica so enquanto alguem fala, subindo
    de volta sozinho depois.

    A trilha entra em loop e e cortada no tamanho do video (`shortest`), entao
    nao importa se veio mais curta ou mais longa.
    """
    filtro = (
        f"[1:a]volume={volume},aloop=loop=-1:size=2e9,asetpts=N/SR/TB[mus];"
        "[mus][0:a]sidechaincompress="
        "threshold=0.03:ratio=8:attack=15:release=350[duck];"
        "[0:a][duck]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
        "alimiter=limit=0.95[a]"
    )
    _rodar([
        "ffmpeg", "-v", "error", "-y", "-i", str(entrada), "-i", str(trilha),
        "-filter_complex", filtro,
        "-map", "0:v", "-map", "[a]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(saida),
    ])


def _clipe_encerramento(imagem: Path, destino: Path, larg: int, alt: int,
                        fps: float, dur: float = 2.5) -> Path:
    """Card de fechamento no fim do vídeo, a partir de um PNG.

    Entra com fade curto e leva áudio mudo na mesma taxa dos outros segmentos —
    sem isso o `concat` recusa a emenda, porque os parâmetros de áudio mudam.
    """
    # O `concat -c copy` só emenda segmentos com os MESMOS parâmetros. Um clipe
    # feito de PNG sai com timebase 1/11988, SAR 1:1 e color_range unknown,
    # enquanto os segmentos de câmera saem 1/30000, SAR N/A e range tv. Com
    # isso o container aceitava a emenda e somava a duração, mas nenhum quadro
    # do fim decodificava — o vídeo simplesmente acabava antes.
    _rodar([
        "ffmpeg", "-v", "error", "-y",
        "-loop", "1", "-t", f"{dur:.2f}", "-i", str(imagem),
        "-f", "lavfi", "-t", f"{dur:.2f}", "-i", "anullsrc=r=48000:cl=stereo",
        "-vf", (f"scale={_par(larg)}:{_par(alt)}:force_original_aspect_ratio=decrease,"
                f"pad={_par(larg)}:{_par(alt)}:(ow-iw)/2:(oh-ih)/2:color=#101010,"
                f"fade=t=in:st=0:d=0.25,setsar=sar=0,fps={fps}"),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-pix_fmt", "yuv420p",
        "-color_range", "tv",
        "-video_track_timescale", "30000",
        "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
        str(destino),
    ])
    return destino


def gerar(edl: dict, destino: Path, pasta: Path, legenda: Path | None = None,
          look: dict | None = None, zoom: bool = False,
          zoom_fator: float = 1.12, tipo: str = "limpa",
          trilha: Path | None = None, volume_trilha: float = 0.22,
          zoom_animado: bool = False, flash: bool = False,
          referencias: list[Path] | None = None,
          encerramento: Path | None = None, dur_encerramento: float = 2.5) -> Path:
    fonte = Path(edl["fonte"])
    ativos = sorted([t for t in edl["takes"] if t.get("ativo", True)], key=lambda t: t["ini"])
    if not ativos:
        raise ValueError("nenhum take ativo — nada pra renderizar")

    info = edl.get("info", {})
    larg = int(info.get("largura") or 1080)
    alt = int(info.get("altura") or 1920)
    fps = float(info.get("fps") or 30.0)
    referencias = [Path(p) for p in (referencias or []) if Path(p).exists()]

    # Pasta unica por execucao: dois renders ao mesmo tempo (dois projetos
    # abertos, ou um teste rodando junto) disputavam `segmentos/` e um apagava
    # os arquivos do outro no meio do caminho.
    pasta.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix="segmentos-", dir=pasta))

    partes = []
    for i, t in enumerate(ativos):
        dur = t["fim"] - t["ini"]
        if dur <= 0.02:
            continue
        saida = tmp / f"s{i:04d}.mp4"
        fim_fade = max(0.0, dur - FADE)
        cmd = [
            "ffmpeg", "-v", "error", "-y",
            "-ss", f"{t['ini']:.3f}", "-t", f"{dur:.3f}", "-i", str(fonte),
            "-af", f"afade=t=in:st=0:d={FADE},afade=t=out:st={fim_fade:.3f}:d={FADE}",
        ]
        # a cor entra aqui, por segmento, antes da legenda — legenda colorizada
        # junto com a imagem perde o branco puro
        # zoom animado e punch-in estatico sao excludentes: os dois juntos
        # brigam pela mesma escala e a imagem pula
        if zoom_animado:
            mov = _filtro_zoom_animado(1 if i % 2 == 0 else -1, dur, larg, alt, fps=fps)
        else:
            mov = _filtro_zoom(zoom_fator if (zoom and i % 2 == 1) else 1.0, larg, alt)

        dividido = tipo in ("dividida", "dividida2")
        ref = referencias[i % len(referencias)] if (dividido and referencias) else None

        if ref:
            # com b-roll a composicao precisa de dois inputs, entao vira
            # filter_complex e o -vf sai de cena
            antes = ",".join(f for f in (_filtro_cor(look), mov) if f)
            cmd = cmd[:1] + ["-v", "error", "-y",
                             "-ss", f"{t['ini']:.3f}", "-t", f"{dur:.3f}", "-i", str(fonte),
                             "-loop", "1", "-t", f"{dur:.3f}", "-i", str(ref),
                             "-af", f"afade=t=in:st=0:d={FADE},"
                                    f"afade=t=out:st={fim_fade:.3f}:d={FADE}"]
            complexo = _filtro_complexo_dividida(tipo, larg, alt, antes)
            if flash and i > 0:
                complexo = complexo.replace("[vout]", "[vstacked]")
                complexo += f";[vstacked]{_filtro_flash(dur)}[vout]"
            cmd += ["-filter_complex", complexo, "-map", "[vout]", "-map", "0:a?"]
        else:
            filtros = [f for f in (
                _filtro_cor(look),
                mov,
                _filtro_dividida(tipo, larg, alt),
                _filtro_flash(dur) if (flash and i > 0) else "",
            ) if f]
            if filtros:
                cmd += ["-vf", ",".join(filtros)]

        cmd += [
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000",
            "-avoid_negative_ts", "make_zero",
            str(saida),
        ]
        _rodar(cmd)
        partes.append(saida)

    if not partes:
        raise ValueError("nada sobrou depois de filtrar takes vazios")

    # O card de fechamento entra como mais um segmento, depois da legenda ter
    # sido calculada só sobre a fala — assim ele não recebe legenda em cima.
    if encerramento and Path(encerramento).exists():
        partes.append(_clipe_encerramento(
            Path(encerramento), tmp / "zz_fim.mp4", larg, alt, fps, dur_encerramento))

    # So o nome do arquivo: o demuxer concat resolve caminho relativo a partir
    # da propria lista, entao passar caminho relativo aqui duplica o prefixo.
    lista = tmp / "lista.txt"
    lista.write_text(
        "\n".join(f"file '{p.name}'" for p in partes) + "\n", encoding="utf-8"
    )

    # Cadeia: concat -> legenda -> trilha. Cada etapa le a anterior e so a
    # ultima escreve em `destino`, entao um arquivo final so aparece completo.
    usa_legenda = bool(legenda and legenda.exists())
    usa_trilha = bool(trilha and Path(trilha).exists())
    intermediarios: list[Path] = []

    # nome do intermediario carrega o mesmo sufixo unico da pasta temporaria,
    # senao dois renders simultaneos escreveriam no mesmo `_concat.mp4`
    sufixo = tmp.name.replace("segmentos-", "")

    def proximo(nome: str, ultima: bool) -> Path:
        if ultima:
            return destino
        p = pasta / f"_{sufixo}{nome}"
        intermediarios.append(p)
        return p

    atual = proximo("_concat.mp4", not (usa_legenda or usa_trilha))
    _rodar([
        "ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0",
        "-i", str(lista), "-c", "copy", str(atual),
    ])

    # legenda entra depois de qualquer overlay de imagem, senao some atras deles
    if usa_legenda:
        # o ffmpeg le esse caminho como argumento de filtro: no Windows a
        # barra invertida e os dois-pontos do drive precisam ser escapados
        caminho = legenda.as_posix().replace("\\", "/").replace(":", "\\:")
        alvo = proximo("_legendado.mp4", not usa_trilha)
        _rodar([
            "ffmpeg", "-v", "error", "-y", "-i", str(atual),
            "-vf", f"subtitles='{caminho}'",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "copy", str(alvo),
        ])
        atual = alvo

    # a trilha e a ultima: mexe so no audio e copia o video ja pronto
    if usa_trilha:
        _mixar_trilha(atual, Path(trilha), destino, volume_trilha)

    for p in intermediarios:
        p.unlink(missing_ok=True)
    shutil.rmtree(tmp, ignore_errors=True)
    return destino

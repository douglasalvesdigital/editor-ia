"""Prepara um bruto para revisao: probe, transcricao por palavra, takes, waveform e thumbs.

Gera tudo dentro de <pasta_do_video>/edit/, sem tocar no material original.

Uso:
    python pipeline/prep.py "C:/caminho/bruto.mp4"
    python pipeline/prep.py "C:/caminho/bruto.mp4" --ate 60      (so os primeiros 60s)
    python pipeline/prep.py "C:/caminho/bruto.mp4" --modelo medium
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent.parent))
from pipeline import repeticoes  # noqa: E402

# Pausa acima disso separa um take do outro.
GAP_CORTE = 0.35

# Pausa DENTRO da frase. Acima disso o vao e encolhido ate RESPIRO, em vez de
# virar corte: a fala continua, so para de arrastar. Medido nos brutos da ili,
# sobrava ~1s por video em pausas de 0,32-0,34s — logo abaixo do GAP_CORTE.
PAUSA_INTERNA = 0.22
RESPIRO = 0.10

# Limiar do silencedetect. -32dB pega pausa real sem confundir com ar
# condicionado, respiracao ou ruido de sala.
RUIDO_DB = -32.0
MIN_SILENCIO = 0.30

# Folga em cada borda do take. Os timestamps do ASR derrapam 50-100ms; sem
# padding o corte come a primeira consoante e o ultimo fonema.
PAD_ENTRADA = 0.08
PAD_SAIDA = 0.12

# Quanto o ASR pode errar a borda da palavra. Dentro dessa janela o silencio
# medido tem a palavra final sobre onde o take comeca e termina.
BUSCA_BORDA = 0.60

N_PEAKS = 4000
N_THUMBS = 120


def rodar(cmd: list[str]) -> str:
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(f"falhou: {' '.join(cmd[:3])}...\n{r.stderr[:800]}")
    return r.stdout


def probe(video: Path) -> dict:
    saida = rodar([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=index,codec_type,codec_name,width,height,r_frame_rate,duration",
        "-show_entries", "format=duration,size,format_name",
        "-of", "json", str(video),
    ])
    dados = json.loads(saida)
    v = next((s for s in dados.get("streams", []) if s.get("codec_type") == "video"), {})
    a = next((s for s in dados.get("streams", []) if s.get("codec_type") == "audio"), {})

    fps = 30.0
    if v.get("r_frame_rate") and "/" in v["r_frame_rate"]:
        num, den = v["r_frame_rate"].split("/")
        if float(den):
            fps = float(num) / float(den)

    return {
        "largura": int(v.get("width") or 0),
        "altura": int(v.get("height") or 0),
        "fps": round(fps, 3),
        "duracao": float(dados.get("format", {}).get("duration") or 0.0),
        "codec_video": v.get("codec_name"),
        "codec_audio": a.get("codec_name"),
        "tem_audio": bool(a),
    }


def extrair_audio(video: Path, wav: Path, ate: float | None) -> None:
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if ate:
        cmd += ["-t", str(ate)]
    cmd += ["-i", str(video), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(wav)]
    rodar(cmd)


def transcrever(wav: Path, modelo: str, idioma: str) -> list[dict]:
    from faster_whisper import WhisperModel

    m = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=8)
    segmentos, _ = m.transcribe(
        str(wav),
        language=idioma,
        word_timestamps=True,   # obrigatorio: sem palavra nao da pra cortar direito
        # VAD LIGADO. Sem ele o Whisper estica a palavra que antecede uma pausa
        # pra cobrir o silencio — num bruto real apareceu um "que" de 4,4s — e
        # ai o vao entre palavras vira zero e nao sobra sinal nenhum pra decidir
        # o corte. Medido no mesmo material: sem VAD 44 palavras e 2 esticadas;
        # com VAD 78 palavras e nenhuma. Os timestamps continuam na timeline
        # original, entao nao se perde nada.
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        beam_size=1,
        condition_on_previous_text=False,
    )
    palavras: list[dict] = []
    for seg in segmentos:
        for w in seg.words or []:
            texto = w.word.strip()
            if texto:
                palavras.append({"t": texto, "ini": round(w.start, 3), "fim": round(w.end, 3)})
    return palavras


def detectar_silencios(wav: Path) -> list[tuple[float, float]]:
    """Silencios medidos no audio real, via ffmpeg silencedetect.

    Mais confiavel que inferir do gap entre palavras: o ASR encosta os
    timestamps quando a pausa e curta, e nao enxerga pausa antes da primeira
    palavra nem depois da ultima.
    """
    r = subprocess.run(
        ["ffmpeg", "-v", "info", "-i", str(wav),
         "-af", f"silencedetect=noise={RUIDO_DB}dB:d={MIN_SILENCIO}", "-f", "null", "-"],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    silencios: list[tuple[float, float]] = []
    inicio = None
    for linha in r.stderr.splitlines():
        m_ini = re.search(r"silence_start:\s*(-?[\d.]+)", linha)
        if m_ini:
            inicio = float(m_ini.group(1))
        m_fim = re.search(r"silence_end:\s*(-?[\d.]+)", linha)
        if m_fim and inicio is not None:
            fim = float(m_fim.group(1))
            if fim > inicio:
                silencios.append((max(0.0, inicio), fim))
            inicio = None
    return silencios


def montar_takes(palavras: list[dict], duracao: float,
                 silencios: list[tuple[float, float]]) -> list[dict]:
    """Agrupa palavras em takes, quebrando em cima de pausa real.

    Quebra se houver silencio medido no audio entre duas palavras, ou se o gap
    do proprio ASR ja for grande. O corte nasce sempre numa fronteira de
    palavra, nunca no meio de uma.
    """
    if not palavras:
        return []

    # Com o VAD ligado o gap entre palavras volta a ser confiavel, entao ele
    # sozinho ja define onde um take termina e outro comeca. O silencedetect
    # entra depois, so pra apertar as bordas.
    #
    # Duas escalas de quebra:
    #  - gap >= GAP_CORTE      -> take novo (outra tentativa, outra frase)
    #  - gap >= PAUSA_INTERNA  -> mesma fala, so arrastada; quebra tambem, mas
    #                             marcada como continuacao e com borda apertada,
    #                             pra tirar o arrasto sem picar a frase
    grupos: list[list[dict]] = [[palavras[0]]]
    continuacao: list[bool] = [False]
    for anterior, atual in zip(palavras, palavras[1:]):
        gap = atual["ini"] - anterior["fim"]
        if gap >= GAP_CORTE:
            grupos.append([atual])
            continuacao.append(False)
        elif gap >= PAUSA_INTERNA:
            grupos.append([atual])
            continuacao.append(True)
        else:
            grupos[-1].append(atual)

    def encostar_no_silencio(ini: float, fim: float, ult_ini: float) -> tuple[float, float]:
        """Puxa as bordas ate onde o silencio realmente comeca.

        Dois casos, ambos vistos em material real:
        - o ASR estica a ultima palavra alguns decimos alem da voz;
        - o ASR estica a ultima palavra por CIMA da pausa inteira, e ai o
          silencio comeca no meio do span dela.
        O silencedetect sabe onde a voz parou de verdade, entao ele manda —
        desde que so aperte o take, nunca alargue.
        """
        for s_ini, s_fim in silencios:
            if ult_ini < s_ini <= fim + BUSCA_BORDA:
                fim = min(fim, s_ini + PAD_SAIDA)
            if abs(s_fim - ini) <= BUSCA_BORDA:
                ini = max(ini, s_fim - PAD_ENTRADA)
        return ini, fim

    takes = []
    for i, grupo in enumerate(grupos):
        segue = continuacao[i]
        proprio_continua = (i + 1 < len(grupos)) and continuacao[i + 1]

        # Numa emenda interna o padding cheio devolveria o silencio que a gente
        # acabou de tirar: 0,12 + 0,08 = 0,20s de volta. Ali usamos meio respiro
        # de cada lado.
        pad_ini = (RESPIRO / 2) if segue else PAD_ENTRADA
        pad_fim = (RESPIRO / 2) if proprio_continua else PAD_SAIDA

        ini = max(0.0, grupo[0]["ini"] - pad_ini)
        fim = min(duracao, grupo[-1]["fim"] + pad_fim)
        if not segue and not proprio_continua:
            ini, fim = encostar_no_silencio(ini, fim, grupo[-1]["ini"])
        # nao deixa o padding invadir o take vizinho
        if takes and ini < takes[-1]["fim"]:
            ini = takes[-1]["fim"]
        if fim <= ini:
            continue
        takes.append({
            "id": i + 1,
            "ini": round(ini, 3),
            "fim": round(fim, 3),
            "ini_orig": round(ini, 3),
            "fim_orig": round(fim, 3),
            "texto": " ".join(w["t"] for w in grupo),
            "ativo": True,
            "continua": segue,   # emenda na fala anterior, nao e take novo
            "palavras": grupo,
        })
    return takes


def calcular_peaks(wav: Path, n: int) -> list[float]:
    """Envelope do audio normalizado 0..1, pronto pra desenhar no canvas."""
    bruto = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(wav), "-f", "s16le", "-ac", "1", "-"],
        capture_output=True,
    ).stdout
    amostras = np.frombuffer(bruto, dtype=np.int16).astype(np.float32)
    if amostras.size == 0:
        return []
    tamanho = max(1, amostras.size // n)
    usavel = (amostras.size // tamanho) * tamanho
    blocos = np.abs(amostras[:usavel]).reshape(-1, tamanho)
    env = blocos.max(axis=1)
    pico = float(env.max()) or 1.0
    return [round(float(x) / pico, 4) for x in env]


def gerar_proxy(video: Path, destino: Path, ate: float | None) -> None:
    """Copia leve pra interface reproduzir sem engasgo.

    O bruto da camera nao serve pra revisar no navegador: 1728x3072 a ~30 Mbps
    e, pior, com o indice (moov) no FIM do arquivo — o player teria que baixar
    quase tudo antes de conseguir pular pra um ponto qualquer. O proxy resolve
    os dois: 720px na maior dimensao e +faststart, que poe o indice na frente.
    O render final continua usando o bruto.
    """
    cmd = ["ffmpeg", "-v", "error", "-y"]
    if ate:
        cmd += ["-t", str(ate)]
    cmd += [
        "-i", str(video),
        "-vf", "scale=720:720:force_original_aspect_ratio=decrease:force_divisible_by=2",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "28", "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-movflags", "+faststart",
        str(destino),
    ]
    rodar(cmd)


def extrair_thumbs(video: Path, destino: Path, duracao: float, n: int) -> int:
    destino.mkdir(parents=True, exist_ok=True)
    for antigo in destino.glob("*.jpg"):
        antigo.unlink()
    fps = n / duracao if duracao > 0 else 1
    rodar([
        "ffmpeg", "-v", "error", "-y", "-t", str(duracao), "-i", str(video),
        "-vf", f"fps={fps:.6f},scale=-1:72", "-q:v", "6",
        str(destino / "t%04d.jpg"),
    ])
    return len(list(destino.glob("*.jpg")))


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("video")
    p.add_argument("--ate", type=float, default=None, help="processa so os primeiros N segundos")
    p.add_argument("--modelo", default="small")
    p.add_argument("--idioma", default="pt")
    p.add_argument("--saida", default=None,
                   help="onde gravar (padrao: <pasta_do_video>/edit)")
    args = p.parse_args()

    video = Path(args.video).resolve()
    if not video.exists():
        print(f"nao achei: {video}")
        return 1

    edit = Path(args.saida).resolve() if args.saida else video.parent / "edit"
    edit.mkdir(parents=True, exist_ok=True)

    print("[1/6] lendo o arquivo...")
    info = probe(video)
    duracao = min(info["duracao"], args.ate) if args.ate else info["duracao"]
    print(f"      {info['largura']}x{info['altura']} @ {info['fps']}fps, {duracao:.1f}s")

    print("[2/6] extraindo audio...")
    wav = edit / "audio.wav"
    extrair_audio(video, wav, args.ate)

    print(f"[3/6] transcrevendo (modelo {args.modelo})...")
    palavras = transcrever(wav, args.modelo, args.idioma)
    print(f"      {len(palavras)} palavras")

    print("[4/6] montando takes e waveform...")
    silencios = detectar_silencios(wav)
    print(f"      {len(silencios)} pausas detectadas no audio")
    takes = montar_takes(palavras, duracao, silencios)
    peaks = calcular_peaks(wav, N_PEAKS)
    tempo_falado = sum(t["fim"] - t["ini"] for t in takes)
    print(f"      {len(takes)} takes, {tempo_falado:.1f}s de fala em {duracao:.1f}s")

    resumo = repeticoes.marcar(takes)
    if any(resumo[k] for k in ("repetidos", "desistencias", "curtos")):
        print(f"      descartados: {resumo['repetidos']} repetição, "
              f"{resumo['desistencias']} desistência, {resumo['curtos']} curto")
        for g in resumo["grupos"]:
            print(f"        tentativas {g} -> fica #{g[-1]}")

    print("[5/6] extraindo thumbs...")
    n_thumbs = extrair_thumbs(video, edit / "thumbs", duracao, N_THUMBS)

    print("[6/6] gerando proxy pra interface...")
    gerar_proxy(video, edit / "proxy.mp4", args.ate)

    edl = {
        "fonte": str(video),
        "nome": video.name,
        "duracao": round(duracao, 3),
        "info": info,
        "takes": takes,
        "peaks": peaks,
        "n_thumbs": n_thumbs,
        "fase": 1,
        "aprovado": False,
    }
    (edit / "edl.json").write_text(json.dumps(edl, ensure_ascii=False, indent=1), encoding="utf-8")

    cortado = duracao - tempo_falado
    print(f"\npronto -> {edit / 'edl.json'}")
    print(f"corte proposto remove {cortado:.1f}s ({cortado / duracao * 100:.0f}%) de silencio")
    return 0


if __name__ == "__main__":
    sys.exit(main())

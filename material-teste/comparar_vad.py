"""Compara transcricao com e sem VAD no mesmo material, pra decidir por medida
e nao por achismo. Uso: python comparar_vad.py <video> [modelo]
"""
import io
import subprocess
import sys
from pathlib import Path

from faster_whisper import WhisperModel

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

video = Path(sys.argv[1])
modelo = sys.argv[2] if len(sys.argv) > 2 else "small"
wav = Path(__file__).parent / "_cmp.wav"

subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(video), "-vn", "-ac", "1",
                "-ar", "16000", "-c:a", "pcm_s16le", str(wav)], check=True)

m = WhisperModel(modelo, device="cpu", compute_type="int8", cpu_threads=8)

for rotulo, vad in (("SEM VAD", False), ("COM VAD", True)):
    kw = {}
    if vad:
        kw["vad_parameters"] = {"min_silence_duration_ms": 400}
    segs, _ = m.transcribe(str(wav), language="pt", word_timestamps=True,
                           vad_filter=vad, beam_size=1,
                           condition_on_previous_text=False, **kw)
    segs = list(segs)
    palavras = [w for s in segs for w in (s.words or [])]

    esticadas = [w for w in palavras if (w.end - w.start) > 1.5]
    gaps = [round(b.start - a.end, 2) for a, b in zip(palavras, palavras[1:])]
    grandes = [g for g in gaps if g >= 0.35]

    print(f"\n===== {rotulo} ({modelo}) =====")
    print(f"segmentos: {len(segs)}   palavras: {len(palavras)}")
    print(f"palavras esticadas (>1.5s): {len(esticadas)}"
          + (f"  ex: {[(w.word.strip(), round(w.end-w.start,1)) for w in esticadas[:4]]}"
             if esticadas else ""))
    print(f"gaps >= 0.35s entre palavras: {len(grandes)}  {sorted(grandes, reverse=True)[:8]}")
    print("segmentos:")
    for s in segs:
        print(f"  {s.start:6.2f}-{s.end:6.2f}  {s.text.strip()[:74]}")

wav.unlink(missing_ok=True)

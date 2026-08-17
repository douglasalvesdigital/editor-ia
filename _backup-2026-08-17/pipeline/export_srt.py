"""EDL -> SRT na timeline de SAIDA.

O pulo do gato: cada palavra tem timestamp no bruto, mas a legenda precisa dos
tempos do video ja cortado. Formula:
    tempo_saida = palavra.ini - take.ini + deslocamento_do_take
Sem isso a legenda desanda a partir do primeiro corte.
"""

from __future__ import annotations

from pathlib import Path

CHARS_LINHA = 42
MAX_BLOCO = 6.0
MIN_BLOCO = 0.9


def _ts(t: float) -> str:
    if t < 0:
        t = 0.0
    h = int(t // 3600); m = int(t % 3600 // 60); s = int(t % 60)
    ms = int(round((t - int(t)) * 1000))
    if ms == 1000:
        ms = 0; s += 1
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _blocos(palavras: list[dict]) -> list[dict]:
    """Junta palavras em blocos legiveis, quebrando por tamanho ou duracao."""
    blocos, atual = [], []
    for p in palavras:
        tentativa = " ".join(w["t"] for w in atual + [p])
        estourou = len(tentativa) > CHARS_LINHA * 2
        longo = atual and (p["fim"] - atual[0]["ini"]) > MAX_BLOCO
        if atual and (estourou or longo):
            blocos.append(atual)
            atual = []
        atual.append(p)
    if atual:
        blocos.append(atual)
    return [{"ini": b[0]["ini"], "fim": b[-1]["fim"],
             "texto": " ".join(w["t"] for w in b)} for b in blocos]


def gerar(edl: dict, destino: Path) -> Path:
    ativos = sorted([t for t in edl["takes"] if t.get("ativo", True)], key=lambda t: t["ini"])

    palavras_saida: list[dict] = []
    deslocamento = 0.0
    for t in ativos:
        for w in t.get("palavras", []):
            # descarta palavra que ficou fora depois do usuario ajustar a borda
            if w["fim"] < t["ini"] or w["ini"] > t["fim"]:
                continue
            palavras_saida.append({
                "t": w["t"],
                "ini": max(0.0, w["ini"] - t["ini"]) + deslocamento,
                "fim": max(0.0, min(w["fim"], t["fim"]) - t["ini"]) + deslocamento,
            })
        deslocamento += t["fim"] - t["ini"]

    linhas = []
    for i, b in enumerate(_blocos(palavras_saida), start=1):
        fim = max(b["fim"], b["ini"] + MIN_BLOCO)
        texto = b["texto"]
        if len(texto) > CHARS_LINHA:  # quebra equilibrada em duas linhas
            meio = len(texto) // 2
            corte = texto.rfind(" ", 0, meio + 1)
            if corte == -1:
                corte = texto.find(" ", meio)
            if corte > 0:
                texto = texto[:corte] + "\n" + texto[corte+1:]
        linhas.append(f"{i}\n{_ts(b['ini'])} --> {_ts(fim)}\n{texto}\n")

    destino.write_text("\n".join(linhas), encoding="utf-8")
    return destino

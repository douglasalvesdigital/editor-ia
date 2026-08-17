"""Gera os LUTs .cube da casa.

Por que gerar em vez de só usar os filtros paramétricos que já existem: LUT é
um arquivo que serve em qualquer lugar — Premiere, Resolve, ffmpeg — então o
mesmo look que sai daqui pode ser aplicado numa finalização manual depois.

    python luts/gerar_luts.py
"""

from __future__ import annotations

from pathlib import Path

N = 33   # 33^3 é o tamanho padrão de LUT de finalização; 17 já serrilha


def _clamp(v: float) -> float:
    return 0.0 if v < 0 else 1.0 if v > 1 else v


def look(r: float, g: float, b: float, sat: float, contraste: float,
         lift: float, quente: float = 0.0) -> tuple[float, float, float]:
    """Mesma matemática do filtro de cor do render, em forma de tabela.

    Ordem importa: dessatura, depois contraste em torno do meio, depois lift
    nas sombras. Inverter isso levanta o preto antes de comprimir e o resultado
    fica leitoso.
    """
    luma = 0.2126 * r + 0.7152 * g + 0.0722 * b
    r = luma + (r - luma) * sat
    g = luma + (g - luma) * sat
    b = luma + (b - luma) * sat

    r = (r - 0.5) * contraste + 0.5
    g = (g - 0.5) * contraste + 0.5
    b = (b - 0.5) * contraste + 0.5

    # lift só nas sombras: peso cai conforme o pixel clareia
    for _ in (0,):
        peso_r = (1 - _clamp(r)) ** 2
        peso_g = (1 - _clamp(g)) ** 2
        peso_b = (1 - _clamp(b)) ** 2
    r += lift * peso_r
    g += lift * peso_g
    b += lift * peso_b

    if quente:                       # leve viés de temperatura
        r += quente * 0.6 * (1 - _clamp(r))
        b -= quente * 0.5 * _clamp(b)

    return _clamp(r), _clamp(g), _clamp(b)


def gerar(nome: str, titulo: str, **kw) -> Path:
    destino = Path(__file__).parent / f"{nome}.cube"
    linhas = [f'TITLE "{titulo}"', f"LUT_3D_SIZE {N}", "DOMAIN_MIN 0 0 0",
              "DOMAIN_MAX 1 1 1", ""]
    # no .cube o vermelho é o eixo que varia mais rápido
    for ib in range(N):
        for ig in range(N):
            for ir in range(N):
                r, g, b = look(ir / (N - 1), ig / (N - 1), ib / (N - 1), **kw)
                linhas.append(f"{r:.6f} {g:.6f} {b:.6f}")
    destino.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    return destino


if __name__ == "__main__":
    feitos = [
        gerar("ili", "ili — dessaturado suave",
              sat=0.55, contraste=1.06, lift=0.045),
        gerar("ili-forte", "ili — dessaturado forte",
              sat=0.28, contraste=1.10, lift=0.060),
        gerar("ili-quente", "ili — dessaturado quente",
              sat=0.50, contraste=1.05, lift=0.040, quente=0.05),
    ]
    for p in feitos:
        print(f"  {p.name}  ({p.stat().st_size // 1024} KB)")

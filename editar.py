"""Atalho: prepara o material e abre a interface, num comando so.

    python editar.py "C:/caminho/do/bruto.mp4"
    python editar.py "C:/caminho/da/pasta"      (pega o maior video da pasta)
    python editar.py "C:/pasta" --todos         (prepara todos e abre o primeiro)

Se o material ja foi preparado antes, nao refaz — vai direto pra interface.
Use --refazer pra forcar.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).parent
VIDEOS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".mts"}


def videos_de(alvo: Path) -> list[Path]:
    if alvo.is_file():
        return [alvo]
    achados = [p for p in sorted(alvo.iterdir())
               if p.is_file() and p.suffix.lower() in VIDEOS]
    if not achados:
        raise SystemExit(f"nenhum video em {alvo}")
    return achados


def saida_de(video: Path, base: Path | None) -> Path:
    return (base / video.stem) if base else (video.parent / "edit")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("alvo")
    p.add_argument("--todos", action="store_true", help="prepara todos os videos da pasta")
    p.add_argument("--refazer", action="store_true", help="reprocessa mesmo se ja existir")
    p.add_argument("--saida", default=None, help="pasta raiz das saidas")
    p.add_argument("--modelo", default="small")
    args = p.parse_args()

    alvo = Path(args.alvo).resolve()
    if not alvo.exists():
        raise SystemExit(f"nao achei: {alvo}")

    base = Path(args.saida).resolve() if args.saida else None
    lista = videos_de(alvo)
    if not args.todos and len(lista) > 1:
        lista = [max(lista, key=lambda p: p.stat().st_size)]
        print(f"pasta com varios videos — peguei o maior: {lista[0].name}")
        print("(use --todos pra preparar todos)\n")

    preparados = []
    for v in lista:
        destino = saida_de(v, base)
        if (destino / "edl.json").exists() and not args.refazer:
            print(f"[ja pronto] {v.name}")
        else:
            print(f"[preparando] {v.name}")
            r = subprocess.run(
                [sys.executable, str(RAIZ / "pipeline" / "prep.py"), str(v),
                 "--saida", str(destino), "--modelo", args.modelo])
            if r.returncode != 0:
                print(f"  falhou em {v.name}, seguindo")
                continue
        preparados.append(destino)

    if not preparados:
        raise SystemExit("nada preparado")

    print()
    subprocess.run([sys.executable, str(RAIZ / "server.py"), str(preparados[0])])
    return 0


if __name__ == "__main__":
    sys.exit(main())

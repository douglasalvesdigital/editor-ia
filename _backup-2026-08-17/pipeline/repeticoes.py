"""Acha tentativas repetidas da mesma fala e escolhe qual fica.

Quem grava sozinho erra e recomeça a frase do inicio. O sinal disso nao e a
frase inteira parecida — a tentativa boa costuma ser bem mais longa que a
abortada — e sim o COMECO igual:

    "E o pior e que da pra fazer ajustes..."                      (abortou)
    "E o pior e que da pra virar esse jogo com ajustes que..."    (abortou)
    "E o pior e que da pra virar esse jogo com ajustes que        (boa)
     quase ninguem percebe que da pra fazer."

Comparando os primeiros termos, as tres batem. Comparando por inteiro, nao.

Nada aqui apaga material: os takes descartados so ficam desativados, com o
motivo escrito, e voltam com um clique na interface.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

PALAVRAS_PREFIXO = 6      # quantas palavras do comeco entram na comparacao
SIMILAR_MIN = 0.82        # acima disso, e a mesma frase recomecada
INICIAIS_IGUAIS = 3       # tantas palavras iniciais identicas ja denunciam retake
SOBREPOSICAO_MIN = 0.80   # quanto do take menor precisa caber dentro do maior
MIN_PALAVRAS_CONTIDO = 4  # abaixo disso a contencao acerta por acaso
JANELA = 90.0             # segundos: tentativas longe demais nao sao retake
CURTO = 1.3               # take curto E de poucas palavras: quase nunca e fala util
MUITO_CURTO = 0.8         # abaixo disso nao cabe fala aproveitavel, seja la o que o ASR leu

# Marcadores de desistencia. MUITO conservador de proposito: descartar fala boa
# e pior que deixar sobrar, porque a sobra o editor ve e tira, e a falta ele so
# descobre depois. Ja saiu daqui "deixa eu" (aparece em "deixa eu te mostrar"),
# "de novo", "desculpa", "caramba" e "nao nao" — todos pegaram roteiro legitimo.
DESISTENCIA = [
    "perai", "pera ai", "peraí", "errei", "foi mal",
    "o que eu gravei", "corta isso",
]


def _normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9\s]", " ", t).strip()


def _prefixo(texto: str) -> str:
    return " ".join(_normalizar(texto).split()[:PALAVRAS_PREFIXO])


def _parecidos(a: str, b: str) -> float:
    pa, pb = _prefixo(a), _prefixo(b)
    if not pa or not pb:
        return 0.0
    return SequenceMatcher(None, pa, pb).ratio()


def _iniciais_iguais(a: str, b: str) -> int:
    """Quantas palavras do comeco batem exatamente."""
    n = 0
    for x, y in zip(_normalizar(a).split(), _normalizar(b).split()):
        if x != y:
            break
        n += 1
    return n


def _sobreposicao(a: str, b: str) -> float:
    """Quanto do take menor cabe dentro do maior, em bloco contiguo.

    Cobre o caso em que a tentativa boa engole a anterior mas comeca de outro
    jeito: "a gente montou um diagnostico..." dentro de "aqui na ili a gente
    montou um diagnostico...". Comparar so o prefixo nao acha isso.
    """
    na, nb = _normalizar(a), _normalizar(b)
    if not na or not nb:
        return 0.0
    menor, maior = (na, nb) if len(na) <= len(nb) else (nb, na)
    if len(menor.split()) < MIN_PALAVRAS_CONTIDO:
        return 0.0
    bloco = SequenceMatcher(None, menor, maior).find_longest_match(
        0, len(menor), 0, len(maior))
    return bloco.size / len(menor)


def _mesma_fala(a: str, b: str) -> bool:
    return (_iniciais_iguais(a, b) >= INICIAIS_IGUAIS
            or _parecidos(a, b) >= SIMILAR_MIN
            or _sobreposicao(a, b) >= SOBREPOSICAO_MIN)


def _e_desistencia(texto: str) -> bool:
    n = _normalizar(texto)
    return any(m in n for m in (_normalizar(x) for x in DESISTENCIA))


def _falas(ordenados: list[dict]) -> list[list[dict]]:
    """Junta cada take com as suas continuacoes.

    Um take marcado `continua` e o resto da mesma frase, quebrada so pra tirar
    o arrasto de uma pausa. Comparar esses fragmentos soltos com outros takes
    daria falso positivo facil ("que dá pra virar" parece com meio mundo) — a
    comparacao tem que ser entre falas inteiras.
    """
    blocos: list[list[dict]] = []
    for t in ordenados:
        if t.get("continua") and blocos:
            blocos[-1].append(t)
        else:
            blocos.append([t])
    return blocos


def _texto_do_bloco(bloco: list[dict]) -> str:
    return " ".join(t["texto"] for t in bloco)


def marcar(takes: list[dict]) -> dict:
    """Desativa repeticoes e desistencias. Devolve um resumo do que mudou."""
    ordenados = sorted(takes, key=lambda t: t["ini"])
    for t in ordenados:          # idempotente: reavaliar do zero, sem herdar
        t.pop("motivo", None)    # decisao de rodada anterior
        t["ativo"] = True

    # Tudo abaixo raciocina em FALAS (take + suas continuacoes), nunca em
    # fragmento solto.
    blocos = _falas(ordenados)

    def desativar(bloco: list[dict], motivo: str) -> None:
        for t in bloco:
            t["ativo"] = False
            t["motivo"] = motivo if t is bloco[0] else "continuação do trecho acima"

    descartados_desistencia = 0
    for b in blocos:
        dur = b[-1]["fim"] - b[0]["ini"]
        if _e_desistencia(_texto_do_bloco(b)) and dur <= 4.0:
            desativar(b, "parece desistência de take")
            descartados_desistencia += 1

    # agrupa tentativas da mesma frase; a ULTIMA do grupo e a que fica, porque
    # e a que a pessoa deu por boa antes de seguir em frente
    grupos: list[list[list[dict]]] = []
    for b in blocos:
        if b[0].get("motivo"):
            continue
        texto = _texto_do_bloco(b)
        for g in grupos:
            ultimo = g[-1]
            if (b[0]["ini"] - ultimo[-1]["fim"] <= JANELA
                    and _mesma_fala(_texto_do_bloco(ultimo), texto)):
                g.append(b)
                break
        else:
            grupos.append([b])

    repetidos = 0
    for g in grupos:
        if len(g) < 2:
            continue
        escolhido = g[-1]
        for b in g[:-1]:
            desativar(b, f"tentativa anterior do take #{escolhido[0]['id']}")
            repetidos += 1
        escolhido[0]["motivo"] = f"escolhido entre {len(g)} tentativas"

    # fala muito curta e isolada costuma ser respiracao ou grunhido
    curtos = 0
    for b in blocos:
        if b[0].get("motivo") or not b[0]["ativo"]:
            continue
        dur = b[-1]["fim"] - b[0]["ini"]
        poucas = len(_normalizar(_texto_do_bloco(b)).split()) <= 3
        # Abaixo de MUITO_CURTO nem importa o que o ASR leu: num trecho desses
        # apareceu "O que que eu quero..." em 0,45s, que e fala picada, nao frase.
        if dur < MUITO_CURTO or (dur < CURTO and poucas):
            desativar(b, "trecho muito curto")
            curtos += 1

    return {
        "repetidos": repetidos,
        "desistencias": descartados_desistencia,
        "curtos": curtos,
        "grupos": [[b[0]["id"] for b in g] for g in grupos if len(g) > 1],
    }

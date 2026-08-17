"""O que a edicao TEM, na timeline de saida — fonte unica pra interface e render.

Antes existiam tres versoes da mesma verdade: o `edl.json`, o desenho da
timeline (que so sabia de corte) e o que o `render.gerar` de fato produzia.
Quem editava tinha que confiar no palpite. Este modulo e a resposta: ele le o
EDL e o estilo e devolve, em segundos da SAIDA, cada coisa que vai aparecer no
arquivo — legenda, headline, b-roll, movimento, flash, trilha, card de fim.

Duas regras que fazem ele valer alguma coisa:

1. **Nao reimplementa nada.** A legenda vem de `export_ass.blocos`, o mesmo
   codigo que escreve o .ass. O movimento e o flash seguem, indice por indice,
   a regra que o `render.gerar` usa. Se um mudar, o outro muda junto — que e
   exatamente o que impede a timeline de virar decoracao.
2. **Fala o que NAO vai acontecer.** Ligar b-roll sem imagem na pasta, ou
   trilha sem mp3, antes saia calado: o render ignorava e o video vinha
   diferente do que a tela prometia. Agora isso volta como alerta.
"""

from __future__ import annotations

from pathlib import Path

from . import export_ass

DUR_ENCERRAMENTO = 2.5

# O padrao de um projeto que ainda nao escolheu nada.
#
# Mora AQUI e em nenhum outro lugar. Enquanto ele viveu tambem no
# ESTILO_PADRAO do app.js, um projeto recem-preparado (`estilo: null`) abria
# com o inspetor dizendo "legenda: Frase" e a pista de legenda vazia na
# timeline — o servidor lia `{}` e concluia "nenhuma". Dois padroes sao duas
# verdades, que e exatamente o que este modulo existe pra impedir.
ESTILO_PADRAO = {
    "tipo": "limpa",
    "cor": "#EE8656",
    "headline_estilo": "contorno",
    "headline": "",
    "legenda": "ili-frase",
    "zoom": True,
    "zoom_animado": False,
    "flash": False,
    "cor_look": True,
    "trilha": False,
    "broll": False,
    "caixa": "minuscula",
    "altura_legenda": 0.20,
    "lut": "",
    "encerramento": False,
    "observacoes": "",
}


def com_padrao(estilo: dict | None) -> dict:
    """O estilo do projeto por cima do padrao — como todo mundo deve ler."""
    return {**ESTILO_PADRAO, **(estilo or {})}


def _ativos(edl: dict) -> list[dict]:
    return sorted([t for t in edl.get("takes", []) if t.get("ativo", True)],
                  key=lambda t: t["ini"])


def clipes_video(edl: dict) -> list[dict]:
    """Os takes emendados, ja reposicionados na timeline de saida.

    `fonte_ini`/`fonte_fim` ficam junto porque a interface precisa dos dois
    tempos: desenha no tempo da saida, mas busca a miniatura no tempo do bruto.
    """
    saida, acc = [], 0.0
    for i, t in enumerate(_ativos(edl)):
        dur = t["fim"] - t["ini"]
        saida.append({
            "i": i,
            "take_id": t["id"],
            "ini": round(acc, 3),
            "fim": round(acc + dur, 3),
            "fonte_ini": t["ini"],
            "fonte_fim": t["fim"],
            "texto": (t.get("texto") or "").strip(),
            "manual": bool(t.get("manual")),
        })
        acc += dur
    return saida


def duracao_fala(edl: dict) -> float:
    """Quanto dura o corte falado — sem o card de encerramento."""
    return sum(t["fim"] - t["ini"] for t in _ativos(edl))


def montar(edl: dict, estilo: dict, recursos: dict | None = None) -> dict:
    """Monta o plano completo: trilhas com clipes + alertas do que nao bate.

    `recursos` e o que a PASTA oferece de verdade (trilha, referencias, card de
    fim, luts). E ele que permite dizer "voce ligou b-roll e nao ha imagem",
    em vez de deixar o render decidir isso calado.
    """
    estilo = com_padrao(estilo)
    rec = recursos or {}
    refs = list(rec.get("referencias") or [])
    tem_trilha = bool(rec.get("trilha"))
    tem_encerramento = bool(rec.get("encerramento"))

    tipo = estilo.get("tipo") or "limpa"
    dividido = tipo in ("dividida", "dividida2")
    zoom = bool(estilo.get("zoom"))
    zoom_animado = bool(estilo.get("zoom_animado"))
    flash = bool(estilo.get("flash"))
    quer_broll = bool(estilo.get("broll"))
    quer_trilha = bool(estilo.get("trilha"))
    quer_encerramento = bool(estilo.get("encerramento"))
    leg_estilo = estilo.get("legenda") or "nenhuma"
    headline = (estilo.get("headline") or "").strip()

    video = clipes_video(edl)
    fala = duracao_fala(edl)
    # o card de fim entra como mais um segmento antes do concat, entao ele conta
    # na duracao do arquivo — mas NAO recebe legenda nem headline
    usa_encerramento = quer_encerramento and tem_encerramento
    total = fala + (DUR_ENCERRAMENTO if usa_encerramento else 0.0)

    trilhas: list[dict] = []
    alertas: list[dict] = []

    # ---- headline: uma faixa unica sobre toda a fala ----
    hl_clips = []
    if headline:
        hl_clips.append({
            "id": "hl",
            "ini": 0.0, "fim": round(fala, 3),
            "rotulo": headline.splitlines()[0],
            "sub": f"{len(headline.splitlines())} linha(s) · "
                   f"{'caixa' if estilo.get('headline_estilo') == 'caixa' else 'contorno'}",
        })
    trilhas.append({"id": "headline", "rotulo": "headline", "clips": hl_clips,
                    "vazia": "nenhuma headline escrita"})

    # ---- legenda: exatamente os blocos que o .ass vai conter ----
    leg_clips = []
    for n, b in enumerate(export_ass.blocos(edl, leg_estilo)):
        leg_clips.append({
            "id": f"leg{n}",
            "ini": round(b["ini"], 3), "fim": round(b["fim"], 3),
            "rotulo": " ".join(w["t"] for w in b["palavras"]),
            "sub": b["modo"],
            # as palavras vao junto pra previa sobre o player poder realcar a
            # mesma que o arquivo vai realcar — sem recalcular a regra aqui
            "palavras": b["palavras"],
        })
    trilhas.append({"id": "legenda", "rotulo": "legenda", "clips": leg_clips,
                    "vazia": "sem legenda"})

    # ---- b-roll: uma imagem por take, alternando, so na tela dividida ----
    broll_clips = []
    if quer_broll and dividido and refs:
        for c in video:
            nome = Path(refs[c["i"] % len(refs)]).name
            broll_clips.append({
                "id": f"br{c['i']}", "ini": c["ini"], "fim": c["fim"],
                "rotulo": nome, "sub": "metade de cima" if tipo == "dividida" else "metade de baixo",
            })
    trilhas.append({"id": "broll", "rotulo": "b-roll", "clips": broll_clips,
                    "vazia": "sem imagem de apoio"})

    # ---- movimento e flash: a MESMA regra de indice que o render usa ----
    mov_clips = []
    for c in video:
        i = c["i"]
        if zoom_animado:
            qual = "zoom in" if i % 2 == 0 else "zoom out"
            mov_clips.append({"id": f"mv{i}", "ini": c["ini"], "fim": c["fim"],
                              "rotulo": qual, "sub": "ao longo do take", "kind": "zoom"})
        elif zoom and i % 2 == 1:
            mov_clips.append({"id": f"mv{i}", "ini": c["ini"], "fim": c["fim"],
                              "rotulo": "punch-in", "sub": "escala fixa", "kind": "zoom"})
        # flash mora na EMENDA, entao so existe a partir do segundo take
        if flash and i > 0:
            dur_flash = min(0.07, max(0.04, (c["fim"] - c["ini"]) / 30))
            mov_clips.append({"id": f"fl{i}", "ini": c["ini"],
                              "fim": round(c["ini"] + dur_flash, 3),
                              "rotulo": "flash", "sub": "na emenda", "kind": "flash"})
    mov_clips.sort(key=lambda c: (c["ini"], c["kind"]))
    trilhas.append({"id": "motion", "rotulo": "motion", "clips": mov_clips,
                    "vazia": "sem movimento nem efeito"})

    # ---- video: os takes emendados + o card de fim, se houver ----
    vid_clips = [{
        "id": f"v{c['i']}", "ini": c["ini"], "fim": c["fim"],
        "rotulo": c["texto"] or "(trecho sem fala)",
        "sub": f"take #{c['take_id']}",
        "take_id": c["take_id"], "fonte_ini": c["fonte_ini"], "fonte_fim": c["fonte_fim"],
        "kind": "take",
    } for c in video]
    if usa_encerramento:
        vid_clips.append({
            "id": "fim", "ini": round(fala, 3), "fim": round(total, 3),
            "rotulo": Path(str(rec.get("encerramento"))).name,
            "sub": "card de encerramento", "kind": "encerramento",
        })
    trilhas.append({"id": "video", "rotulo": "vídeo", "clips": vid_clips,
                    "vazia": "nenhum take no corte"})

    # ---- audio: a voz acompanha os takes; a onda a interface desenha sozinha ----
    trilhas.append({
        "id": "audio", "rotulo": "áudio", "onda": True,
        "clips": [{"id": f"a{c['i']}", "ini": c["ini"], "fim": c["fim"],
                   "rotulo": "voz", "sub": f"take #{c['take_id']}",
                   "fonte_ini": c["fonte_ini"], "fonte_fim": c["fonte_fim"]}
                  for c in video],
        "vazia": "sem áudio",
    })

    # ---- trilha: entra no arquivo inteiro, com ducking ----
    mus_clips = []
    if quer_trilha and tem_trilha:
        mus_clips.append({
            "id": "mus", "ini": 0.0, "fim": round(total, 3),
            "rotulo": Path(str(rec.get("trilha"))).name,
            "sub": "em loop, abaixa sozinha na fala",
        })
    trilhas.append({"id": "trilha", "rotulo": "trilha", "clips": mus_clips,
                    "vazia": "sem trilha"})

    # ---- alertas: tudo que a tela promete e o arquivo nao vai cumprir ----
    def alerta(texto: str, acao: str = "", nivel: str = "alerta") -> None:
        alertas.append({"nivel": nivel, "texto": texto, "acao": acao})

    if quer_broll and not dividido:
        alerta("b-roll está ligado, mas o tipo de edição é “limpa” — "
               "a imagem de apoio só entra na tela dividida.",
               "escolha tela dividida ou desligue o b-roll")
    elif quer_broll and not refs:
        alerta("b-roll está ligado e não há nenhuma imagem na pasta do projeto — "
               "a outra metade da tela vai sair como faixa lisa.",
               "salve ref1.png (ref2.jpg…) na pasta do projeto")
    if quer_trilha and not tem_trilha:
        alerta("trilha está ligada e não há trilha.mp3 na pasta — "
               "o vídeo vai sair sem música.",
               "salve trilha.mp3 na pasta do projeto")
    if quer_encerramento and not tem_encerramento:
        alerta("card de encerramento está ligado e nenhum arquivo foi encontrado.",
               "salve encerramento.png na pasta do projeto")
    if estilo.get("lut") and estilo["lut"] not in (rec.get("luts") or []):
        alerta(f"o LUT “{estilo['lut']}” não está mais disponível — "
               "o render vai sair sem ele.", "escolha outro LUT")
    if not video:
        alerta("nenhum take ativo — não há o que renderizar.",
               "volte ao Corte e traga algum take de volta")
    if leg_estilo == "nenhuma" and not headline:
        alerta("o vídeo vai sair sem legenda e sem headline.", "", "info")

    return {
        "duracao": round(total, 3),
        "duracao_fala": round(fala, 3),
        "dur_encerramento": DUR_ENCERRAMENTO if usa_encerramento else 0.0,
        "trilhas": trilhas,
        "alertas": alertas,
    }

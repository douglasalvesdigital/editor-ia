---
name: editar-video
description: Corta vídeo bruto automaticamente e abre a interface de revisão. Use quando pedirem para editar, cortar, decupar ou limpar um vídeo gravado — remover silêncio, escolher entre takes repetidos, gerar legenda, exportar MP4 ou sequência para o Premiere. Também quando apontarem uma pasta de brutos e disserem "edita isso".
---

# Editar vídeo

Transcreve o bruto, propõe o corte, abre uma interface local pra revisão e
exporta.

Esta skill mora **dentro do repositório do editor**, então os comandos abaixo
rodam a partir da raiz do projeto. Se você instalou a skill solta em
`~/.claude/skills/`, troque `python editar.py` pelo caminho completo até o
`editar.py` do clone.

## Antes da primeira vez

Confira que a máquina tem o que o pipeline precisa — nada disso é opcional:

```bash
ffmpeg -version && ffprobe -version
python -c "import faster_whisper, numpy, PIL; print('dependencias ok')"
```

Faltando: `ffmpeg`/`ffprobe` no PATH, e
`pip install faster-whisper numpy Pillow`.

**Fontes.** A capa e a legenda usam *Funnel Display* e *Trirong*. O
`pipeline/thumb.py` procura em `C:/Windows/Fonts` e, se não achar, cai numa
fonte padrão **sem avisar** — a capa sai com a tipografia errada e ninguém
entende por quê. Em macOS/Linux isso acontece sempre. Se a capa sair estranha,
é isso: instale as fontes ou ajuste `SISTEMA` no `thumb.py`.

## O caminho curto

Na maioria das vezes é só isso:

```bash
python editar.py "<pasta ou arquivo>"
```

Prepara o que faltar e abre http://localhost:5178. Se já tiver sido preparado
antes, vai direto pra interface.

Avise que a interface abriu e o que ela propôs (quantos takes, quanto foi
cortado, o que foi descartado e por quê). **Não decida pela pessoa o que fica** —
a interface existe pra isso.

## Quando precisar de controle fino

```bash
# só preparar, sem abrir a interface
python pipeline/prep.py "<video>" --saida "<pasta>" --modelo small

# abrir a interface num projeto já preparado
python server.py "<pasta com edl.json>"
```

Opções do prep: `--ate N` (só os primeiros N segundos, bom pra testar),
`--modelo` (padrão `small`), `--saida` (onde gravar).

## Regras que não são preferência

1. **Modelo `small` por padrão.** O `large-v3` "conserta" a fala — funde as
   tentativas repetidas numa frase contínua e apaga a hesitação. Ótimo pra
   legenda, destrutivo pra decidir corte. Medido: `small` 78 palavras e as três
   tentativas separadas; `large-v3` 41 palavras e tudo fundido.
2. **Nunca escreva dentro da pasta de brutos do cliente.** Use `--saida`
   apontando pra uma pasta de trabalho do projeto. O material original não se
   toca.
3. **A interface usa proxy, o render usa o bruto.** Isso já é automático. Não
   troque o `fonte` do `edl.json` pelo proxy.
4. **Não conclua que ficou bom sem alguém ver.** O corte automático acerta a
   maior parte, mas decisão editorial (resmungo, ênfase, ritmo) é humana.

## O que sai

Tudo na pasta de saída:

| arquivo | o quê |
|---|---|
| `edl.json` | as decisões de corte — é a fonte da verdade |
| `sequencia.xml` | sequência pro Premiere (Arquivo > Importar) |
| `master.srt` | legenda nos tempos do vídeo cortado |
| `final.mp4` | vídeo pronto, com legenda se escolhida |
| `proxy.mp4` | cópia leve, só pra interface |

O XML aponta pros brutos com in/out, então o editor consegue arrastar a borda
de um take e recuperar material.

## Se der problema

- **Player não reproduz / trava:** falta o `proxy.mp4`. Rode o prep de novo, ou
  gere só o proxy com `pipeline.prep.gerar_proxy`.
- **Cortou no meio da fala:** aumente `PAD_SAIDA`/`PAD_ENTRADA` em
  `pipeline/prep.py`, ou ajuste arrastando a borda na interface.
- **Deixou passar take repetido:** os limiares estão em
  `pipeline/repeticoes.py` (`INICIAIS_IGUAIS`, `SOBREPOSICAO_MIN`).
- **Descartou fala boa:** olhe a lista `DESISTENCIA` em `repeticoes.py`. Ela é
  conservadora de propósito — falso positivo é pior que falso negativo, porque
  a sobra o editor vê e tira, a falta ele só descobre depois.
- **A porta 5178 já está em uso:** feche o servidor anterior. No Windows dois
  processos conseguem escutar a mesma porta e metade dos pedidos cai no antigo.

Detalhes e o porquê de cada decisão: `README.md` do projeto.

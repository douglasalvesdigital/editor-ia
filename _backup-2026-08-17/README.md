# Editor IA — corte assistido com revisão humana

Pipeline que transcreve um bruto, propõe o corte de silêncio e abre uma
interface local pra você revisar, ajustar e aprovar. Depois exporta pro
Premiere, pra legenda ou pra mp4 pronto.

A máquina faz a decupagem chata. Você dá a palavra final.

## Requisitos

- `ffmpeg` e `ffprobe` no PATH
- Python 3.10+ com `faster-whisper` e `numpy`

Nada mais. O servidor da interface usa só a biblioteca padrão.

## Uso

**1. Preparar o bruto** — transcreve, mede o áudio e propõe os takes:

```bash
python pipeline/prep.py "C:/caminho/do/bruto.mp4"
```

Grava tudo em `<pasta_do_bruto>/edit/`. O material original nunca é tocado.

Opções: `--ate 60` processa só os primeiros 60s (bom pra testar rápido),
`--saida <pasta>` grava em outro lugar, `--modelo <nome>` troca o Whisper.

**Sobre o modelo: aqui, maior é pior.** Medido no mesmo bruto:

| modelo | palavras | o que fez com as 3 tentativas da mesma frase |
|---|---|---|
| `small` | 78 | separou as três, e pegou o *"Não, pera aí"* |
| `large-v3` | 41 | fundiu tudo numa frase contínua, apagou a desistência |

O `large-v3` é melhor em *entender* e por isso **conserta** a fala: normaliza
gagueira, remove repetição, limpa a hesitação. Para legenda isso é ótimo; para
decidir corte é destrutivo, porque apaga exatamente o sinal de que houve um
retake. O padrão é `small` de propósito.

**2. Revisar** — abre a interface em http://localhost:5178:

```bash
python server.py "C:/caminho/do/bruto.mp4"
```

Na tela: player com preview do corte, timeline com waveform e os takes.

| ação | como |
|---|---|
| play / pause | `espaço` |
| frame a frame | `←` `→` (com `shift`, 1 segundo) |
| tirar/pôr um take no corte | `delete`, ou o checkbox na lista |
| ajustar onde o take começa/termina | arrastar as bordas na timeline |
| desfazer o ajuste de um take | duplo-clique nele |

O preview pula os trechos removidos, então o que você ouve é o corte final.
Cada alteração salva sozinha.

**3. Estilo — como a Fase 2 vai ser montada.** Aprovar o corte leva pra cá:

| seção | opções |
|---|---|
| Tipo de edição | Limpa · Tela dividida · Tela dividida 2 |
| Cor de destaque | picker + hex + swatches da marca |
| Estilo de headline | Contorno · Caixa · Nenhuma |
| Estilo de legenda | Frase com ênfase · Palavra por vez · Bloco · Nenhuma |
| Elementos | zoom in · zoom in/out · flash · colorização · trilha IA · b-roll · tracking *(não implementado)* |
| Observações | texto livre pra Fase 2 |

Os cards de headline e legenda **renderizam o texto de verdade** — você vê como
vai ficar antes de gerar.

**4. Fase 2 — acabamento.** Preview e geração:

| legenda | como fica |
|---|---|
| `ili-frase` | 3 palavras por vez, a principal em laranja — é o padrão |
| `ili-palavra` | uma palavra grande por vez, ritmo acelerado |
| `ili-bloco` | duas linhas corridas, leitura calma |

| cor | efeito |
|---|---|
| `ili` | saturação 105 → 63, sombras levantadas |
| `ili-forte` | saturação 105 → 33, look de marca |

Medido em pixel, não no olho: `PIL.ImageStat` sobre o mesmo frame dos três
renders. O tratamento é aplicado **por segmento, antes da legenda** — colorizar
depois lavaria o branco do texto junto com a imagem.

**4. Exportar** — os botões da Fase 2 geram, dentro da pasta de saída:

- `final.mp4` — vídeo pronto, com legenda e cor
- `sequencia.xml` — importe no Premiere por **Arquivo > Importar**
- `master.srt` — legenda já nos tempos do vídeo cortado
- `legenda.ass` — a legenda estilizada, se quiser reaproveitar

## Proxy

O prep gera um `proxy.mp4` de 720px com `+faststart`, e a interface reproduz
esse. O motivo é concreto: um bruto DJI de 1728×3072 a **29,8 Mbps** tem o
índice (`moov`) no **fim** do arquivo, então o player precisaria baixar quase
tudo antes de pular pra qualquer ponto — na prática a timeline não respondia ao
clique. Com proxy, 177 MB viram 1,2 MB e o vídeo inteiro carrega na hora.

O render final continua lendo o bruto. Nunca troque o `fonte` do `edl.json`
pelo proxy.

## Por que o XML aponta pro bruto

Os clipes do `sequencia.xml` referenciam o **arquivo original** com pontos de
entrada e saída, não pedaços recortados em disco. Assim o editor abre a
sequência e consegue arrastar a borda de um take pra recuperar material que a
máquina cortou de mais. Exportar segmentos já cortados travaria a timeline.

## Decisões que não são gosto, são correção

Cada uma dessas custou um bug:

- **VAD ligado na transcrição** (`min_silence_duration_ms: 400`). Sem ele o
  Whisper estica a palavra que vem antes de uma pausa pra cobrir o silêncio
  inteiro — num bruto real saiu um `"que"` de **4,4 segundos**. Aí o vão entre
  palavras vira zero e não sobra sinal nenhum pra decidir onde cortar. Medido
  no mesmo material: sem VAD, 44 palavras e 2 esticadas; com VAD, 78 palavras
  e nenhuma. Os timestamps continuam na timeline original, então não se perde
  nada.
- **Silêncio medido no áudio, não inferido do texto.** O `silencedetect` diz
  onde a voz parou de verdade; o ASR ainda erra a borda por alguns décimos.
  Cruzando os dois, o resíduo de silêncio em cada emenda caiu de ~0,5s pra zero.
- **Corte só em fronteira de palavra**, com folga de 80–120ms. Os timestamps
  derrapam; sem a folga o corte come a primeira consoante.
- **Fade de 30ms em cada emenda.** Sem isso, estala em todo corte.
- **Extrai por segmento, junta com `-c copy`.** Um filtergraph único
  reencodaria o vídeo inteiro a cada mudança.
- **Legenda por último no filtro**, depois de qualquer overlay — senão some
  atrás deles.

## Escolha de take repetido

Quem grava sozinho erra e recomeça a frase do início. O sinal disso não é a
frase inteira parecida — a tentativa boa é bem mais longa que a abortada — e
sim o **começo igual**. `pipeline/repeticoes.py` compara as primeiras 6
palavras normalizadas; batendo acima de 0,82 dentro de 90s, é retake, e a
**última** tentativa é a que fica.

Também desativa desistências declaradas ("não, pera aí", "o que eu gravei") e
trechos curtos demais pra ser fala útil.

Nada é apagado: os descartados ficam desativados com o motivo escrito, e
voltam com um clique.

## Movimento e transição

**Automação de zoom in** é punch-in fixo: um take sim, outro não, escala
constante dentro do take. **Zoom in e out nos cortes** é diferente — a escala
se move ao longo do take, alternando o sentido a cada corte. Os dois disputam a
mesma escala, então ligar um desliga o outro na interface.

**Flash na transição** é um quadro estourado na emenda. É também o que explica
por que a detecção de cena acusa 3–4 "cortes" seguidos num vídeo assim: não são
cortes, é o flash.

Duas armadilhas medidas aqui:

- O `fade` precisa de `setpts=PTS-STARTPTS` antes. Com `-ss` anterior ao `-i`,
  o relógio do segmento não zera, e um `st=0` aponta pra instante já passado —
  o flash simplesmente não aparecia, sem erro nenhum.
- O `zoompan` precisa de `s=` na resolução exata e o `fps` real do material.
  Sem isso ele reamostra pra 25fps e o take sai fora de sincronia com o áudio.

## Material de apoio

Dois pontos de encontro entre o app e a geração por IA, ambos por convenção de
nome na pasta do projeto — sem configurar caminho, sem credencial no app:

| arquivo | serve pra |
|---|---|
| `trilha.mp3` (ou `.m4a`, `.wav`) | trilha sonora, mixada com ducking |
| `ref1.png`, `ref2.jpg`… | b-roll na outra metade da tela dividida |

Quem produzir (o agente pelo Magnific, ou você na mão) só precisa salvar ali.

## Trilha sonora

Largue um arquivo chamado `trilha.mp3` (ou `.m4a`, `.wav`) na pasta do projeto
e ligue *Trilha sonora* na aba Estilo. Não precisa configurar caminho: é o
ponto de encontro entre o app e a geração por IA — quem produzir a música
(o agente pelo Magnific, ou você na mão) só precisa deixar o arquivo ali.

A mixagem usa **ducking de verdade** (`sidechaincompress` com a voz como
chave), não volume fixo. Medido em teste: a trilha fica **9,4 dB mais baixa
enquanto alguém fala** e sobe sozinha no silêncio.

## Testes

```bash
python testes/validar.py "<pasta do projeto>"
```

63 checagens sobre material real: conversão de cor RGB→BGR, detecção de
repetição (incluindo os casos que **não** podem ser agrupados), offsets do SRT,
escape do ASS, XML bem formado e contíguo, render em todas as combinações,
ducking medido em dB, e casos de borda (nenhum take ativo, um take só,
headline vazia).

Alguns testes existem porque o bug aconteceu de verdade:

- **zoom com dimensão ímpar** — `crop`+`scale` por fator gerava 1727×3071 e o
  H.264 recusa dimensão ímpar. As contas passaram pra Python, forçadas a par.
- **`{` na transcrição** — abre bloco de override no ASS e o libass engole o
  trecho calado. Todo texto do ASR passa por `esc()` agora.
- **fade-out no instante zero** — um `afade=t=out:st=0` que eu tinha deixado no
  filtro da trilha zerava o áudio inteiro. O teste mede o nível em dB, então
  pega isso; um teste que só checasse "o arquivo existe" não pegaria.
- **caminho relativo no concat** — o demuxer resolve a partir da própria lista,
  então caminho relativo duplicava o prefixo. Agora vai só o nome do arquivo.
- **POST apagando os takes** — o servidor aceitava `takes: []` e destruía o
  corte. Agora responde 409.

## Estado

Pronto e testado: prep, revisão, aba Estilo, tela dividida, zoom, cor,
legenda em 3 estilos, headline em 2 versões, trilha com ducking, export
XML/SRT/MP4.

Falta: **b-roll** (o render ainda não insere clipes) e **movimento de
tracking** — os dois exigem detecção quadro a quadro, que é o trecho caro.

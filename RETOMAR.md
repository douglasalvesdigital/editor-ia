# Onde paramos

Última validação: **86 passaram, 0 falharam**.

```bash
python testes/validar.py "<pasta do projeto>"
```

## Funcionando

**Corte** — transcrição, remoção de silêncio entre falas e de pausa dentro da
frase, escolha entre takes repetidos, descarte de desistência e trecho curto.

**Edição manual** — arrastar numa área vazia cria take, `S` divide no cursor,
botões `tirar`/`voltar`/`apagar` em cada take, `Ctrl+Z` desfaz (40 níveis).

**Visual** — tela dividida (2 tipos, com b-roll na outra metade), punch-in
fixo, zoom in/out animado, flash suave na emenda, colorização, cor de destaque
configurável, legenda em 3 estilos com prévia ao vivo no player, headline em
2 versões, trilha com ducking.

**Capa** — 5 presets, sendo o `ili` fiel aos cards de `03_grafismos`
(minúscula, alinhado à esquerda, última linha em Trirong Bold Italic maior).
Prévia ao vivo em canvas. Formatos 9:16, 4:5 e 1:1.

**Saídas** — `final.mp4`, `sequencia.xml` (Premiere), `master.srt`,
`legenda.ass`, `capa.jpg`.

## Reforma da interface (branch `reforma-editor`)

Os itens 1 e 2 da lista de pendências saíram. Ver `AUDITORIA.md` para o
levantamento completo, com as medidas.

- **3 passos lineares** — Corte → Edição → Entrega. A aba Estilo deixou de
  existir: cada opção virou propriedade da camada a que pertence. A Capa foi
  para a Entrega, junto do render.
- **Timeline com 7 pistas** — headline, legenda, b-roll, motion, vídeo, áudio,
  trilha — em tempo de saída. Clicar num clipe abre as propriedades dele.
- **`pipeline/plano.py`** — fonte única do que a edição contém. A timeline
  desenha o que o render executa; a legenda vem de `export_ass.blocos()`, o
  mesmo código que escreve o `.ass`.
- **O render lê o estilo salvo**, não parâmetros vindos no POST.

Medido antes e depois, com o arquivo final no player aos 80s: o playhead ia
para 28% quando devia ir para 84,87%; agora vai para 84,866%.

## Pendências, em ordem

1. **Legenda desliza em relação ao vídeo.** Os tempos do `.ass` somam durações
   cruas dos takes, mas o render corta na fronteira do quadro e cada segmento
   sai alguns ms mais longo — medido, **+0,25s ao longo de 6 emendas**. No fim
   de um vídeo longo a legenda aparece adiantada. Conserto: quantizar o
   acumulado em `_palavras_na_saida` pelo fps. Mexe no `export_ass` e no
   `export_srt`, então pede rodar a suíte inteira depois.
2. **Lista de projetos recentes** ao abrir vídeo.
3. **Importar `sequencia.xml` no Premiere** — nunca foi aberto lá. Única parte
   verificada só no papel.
4. **Múltiplos brutos num vídeo** — não existe. O `edl.json` tem uma única
   `fonte`. Meio dia de trabalho e muda o formato (projetos atuais teriam que
   ser reprocessados). Na campanha de julho cada vídeo usa um bruto só, então
   não está bloqueando.
5. **Inserção de imagem em tela cheia** — hoje b-roll só na tela dividida.
6. **Mais estilos** — a referência tem 4 de headline e 6 de legenda; temos 2 e 3.
7. **Movimento de tracking** e **detecção de muleta** — os dois caros.

## Decisão em aberto

Uso interno da agência ou produto pra vender? Muda se o app pode depender do
Claude Code no cliente. A arquitetura hoje serve aos dois: trilha e b-roll
entram por convenção de nome na pasta, então o render não precisa de credencial.

## Cuidados que custaram bug

- **Um servidor por porta.** No Windows dois processos conseguem escutar a
  mesma porta e metade dos pedidos cai no antigo, com código velho em memória.
  Já protegido, mas se aparecer comportamento fantasma, cheque isso primeiro.
- **Não meça vídeo com `-ss` em arquivo vindo de `concat`.** O seek devolve o
  mesmo quadro para instantes diferentes — um flash de 1 quadro parecia 3.
  Use `select` + `-vsync 0` e decodifique em sequência.
- **A prévia da capa é código duplicado** (PIL no servidor, canvas no
  navegador). Mexeu num, mexa no outro, senão a prévia passa a mentir.
- **`modelo small` é proposital.** O `large-v3` conserta a fala e apaga o
  retake, que é justamente o sinal que a gente precisa.

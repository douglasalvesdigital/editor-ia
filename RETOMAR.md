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

## Pendências, em ordem

1. **Colapsar as 4 abas em 3 passos lineares** (Cortar → Visual → Exportar)
   com indicador de progresso. É a maior queixa de usabilidade: hoje o fluxo
   reflete o modelo de quem construiu, não o de quem usa.
2. **Legendas na timeline** — a referência mostra, e ajuda a ler o ritmo.
3. **Lista de projetos recentes** ao abrir vídeo.
4. **Importar `sequencia.xml` no Premiere** — nunca foi aberto lá. Única parte
   verificada só no papel.
5. **Múltiplos brutos num vídeo** — não existe. O `edl.json` tem uma única
   `fonte`. Meio dia de trabalho e muda o formato (projetos atuais teriam que
   ser reprocessados). Na campanha de julho cada vídeo usa um bruto só, então
   não está bloqueando.
6. **Inserção de imagem em tela cheia** — hoje b-roll só na tela dividida.
7. **Mais estilos** — a referência tem 4 de headline e 6 de legenda; temos 2 e 3.
8. **Movimento de tracking** e **detecção de muleta** — os dois caros.

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

# Auditoria do editor — o que estava ruim e o que virou

Levantada usando o produto de verdade num projeto real (DJI da campanha de
julho, 35,6s, 10 takes), não lendo código. Cada item abaixo foi **medido**, não
suposto.

## O problema de fundo

O Douglas descreveu como "três realidades": o estado interno, o que a interface
mostra e o que o render produz. Estava certo, e dava pra medir. Com o projeto
aberto na Fase 2 e o `final.mp4` no player, aos 10 segundos de vídeo:

| coisa | dizia |
|---|---|
| a timeline | 35,64s de duração, playhead em **28%** |
| o relógio | **4,77s** |
| o EDL | 13,57s de saída |
| o arquivo em disco | **17,42s** |

O playhead deveria estar em **84%** e o relógio em **10,00s**. Quatro números
para o mesmo instante.

A causa é de uma linha: o cursor era desenhado como
`currentTime / duração do bruto`, e com o arquivo final no player — que já está
cortado — isso aponta pro lugar errado por construção. O relógio tinha o
espelho do mesmo erro: convertia bruto→saída um tempo que já era de saída.

---

## Problemas, por impacto

### Impacto alto — a interface mente

1. **A timeline mentia na Fase 2.** Medido acima. Um editor cuja timeline não
   corresponde ao que toca é um editor em que não dá pra confiar em nada.

2. **A timeline não representava a edição.** Duas pistas (vídeo, áudio) e as
   regiões de corte. Legenda, headline, b-roll, zoom, flash, trilha e card de
   encerramento não existiam ali — eram checkboxes num formulário à parte.

3. **A duração nunca incluiu o card de encerramento.** A tela prometia 13,57s;
   o arquivo saía com 2,5s a mais. Nada explicava a diferença.

4. **A UI prometia b-roll impossível.** `broll: true` no estilo e **zero**
   imagens na pasta. O render fazia tela dividida com uma faixa cinza lisa e
   não avisava. Mesmo caso da trilha sem `trilha.mp3`.

5. **A headline se perdia ao recarregar.** O texto vivia só no `value` do
   textarea e só era lido na hora de exportar. `headline_estilo` era salvo, o
   texto não. Fechou a aba, perdeu.

6. **O render lia parâmetros vindos do POST**, não o estilo salvo. Quinze
   argumentos soltos entre a tela e o ffmpeg, cada um uma chance de divergir.

### Impacto médio — atrapalha o fluxo

7. **Quatro abas para duas fases.** "FASE 1 Corte", "Estilo", "FASE 2 Visual",
   "Capa" — duas numeradas como fase, duas não, e a Estilo ficava *entre* as
   fases sem ser uma. Já era a queixa nº 1 do `RETOMAR.md`.

8. **A aba Estilo escondia o vídeo.** `body[data-fase="estilo"] main { display:none }`
   — escolher legenda, cor, zoom e tela dividida numa tela **sem player e sem
   timeline**. É o oposto de editar.

9. **A Fase 2 não editava nada.** Era um resumo em texto e dois botões. Tudo
   que era edição estava na aba Estilo — menos a headline, órfã na Fase 2,
   separada do próprio estilo de headline.

10. **"Saídas: nada gerado ainda"** com quatro arquivos prontos em disco. A
    lista só conhecia exports feitos naquela aba, desde o último F5.

11. **Desfazer só valia na Fase 1.** O botão ficava visível e habilitado em
    todas as abas; mudança de estilo não era desfazível.

12. **Atalhos morriam fora da Fase 1.** `espaço` não dava play na Fase 2,
    embora houvesse um player e um botão de play ali.

13. **Informação duplicada.** `#resumo-estilo` e `#resumo-fase2` eram o mesmo
    HTML copiado de um pro outro.

### Impacto baixo — atrito

14. **Dois checkboxes de zoom que se desligavam sozinhos.** A regra estava
    certa (disputam a mesma escala), a forma é que mentia: escolha única
    resolve.

15. **"Aprovar corte" não aprovava nada.** Só trocava de aba. O campo
    `aprovado` existe no EDL desde o prep e nunca foi escrito.

16. **Player de 365px num palco de 1300px.** ~70% do espaço vazio.

17. **Código morto.** A classe `.opcao` tinha CSS e um handler em JS; não
    aparecia uma vez no HTML.

---

## Como passou a funcionar

### Uma fonte de verdade: `pipeline/plano.py`

O servidor calcula o que a edição contém e devolve em `/api/plano`. A timeline
desenha **isso**. Duas regras fazem valer:

- **não reimplementa nada** — a legenda vem de `export_ass.blocos()`, o mesmo
  código que escreve o `.ass`; movimento e flash seguem, índice por índice, a
  regra que o `render.gerar` usa;
- **fala o que não vai acontecer** — b-roll sem imagem, trilha sem mp3, LUT que
  sumiu: tudo volta como alerta em vez de sair calado.

Para provar que o refactor do `export_ass` não mudou o resultado, gerei o ASS
antes e depois em 16 combinações de estilo/caixa/headline: **16 de 16
byte-idênticos**.

### Três passos, na ordem do trabalho

`① Corte → ② Edição → ③ Entrega`. A aba Estilo deixou de existir: cada opção
virou propriedade da camada que ela afeta. A Capa foi pra Entrega, junto do
render e dos arquivos — capa é entregável, não edição.

### A timeline representa a edição

Sete pistas — headline, legenda, b-roll, motion, vídeo, áudio, trilha — em
**tempo de saída**, com um cursor só atravessando todas. Pista vazia continua
visível e diz por que está vazia ("sem imagem de apoio").

No passo 1 a timeline segue sendo a do bruto: ali você decide o que sobra, e
precisa ver o que está jogando fora.

### Clicar num clipe abre as propriedades dele

Legenda, headline, b-roll, motion, take, trilha. Clicar no rótulo da pista abre
as propriedades da camada. `esc` volta pro projeto.

### O render lê o que está salvo

`/api/exportar` recebe só os formatos; todo o resto vem do `edl.json`. A
interface salva e **espera o salvamento** antes de pedir o render. Não sobrou
caminho para o arquivo divergir da tela.

---

## Um furo que a própria reforma criou

Testando um projeto recém-preparado (`estilo: null`), o inspetor mostrava
"legenda: Frase" e a pista de legenda aparecia **vazia**. Causa: o padrão
estava definido em dois lugares — `ESTILO_PADRAO` no `app.js` e a leitura
`estilo or {}` no servidor. Dois padrões são duas verdades, exatamente o que
este trabalho existe pra impedir.

O padrão passou a morar só em `plano.ESTILO_PADRAO`, e o `/api/projeto` entrega
o estilo já resolvido. O cliente não tem mais cópia.

---

## O que continua pendente

- **Múltiplos brutos num vídeo** — o `edl.json` tem uma `fonte` só.
- **Tracking** e **detecção de muleta** — exigem análise quadro a quadro.
- **`sequencia.xml` nunca foi aberto no Premiere.** Continua verificado só no
  papel, e é a única saída nessa condição.
- **A prévia da capa é código duplicado** (PIL no servidor, canvas no
  navegador). Mexeu num, mexa no outro.

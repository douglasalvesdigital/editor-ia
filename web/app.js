/* Interface do editor — 3 passos: corte, edição, entrega.
 *
 * A regra que organiza este arquivo: a timeline do passo 2 desenha o `plano`
 * que o servidor calcula (pipeline/plano.py), e o render lê o estilo SALVO.
 * Ninguém aqui reimplementa "onde a legenda cai" ou "onde o zoom entra" — se
 * isso voltasse a ser calculado no cliente, voltaríamos a ter uma timeline que
 * mostra uma edição e um arquivo que contém outra.
 */

const $  = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const player    = $("#player");
const trilhasEl = $("#trilhas");
const listaEl   = $("#lista-takes");
const legendaEl = $("#legenda-preview");
const headlineEl= $("#headline-preview");

let proj = null;
let takes = [];
let plano = null;
let recursos = { luts: [], referencias: [], saidas: [], final: {} };
let passo = "corte";
let selecionado = null;      // take selecionado (passo 1)
let selecao = null;          // {pista, clipe} selecionado (passo 2)
let arrasto = null;
let criando = null;

// Quando o usuário clica de propósito num trecho cortado, ele quer OUVIR
// aquilo. Sem isso o preview pularia na mesma hora e daria a impressão de que
// a timeline não responde ao clique.
let tregua = false;

const FRAME = () => 1 / (proj?.info?.fps || 30);
const clamp = (v, a, b) => Math.max(a, Math.min(b, v));

/* ---------------- utilidades ---------------- */

function fmt(t){
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  const c = Math.floor((t % 1) * 100);
  return `${m}:${String(s).padStart(2,"0")},${String(c).padStart(2,"0")}`;
}

const esc = s => String(s ?? "").replace(/[&<>"]/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));

function avisar(msg, ruim=false){
  const el = $("#aviso");
  el.textContent = msg;
  el.classList.toggle("ruim", ruim);
  el.classList.add("on");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("on"), 3200);
}

function trabalhando(on, txt="renderizando…"){
  $("#trabalhando-txt").textContent = txt;
  $("#trabalhando").classList.toggle("on", on);
}

const ativos = () => takes.filter(t => t.ativo).sort((a,b) => a.ini - b.ini);
const duracaoFala = () => ativos().reduce((s,t) => s + (t.fim - t.ini), 0);

/* ---------------- mapa de tempo: bruto <-> saída ----------------
 *
 * É o que faltava. A timeline antiga desenhava o cursor sempre como
 * `currentTime / duração do bruto`; com o arquivo final no player — que já
 * está cortado — isso apontava para o lugar errado por construção. Medido
 * num projeto real: o cursor caía em 28% quando o certo era 84%.
 */

function saidaDe(tFonte){
  let acc = 0;
  for (const x of ativos()){
    if (tFonte >= x.fim) acc += x.fim - x.ini;
    else if (tFonte >= x.ini) return acc + (tFonte - x.ini);
    else break;
  }
  return acc;    // caiu num trecho cortado: encosta na emenda anterior
}

function fonteDe(tSaida){
  let resto = tSaida;
  for (const x of ativos()){
    const d = x.fim - x.ini;
    if (resto <= d) return x.ini + resto;
    resto -= d;
  }
  return null;   // passou do fim da fala (card de encerramento)
}

const duracaoSaida = () => plano?.duracao ?? duracaoFala();

/* ---------------- carregar ---------------- */

async function carregar(){
  const r = await fetch("/api/projeto");
  if (!r.ok) throw new Error("servidor respondeu " + r.status);
  proj = await r.json();
  takes = proj.takes;

  $("#nome-projeto").textContent = proj.nome;
  player.src = "/midia/fonte";

  // o servidor já resolve o estilo sobre o padrão (pipeline/plano.py). Ter um
  // padrão aqui também foi o que fez o inspetor dizer "legenda: Frase" com a
  // pista de legenda vazia num projeto recém-preparado.
  estilo = proj.estilo;
  await recarregarRecursos();
  await recarregarPlano();

  ligarCapa();
  aplicarCorNaTela();
  irParaPasso(passoSalvo(proj.fase));
  renderTudo();
  new ResizeObserver(() => desenharTimeline()).observe(trilhasEl);
}

// O EDL antigo guardava 1 | "estilo" | 2 | "capa". Traduzir em vez de migrar
// o arquivo: projeto velho abre no lugar certo sem ser reescrito.
function passoSalvo(f){
  if (f === "corte" || f === "edicao" || f === "entrega") return f;
  if (f === 2 || f === "estilo") return "edicao";
  if (f === "capa") return "entrega";
  return "corte";
}

async function recarregarRecursos(){
  try { recursos = await (await fetch("/api/recursos")).json(); } catch {}
}

async function recarregarPlano(){
  try {
    plano = await (await fetch("/api/plano")).json();
  } catch { plano = null; }
  atualizarStatus();
  if (passo !== "corte") desenharTimeline();
  if (passo === "entrega") pintarEntrega();
  atualizarAvisoFinal();
}

function atualizarStatus(){
  const removidos = takes.filter(t => !t.ativo).length;
  const repetidos = takes.filter(t => !t.ativo && /tentativa anterior/.test(t.motivo || "")).length;
  const fala = duracaoFala();
  const cortado = proj.duracao - fala;
  $("#status-corte").textContent =
    `${takes.length} takes` +
    (removidos ? `, ${removidos} removido${removidos>1?"s":""}` : "") +
    (repetidos ? ` (${repetidos} repetição)` : "") +
    ` · −${cortado.toFixed(1)}s de bruto`;

  // O relógio do player mostra a duração do ARQUIVO, card de fim incluído.
  // Antes ele mostrava só a soma dos takes: o vídeo saía 2,5s mais longo do
  // que a interface prometia e nada na tela explicava a diferença.
  $("#t-final").textContent = fmt(duracaoSaida());
  $("#rot-corte").textContent = `${ativos().length} takes · ${fmt(fala)}`;
  $("#rot-edicao").textContent = plano ? resumoCurto() : "como o vídeo fica";
  const prontos = (recursos.saidas || []).filter(s => !s.desatualizado).length;
  $("#rot-entrega").textContent = prontos
    ? `${prontos} arquivo${prontos>1?"s":""} em dia` : "gerar os arquivos";
}

/* ================================================================
   TIMELINE
   ================================================================ */

const PISTAS = {
  headline: {rotulo:"headline", alt:26, cor:"hl"},
  legenda:  {rotulo:"legenda",  alt:26, cor:"leg"},
  broll:    {rotulo:"b-roll",   alt:26, cor:"br"},
  motion:   {rotulo:"motion",   alt:26, cor:"mv"},
  video:    {rotulo:"vídeo",    alt:52, cor:"vid"},
  audio:    {rotulo:"áudio",    alt:38, cor:"aud"},
  trilha:   {rotulo:"trilha",   alt:24, cor:"mus"},
};

const baseFonte = () => passo === "corte";

// Com o arquivo renderizado no player, a régua da timeline é a duração REAL
// dele, não a prevista. Os dois diferem por quantização de quadro: cada
// segmento é cortado na fronteira do frame e ganha alguns ms — medido, +0,25s
// em 6 emendas. Usar a previsão aqui arrastaria o cursor uns 0,3% ao longo do
// vídeo, que é o mesmo tipo de mentira que esta reforma veio tirar.
function duracaoBase(){
  if (baseFonte()) return proj.duracao;
  if (fontePlayer === "final" && player.duration > 0) return player.duration;
  return duracaoSaida();
}

function thumbSrc(tFonte){
  const n = proj.n_thumbs || 0;
  if (!n) return "";
  const idx = clamp(Math.round(tFonte / proj.duracao * (n - 1)) + 1, 1, n);
  return `/midia/thumbs/t${String(idx).padStart(4,"0")}.jpg`;
}

function desenharTimeline(){
  if (!proj) return;
  desenharRegua();
  trilhasEl.innerHTML = "";
  $("#tl-base").textContent = baseFonte()
    ? `timeline do bruto · ${fmt(proj.duracao)}`
    : `timeline do vídeo final · ${fmt(duracaoSaida())}`;
  $("#tl-dica").textContent = baseFonte()
    ? "cinza é o que sai fora do corte"
    : "clique num clipe para abrir as propriedades dele";
  $("#atalhos").innerHTML = baseFonte() ? ATALHOS_CORTE : ATALHOS_EDICAO;
  baseFonte() ? desenharPistasCorte() : desenharPistasSaida();
  posicionarCursor();
}

function desenharRegua(){
  const regua = $("#regua");
  regua.innerHTML = "";
  const dur = duracaoBase();
  if (!dur) return;
  const passoR = dur <= 20 ? 2 : dur <= 60 ? 5 : dur <= 180 ? 15 : dur <= 600 ? 30 : 60;
  for (let t = 0; t <= dur; t += passoR){
    const s = document.createElement("span");
    s.style.left = (t / dur * 100) + "%";
    s.textContent = fmt(t).replace(/,\d+$/,"");
    regua.appendChild(s);
  }
}

function novaPista(id, cfg, vazia){
  const linha = document.createElement("div");
  linha.className = "linha-pista" + (vazia ? " vazia" : "");
  linha.dataset.pista = id;
  linha.style.setProperty("--alt", (vazia ? 20 : cfg.alt) + "px");

  const rot = document.createElement("button");
  rot.className = "rot-pista";
  rot.dataset.pista = id;
  rot.textContent = cfg.rotulo;
  rot.title = `propriedades de ${cfg.rotulo}`;

  const pista = document.createElement("div");
  pista.className = "pista";
  pista.dataset.pista = id;

  linha.append(rot, pista);
  trilhasEl.appendChild(linha);
  return pista;
}

/* ---------- passo 1: o bruto, pra decidir o que fica ---------- */

function desenharPistasCorte(){
  const dur = proj.duracao;
  const pct = t => (t / dur * 100) + "%";

  // vídeo: tira de miniaturas do bruto inteiro
  const pv = novaPista("video", PISTAS.video, false);
  const faixa = document.createElement("div");
  faixa.className = "tira";
  const alvo = Math.min(proj.n_thumbs || 0, 80);
  for (let i = 0; i < alvo; i++){
    const img = new Image();
    img.src = thumbSrc(i * dur / Math.max(1, alvo - 1));
    img.loading = "lazy";
    faixa.appendChild(img);
  }
  pv.appendChild(faixa);

  const camada = document.createElement("div");
  camada.className = "camada-takes";
  camada.id = "camada-takes";
  pv.appendChild(camada);

  // áudio: forma de onda do bruto
  const pa = novaPista("audio", PISTAS.audio, false);
  const cv = document.createElement("canvas");
  cv.className = "onda"; cv.id = "onda-corte";
  pa.appendChild(cv);
  requestAnimationFrame(() => desenharOnda(cv, 0, dur));

  renderRegioes();
  cursorEm(pv.parentElement);
}

function renderRegioes(){
  const camada = $("#camada-takes");
  if (!camada) return;
  camada.innerHTML = "";
  const dur = proj.duracao;
  const pct = t => (t / dur * 100) + "%";
  const ord = [...takes].sort((a,b) => a.ini - b.ini);

  // O véu escuro cobre tudo que NÃO entra no corte final — silêncio entre
  // takes e também take desativado.
  let anterior = 0;
  for (const t of ord.filter(x => x.ativo)){
    if (t.ini > anterior + 0.02) addCortada(anterior, t.ini);
    anterior = Math.max(anterior, t.fim);
  }
  if (dur > anterior + 0.02) addCortada(anterior, dur);

  function addCortada(a, b){
    const d = document.createElement("div");
    d.className = "regiao cortada";
    d.style.left = pct(a); d.style.width = pct(b - a);
    camada.appendChild(d);
  }

  if (criando && criando.arrastou){
    const a = Math.min(criando.ini, criando.fim), b = Math.max(criando.ini, criando.fim);
    const g = document.createElement("div");
    g.className = "regiao criando";
    g.style.left = pct(a); g.style.width = pct(b - a);
    g.textContent = `+${(b - a).toFixed(1)}s`;
    camada.appendChild(g);
  }

  for (const t of ord){
    const d = document.createElement("div");
    d.className = "regiao take" + (t.ativo ? "" : " off")
                + (t.id === selecionado ? " sel" : "")
                + (t.manual ? " manual" : "");
    d.style.left = pct(t.ini);
    d.style.width = pct(t.fim - t.ini);
    d.dataset.id = t.id;
    d.title = t.texto;
    for (const borda of ["esq","dir"]){
      const a = document.createElement("div");
      a.className = "alca " + borda;
      a.dataset.id = t.id; a.dataset.borda = borda;
      d.appendChild(a);
    }
    camada.appendChild(d);
  }
}

/* ---------- passo 2: o vídeo final, camada por camada ---------- */

function desenharPistasSaida(){
  if (!plano) return;
  const dur = duracaoSaida() || 1;
  const pct = t => (t / dur * 100) + "%";

  for (const tr of plano.trilhas){
    const cfg = PISTAS[tr.id];
    if (!cfg) continue;
    const vazia = !tr.clips.length;
    const pista = novaPista(tr.id, cfg, vazia);

    if (vazia){
      const v = document.createElement("span");
      v.className = "sem-nada";
      v.textContent = tr.vazia;
      pista.appendChild(v);
      continue;
    }

    if (tr.id === "audio"){
      const cv = document.createElement("canvas");
      cv.className = "onda";
      pista.appendChild(cv);
      requestAnimationFrame(() => desenharOndaSaida(cv));
    }

    for (const c of tr.clips){
      const el = document.createElement("div");
      const largura = (c.fim - c.ini) / dur * 100;
      el.className = `clipe c-${cfg.cor}`
        + (c.kind ? ` k-${c.kind}` : "")
        + (selecao?.pista === tr.id && selecao?.clipe === c.id ? " sel" : "")
        + (largura < 1.4 ? " estreito" : "");
      el.style.left = pct(c.ini);
      el.style.width = `max(3px, ${largura}%)`;
      el.dataset.pista = tr.id;
      el.dataset.clipe = c.id;
      el.title = `${c.rotulo}\n${fmt(c.ini)} → ${fmt(c.fim)}${c.sub ? "\n" + c.sub : ""}`;

      if (tr.id === "video" && c.kind === "take"){
        const tira = document.createElement("div");
        tira.className = "tira";
        const n = clamp(Math.round((c.fim - c.ini) / 1.2), 1, 8);
        for (let i = 0; i < n; i++){
          const img = new Image();
          img.src = thumbSrc(c.fonte_ini + (c.fonte_fim - c.fonte_ini) * (i + .5) / n);
          img.loading = "lazy";
          tira.appendChild(img);
        }
        el.appendChild(tira);
      }

      const rot = document.createElement("span");
      rot.className = "rot-clipe";
      rot.textContent = c.rotulo;
      el.appendChild(rot);
      pista.appendChild(el);
    }
  }
  cursorEm(trilhasEl);
}

// Um cursor só, atravessando todas as pistas — é o que faz as camadas serem
// lidas como um instante do vídeo, e não como sete gráficos empilhados.
function cursorEm(){
  let c = $("#cursor");
  if (!c){
    c = document.createElement("div");
    c.className = "cursor"; c.id = "cursor";
  }
  trilhasEl.appendChild(c);
}

function posicionarCursor(){
  const c = $("#cursor");
  if (!c || !proj) return;
  const dur = duracaoBase() || 1;
  const t = baseFonte() ? player.currentTime : posicaoSaida();
  c.style.left = `calc(var(--rot) + (100% - var(--rot)) * ${clamp(t / dur, 0, 1)})`;
}

/* ---------- ondas ---------- */

function pico(tFonte){
  const peaks = proj?.peaks || [];
  if (!peaks.length) return 0;
  return peaks[clamp(Math.floor(tFonte / proj.duracao * peaks.length), 0, peaks.length - 1)];
}

function prepararCanvas(cv){
  const dpr = window.devicePixelRatio || 1;
  const larg = cv.clientWidth, alt = cv.clientHeight;
  if (!larg || !alt) return null;
  cv.width = larg * dpr; cv.height = alt * dpr;
  const ctx = cv.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0,0,larg,alt);
  const grad = ctx.createLinearGradient(0,0,larg,0);
  grad.addColorStop(0, "#D23089");
  grad.addColorStop(1, "#EE8656");
  ctx.strokeStyle = grad;
  ctx.lineWidth = 1;
  return {ctx, larg, alt};
}

function desenharOnda(cv, de, ate){
  const c = prepararCanvas(cv);
  if (!c) return;
  const {ctx, larg, alt} = c, meio = alt / 2;
  ctx.beginPath();
  for (let x = 0; x < larg; x++){
    const h = Math.max(0.6, pico(de + (ate - de) * x / larg) * (alt/2 - 2));
    ctx.moveTo(x + .5, meio - h); ctx.lineTo(x + .5, meio + h);
  }
  ctx.stroke();
}

// A onda do passo 2 é a MESMA amostragem, reposicionada: cada pixel pergunta
// "que instante do bruto toca aqui?" e busca o pico lá. Assim a onda encosta
// nos cortes em vez de ignorar que eles existem.
function desenharOndaSaida(cv){
  const c = prepararCanvas(cv);
  if (!c) return;
  const {ctx, larg, alt} = c, meio = alt / 2, dur = duracaoSaida();
  ctx.beginPath();
  for (let x = 0; x < larg; x++){
    const f = fonteDe(dur * x / larg);
    const h = f === null ? 0.6 : Math.max(0.6, pico(f) * (alt/2 - 2));
    ctx.moveTo(x + .5, meio - h); ctx.lineTo(x + .5, meio + h);
  }
  ctx.stroke();
}

const ATALHOS_CORTE = `
  <kbd>espaço</kbd> play/pause
  <kbd>←</kbd><kbd>→</kbd> frame a frame
  <kbd>shift</kbd>+setas 1s
  <kbd>S</kbd> divide no cursor
  <kbd>delete</kbd> tira do corte
  <kbd>ctrl</kbd>+<kbd>Z</kbd> desfaz
  <span><b>arraste numa área vazia para criar um take</b></span>
  <span>arraste as bordas para ajustar · duplo-clique = reset</span>`;

const ATALHOS_EDICAO = `
  <kbd>espaço</kbd> play/pause
  <kbd>←</kbd><kbd>→</kbd> frame a frame
  <kbd>esc</kbd> volta às propriedades do projeto
  <span>cada pista mostra o que vai estar no arquivo — clique para editar</span>`;

/* ---------------- clique na timeline ---------------- */

function tempoDoEvento(e, pista){
  const r = pista.getBoundingClientRect();
  return clamp((e.clientX - r.left) / r.width, 0, 1) * duracaoBase();
}

trilhasEl.addEventListener("mousedown", (e) => {
  const pista = e.target.closest(".pista");
  if (!pista) return;

  if (!baseFonte()){
    const cl = e.target.closest(".clipe");
    if (cl){
      selecionarClipe(cl.dataset.pista, cl.dataset.clipe);
      const c = clipePorId(cl.dataset.pista, cl.dataset.clipe);
      if (c) irParaSaida(c.ini + 0.01);
      return;
    }
    irParaSaida(tempoDoEvento(e, pista));
    return;
  }

  // ----- passo 1 -----
  const alca = e.target.closest(".alca");
  if (alca){
    fotografar(`ajuste da borda do take #${alca.dataset.id}`);
    arrasto = { id: +alca.dataset.id, borda: alca.dataset.borda, pista };
    selecionado = arrasto.id;
    e.preventDefault();
    return;
  }
  const reg = e.target.closest(".regiao.take");
  const t = tempoDoEvento(e, pista);
  if (reg) selecionado = +reg.dataset.id;
  else criando = { ini: t, fim: t, arrastou: false, pista };

  tregua = !takeEm(t);
  irPara(t);
  renderTudo();
});

window.addEventListener("mousemove", (e) => {
  if (criando){
    const t = tempoDoEvento(e, criando.pista);
    if (Math.abs(t - criando.ini) > 0.05) criando.arrastou = true;
    criando.fim = t;
    renderRegioes();
    return;
  }
  if (!arrasto) return;
  const t = takes.find(x => x.id === arrasto.id);
  const novo = tempoDoEvento(e, arrasto.pista);
  const ord = [...takes].sort((a,b) => a.ini - b.ini);
  const i = ord.indexOf(t);
  const antes = ord[i-1], depois = ord[i+1];
  const MIN = 0.08;
  if (arrasto.borda === "esq") t.ini = Math.max(antes ? antes.fim : 0, Math.min(novo, t.fim - MIN));
  else t.fim = Math.min(depois ? depois.ini : proj.duracao, Math.max(novo, t.ini + MIN));
  renderRegioes(); atualizarStatus();
});

window.addEventListener("mouseup", () => {
  if (criando){
    const { ini, fim, arrastou } = criando;
    criando = null;
    if (arrastou) criarTake(Math.min(ini, fim), Math.max(ini, fim));
    else renderRegioes();
  }
  if (arrasto){ arrasto = null; renderTudo(); commit(); }
});

trilhasEl.addEventListener("dblclick", (e) => {
  const reg = e.target.closest(".regiao.take");
  if (!reg) return;
  const t = takes.find(x => x.id === +reg.dataset.id);
  fotografar(`reset do take #${t.id}`);
  t.ini = t.ini_orig; t.fim = t.fim_orig; t.ativo = true;
  renderTudo(); commit();
  avisar(`take #${t.id} voltou ao original`);
});

trilhasEl.addEventListener("click", (e) => {
  const rot = e.target.closest(".rot-pista");
  if (rot && !baseFonte()) selecionarClipe(rot.dataset.pista, null);
});

function clipePorId(pista, id){
  return plano?.trilhas.find(t => t.id === pista)?.clips.find(c => c.id === id) || null;
}

function selecionarClipe(pista, clipe){
  selecao = { pista, clipe };
  desenharTimeline();
  pintarInspetor();
}

/* ================================================================
   PLAYER
   ================================================================ */

let fontePlayer = "previa";

function irPara(t){
  player.currentTime = clamp(t, 0, proj.duracao - 0.01);
}

function irParaSaida(t){
  if (fontePlayer === "final"){
    player.currentTime = clamp(t, 0, (player.duration || duracaoSaida()) - 0.01);
    return;
  }
  const f = fonteDe(t);
  if (f === null){
    // o card de encerramento não existe na prévia: encosta no último quadro
    const u = ativos().at(-1);
    if (u) irPara(u.fim - 0.05);
    avisar("o card de encerramento só aparece no arquivo renderizado");
    return;
  }
  tregua = false;
  irPara(f);
}

// Onde o player está, sempre em segundos do VÍDEO FINAL — não importa se o
// que toca é a prévia ou o arquivo. É esse número que a timeline e o relógio
// usam, e é por isso que os dois pararam de discordar.
function posicaoSaida(){
  if (!proj) return 0;
  return fontePlayer === "final" ? player.currentTime : saidaDe(player.currentTime);
}

const takeEm = (t) => ativos().find(x => t >= x.ini - 0.001 && t < x.fim);
const proximoTake = (t) => ativos().find(x => x.ini > t - 0.001);

function laco(){
  if (proj){
    posicionarCursor();
    $("#t-atual").textContent = fmt(posicaoSaida());

    if (fontePlayer === "previa"){
      const t = player.currentTime;
      const dentro = takeEm(t);
      if (dentro) tregua = false;
      if ($("#pular-cortes").checked && !player.paused && !tregua && !dentro){
        const prox = proximoTake(t);
        if (prox) player.currentTime = prox.ini;
        else player.pause();
      }
      atualizarSobreposicoes(t);
    }
  }
  requestAnimationFrame(laco);
}

/* Prévia de legenda e headline sobre o player.
 *
 * A legenda desenha os MESMOS blocos do plano (que vêm do mesmo código que
 * escreve o .ass), traduzidos de volta pro tempo do bruto. Enquanto ela era
 * recalculada aqui com uma regra própria, a prévia mostrava um agrupamento e
 * o arquivo saía com outro. */
function atualizarSobreposicoes(tFonte){
  const ts = saidaDe(tFonte);
  const dentro = !!takeEm(tFonte);

  const hl = plano?.trilhas.find(t => t.id === "headline")?.clips[0];
  if (hl && dentro && ts >= hl.ini && ts <= hl.fim){
    headlineEl.className = "headline-prev on hl-" + (estilo.headline_estilo || "contorno");
    headlineEl.innerHTML = (estilo.headline || "").split("\n")
      .filter(Boolean).map(l => `<span>${esc(l.toUpperCase())}</span>`).join("");
  } else headlineEl.className = "headline-prev";

  const blocos = plano?.trilhas.find(t => t.id === "legenda")?.clips || [];
  const b = dentro ? blocos.find(c => ts >= c.ini && ts <= c.fim) : null;
  if (!b){ legendaEl.innerHTML = ""; legendaEl.className = "legenda"; return; }

  const cx = s => estilo.caixa === "maiuscula" ? s.toUpperCase() : s.toLowerCase();
  legendaEl.style.setProperty("--realce", estilo.cor);
  legendaEl.className = "legenda leg-" + b.sub;
  // `realce` vem marcado no plano: a prévia destaca exatamente a palavra que o
  // arquivo vai destacar, em vez de aplicar uma segunda regra aqui.
  legendaEl.innerHTML = (b.palavras || []).map(w =>
    w.realce ? `<b>${esc(cx(w.t))}</b>` : esc(cx(w.t))).join(" ");
}

$("#btn-play").addEventListener("click", () => player.paused ? player.play() : player.pause());
$("#btn-inicio").addEventListener("click", () => {
  tregua = false;
  fontePlayer === "final" ? (player.currentTime = 0) : irPara(ativos()[0]?.ini ?? 0);
});
player.addEventListener("play",  () => $("#btn-play").textContent = "❚❚");
player.addEventListener("pause", () => $("#btn-play").textContent = "▶");

$("#fonte-player").addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (b && !b.disabled) trocarFontePlayer(b.dataset.fonte);
});

function trocarFontePlayer(qual){
  const info = recursos.final || {};
  if (qual === "final" && !info.existe) return;
  if (qual === fontePlayer) return;
  const ts = posicaoSaida();
  fontePlayer = qual;
  document.body.dataset.fonte = qual;
  $$("#fonte-player button").forEach(b => b.classList.toggle("sel", b.dataset.fonte === qual));
  $("#cx-pular").classList.toggle("escondido", qual === "final");
  $("#selo-player").textContent = qual === "final" ? "arquivo renderizado" : "prévia do corte";

  if (qual === "final"){
    player.src = info.url;
    legendaEl.innerHTML = ""; headlineEl.className = "headline-prev";
    player.addEventListener("loadeddata", () => { player.currentTime = clamp(ts, 0, player.duration - .05); }, {once:true});
  } else {
    player.src = "/midia/fonte";
    player.addEventListener("loadeddata", () => { irParaSaida(ts); }, {once:true});
  }
}

function atualizarAvisoFinal(){
  const info = recursos.final || {};
  const btn = $('#fonte-player button[data-fonte="final"]');
  const el = $("#aviso-final");
  btn.disabled = !info.existe;
  if (!info.existe){
    btn.title = "ainda não renderizado";
    el.textContent = ""; el.className = "aviso-inline";
  } else if (info.desatualizado){
    btn.title = "renderizado antes da última mudança";
    el.textContent = "⚠ o render está atrasado em relação à edição";
    el.className = "aviso-inline alerta";
  } else {
    btn.title = "o arquivo que saiu do render";
    el.textContent = "✓ render em dia";
    el.className = "aviso-inline ok";
  }
  if (!info.existe && fontePlayer === "final") trocarFontePlayer("previa");
}

/* ================================================================
   PASSOS
   ================================================================ */

const PROXIMO = { corte: "edicao", edicao: "entrega" };
const ROTULO_AVANCAR = {
  corte:  "Ir para a Edição →",
  edicao: "Ir para a Entrega →",
  entrega:"Renderizar o MP4",
};

function irParaPasso(p){
  passo = p;
  document.body.dataset.passo = p;
  $$(".passo").forEach(b => b.classList.toggle("ativo", b.dataset.passo === p));
  $("#btn-avancar").textContent = ROTULO_AVANCAR[p];
  $("#btn-avancar").classList.toggle("primario", true);
  selecao = null;
  desenharTimeline();
  if (p === "edicao") pintarInspetor();
  if (p === "entrega") pintarEntrega();
  if (proj && proj.fase !== p){ proj.fase = p; commit(); }
}

$$(".passo").forEach(b => b.addEventListener("click", () => irParaPasso(b.dataset.passo)));
$("#btn-avancar").addEventListener("click", () => {
  if (passo === "entrega") return renderizarMp4();
  irParaPasso(PROXIMO[passo]);
});

/* ================================================================
   ESTILO — agora sem aba própria: cada opção mora no inspetor da
   camada que ela afeta.
   ================================================================ */

// O padrão vive em pipeline/plano.py e chega pronto no /api/projeto. Aqui só
// existe o objeto vazio pro caso de o carregamento falhar antes da resposta.
let estilo = {};

const NOMES = {
  limpa:"tela limpa", dividida:"dividida (apoio em cima)", dividida2:"dividida (apoio embaixo)",
  contorno:"headline contorno", caixa:"headline em caixa", nenhuma:"sem headline",
  "ili-frase":"legenda em frase", "ili-palavra":"legenda palavra a palavra",
  "ili-bloco":"legenda em bloco",
};

function resumoCurto(){
  const l = [];
  if (estilo.zoom_animado) l.push("zoom in/out");
  else if (estilo.zoom) l.push("punch-in");
  if (estilo.flash) l.push("flash");
  if (estilo.trilha) l.push("trilha");
  if (estilo.broll) l.push("b-roll");
  return `${NOMES[estilo.tipo]} · ${estilo.legenda === "nenhuma" ? "sem legenda" : NOMES[estilo.legenda]}`
       + (l.length ? ` · ${l.join(", ")}` : "");
}

function aplicarCorNaTela(){
  document.documentElement.style.setProperty("--cor-destaque", estilo.cor);
  document.documentElement.style.setProperty("--altura-legenda",
    (estilo.altura_legenda * 100) + "%");
}

function mudarEstilo(patch, rotulo){
  if (rotulo) fotografar(rotulo);
  Object.assign(estilo, patch);
  aplicarCorNaTela();
  commit();
  pintarInspetor();
}

/* ================================================================
   INSPETOR
   ================================================================ */

function op(valor, atual, rotulo, sub=""){
  return `<button class="op${valor === atual ? " sel" : ""}" data-v="${esc(valor)}">
    <b>${esc(rotulo)}</b>${sub ? `<small>${esc(sub)}</small>` : ""}</button>`;
}

function grupo(titulo, corpo){
  return `<div class="insp-grupo"><label>${esc(titulo)}</label>${corpo}</div>`;
}

function toggle(id, ligado, rotulo, sub, {desligado=false, alerta=""}={}){
  return `<label class="tg${desligado ? " desligado" : ""}${alerta ? " com-alerta" : ""}">
    <input type="checkbox" data-tg="${id}" ${ligado ? "checked" : ""} ${desligado ? "disabled" : ""}>
    <span><b>${esc(rotulo)}</b><small>${esc(sub)}</small>
    ${alerta ? `<i class="mini-alerta">${esc(alerta)}</i>` : ""}</span></label>`;
}

function pintarInspetor(){
  const alvo = $("#inspetor");
  if (!alvo || passo !== "edicao") return;
  const p = selecao?.pista || "projeto";
  const clipe = selecao?.clipe ? clipePorId(selecao.pista, selecao.clipe) : null;

  const titulos = {
    projeto: ["Projeto", "vale pro vídeo inteiro"],
    headline: ["Headline", "o texto fixo no topo"],
    legenda: ["Legenda", "o que aparece embaixo, palavra por palavra"],
    broll:   ["B-roll", "imagem de apoio na outra metade"],
    motion:  ["Motion", "zoom e efeito nos cortes"],
    video:   ["Vídeo", "os takes emendados"],
    audio:   ["Áudio", "a voz gravada"],
    trilha:  ["Trilha", "música por baixo, com ducking"],
  };
  $("#insp-titulo").textContent = titulos[p][0];
  $("#insp-sub").textContent = clipe
    ? `${fmt(clipe.ini)} → ${fmt(clipe.fim)} · ${clipe.sub || ""}`
    : titulos[p][1];

  alvo.innerHTML = (
    p === "headline" ? inspHeadline(clipe) :
    p === "legenda"  ? inspLegenda(clipe) :
    p === "broll"    ? inspBroll() :
    p === "motion"   ? inspMotion(clipe) :
    p === "video"    ? inspVideo(clipe) :
    p === "audio"    ? inspAudio() :
    p === "trilha"   ? inspTrilha() :
                       inspProjeto()
  ) + botaoVoltar(p);

  ligarInspetor();
}

const botaoVoltar = (p) => p === "projeto" ? "" :
  `<button class="btn mini-btn largo" data-acao="voltar-projeto">← propriedades do projeto</button>`;

function inspProjeto(){
  return grupo("Tipo de edição", `<div class="ops" data-campo="tipo">
      ${op("limpa", estilo.tipo, "Limpa", "só a imagem")}
      ${op("dividida", estilo.tipo, "Dividida", "apoio em cima")}
      ${op("dividida2", estilo.tipo, "Dividida 2", "apoio embaixo")}
    </div>`)
  + grupo("Cor de destaque", `
      <div class="linha-cor">
        <input type="color" id="cor-destaque" value="${estilo.cor}">
        <input type="text" id="cor-hex" class="campo campo-hex" value="${estilo.cor.toUpperCase()}"
          spellcheck="false" placeholder="#RRGGBB">
      </div>
      <div class="swatches">
        ${["#EE8656","#D23089","#EF1F92","#00FF91","#FFD400","#FFFFFF"]
          .map(c => `<button class="sw${c.toLowerCase()===estilo.cor.toLowerCase()?" sel":""}"
             style="--c:${c}" data-cor="${c}" title="${c}"></button>`).join("")}
      </div>`)
  + grupo("Tratamento de cor", toggle("cor_look", estilo.cor_look, "Colorização ili",
      "dessaturado, sombras levantadas")
    + `<select id="lut" class="campo campo-sel">
        <option value="">sem LUT</option>
        ${(recursos.luts||[]).map(n =>
          `<option value="${esc(n)}"${n===estilo.lut?" selected":""}>${esc(n)}</option>`).join("")}
      </select>
      <p class="ajuda">${(recursos.luts||[]).length
        ? `${recursos.luts.length} LUTs disponíveis`
        : "coloque .cube em editor-ia/luts"}</p>`)
  + grupo("Card de encerramento",
      toggle("encerramento", estilo.encerramento, "Fechar com o card",
        recursos.encerramento ? `${recursos.encerramento} · +${plano?.dur_encerramento || 2.5}s`
                              : "nenhum card encontrado na pasta",
        {desligado: !recursos.encerramento}))
  + grupo("Anotações", `<textarea id="obs" class="campo" rows="2"
      placeholder="lembretes pra você — não entram no vídeo">${esc(estilo.observacoes||"")}</textarea>`);
}

function inspHeadline(){
  return grupo("Texto", `<textarea id="headline" class="campo" rows="3"
      placeholder="uma linha por linha da headline">${esc(estilo.headline||"")}</textarea>
    <button class="btn mini-btn largo" data-acao="sugerir-hl">sugerir a partir do 1º take</button>`)
  + grupo("Estilo", `<div class="ops" data-campo="headline_estilo">
      ${op("contorno", estilo.headline_estilo, "Contorno", "texto vazado")}
      ${op("caixa", estilo.headline_estilo, "Caixa", "fundo escuro atrás")}
      ${op("nenhuma", estilo.headline_estilo, "Nenhuma", "sem headline")}
    </div>`)
  + (estilo.headline_estilo === "nenhuma" && (estilo.headline||"").trim()
     ? `<p class="ajuda alerta-inline">o texto está escrito mas o estilo é
        “nenhuma” — nada vai aparecer no vídeo.</p>` : "");
}

function inspLegenda(clipe){
  return (clipe ? grupo("Este bloco", `<div class="clipe-info">
      <p>“${esc(clipe.rotulo)}”</p>
      <span>${fmt(clipe.ini)} → ${fmt(clipe.fim)} · ${(clipe.fim-clipe.ini).toFixed(2)}s</span>
    </div>
    <p class="ajuda">O agrupamento vem da fala e do estilo. Pra mudar onde este
      bloco começa, ajuste o take no passo 1.</p>`) : "")
  + grupo("Estilo", `<div class="ops" data-campo="legenda">
      ${op("ili-frase", estilo.legenda, "Frase", "3 palavras, uma realçada")}
      ${op("ili-palavra", estilo.legenda, "Palavra", "uma por vez, ritmo rápido")}
      ${op("ili-bloco", estilo.legenda, "Bloco", "duas linhas, leitura calma")}
      ${op("nenhuma", estilo.legenda, "Nenhuma", "sem legenda")}
    </div>`)
  + grupo("Caixa", `<div class="ops" data-campo="caixa">
      ${op("minuscula", estilo.caixa, "minúscula")}
      ${op("maiuscula", estilo.caixa, "MAIÚSCULA")}
    </div>`)
  + grupo("Altura na tela", `<div class="linha-radio">
      <input type="range" id="altura-legenda" class="faixa" min="0.10" max="0.40"
        step="0.01" value="${estilo.altura_legenda}">
      <b class="mini">${Math.round(estilo.altura_legenda*100)}%</b>
    </div>
    <p class="ajuda">abaixo de 20% a legenda briga com a interface do Instagram</p>`);
}

function inspBroll(){
  const refs = recursos.referencias || [];
  const dividido = estilo.tipo !== "limpa";
  return grupo("B-roll", toggle("broll", estilo.broll, "Usar imagem de apoio",
      refs.length ? `${refs.length} imagem(ns) na pasta, alternando por take`
                  : "nenhuma imagem na pasta do projeto",
      {desligado: !refs.length,
       alerta: estilo.broll && !dividido ? "precisa de tela dividida" : ""}))
  + (refs.length ? grupo("Imagens encontradas",
      `<ul class="lista-arq">${refs.map(n => `<li>${esc(n)}</li>`).join("")}</ul>`)
    : `<p class="ajuda">Salve <code>ref1.png</code>, <code>ref2.jpg</code>… na pasta
       do projeto e elas aparecem aqui.</p>`)
  + grupo("Onde entra", `<div class="ops" data-campo="tipo">
      ${op("limpa", estilo.tipo, "Não usar", "tela limpa")}
      ${op("dividida", estilo.tipo, "Metade de cima")}
      ${op("dividida2", estilo.tipo, "Metade de baixo")}
    </div>`);
}

function inspMotion(clipe){
  const zoomAtual = estilo.zoom_animado ? "animado" : estilo.zoom ? "punch" : "nenhum";
  return (clipe ? grupo("Este efeito", `<div class="clipe-info">
      <p>${esc(clipe.rotulo)}</p><span>${fmt(clipe.ini)} → ${fmt(clipe.fim)}</span></div>`) : "")
  // Eram dois checkboxes que se desligavam sozinhos quando você marcava o
  // outro — o comportamento estava certo e a interface mentia sobre ele.
  // Escolha única resolve na forma, não na regra.
  + grupo("Movimento", `<div class="ops empilhado" data-campo="zoom3">
      ${op("nenhum", zoomAtual, "Nenhum", "câmera parada")}
      ${op("punch", zoomAtual, "Punch-in", "um take sim, outro não — escala fixa")}
      ${op("animado", zoomAtual, "Zoom in/out", "a escala se move, alternando o sentido")}
    </div>`)
  + grupo("Transição", toggle("flash", estilo.flash, "Flash na emenda",
      "um clarão curto em cada corte, a partir do segundo take"));
}

function inspVideo(clipe){
  if (clipe?.kind === "encerramento"){
    return grupo("Card de encerramento", `<div class="clipe-info">
        <p>${esc(clipe.rotulo)}</p>
        <span>entra depois da fala, sem legenda em cima</span></div>`)
      + grupo("", toggle("encerramento", estilo.encerramento, "Fechar com o card",
          recursos.encerramento || "nenhum card na pasta",
          {desligado: !recursos.encerramento}));
  }
  return (clipe ? grupo("Este take", `<div class="clipe-info">
      <p>“${esc(clipe.rotulo)}”</p>
      <span>${clipe.sub} · no bruto ${fmt(clipe.fonte_ini)} → ${fmt(clipe.fonte_fim)}</span>
    </div>
    <button class="btn mini-btn largo" data-acao="editar-take" data-id="${clipe.take_id}">
      ajustar este take no passo 1
    </button>`) : "")
  + grupo("Composição", `<div class="ops" data-campo="tipo">
      ${op("limpa", estilo.tipo, "Limpa")}
      ${op("dividida", estilo.tipo, "Dividida")}
      ${op("dividida2", estilo.tipo, "Dividida 2")}
    </div>`)
  + `<p class="ajuda">Os cortes são decididos no passo 1. Aqui a timeline mostra
     como eles ficaram emendados no arquivo final.</p>`;
}

function inspAudio(){
  return `<p class="ajuda">A voz vem dos takes, com fade de 30ms em cada emenda —
    sem ele o corte estala. Para mudar o que é falado, volte ao passo 1.</p>`
  + grupo("Trilha por baixo", toggle("trilha", estilo.trilha, "Usar trilha",
      recursos.trilha || "nenhuma trilha na pasta do projeto",
      {desligado: !recursos.trilha}));
}

function inspTrilha(){
  return grupo("Trilha", toggle("trilha", estilo.trilha, "Usar trilha",
      recursos.trilha ? `${recursos.trilha} · em loop, cortada no fim do vídeo`
                      : "nenhuma trilha na pasta do projeto",
      {desligado: !recursos.trilha}))
  + (recursos.trilha
     ? `<p class="ajuda">A mistura usa ducking de verdade: a música abaixa
        ~9 dB enquanto alguém fala e sobe sozinha no silêncio.</p>`
     : `<p class="ajuda">Salve <code>trilha.mp3</code> (ou .m4a/.wav) na pasta do
        projeto e ela aparece aqui.</p>`);
}

function ligarInspetor(){
  const alvo = $("#inspetor");

  alvo.querySelectorAll(".ops").forEach(box => {
    box.addEventListener("click", e => {
      const b = e.target.closest(".op");
      if (!b) return;
      const campo = box.dataset.campo, v = b.dataset.v;
      if (campo === "zoom3"){
        mudarEstilo({ zoom: v === "punch", zoom_animado: v === "animado" }, "movimento");
      } else {
        mudarEstilo({ [campo]: v }, campo);
      }
    });
  });

  alvo.querySelectorAll("[data-tg]").forEach(cx =>
    cx.addEventListener("change", () =>
      mudarEstilo({ [cx.dataset.tg]: cx.checked }, cx.dataset.tg)));

  alvo.querySelectorAll(".sw").forEach(b =>
    b.addEventListener("click", () => mudarEstilo({ cor: b.dataset.cor }, "cor")));

  const cor = alvo.querySelector("#cor-destaque");
  if (cor) cor.addEventListener("input", e => {
    estilo.cor = e.target.value; aplicarCorNaTela();
    const hex = alvo.querySelector("#cor-hex"); if (hex) hex.value = e.target.value.toUpperCase();
    commit();
  });
  const hex = alvo.querySelector("#cor-hex");
  if (hex) hex.addEventListener("change", e => {
    const v = e.target.value.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) mudarEstilo({ cor: v }, "cor");
    else { e.target.value = estilo.cor.toUpperCase(); avisar("cor inválida — use #RRGGBB", true); }
  });

  const lut = alvo.querySelector("#lut");
  if (lut) lut.addEventListener("change", e => mudarEstilo({ lut: e.target.value }, "LUT"));

  const hl = alvo.querySelector("#headline");
  if (hl) hl.addEventListener("input", () => {
    estilo.headline = hl.value;      // sem repintar: repintar rouba o cursor
    commit();
  });

  const obs = alvo.querySelector("#obs");
  if (obs) obs.addEventListener("input", () => { estilo.observacoes = obs.value; commit(); });

  const alt = alvo.querySelector("#altura-legenda");
  if (alt) alt.addEventListener("input", e => {
    estilo.altura_legenda = +e.target.value;
    aplicarCorNaTela();
    e.target.nextElementSibling.textContent = Math.round(estilo.altura_legenda*100) + "%";
    commit();
  });

  alvo.querySelectorAll("[data-acao]").forEach(b =>
    b.addEventListener("click", () => {
      const a = b.dataset.acao;
      if (a === "voltar-projeto"){ selecao = null; desenharTimeline(); pintarInspetor(); }
      if (a === "sugerir-hl") sugerirHeadline();
      if (a === "editar-take"){
        selecionado = +b.dataset.id;
        irParaPasso("corte");
        const t = takes.find(x => x.id === selecionado);
        if (t) irPara(t.ini);
        renderTudo();
      }
    }));
}

function sugerirHeadline(){
  const primeiro = ativos()[0];
  if (!primeiro) return avisar("nenhum take ativo", true);
  const palavras = (primeiro.texto||"").replace(/[.,!?;:]/g, "").split(/\s+/).filter(Boolean);
  const corte = Math.min(Math.ceil(palavras.length / 2), 4);
  mudarEstilo({
    headline: palavras.slice(0, corte).join(" ") + "\n"
            + palavras.slice(corte, corte + 4).join(" "),
    headline_estilo: estilo.headline_estilo === "nenhuma" ? "contorno" : estilo.headline_estilo,
  }, "sugerir headline");
  avisar("headline sugerida a partir do primeiro take — edite à vontade");
}

/* ================================================================
   ENTREGA
   ================================================================ */

function pintarEntrega(){
  // Enquanto não há arquivo, a duração é previsão. Depois que há, é medida —
  // e as duas não batem exatamente: o corte acontece na fronteira do quadro.
  const real = recursos.final?.duracao;
  const emDia = recursos.final?.existe && !recursos.final?.desatualizado;
  const dur = emDia && real
    ? `<b>${fmt(real)}</b> de vídeo <small>(medido no arquivo)</small>`
    : `<b>${fmt(duracaoSaida())}</b> de vídeo <small>(previsto)</small>`;
  $("#resumo-entrega").innerHTML =
    `${dur} · ${esc(resumoCurto())}`
    + (estilo.headline?.trim() && estilo.headline_estilo !== "nenhuma"
       ? ` · headline “${esc(estilo.headline.split("\n")[0])}”` : "")
    + ` · destaque <b>${esc(estilo.cor.toUpperCase())}</b>`;

  // Os alertas vêm do plano, calculado do mesmo jeito que o render decide.
  // É aqui que "liguei b-roll e não há imagem" para de sair calado.
  const box = $("#alertas-entrega");
  const as = plano?.alertas || [];
  box.innerHTML = as.map(a => `<div class="alerta n-${a.nivel}">
      <b>${a.nivel === "info" ? "i" : "!"}</b>
      <span>${esc(a.texto)}${a.acao ? `<small>${esc(a.acao)}</small>` : ""}</span>
    </div>`).join("");

  const ul = $("#saidas");
  const saidas = recursos.saidas || [];
  ul.innerHTML = saidas.length ? saidas.map(s => `<li class="${s.desatualizado?"velho":"ok"}">
      <div><b>${esc(s.arquivo)}</b><small>${esc(s.oque)}</small></div>
      <span>${s.desatualizado ? "desatualizado" : "em dia"}</span>
    </li>`).join("")
    : `<li class="vazio"><div><b>nada gerado ainda</b>
       <small>o botão acima cria os arquivos nesta pasta</small></div></li>`;
}

async function exportar(formatos, txt){
  // Salva ANTES de pedir o render. O servidor lê o estilo do edl.json, então
  // esta espera é o que garante que o arquivo sai com o que está na tela.
  await garantirSalvo();
  trabalhando(true, txt);
  try{
    const r = await fetch("/api/exportar", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ formatos }),
    });
    const j = await r.json();
    if (j.erro) avisar("erro: " + j.erro, true);
    else {
      recursos = j.recursos || recursos;
      await recarregarPlano();
      pintarEntrega();
      avisar("gerado: " + j.arquivos.join(", "));
      if (j.arquivos.includes("final.mp4")){
        fontePlayer = "previa";
        trocarFontePlayer("final");
      }
    }
  } catch(err){ avisar("falhou: " + err.message, true); }
  trabalhando(false);
}

const renderizarMp4 = () => exportar(["mp4"], "renderizando o MP4…");
$("#btn-mp4").addEventListener("click", renderizarMp4);
$("#btn-premiere").addEventListener("click", () => exportar(["xml","srt"], "gerando a sequência…"));
$("#btn-pasta2").addEventListener("click", () => fetch("/api/abrir-pasta", {method:"POST"}));

/* ================================================================
   PASSO 1 — lista de takes e edição do corte
   ================================================================ */

function renderLista(){
  listaEl.innerHTML = "";
  for (const t of [...takes].sort((a,b) => a.ini - b.ini)){
    const li = document.createElement("li");
    li.className = "item-take" + (t.ativo ? "" : " off")
                 + (t.id === selecionado ? " atual" : "")
                 + (t.continua ? " emenda" : "")
                 + (t.manual ? " manual-item" : "");
    li.dataset.id = t.id;

    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = t.ativo;
    cb.addEventListener("click", (e) => {
      e.stopPropagation();
      fotografar(`take #${t.id} ${cb.checked ? "de volta" : "fora"}`);
      t.ativo = cb.checked;
      renderTudo(); commit();
    });

    const motivo = t.motivo
      ? `<span class="motivo${t.ativo ? " bom" : ""}">${esc(t.motivo)}</span>` : "";
    const txt = document.createElement("div");
    txt.innerHTML = `<span class="txt">${esc(t.texto)}</span>
      <span class="meta">#${t.id} · ${fmt(t.ini)} → ${fmt(t.fim)} · ${(t.fim-t.ini).toFixed(2)}s</span>
      ${motivo}`;

    // Botões explícitos: atalho é conveniência, não pode ser o único caminho.
    const acoes = document.createElement("div");
    acoes.className = "acoes-take";
    const bTirar = document.createElement("button");
    bTirar.className = "btn-take";
    bTirar.textContent = t.ativo ? "tirar" : "voltar";
    bTirar.addEventListener("click", (e) => {
      e.stopPropagation();
      fotografar(`take #${t.id} ${t.ativo ? "fora" : "de volta"}`);
      t.ativo = !t.ativo;
      renderTudo(); commit();
      avisar(t.ativo ? `take #${t.id} de volta` : `take #${t.id} fora do corte`);
    });
    acoes.appendChild(bTirar);

    if (t.manual){
      const bApagar = document.createElement("button");
      bApagar.className = "btn-take perigo";
      bApagar.textContent = "apagar";
      bApagar.addEventListener("click", (e) => {
        e.stopPropagation(); selecionado = t.id; apagarTake();
      });
      acoes.appendChild(bApagar);
    }

    li.append(cb, txt, acoes);
    li.addEventListener("click", () => { selecionado = t.id; irPara(t.ini); renderTudo(); });
    listaEl.appendChild(li);
  }
}

function renderTudo(){
  if (baseFonte()) renderRegioes();
  renderLista();
  atualizarStatus();
}

const DUR_MIN = 0.15;

function palavrasNoIntervalo(a, b){
  return takes.flatMap(t => t.palavras || [])
    .filter(w => w.fim > a && w.ini < b)
    .sort((x, y) => x.ini - y.ini);
}

const novoId = () => takes.reduce((m, t) => Math.max(m, t.id), 0) + 1;

function criarTake(a, b){
  a = Math.max(0, a); b = Math.min(proj.duracao, b);
  if (b - a < DUR_MIN) return avisar("trecho curto demais", true);
  for (const t of takes){
    if (a < t.fim && b > t.ini){
      if (a >= t.ini && b <= t.fim) return avisar("já existe take aqui", true);
      if (a < t.ini) b = Math.min(b, t.ini); else a = Math.max(a, t.fim);
    }
  }
  if (b - a < DUR_MIN) return avisar("não coube entre os takes vizinhos", true);
  const ps = palavrasNoIntervalo(a, b);
  const t = {
    id: novoId(), ini: +a.toFixed(3), fim: +b.toFixed(3),
    ini_orig: +a.toFixed(3), fim_orig: +b.toFixed(3),
    texto: ps.map(w => w.t).join(" ") || "(trecho sem fala)",
    ativo: true, manual: true, palavras: ps,
  };
  fotografar("criar take");
  takes.push(t);
  selecionado = t.id;
  renderTudo(); commit();
  avisar(`take #${t.id} criado (${(b - a).toFixed(2)}s)`);
}

function dividirTake(){
  const corte = player.currentTime;
  const t = takes.find(x => corte >= x.ini && corte < x.fim);
  if (!t) return avisar("posicione o cursor dentro de um take", true);
  if (corte - t.ini < DUR_MIN || t.fim - corte < DUR_MIN)
    return avisar("corte perto demais da borda", true);
  fotografar(`dividir take #${t.id}`);
  const direita = {
    id: novoId(), ini: +corte.toFixed(3), fim: t.fim,
    ini_orig: +corte.toFixed(3), fim_orig: t.fim,
    texto: "", ativo: t.ativo, manual: true,
    palavras: (t.palavras || []).filter(w => w.ini >= corte),
  };
  direita.texto = direita.palavras.map(w => w.t).join(" ") || "(trecho sem fala)";
  t.fim = +corte.toFixed(3); t.fim_orig = t.fim;
  t.palavras = (t.palavras || []).filter(w => w.ini < corte);
  t.texto = t.palavras.map(w => w.t).join(" ") || "(trecho sem fala)";
  takes.push(direita);
  selecionado = direita.id;
  renderTudo(); commit();
  avisar(`take dividido em #${t.id} e #${direita.id}`);
}

function apagarTake(){
  if (selecionado == null) return;
  const t = takes.find(x => x.id === selecionado);
  if (!t?.manual) return avisar("só dá pra apagar take criado à mão — use delete para tirar do corte", true);
  fotografar(`apagar take #${t.id}`);
  takes = takes.filter(x => x.id !== t.id);
  proj.takes = takes;
  selecionado = null;
  renderTudo(); commit();
  avisar(`take #${t.id} apagado`);
}

/* ---------------- atalhos ---------------- */

document.addEventListener("keydown", (e) => {
  if (e.target.matches?.("input[type=text], input[type=number], textarea, select")) return;
  if (passo === "entrega" && e.code !== "Space") return;

  if (e.code === "Space"){
    e.preventDefault();
    player.paused ? player.play() : player.pause();
  } else if (e.key === "ArrowLeft" || e.key === "ArrowRight"){
    e.preventDefault();
    const p = e.shiftKey ? 1 : FRAME();
    tregua = true;
    player.currentTime += (e.key === "ArrowRight" ? p : -p);
  } else if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z")){
    e.preventDefault(); desfazer();
  } else if (e.key === "Escape" && passo === "edicao"){
    selecao = null; pintarInspetor(); desenharTimeline();
  } else if (passo === "corte" && (e.key === "Delete" || e.key === "Backspace")){
    if (selecionado == null) return;
    e.preventDefault();
    if (e.shiftKey) return apagarTake();
    const t = takes.find(x => x.id === selecionado);
    fotografar(`take #${t.id} ${t.ativo ? "fora" : "de volta"}`);
    t.ativo = !t.ativo;
    renderTudo(); commit();
    avisar(t.ativo ? `take #${t.id} de volta no corte` : `take #${t.id} removido`);
  } else if (passo === "corte" && (e.key === "s" || e.key === "S")){
    e.preventDefault(); dividirTake();
  }
});

/* ---------------- desfazer ----------------
 * Agora guarda takes E estilo. O botão vivia visível em todas as abas mas só
 * desfazia corte; mudar a legenda e se arrepender não tinha volta. */

const historico = [];
const MAX_HISTORICO = 40;
let refazendo = false;

function fotografar(rotulo){
  if (refazendo) return;
  historico.push({ rotulo,
    takes: JSON.parse(JSON.stringify(takes)),
    estilo: JSON.parse(JSON.stringify(estilo)) });
  if (historico.length > MAX_HISTORICO) historico.shift();
  atualizarBotaoDesfazer();
}

function desfazer(){
  const p = historico.pop();
  if (!p) return avisar("nada para desfazer");
  refazendo = true;
  takes = p.takes; proj.takes = takes;
  estilo = p.estilo;
  selecionado = null;
  aplicarCorNaTela();
  renderTudo(); pintarInspetor();
  refazendo = false;
  commit();
  atualizarBotaoDesfazer();
  avisar(`desfeito: ${p.rotulo}`);
}

function atualizarBotaoDesfazer(){
  const b = $("#btn-desfazer");
  b.disabled = historico.length === 0;
  b.title = historico.length ? `desfazer: ${historico.at(-1).rotulo}` : "nada para desfazer";
}

/* ---------------- persistir ---------------- */

let commitTimer = null;
let salvando = null;

function marcarSalvando(estado){
  const el = $("#estado-salvo");
  el.textContent = estado === "salvando" ? "salvando…" : estado === "salvo" ? "salvo" : "erro ao salvar";
  el.className = "estado-salvo " + estado;
}

async function salvarAgora(){
  marcarSalvando("salvando");
  try{
    const r = await fetch("/api/edl", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ takes, fase: passo, estilo }),
    });
    marcarSalvando(r.ok ? "salvo" : "erro");
    return r.ok;
  } catch { marcarSalvando("erro"); return false; }
}

// Uma porta só pra "mudou alguma coisa": salva e recalcula o plano. Enquanto
// eram duas funções (`salvar` e `salvarEstilo`) compartilhando o mesmo timer,
// uma cancelava a outra e a mudança de estilo nunca mostrava "salvo".
function commit(){
  clearTimeout(commitTimer);
  marcarSalvando("salvando");
  commitTimer = setTimeout(async () => {
    commitTimer = null;
    salvando = salvarAgora().then(async () => {
      await recarregarPlano();
      salvando = null;
    });
  }, 300);
}

async function garantirSalvo(){
  if (commitTimer){ clearTimeout(commitTimer); commitTimer = null; await salvarAgora(); }
  if (salvando) await salvando;
  await recarregarRecursos();
}

window.addEventListener("pagehide", () => {
  if (!commitTimer || !proj) return;
  clearTimeout(commitTimer);
  navigator.sendBeacon("/api/edl", new Blob(
    [JSON.stringify({ takes, fase: passo, estilo })], {type: "application/json"}));
});

$("#btn-pasta").addEventListener("click", () => fetch("/api/abrir-pasta", {method:"POST"}));
$("#btn-desfazer").addEventListener("click", desfazer);

/* ================================================================
   CAPA
   ================================================================ */

let capaFormato = "9:16";
let capaPreset = "impacto";

// Espelha os presets do thumb.py. Precisa bater visualmente com o resultado —
// se divergir, a prévia mente e o usuário só descobre depois de gerar.
const PRESETS_CAPA = {
  impacto:   {fonte:"Funnel Display", peso:800, corpo:.070, lh:1.06, alta:true,
              alinhar:"esquerda", enfase:"marca",   scrim:.82, vinheta:true,  barra:false},
  destaque:  {fonte:"Funnel Display", peso:700, corpo:.062, lh:1.12, alta:true,
              alinhar:"esquerda", enfase:"cor",     scrim:.72, vinheta:false, barra:false},
  faixa:     {fonte:"Funnel Display", peso:700, corpo:.054, lh:1.18, alta:true,
              alinhar:"esquerda", enfase:"nenhuma", scrim:0,   vinheta:false, barra:true},
  editorial: {fonte:"Funnel Display", peso:500, corpo:.056, lh:1.20, alta:false,
              alinhar:"esquerda", enfase:"italico", scrim:.70, vinheta:true,  barra:false,
              fonteEnfase:"Trirong"},
  limpo:     {fonte:"Funnel Display", peso:600, corpo:.040, lh:1.16, alta:true,
              alinhar:"centro",   enfase:"cor",     scrim:.35, vinheta:false, barra:false},
};
const FORMATOS_CAPA = {"9:16":[1080,1920], "4:5":[1080,1350], "1:1":[1080,1080]};

const vid = () => $("#capa-video");

function ligarCapa(){
  const faixa = $("#capa-t");
  faixa.max = proj.duracao;
  const p = ativos()[0];
  faixa.value = p ? (p.ini + (p.fim - p.ini) / 2) : 0;

  const atualizar = () => { mostrarT(); irNoQuadro(+faixa.value); };
  faixa.addEventListener("input", atualizar);
  vid().addEventListener("seeked", desenharPreview);
  vid().addEventListener("loadeddata", () => atualizar());

  $("#capa-usar-player").addEventListener("click", () => {
    // no modo "arquivo final" o instante do player é tempo de saída: traduz
    faixa.value = fontePlayer === "final"
      ? (fonteDe(player.currentTime) ?? player.currentTime)
      : player.currentTime;
    atualizar();
    avisar("instante pego do player");
  });

  for (const [id, alvo] of [["#capa-presets","preset"], ["#capa-formatos","fmt"]]){
    document.querySelectorAll(`${id} .card`).forEach(c =>
      c.addEventListener("click", () => {
        if (alvo === "preset") capaPreset = c.dataset.preset;
        else capaFormato = c.dataset.fmt;
        document.querySelectorAll(`${id} .card`).forEach(x => x.classList.toggle("sel", x === c));
        desenharPreview();
      }));
  }

  ["#capa-texto","#capa-destaque"].forEach(s => $(s).addEventListener("input", desenharPreview));
  ["#capa-scrim","#capa-look"].forEach(s => $(s).addEventListener("input", desenharPreview));
  document.querySelectorAll("input[name=capa-pos]").forEach(r =>
    r.addEventListener("change", desenharPreview));
  $("#btn-capa").addEventListener("click", gerarCapa);
  atualizar();
}

function mostrarT(){ $("#capa-t-txt").textContent = fmt(+$("#capa-t").value); }

function irNoQuadro(t){
  const v = vid();
  if (!v.duration) return;
  v.currentTime = clamp(t, 0, v.duration - 0.05);
}

function desenharPreview(){
  const v = vid(), cv = $("#capa-canvas");
  if (!v.videoWidth) return;

  $("#capa-img").classList.remove("on");
  cv.classList.remove("off");
  $("#capa-selo").textContent = "prévia";
  $("#capa-selo").classList.remove("final");

  const [W, H] = FORMATOS_CAPA[capaFormato];
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d");
  const cfg = PRESETS_CAPA[capaPreset];

  const escala = Math.max(W / v.videoWidth, H / v.videoHeight);
  const dw = v.videoWidth * escala, dh = v.videoHeight * escala;
  g.clearRect(0, 0, W, H);
  g.drawImage(v, (W - dw) / 2, (H - dh) / 2, dw, dh);

  if ($("#capa-look").checked){
    g.globalCompositeOperation = "saturation";
    g.fillStyle = "hsl(0,45%,50%)";
    g.fillRect(0, 0, W, H);
    g.globalCompositeOperation = "source-over";
  }

  const texto = $("#capa-texto").value.trim();
  const pos = document.querySelector("input[name=capa-pos]:checked").value;
  const scrim = +$("#capa-scrim").value;

  if (texto && scrim > 0 && !cfg.barra) pintarScrim(g, W, H, pos, scrim);
  if (cfg.vinheta) pintarVinheta(g, W, H);
  if (!texto) return;

  let corpo = Math.round(H * cfg.corpo);
  const margem = Math.round(W * 0.072);
  const conteudo = cfg.alta ? texto.toUpperCase() : texto;
  const fonteDeCapa = (px, ital) =>
    `${ital ? "italic " : ""}${ital ? 700 : cfg.peso} ${px}px "${ital ? (cfg.fonteEnfase||cfg.fonte) : cfg.fonte}", sans-serif`;

  g.font = fonteDeCapa(corpo, false);
  let linhas = quebrarTexto(g, conteudo, W - margem * 2);
  while (linhas.length > 4 && corpo > 24){
    corpo = Math.round(corpo * 0.92);
    g.font = fonteDeCapa(corpo, false);
    linhas = quebrarTexto(g, conteudo, W - margem * 2);
  }

  const lh = Math.round(corpo * cfg.lh);
  const bloco = lh * linhas.length;
  const pad = Math.round(corpo * 0.34);
  let y = pos === "topo" ? Math.round(H * 0.085)
        : pos === "centro" ? Math.round((H - bloco) / 2)
        : H - bloco - Math.round(H * 0.11);

  const cor = estilo.cor;
  if (cfg.barra){ g.fillStyle = cor; g.fillRect(0, y - pad, W, bloco + pad * 2); }

  const alvo = $("#capa-destaque").value.trim().toLowerCase();
  const contorno = cfg.barra ? 0 : Math.max(2, Math.round(corpo * 0.055));
  g.textBaseline = "top";

  for (const linha of linhas){
    g.font = fonteDeCapa(corpo, false);
    let x = cfg.alinhar === "centro" ? (W - g.measureText(linha).width) / 2 : margem;

    linha.split(" ").forEach((palavra, i) => {
      const ehAlvo = alvo && palavra.toLowerCase().includes(alvo);
      const ital = ehAlvo && cfg.enfase === "italico";
      // o espaço anda antes e fora da palavra — ver comentário no thumb.py
      if (i){ g.font = fonteDeCapa(corpo, false); x += g.measureText(" ").width; }
      g.font = fonteDeCapa(corpo, ital);
      const w = g.measureText(palavra).width;

      if (ehAlvo && cfg.enfase === "marca"){
        const m = g.measureText(palavra);
        const alto = (m.actualBoundingBoxAscent || corpo * 0.72)
                   + (m.actualBoundingBoxDescent || corpo * 0.08);
        const y0 = y + (corpo - (m.actualBoundingBoxAscent || corpo * 0.72)) * 0.30;
        const folgaX = pad * 0.34, folgaY = pad * 0.28;
        g.fillStyle = cor;
        g.fillRect(x - folgaX, y0 - folgaY, w + folgaX * 2, alto + folgaY * 2);
        g.fillStyle = "#121212";
        g.fillText(palavra, x, y);
      } else {
        let c = "#fff";
        if (ehAlvo && (cfg.enfase === "cor" || cfg.enfase === "italico")) c = cor;
        if (cfg.barra) c = ehAlvo ? "#fff" : "#121212";
        if (contorno){
          g.lineWidth = contorno * 2; g.strokeStyle = "#000"; g.lineJoin = "round";
          g.strokeText(palavra, x, y);
        }
        g.fillStyle = c;
        g.fillText(palavra, x, y);
      }
      x += w;
    });
    y += lh;
  }
}

function quebrarTexto(g, texto, largMax){
  const saida = [];
  for (const bruta of texto.split("\n")){
    const palavras = bruta.trim().split(/\s+/).filter(Boolean);
    if (!palavras.length) continue;
    let atual = palavras[0];
    for (const p of palavras.slice(1)){
      if (g.measureText(`${atual} ${p}`).width <= largMax) atual += " " + p;
      else { saida.push(atual); atual = p; }
    }
    saida.push(atual);
  }
  return saida;
}

function pintarScrim(g, W, H, pos, forca){
  const grad = g.createLinearGradient(0, 0, 0, H);
  const a = Math.min(1, forca);
  if (pos === "topo"){ grad.addColorStop(0, `rgba(8,8,8,${a})`); grad.addColorStop(0.55, "rgba(8,8,8,0)"); }
  else if (pos === "centro"){
    grad.addColorStop(0, "rgba(8,8,8,0)");
    grad.addColorStop(0.5, `rgba(8,8,8,${a})`);
    grad.addColorStop(1, "rgba(8,8,8,0)");
  } else { grad.addColorStop(0.45, "rgba(8,8,8,0)"); grad.addColorStop(1, `rgba(8,8,8,${a})`); }
  g.fillStyle = grad;
  g.fillRect(0, 0, W, H);
}

function pintarVinheta(g, W, H){
  const r = g.createRadialGradient(W/2, H/2, Math.min(W,H)*0.3, W/2, H/2, Math.max(W,H)*0.72);
  r.addColorStop(0, "rgba(0,0,0,0)");
  r.addColorStop(1, "rgba(0,0,0,0.38)");
  g.fillStyle = r;
  g.fillRect(0, 0, W, H);
}

async function gerarCapa(){
  trabalhando(true, "montando a capa…");
  try{
    const r = await fetch("/api/capa", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        t: +$("#capa-t").value,
        texto: $("#capa-texto").value,
        destacar: $("#capa-destaque").value,
        formato: capaFormato,
        posicao: document.querySelector("input[name=capa-pos]:checked").value,
        preset: capaPreset,
        scrim: +$("#capa-scrim").value,
        look: $("#capa-look").checked,
        cor: estilo.cor,
      }),
    });
    const j = await r.json();
    if (j.erro) avisar("erro na capa: " + j.erro, true);
    else {
      const img = $("#capa-img");
      img.onload = () => {
        img.classList.add("on");
        $("#capa-canvas").classList.add("off");
        $("#capa-selo").textContent = "arquivo gerado";
        $("#capa-selo").classList.add("final");
      };
      img.src = j.url;
      await recarregarRecursos();
      pintarEntrega();
      avisar("capa gerada: " + j.arquivo);
    }
  } catch(e){ avisar("falhou: " + e.message, true); }
  trabalhando(false);
}

/* ================================================================
   ABRIR OUTRO VÍDEO
   ================================================================ */

const modal = $("#abrir");
const abrirModal = (on) => modal.classList.toggle("on", on);

$("#btn-abrir").addEventListener("click", () => {
  $("#abrir-erro").textContent = "";
  abrirModal(true);
  $("#caminho").focus();
});
$("#abrir-cancelar").addEventListener("click", () => abrirModal(false));
modal.addEventListener("click", e => { if (e.target === modal) abrirModal(false); });

// O navegador não entrega o caminho real de um arquivo escolhido, e sem
// caminho o prep não roda. Quem abre o seletor é o servidor.
$("#btn-procurar").addEventListener("click", async () => {
  const r = await fetch("/api/escolher-arquivo", {method:"POST"});
  const j = await r.json();
  if (j.caminho) { $("#caminho").value = j.caminho; abrirVideo(); }
});

$("#abrir-ok").addEventListener("click", abrirVideo);
$("#caminho").addEventListener("keydown", e => { if (e.key === "Enter") abrirVideo(); });

async function abrirVideo(){
  const caminho = $("#caminho").value.trim();
  if (!caminho) return ($("#abrir-erro").textContent = "informe um caminho");
  $("#abrir-erro").textContent = "";
  const r = await fetch("/api/abrir-projeto", {
    method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({ caminho }),
  });
  const j = await r.json();
  if (j.erro) return ($("#abrir-erro").textContent = j.erro);

  abrirModal(false);
  if (j.ja_pronto) return location.reload();

  trabalhando(true, `preparando ${j.nome}…`);
  const t0 = Date.now();
  const timer = setInterval(async () => {
    const p = await (await fetch("/api/preparo")).json();
    if (p.erro){ clearInterval(timer); trabalhando(false); avisar("falhou: " + p.erro, true); return; }
    if (p.pronto){ clearInterval(timer); location.reload(); return; }
    const s = Math.round((Date.now() - t0) / 1000);
    const falta = p.estimativa ? Math.max(0, p.estimativa - s) : 0;
    const restante = falta ? ` · ~${Math.ceil(falta / 60)} min restantes` : "";
    trabalhando(true, `${p.etapa || "preparando…"}  (${s}s${restante})`);
  }, 1500);
}

carregar()
  .then(() => requestAnimationFrame(laco))
  .catch(err => {
    console.error(err);
    $("#status-corte").textContent = "falhou ao carregar: " + err.message;
    avisar("falhou ao carregar o projeto: " + err.message, true);
  });

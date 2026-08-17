/* Interface de revisão — fase 1 (corte) e fase 2 (visual) */

const $ = (s) => document.querySelector(s);

const player   = $("#player");
const pista    = $("#pista");
const camada   = $("#camada-takes");
const cursor   = $("#cursor");
const canvas   = $("#trilha-audio");
const trVideo  = $("#trilha-video");
const listaEl  = $("#lista-takes");
const legendaEl= $("#legenda-preview");

let proj = null;
let takes = [];
let selecionado = null;
let arrasto = null;
let salvarTimer = null;

// Quando o usuário clica de propósito num trecho cortado, ele quer OUVIR
// aquilo. Sem isso o preview pularia na mesma hora e daria a impressão de que
// a timeline não responde ao clique.
let tregua = false;

const FRAME = () => 1 / (proj?.info?.fps || 30);

/* ---------------- utilidades ---------------- */

function fmt(t){
  if (!isFinite(t) || t < 0) t = 0;
  const m = Math.floor(t / 60);
  const s = Math.floor(t % 60);
  const c = Math.floor((t % 1) * 100);
  return `${m}:${String(s).padStart(2,"0")},${String(c).padStart(2,"0")}`;
}

function avisar(msg, ruim=false){
  const el = $("#aviso");
  el.textContent = msg;
  el.classList.toggle("ruim", ruim);
  el.classList.add("on");
  clearTimeout(el._t);
  el._t = setTimeout(() => el.classList.remove("on"), 3000);
}

function trabalhando(on, txt="renderizando…"){
  $("#trabalhando-txt").textContent = txt;
  $("#trabalhando").classList.toggle("on", on);
}

const ativos = () => takes.filter(t => t.ativo).sort((a,b) => a.ini - b.ini);
const duracaoSaida = () => ativos().reduce((s,t) => s + (t.fim - t.ini), 0);

/* ---------------- carregar ---------------- */

async function carregar(){
  const r = await fetch("/api/projeto");
  if (!r.ok) throw new Error("servidor respondeu " + r.status);
  proj = await r.json();
  takes = proj.takes;

  $("#nome-projeto").textContent = proj.nome;
  player.src = "/midia/fonte";

  estilo = { ...ESTILO_PADRAO, ...(proj.estilo || {}) };
  ligarPainelEstilo();
  ligarCapa();
  aplicarEstiloNaTela();
  espelharNaFase2();
  if (proj.fase === "estilo" || proj.fase >= 2) trocarFase(proj.fase);

  desenharThumbs();
  desenharRegua();
  renderTudo();
  desenharWaveform();
  new ResizeObserver(() => desenharWaveform()).observe(canvas);
}

function atualizarStatus(){
  const removidos = takes.filter(t => !t.ativo).length;
  const repetidos = takes.filter(t => !t.ativo && /tentativa anterior/.test(t.motivo || "")).length;
  const saida = duracaoSaida();
  const corte = proj.duracao - saida;
  $("#status-corte").textContent =
    `${takes.length} takes` +
    (removidos ? `, ${removidos} removido${removidos>1?"s":""}` : "") +
    (repetidos ? ` (${repetidos} repetição)` : "") +
    ` · ${fmt(saida)} finais`;
  $("#t-final").textContent = fmt(saida);
  $("#t-economia").textContent = corte > 0.05 ? `−${corte.toFixed(1)}s` : "";
}

/* ---------------- timeline ---------------- */

function desenharThumbs(){
  trVideo.innerHTML = "";
  const n = proj.n_thumbs || 0;
  const alvo = Math.min(n, 80);
  for (let i = 0; i < alvo; i++){
    const idx = Math.round(i * (n - 1) / Math.max(1, alvo - 1)) + 1;
    const img = new Image();
    img.src = `/midia/thumbs/t${String(idx).padStart(4,"0")}.jpg`;
    img.loading = "lazy";
    trVideo.appendChild(img);
  }
}

function desenharWaveform(){
  const peaks = proj?.peaks || [];
  const dpr = window.devicePixelRatio || 1;
  const larg = canvas.clientWidth, alt = canvas.clientHeight;
  if (!larg || !alt) return;
  canvas.width = larg * dpr; canvas.height = alt * dpr;
  const ctx = canvas.getContext("2d");
  ctx.scale(dpr, dpr);
  ctx.clearRect(0,0,larg,alt);
  if (!peaks.length) return;

  const meio = alt / 2;
  const grad = ctx.createLinearGradient(0,0,larg,0);
  grad.addColorStop(0, "#D23089");
  grad.addColorStop(1, "#EE8656");
  ctx.strokeStyle = grad;
  ctx.lineWidth = 1;
  ctx.beginPath();
  for (let x = 0; x < larg; x++){
    const i = Math.floor(x / larg * peaks.length);
    const h = Math.max(0.6, peaks[i] * (alt/2 - 2));
    ctx.moveTo(x + .5, meio - h);
    ctx.lineTo(x + .5, meio + h);
  }
  ctx.stroke();
}

function desenharRegua(){
  const regua = $("#regua");
  regua.innerHTML = "";
  const dur = proj.duracao;
  const passo = dur <= 30 ? 5 : dur <= 120 ? 10 : dur <= 600 ? 30 : 60;
  for (let t = 0; t <= dur; t += passo){
    const s = document.createElement("span");
    s.style.left = (t / dur * 100) + "%";
    s.textContent = fmt(t).replace(/,\d+$/,"");
    regua.appendChild(s);
  }
}

function renderRegioes(){
  camada.innerHTML = "";
  const dur = proj.duracao;
  const pct = (t) => (t / dur * 100) + "%";
  const ord = [...takes].sort((a,b) => a.ini - b.ini);

  // O véu escuro cobre tudo que NÃO entra no corte final — silêncio entre
  // takes e também take desativado. Calcular isso sobre todos os takes deixava
  // o take removido sem véu, com a mesma cara de quem continua no vídeo.
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

  // retângulo fantasma enquanto o usuário arrasta pra criar
  if (criando && criando.arrastou){
    const a = Math.min(criando.ini, criando.fim);
    const b = Math.max(criando.ini, criando.fim);
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
      renderTudo(); salvar();
    });

    const motivo = t.motivo
      ? `<span class="motivo${t.ativo ? " bom" : ""}">${t.motivo}</span>` : "";
    const txt = document.createElement("div");
    txt.innerHTML = `<span class="txt">${t.texto}</span>
      <span class="meta">#${t.id} · ${fmt(t.ini)} → ${fmt(t.fim)} · ${(t.fim-t.ini).toFixed(2)}s</span>
      ${motivo}`;

    // Botões explícitos: atalho é conveniência, não pode ser o único caminho.
    const acoes = document.createElement("div");
    acoes.className = "acoes-take";

    const bTirar = document.createElement("button");
    bTirar.className = "btn-take";
    bTirar.textContent = t.ativo ? "tirar" : "voltar";
    bTirar.title = t.ativo ? "tirar do corte" : "trazer de volta pro corte";
    bTirar.addEventListener("click", (e) => {
      e.stopPropagation();
      fotografar(`take #${t.id} ${t.ativo ? "fora" : "de volta"}`);
      t.ativo = !t.ativo;
      renderTudo(); salvar();
      avisar(t.ativo ? `take #${t.id} de volta` : `take #${t.id} fora do corte`);
    });
    acoes.appendChild(bTirar);

    if (t.manual){
      const bApagar = document.createElement("button");
      bApagar.className = "btn-take perigo";
      bApagar.textContent = "apagar";
      bApagar.title = "apagar este take criado à mão";
      bApagar.addEventListener("click", (e) => {
        e.stopPropagation();
        selecionado = t.id;
        apagarTake();
      });
      acoes.appendChild(bApagar);
    }

    li.append(cb, txt, acoes);
    li.addEventListener("click", () => { selecionado = t.id; irPara(t.ini); renderTudo(); });
    listaEl.appendChild(li);
  }
}

function renderTudo(){
  renderRegioes();
  renderLista();
  atualizarStatus();
}

/* ---------------- reprodução ---------------- */

function irPara(t){
  player.currentTime = Math.max(0, Math.min(t, proj.duracao - 0.01));
}

const takeEm = (t) => ativos().find(x => t >= x.ini - 0.001 && t < x.fim);
const proximoTake = (t) => ativos().find(x => x.ini > t - 0.001);

function tempoSaida(t){
  let acc = 0;
  for (const x of ativos()){
    if (t >= x.fim) acc += x.fim - x.ini;
    else if (t >= x.ini) return acc + (t - x.ini);
    else break;
  }
  return acc;
}

function laco(){
  if (proj){
    const t = player.currentTime;
    cursor.style.left = (t / proj.duracao * 100) + "%";
    $("#t-atual").textContent = fmt(tempoSaida(t));

    const dentro = takeEm(t);
    if (dentro) tregua = false;          // voltou pro corte, volta a valer o pulo

    if ($("#pular-cortes").checked && !player.paused && !tregua && !dentro){
      const prox = proximoTake(t);
      if (prox) player.currentTime = prox.ini;
      else player.pause();
    }
    atualizarLegenda(t);
  }
  requestAnimationFrame(laco);
}

// Prévia da legenda sobre o player, no estilo escolhido na aba Estilo.
// Sem isso, a pessoa só descobria como a legenda ia ficar depois de renderizar
// — minutos de espera pra ver que o estilo não era o que queria.
// (A variável local chamava `estilo` e sombreava a global do painel.)
function atualizarLegenda(t){
  const take = takeEm(t) || (tregua ? takes.find(x => t >= x.ini && t < x.fim) : null);
  if (!take || estilo.legenda === "nenhuma"){ legendaEl.innerHTML = ""; return; }

  const ps = take.palavras || [];
  const i = ps.findIndex(w => t >= w.ini && t <= w.fim + 0.05);
  if (i < 0){ legendaEl.innerHTML = ""; return; }

  const cx = s => estilo.caixa === "maiuscula" ? s.toUpperCase() : s.toLowerCase();
  const esc = s => s.replace(/[&<>]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;"}[c]));
  legendaEl.style.setProperty("--realce", estilo.cor);

  if (estilo.legenda === "ili-palavra"){
    legendaEl.className = "legenda leg-palavra";
    legendaEl.innerHTML = `<span>${esc(cx(ps[i].t))}</span>`;
    return;
  }
  if (estilo.legenda === "ili-frase"){
    // mesmos grupos de 3 do export_ass, pra prévia não mentir sobre o ritmo
    const g0 = Math.floor(i / 3) * 3;
    const grupo = ps.slice(g0, g0 + 3);
    const limpo = w => w.t.replace(/[.,!?;:]/g, "");
    const principal = grupo.reduce((a,b) => limpo(b).length > limpo(a).length ? b : a, grupo[0]);
    legendaEl.className = "legenda leg-frase";
    legendaEl.innerHTML = grupo.map(w =>
      w === principal ? `<b>${esc(cx(w.t))}</b>` : esc(cx(w.t))).join(" ");
    return;
  }
  legendaEl.className = "legenda leg-bloco";
  const a = Math.max(0, i - 4), b = Math.min(ps.length, i + 4);
  legendaEl.innerHTML = esc(cx(ps.slice(a, b).map(w => w.t).join(" ")));
}

/* ---------------- interação na timeline ---------------- */

function tempoDoEvento(e){
  const r = pista.getBoundingClientRect();
  return Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * proj.duracao;
}

let criando = null;   // {ini, fim} enquanto o usuário arrasta numa área vazia

pista.addEventListener("mousedown", (e) => {
  const alca = e.target.closest(".alca");
  if (alca){
    fotografar(`ajuste da borda do take #${alca.dataset.id}`);
    arrasto = { id: +alca.dataset.id, borda: alca.dataset.borda };
    selecionado = arrasto.id;
    e.preventDefault();
    return;
  }
  const reg = e.target.closest(".regiao.take");
  const t = tempoDoEvento(e);

  if (reg){
    selecionado = +reg.dataset.id;
  } else {
    // Área sem take: pode ser clique (posicionar) ou arrasto (criar take novo).
    // Só decide quando o mouse andar — senão todo clique viraria take de 0s.
    criando = { ini: t, fim: t, arrastou: false };
  }

  tregua = !takeEm(t);      // clicou fora do corte: respeita e deixa ouvir
  irPara(t);
  renderTudo();
});

window.addEventListener("mousemove", (e) => {
  if (criando){
    const t = tempoDoEvento(e);
    if (Math.abs(t - criando.ini) > 0.05) criando.arrastou = true;
    criando.fim = t;
    renderRegioes();
    return;
  }
  if (!arrasto) return;
  const t = takes.find(x => x.id === arrasto.id);
  const novo = tempoDoEvento(e);
  const ord = [...takes].sort((a,b) => a.ini - b.ini);
  const i = ord.indexOf(t);
  const antes = ord[i-1], depois = ord[i+1];
  const MIN = 0.08;

  if (arrasto.borda === "esq"){
    t.ini = Math.max(antes ? antes.fim : 0, Math.min(novo, t.fim - MIN));
  } else {
    t.fim = Math.min(depois ? depois.ini : proj.duracao, Math.max(novo, t.ini + MIN));
  }
  renderRegioes(); atualizarStatus();
});

window.addEventListener("mouseup", () => {
  if (criando){
    const { ini, fim, arrastou } = criando;
    criando = null;
    if (arrastou) criarTake(Math.min(ini, fim), Math.max(ini, fim));
    else renderRegioes();
  }
  if (arrasto){ arrasto = null; renderTudo(); salvar(); }
});

/* ---------------- criar, dividir e apagar take ---------------- */

const DUR_MIN = 0.15;

function palavrasNoIntervalo(a, b){
  // As palavras vivem dentro dos takes; um trecho que a IA descartou pode ter
  // fala que o ASR pegou mas ninguém está usando. Varre todas e traz as que
  // caem no intervalo, pra legenda funcionar no take criado à mão.
  return takes.flatMap(t => t.palavras || [])
    .filter(w => w.fim > a && w.ini < b)
    .sort((x, y) => x.ini - y.ini);
}

function novoId(){
  return takes.reduce((m, t) => Math.max(m, t.id), 0) + 1;
}

function criarTake(a, b){
  a = Math.max(0, a); b = Math.min(proj.duracao, b);
  if (b - a < DUR_MIN) return avisar("trecho curto demais", true);

  // não deixa nascer por cima de outro take: encolhe até o vizinho
  for (const t of takes){
    if (a < t.fim && b > t.ini){
      if (a >= t.ini && b <= t.fim) return avisar("já existe take aqui", true);
      if (a < t.ini) b = Math.min(b, t.ini); else a = Math.max(a, t.fim);
    }
  }
  if (b - a < DUR_MIN) return avisar("não coube entre os takes vizinhos", true);

  const ps = palavrasNoIntervalo(a, b);
  const t = {
    id: novoId(),
    ini: +a.toFixed(3), fim: +b.toFixed(3),
    ini_orig: +a.toFixed(3), fim_orig: +b.toFixed(3),
    texto: ps.map(w => w.t).join(" ") || "(trecho sem fala)",
    ativo: true, manual: true, palavras: ps,
  };
  fotografar("criar take");
  takes.push(t);
  selecionado = t.id;
  renderTudo(); salvar();
  avisar(`take #${t.id} criado (${(b - a).toFixed(2)}s)`);
}

function dividirTake(){
  const t = takeEm(player.currentTime)
         || takes.find(x => player.currentTime >= x.ini && player.currentTime < x.fim);
  if (!t) return avisar("posicione o cursor dentro de um take", true);
  fotografar(`dividir take #${t.id}`);
  const corte = player.currentTime;
  if (corte - t.ini < DUR_MIN || t.fim - corte < DUR_MIN)
    return avisar("corte perto demais da borda", true);

  const direita = {
    id: novoId(),
    ini: +corte.toFixed(3), fim: t.fim,
    ini_orig: +corte.toFixed(3), fim_orig: t.fim,
    texto: "", ativo: t.ativo, manual: true,
    palavras: (t.palavras || []).filter(w => w.ini >= corte),
  };
  direita.texto = direita.palavras.map(w => w.t).join(" ") || "(trecho sem fala)";

  t.fim = +corte.toFixed(3);
  t.fim_orig = t.fim;
  t.palavras = (t.palavras || []).filter(w => w.ini < corte);
  t.texto = t.palavras.map(w => w.t).join(" ") || "(trecho sem fala)";

  takes.push(direita);
  selecionado = direita.id;
  renderTudo(); salvar();
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
  renderTudo(); salvar();
  avisar(`take #${t.id} apagado`);
}

camada.addEventListener("dblclick", (e) => {
  const reg = e.target.closest(".regiao.take");
  if (!reg) return;
  const t = takes.find(x => x.id === +reg.dataset.id);
  fotografar(`reset do take #${t.id}`);
  t.ini = t.ini_orig; t.fim = t.fim_orig; t.ativo = true;
  renderTudo(); salvar();
  avisar(`take #${t.id} voltou ao original`);
});

/* ---------------- atalhos ---------------- */

document.addEventListener("keydown", (e) => {
  // Nunca sequestrar teclado enquanto o usuário escreve.
  const escrevendo = e.target.matches?.("input[type=text], input[type=number], textarea");
  if (escrevendo) return;
  // Os atalhos são da bancada de corte. Sem isso, um Delete na aba Capa
  // removia o take que tinha ficado selecionado lá atrás, sem nada na tela
  // indicando que algo mudou.
  if (document.body.dataset.fase !== "1") return;

  if (e.code === "Space"){
    e.preventDefault();
    player.paused ? player.play() : player.pause();
  } else if (e.key === "ArrowLeft" || e.key === "ArrowRight"){
    e.preventDefault();
    const passo = e.shiftKey ? 1 : FRAME();
    tregua = true;   // navegando quadro a quadro, não pula sozinho
    player.currentTime += (e.key === "ArrowRight" ? passo : -passo);
  } else if (e.key === "Delete" || e.key === "Backspace"){
    if (selecionado == null) return;
    e.preventDefault();
    if (e.shiftKey) return apagarTake();
    const t = takes.find(x => x.id === selecionado);
    fotografar(`take #${t.id} ${t.ativo ? "fora" : "de volta"}`);
    t.ativo = !t.ativo;
    renderTudo(); salvar();
    avisar(t.ativo ? `take #${t.id} de volta no corte` : `take #${t.id} removido`);
  } else if ((e.ctrlKey || e.metaKey) && (e.key === "z" || e.key === "Z")){
    e.preventDefault();
    desfazer();
  } else if (e.key === "s" || e.key === "S"){
    e.preventDefault();
    dividirTake();
  }
});

/* ---------------- desfazer ---------------- */

// Pilha de estados do EDL. O objeto é pequeno (só bordas e flags), então
// guardar as últimas dezenas custa quase nada de memória — e é a diferença
// entre "arrastei errado" ser um susto ou ser trabalho perdido.
const historico = [];
const MAX_HISTORICO = 40;
let refazendo = false;

function fotografar(rotulo){
  if (refazendo) return;
  historico.push({
    rotulo,
    takes: JSON.parse(JSON.stringify(takes)),
  });
  if (historico.length > MAX_HISTORICO) historico.shift();
  atualizarBotaoDesfazer();
}

function desfazer(){
  const passo = historico.pop();
  if (!passo) return avisar("nada para desfazer");
  refazendo = true;
  takes = passo.takes;
  proj.takes = takes;
  selecionado = null;
  renderTudo();
  refazendo = false;
  salvar();
  atualizarBotaoDesfazer();
  avisar(`desfeito: ${passo.rotulo}`);
}

function atualizarBotaoDesfazer(){
  const b = $("#btn-desfazer");
  if (!b) return;
  b.disabled = historico.length === 0;
  b.title = historico.length
    ? `desfazer: ${historico[historico.length - 1].rotulo}` : "nada para desfazer";
}

/* ---------------- persistir ---------------- */

function marcarSalvando(estado){
  const el = $("#estado-salvo");
  if (!el) return;
  el.textContent = estado === "salvando" ? "salvando…"
                 : estado === "salvo" ? "salvo"
                 : "erro ao salvar";
  el.className = "estado-salvo " + estado;
}

function salvar(){
  clearTimeout(salvarTimer);
  marcarSalvando("salvando");
  salvarTimer = setTimeout(async () => {
    try{
      const r = await fetch("/api/edl", {
        method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({ takes, fase: proj.fase, estilo }),
      });
      marcarSalvando(r.ok ? "salvo" : "erro");
      if (r.ok && infoFinal.existe && !infoFinal.desatualizado){
        infoFinal.desatualizado = true;
        atualizarAvisoFinal();
      }
    } catch { marcarSalvando("erro"); }
    salvarTimer = null;
  }, 400);
}

window.addEventListener("pagehide", () => {
  if (!salvarTimer || !proj) return;
  clearTimeout(salvarTimer);
  navigator.sendBeacon("/api/edl", new Blob(
    [JSON.stringify({ takes, fase: proj.fase })], {type: "application/json"}));
});

/* ---------------- estilo ---------------- */

const ESTILO_PADRAO = {
  tipo: "limpa",
  cor: "#EE8656",
  headline_estilo: "contorno",
  legenda: "ili-frase",
  zoom: true,
  zoom_animado: false,
  flash: false,
  cor_look: true,
  trilha: false,
  broll: false,
  caixa: "minuscula",
  altura_legenda: 0.20,
  lut: "",
  encerramento: false,
  observacoes: "",
};

let estilo = { ...ESTILO_PADRAO };

function aplicarEstiloNaTela(){
  document.documentElement.style.setProperty("--cor-destaque", estilo.cor);
  marcarCard("#cards-tipo", "tipo", estilo.tipo);
  marcarCard("#cards-headline", "hl", estilo.headline_estilo);
  marcarCard("#cards-legenda", "leg", estilo.legenda);
  $("#cor-destaque").value = estilo.cor;
  $("#cor-hex").value = estilo.cor.toUpperCase();
  $("#el-zoom").checked = estilo.zoom;
  $("#el-zoomanim").checked = estilo.zoom_animado;
  $("#el-flash").checked = estilo.flash;
  $("#el-cor").checked = estilo.cor_look;
  $("#el-trilha").checked = estilo.trilha;
  $("#el-broll").checked = estilo.broll;
  $("#obs").value = estilo.observacoes || "";
  const rc = document.querySelector(`input[name=caixa][value="${estilo.caixa}"]`);
  if (rc) rc.checked = true;
  $("#altura-legenda").value = estilo.altura_legenda;
  $("#altura-legenda-txt").textContent = Math.round(estilo.altura_legenda * 100) + "%";
  document.documentElement.style.setProperty("--altura-legenda",
    (estilo.altura_legenda * 100) + "%");
  $("#el-encerramento").checked = estilo.encerramento;
  if ($("#lut").value !== estilo.lut) $("#lut").value = estilo.lut;
  atualizarResumo();
}

function marcarCard(seletor, chave, valor){
  document.querySelectorAll(`${seletor} .card`).forEach(c =>
    c.classList.toggle("sel", c.dataset[chave] === valor));
}

const NOMES = {
  limpa:"limpa", dividida:"tela dividida", dividida2:"tela dividida 2",
  contorno:"headline contorno", caixa:"headline caixa", nenhuma:"sem headline",
  "ili-frase":"legenda frase", "ili-palavra":"legenda palavra",
  "ili-bloco":"legenda bloco",
};

function atualizarResumo(){
  const liga = [];
  if (estilo.zoom) liga.push("zoom in");
  if (estilo.zoom_animado) liga.push("zoom in/out");
  if (estilo.flash) liga.push("flash");
  if (estilo.cor_look) liga.push("cor");
  if (estilo.trilha) liga.push("trilha IA");
  if (estilo.broll) liga.push("b-roll");
  const leg = estilo.legenda === "nenhuma" ? "sem legenda" : NOMES[estilo.legenda];
  $("#resumo-estilo").innerHTML =
    `<b>${NOMES[estilo.tipo]}</b> · ${NOMES[estilo.headline_estilo]} · ${leg}`
    + ` · destaque <b>${estilo.cor.toUpperCase()}</b>`
    + (liga.length ? ` · ${liga.join(", ")}` : " · sem extras");
}

function mudarEstilo(patch){
  Object.assign(estilo, patch);
  aplicarEstiloNaTela();
  espelharNaFase2();
  salvarEstilo();
}

function salvarEstilo(){
  clearTimeout(salvarTimer);
  salvarTimer = setTimeout(async () => {
    await fetch("/api/edl", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({ takes, fase: proj.fase, estilo }),
    });
    salvarTimer = null;
  }, 400);
}

// A Fase 2 não configura nada — só mostra o que a aba Estilo decidiu, pra
// você conferir antes de gerar. Ter os mesmos controles nos dois lugares
// confundia sobre qual valia.
function espelharNaFase2(){
  const el = $("#resumo-fase2");
  if (el) el.innerHTML = $("#resumo-estilo").innerHTML;
}

function ligarPainelEstilo(){
  document.querySelectorAll("#cards-tipo .card").forEach(c =>
    c.addEventListener("click", () => mudarEstilo({ tipo: c.dataset.tipo })));
  document.querySelectorAll("#cards-headline .card").forEach(c =>
    c.addEventListener("click", () => mudarEstilo({ headline_estilo: c.dataset.hl })));
  document.querySelectorAll("#cards-legenda .card").forEach(c =>
    c.addEventListener("click", () => mudarEstilo({ legenda: c.dataset.leg })));
  document.querySelectorAll("#swatches .sw").forEach(b =>
    b.addEventListener("click", () => mudarEstilo({ cor: b.dataset.cor })));

  $("#cor-destaque").addEventListener("input", e => mudarEstilo({ cor: e.target.value }));
  $("#cor-hex").addEventListener("change", e => {
    const v = e.target.value.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) mudarEstilo({ cor: v });
    else { e.target.value = estilo.cor.toUpperCase(); avisar("cor inválida — use #RRGGBB", true); }
  });

  // os dois zooms disputam a mesma escala; ligar um desliga o outro
  $("#el-zoom").addEventListener("change", e => mudarEstilo(
    { zoom: e.target.checked, zoom_animado: e.target.checked ? false : estilo.zoom_animado }));
  $("#el-zoomanim").addEventListener("change", e => mudarEstilo(
    { zoom_animado: e.target.checked, zoom: e.target.checked ? false : estilo.zoom }));
  $("#el-flash").addEventListener("change", e => mudarEstilo({ flash: e.target.checked }));
  $("#el-cor").addEventListener("change", e => mudarEstilo({ cor_look: e.target.checked }));
  $("#el-trilha").addEventListener("change", e => mudarEstilo({ trilha: e.target.checked }));
  $("#el-broll").addEventListener("change", e => mudarEstilo({ broll: e.target.checked }));
  $("#obs").addEventListener("change", e => mudarEstilo({ observacoes: e.target.value }));
  document.querySelectorAll("input[name=caixa]").forEach(r =>
    r.addEventListener("change", e => mudarEstilo({ caixa: e.target.value })));
  $("#altura-legenda").addEventListener("input", e =>
    mudarEstilo({ altura_legenda: +e.target.value }));
  $("#lut").addEventListener("change", e => mudarEstilo({ lut: e.target.value }));
  $("#el-encerramento").addEventListener("change", e =>
    mudarEstilo({ encerramento: e.target.checked }));
  document.querySelectorAll("input[name=fonte-player]").forEach(r =>
    r.addEventListener("change", e => trocarFontePlayer(e.target.value)));
  carregarRecursos();
  const ir = $("#ir-estilo");
  if (ir) ir.addEventListener("click", () => trocarFase("estilo"));
}

// Lista o que a pasta do projeto oferece: LUTs, card de fechamento, trilha.
// A UI não deve prometer o que não existe em disco.
async function carregarRecursos(){
  try{
    const r = await (await fetch("/api/recursos")).json();
    const sel = $("#lut");
    sel.innerHTML = '<option value="">nenhum</option>' +
      (r.luts || []).map(n => `<option value="${n}">${n}</option>`).join("");
    sel.value = estilo.lut || "";
    $("#lut-dica").textContent = r.luts?.length
      ? `${r.luts.length} disponíveis` : "coloque .cube em editor-ia/luts";

    infoFinal = r.final || {};
    atualizarAvisoFinal();

    const enc = $("#el-encerramento");
    $("#enc-dica").textContent = r.encerramento
      ? `usa ${r.encerramento}` : "nenhum card encontrado na pasta";
    enc.disabled = !r.encerramento;
    enc.closest(".tg").classList.toggle("desligado", !r.encerramento);
  } catch {}
}

/* ---------------- o que toca no player ---------------- */

// A Fase 2 mostra o ARQUIVO renderizado, não a prévia. Antes ela só resumia o
// estilo em texto e o resultado só aparecia abrindo o mp4 na mão.
let fontePlayer = "previa";
let infoFinal = {};

function trocarFontePlayer(qual){
  if (qual === "final" && !infoFinal.existe) return;
  if (qual === fontePlayer) return;
  fontePlayer = qual;
  const t = player.currentTime;
  if (qual === "final"){
    player.src = infoFinal.url;
    // o final já está cortado: pular trecho removido não faz sentido nele
    $("#pular-cortes").checked = false;
    $("#pular-cortes").disabled = true;
    legendaEl.innerHTML = "";
  } else {
    player.src = "/midia/fonte";
    $("#pular-cortes").disabled = false;
    $("#pular-cortes").checked = true;
    player.addEventListener("loadeddata", () => { player.currentTime = t; }, {once:true});
  }
  document.querySelectorAll("input[name=fonte-player]").forEach(r =>
    r.checked = r.value === qual);
  document.body.dataset.fonte = qual;
}

function atualizarAvisoFinal(){
  const el = $("#aviso-final");
  const radio = document.querySelector('input[name=fonte-player][value=final]');
  if (!el || !radio) return;
  radio.disabled = !infoFinal.existe;
  if (!infoFinal.existe){
    el.textContent = "ainda não renderizado";
    el.className = "aviso-inline";
  } else if (infoFinal.desatualizado){
    el.textContent = "o corte mudou depois deste render — gere de novo";
    el.className = "aviso-inline alerta";
  } else {
    el.textContent = "em dia com o corte atual";
    el.className = "aviso-inline ok";
  }
}

/* ---------------- fases ---------------- */

function trocarFase(n){
  document.body.dataset.fase = n;
  document.querySelectorAll(".aba").forEach(a =>
    a.classList.toggle("ativa", a.dataset.fase === String(n)));
  // Fase 2 mostra o resultado quando ele existe e está em dia
  if (n === 2 && infoFinal.existe && !infoFinal.desatualizado) trocarFontePlayer("final");
  else if (n !== 2) trocarFontePlayer("previa");

  $("#dica-fase").textContent =
    n === 1 ? "ajuste o corte e aprove" :
    n === "estilo" ? "defina o visual antes de gerar" :
    n === "capa" ? "escolha o quadro e escreva a chamada" :
    "confira o preview e gere o arquivo";
  if (proj) { proj.fase = n; salvar(); }
}

document.querySelectorAll(".aba").forEach(a =>
  a.addEventListener("click", () => {
    const v = a.dataset.fase;
    trocarFase(/^\d+$/.test(v) ? +v : v);
  }));

document.querySelectorAll(".opcao input[type=radio]").forEach(r =>
  r.addEventListener("change", () => {
    // marca só a opção escolhida dentro do próprio grupo
    document.querySelectorAll(`input[name="${r.name}"]`).forEach(x =>
      x.closest(".opcao").classList.toggle("sel", x.checked));
  }));

/* ---------------- botões ---------------- */

$("#btn-play").addEventListener("click", () => player.paused ? player.play() : player.pause());
$("#btn-inicio").addEventListener("click", () => {
  const p = ativos()[0];
  tregua = false;
  irPara(p ? p.ini : 0);
});
player.addEventListener("play",  () => $("#btn-play").textContent = "❚❚");
player.addEventListener("pause", () => $("#btn-play").textContent = "▶");

$("#btn-aprovar").addEventListener("click", () => {
  trocarFase("estilo");
  avisar("corte aprovado — escolha o estilo da Fase 2");
});

$("#btn-pasta").addEventListener("click", () => fetch("/api/abrir-pasta", {method:"POST"}));
$("#btn-desfazer").addEventListener("click", desfazer);

/* ---------------- capa ---------------- */

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
  // começa no meio do primeiro take aprovado: é onde ele já está falando, com
  // o rosto composto — início de take costuma pegar boca abrindo
  faixa.value = p ? (p.ini + (p.fim - p.ini) / 2) : 0;

  const atualizar = () => { mostrarT(); irNoQuadro(+faixa.value); };
  faixa.addEventListener("input", atualizar);
  vid().addEventListener("seeked", desenharPreview);
  vid().addEventListener("loadeddata", () => atualizar());

  $("#capa-usar-player").addEventListener("click", () => {
    faixa.value = player.currentTime;
    atualizar();
    avisar("instante pego do player");
  });

  for (const [id, alvo] of [["#capa-presets","preset"], ["#capa-formatos","fmt"]]){
    document.querySelectorAll(`${id} .card`).forEach(c =>
      c.addEventListener("click", () => {
        if (alvo === "preset") capaPreset = c.dataset.preset;
        else capaFormato = c.dataset.fmt;
        document.querySelectorAll(`${id} .card`).forEach(x =>
          x.classList.toggle("sel", x === c));
        desenharPreview();
      }));
  }

  ["#capa-texto","#capa-destaque"].forEach(s =>
    $(s).addEventListener("input", desenharPreview));
  ["#capa-scrim","#capa-look"].forEach(s =>
    $(s).addEventListener("input", desenharPreview));
  document.querySelectorAll("input[name=capa-pos]").forEach(r =>
    r.addEventListener("change", desenharPreview));

  $("#btn-capa").addEventListener("click", gerarCapa);
  $("#btn-capa-pasta").addEventListener("click",
    () => fetch("/api/abrir-pasta", {method:"POST"}));

  atualizar();
}

function mostrarT(){
  $("#capa-t-txt").textContent = fmt(+$("#capa-t").value);
}

function irNoQuadro(t){
  const v = vid();
  if (!v.duration) return;
  v.currentTime = Math.max(0, Math.min(t, v.duration - 0.05));
}

/* ---------- prévia desenhada no cliente ---------- */

function desenharPreview(){
  const v = vid(), cv = $("#capa-canvas");
  if (!v.videoWidth) return;

  // volta pra prévia se estava mostrando o arquivo gerado
  $("#capa-img").classList.remove("on");
  cv.classList.remove("off");
  $("#capa-selo").textContent = "prévia";
  $("#capa-selo").classList.remove("final");

  const [W, H] = FORMATOS_CAPA[capaFormato];
  cv.width = W; cv.height = H;
  const g = cv.getContext("2d");
  const cfg = PRESETS_CAPA[capaPreset];

  // enquadra sem distorcer, igual ao _enquadrar do Python
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

  // tipografia
  let corpo = Math.round(H * cfg.corpo);
  const margem = Math.round(W * 0.072);
  const conteudo = cfg.alta ? texto.toUpperCase() : texto;
  const fonteDe = (px, ital) =>
    `${ital ? "italic " : ""}${ital ? 700 : cfg.peso} ${px}px "${ital ? (cfg.fonteEnfase||cfg.fonte) : cfg.fonte}", sans-serif`;

  g.font = fonteDe(corpo, false);
  let linhas = quebrarTexto(g, conteudo, W - margem * 2);
  while (linhas.length > 4 && corpo > 24){
    corpo = Math.round(corpo * 0.92);
    g.font = fonteDe(corpo, false);
    linhas = quebrarTexto(g, conteudo, W - margem * 2);
  }

  const lh = Math.round(corpo * cfg.lh);
  const bloco = lh * linhas.length;
  const pad = Math.round(corpo * 0.34);
  let y = pos === "topo" ? Math.round(H * 0.085)
        : pos === "centro" ? Math.round((H - bloco) / 2)
        : H - bloco - Math.round(H * 0.11);

  const cor = estilo.cor;
  if (cfg.barra){
    g.fillStyle = cor;
    g.fillRect(0, y - pad, W, bloco + pad * 2);
  }

  const alvo = $("#capa-destaque").value.trim().toLowerCase();
  const contorno = cfg.barra ? 0 : Math.max(2, Math.round(corpo * 0.055));
  g.textBaseline = "top";

  for (const linha of linhas){
    g.font = fonteDe(corpo, false);
    let x = cfg.alinhar === "centro"
      ? (W - g.measureText(linha).width) / 2 : margem;

    linha.split(" ").forEach((palavra, i) => {
      const ehAlvo = alvo && palavra.toLowerCase().includes(alvo);
      const ital = ehAlvo && cfg.enfase === "italico";
      // o espaço anda antes e fora da palavra — ver comentário no thumb.py
      if (i){ g.font = fonteDe(corpo, false); x += g.measureText(" ").width; }
      g.font = fonteDe(corpo, ital);
      const w = g.measureText(palavra).width;

      if (ehAlvo && cfg.enfase === "marca"){
        // segue a caixa real do glifo, igual ao thumb.py — ver comentário lá
        const m = g.measureText(palavra);
        const topo = y + (m.actualBoundingBoxAscent !== undefined
          ? (corpo * 0.0) : 0);
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
          g.lineWidth = contorno * 2;
          g.strokeStyle = "#000";
          g.lineJoin = "round";
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
    if (j.erro) { avisar("erro na capa: " + j.erro, true); }
    else {
      const img = $("#capa-img");
      img.onload = () => {
        img.classList.add("on");
        $("#capa-canvas").classList.add("off");
        $("#capa-selo").textContent = "arquivo gerado";
        $("#capa-selo").classList.add("final");
      };
      img.src = j.url;         // já vem com cache-buster
      avisar("capa gerada: " + j.arquivo);
    }
  } catch(e){ avisar("falhou: " + e.message, true); }
  trabalhando(false);
}

/* ---------------- abrir outro vídeo ---------------- */

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
    if (p.erro){
      clearInterval(timer); trabalhando(false);
      avisar("falhou: " + p.erro, true);
      return;
    }
    if (p.pronto){ clearInterval(timer); location.reload(); return; }

    // Mostrar etapa e tempo restante é o que separa "está processando" de
    // "travou" pra quem espera. Transcrição anda perto de 1x a duração.
    const s = Math.round((Date.now() - t0) / 1000);
    const falta = p.estimativa ? Math.max(0, p.estimativa - s) : 0;
    const restante = falta ? ` · ~${Math.ceil(falta / 60)} min restantes` : "";
    trabalhando(true, `${p.etapa || "preparando…"}  (${s}s${restante})`);
  }, 1500);
}

function listarSaidas(arquivos){
  const ul = $("#saidas");
  ul.innerHTML = "";
  for (const a of arquivos){
    const li = document.createElement("li");
    li.innerHTML = `<b>${a}</b><span>pronto</span>`;
    ul.appendChild(li);
  }
}

async function exportar(formatos, txt){
  trabalhando(true, txt);
  try{
    // a aba Estilo é a fonte da verdade; a Fase 2 só espelha
    const r = await fetch("/api/exportar", {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({
        formatos,
        legenda: estilo.legenda,
        look: estilo.cor_look ? "ili" : "nenhum",
        headline: $("#headline").value,
        headline_modo: estilo.headline_estilo === "caixa" ? "stacked" : "outline",
        zoom: estilo.zoom,
        cor: estilo.cor,
        tipo: estilo.tipo,
        trilha: estilo.trilha,
        zoom_animado: estilo.zoom_animado,
        flash: estilo.flash,
        broll: estilo.broll,
        caixa_alta: estilo.caixa === "maiuscula",
        altura_legenda: estilo.altura_legenda,
        lut: estilo.lut,
        encerramento: estilo.encerramento,
      }),
    });
    const j = await r.json();
    if (j.erro){ avisar("erro: " + j.erro, true); }
    else {
      listarSaidas(j.arquivos);
      avisar("gerado: " + j.arquivos.join(", "));
      await carregarRecursos();
      if (j.arquivos.includes("final.mp4")){
        fontePlayer = "previa";          // força a troca abaixo
        trocarFontePlayer("final");
        trocarFase(2);
      }
    }
  } catch(err){ avisar("falhou: " + err.message, true); }
  trabalhando(false);
}

// Sugestão de headline: a primeira frase falada costuma ser o gancho do
// roteiro. É um ponto de partida pra editar, não a headline final.
$("#btn-sugerir-hl").addEventListener("click", () => {
  const primeiro = ativos()[0];
  if (!primeiro) return avisar("nenhum take ativo", true);
  const palavras = primeiro.texto.replace(/[.,!?;:]/g, "").split(/\s+/).filter(Boolean);
  const corte = Math.ceil(palavras.length / 2);
  $("#headline").value = palavras.slice(0, Math.min(corte, 4)).join(" ") + "\n"
                       + palavras.slice(Math.min(corte, 4), Math.min(corte, 4) + 4).join(" ");
  avisar("headline sugerida a partir do primeiro take — edite à vontade");
});

$("#btn-mp4").addEventListener("click", () => exportar(["mp4"], "renderizando o MP4…"));
$("#btn-premiere").addEventListener("click", () => exportar(["xml","srt"], "gerando sequência…"));

carregar()
  .then(() => requestAnimationFrame(laco))
  .catch(err => {
    console.error(err);
    $("#status-corte").textContent = "falhou ao carregar: " + err.message;
    avisar("falhou ao carregar o projeto: " + err.message, true);
  });

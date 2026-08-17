"""Servidor local da interface de revisao de corte.

Sobe em http://localhost:5178 e serve a UI + a API sobre uma pasta edit/.
So depende da stdlib.

Uso:
    python server.py "C:/caminho/do/video.mp4"
    python server.py "C:/caminho/edit"
"""

from __future__ import annotations

import json
import mimetypes
import os
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

PORTA = 5178
RAIZ = Path(__file__).parent
WEB = RAIZ / "web"

EDIT: Path
EDL: Path
FONTE: Path

trava = threading.Lock()


def _texto(corpo: bytes) -> str:
    """Decodifica o corpo aceitando quem nao mandou UTF-8.

    Texto em portugues vem cheio de acento, e um cliente que mande cp1252
    (curl no shell do Windows, por exemplo) derrubava a conexao com
    UnicodeDecodeError antes de qualquer resposta. Melhor tolerar a entrada
    torta do que morrer calado.
    """
    for cod in ("utf-8", "cp1252", "latin-1"):
        try:
            return corpo.decode(cod)
        except UnicodeDecodeError:
            continue
    return corpo.decode("utf-8", errors="replace")


class Servidor(ThreadingHTTPServer):
    """No Windows, SO_REUSEADDR deixa DOIS processos escutarem a mesma porta.

    O bind nao falha, os dois ficam LISTENING e as conexoes caem ora num ora no
    outro — na pratica a interface responde de forma intermitente e o servidor
    velho, com o codigo antigo em memoria, atende metade dos pedidos. Desligar
    o reuse faz o segundo bind estourar OSError, que e o que a gente quer.
    """
    allow_reuse_address = False


def carregar_edl() -> dict:
    return json.loads(EDL.read_text(encoding="utf-8"))


def salvar_edl(dados: dict) -> None:
    with trava:
        tmp = EDL.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(dados, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(EDL)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # silencia o log por request
        pass

    # ---------- helpers ----------

    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(corpo)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(corpo)

    def _arquivo(self, caminho: Path, cache=True):
        """Serve arquivo com suporte a Range. Sem Range o <video> nao seeka."""
        if not caminho.is_file():
            self.send_error(404)
            return

        tamanho = caminho.stat().st_size
        tipo = mimetypes.guess_type(str(caminho))[0] or "application/octet-stream"
        faixa = self.headers.get("Range")

        inicio, fim = 0, tamanho - 1
        parcial = False
        if faixa:
            m = re.match(r"bytes=(\d*)-(\d*)", faixa)
            if m:
                g1, g2 = m.group(1), m.group(2)
                if g1:
                    inicio = int(g1)
                    fim = int(g2) if g2 else tamanho - 1
                elif g2:  # sufixo: ultimos N bytes
                    inicio = max(0, tamanho - int(g2))
                if inicio >= tamanho:
                    self.send_response(416)
                    self.send_header("Content-Range", f"bytes */{tamanho}")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                fim = min(fim, tamanho - 1)
                parcial = True

        comprimento = fim - inicio + 1
        self.send_response(206 if parcial else 200)
        self.send_header("Content-Type", tipo)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(comprimento))
        if parcial:
            self.send_header("Content-Range", f"bytes {inicio}-{fim}/{tamanho}")
        self.send_header("Cache-Control", "public, max-age=3600" if cache else "no-store")
        self.end_headers()

        if self.command == "HEAD":
            return
        with caminho.open("rb") as f:
            f.seek(inicio)
            restante = comprimento
            while restante > 0:
                bloco = f.read(min(256 * 1024, restante))
                if not bloco:
                    break
                try:
                    self.wfile.write(bloco)
                except (BrokenPipeError, ConnectionAbortedError):
                    return  # o player abortou o download, normal ao seekar
                restante -= len(bloco)

    # ---------- rotas ----------

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        rota = unquote(urlparse(self.path).path)

        if rota == "/":
            return self._arquivo(WEB / "index.html", cache=False)
        if rota.startswith("/web/"):
            alvo = (WEB / rota[5:]).resolve()
            if WEB.resolve() in alvo.parents or alvo.parent == WEB.resolve():
                return self._arquivo(alvo, cache=False)
            return self.send_error(403)

        if rota == "/api/projeto":
            return self._json(carregar_edl())

        if rota == "/api/recursos":
            enc = achar_encerramento()
            final = EDIT / "final.mp4"
            # "desatualizado" = o EDL mudou depois do último render. Sem isso a
            # Fase 2 mostraria um arquivo velho como se fosse o resultado atual.
            info_final = {}
            if final.exists():
                info_final = {
                    "existe": True,
                    "quando": final.stat().st_mtime,
                    "desatualizado": final.stat().st_mtime < EDL.stat().st_mtime,
                    "url": f"/saida/final.mp4?v={final.stat().st_mtime_ns}",
                }
            return self._json({
                "luts": [p.stem for p in achar_luts()],
                "encerramento": enc.name if enc else "",
                "trilha": bool(achar_trilha()),
                "referencias": len(achar_referencias()),
                "final": info_final,
            })


        if rota == "/midia/fonte":
            # o player recebe o proxy; o bruto fica reservado pro render
            proxy = EDIT / "proxy.mp4"
            return self._arquivo(proxy if proxy.exists() else FONTE)

        if rota.startswith("/midia/thumbs/"):
            nome = Path(rota).name
            if not re.fullmatch(r"t\d+\.jpg", nome):
                return self.send_error(403)
            return self._arquivo(EDIT / "thumbs" / nome)

        if rota.startswith("/saida/"):
            nome = Path(rota).name
            return self._arquivo(EDIT / nome, cache=False)

        self.send_error(404)

    def do_POST(self):
        try:
            self._post()
        except Exception as e:
            # sem isso, qualquer excecao aqui fecha a conexao sem resposta e o
            # cliente ve um erro vazio, sem pista nenhuma do que aconteceu
            traceback.print_exc()
            try:
                self._json({"erro": f"{type(e).__name__}: {e}"}, 500)
            except Exception:
                pass

    def _post(self):
        rota = unquote(urlparse(self.path).path)
        tamanho = int(self.headers.get("Content-Length") or 0)
        corpo = self.rfile.read(tamanho) if tamanho else b"{}"
        try:
            dados = json.loads(_texto(corpo) or "{}")
        except json.JSONDecodeError as e:
            return self._json({"erro": f"json invalido: {e}"}, 400)

        if rota == "/api/edl":
            atual = carregar_edl()
            novos = dados.get("takes")
            # Salvaguarda: nunca aceitar lista vazia por cima de um corte que ja
            # existe. Um POST disparado antes da UI terminar de carregar, ou um
            # bug no cliente, apagaria o trabalho inteiro sem aviso.
            if isinstance(novos, list) and (novos or not atual.get("takes")):
                atual["takes"] = novos
            elif novos is not None:
                return self._json(
                    {"erro": "recusei apagar todos os takes", "takes": len(atual["takes"])}, 409)
            atual["fase"] = dados.get("fase", atual.get("fase", 1))
            if "estilo" in dados:
                # merge, nao substituicao: a UI manda so o que mudou
                atual.setdefault("estilo", {}).update(dados["estilo"])
            salvar_edl(atual)
            return self._json({"ok": True})

        if rota == "/api/exportar":
            formatos = dados.get("formatos") or ["xml", "srt"]
            try:
                gerados = exportar(
                    formatos,
                    dados.get("legenda") or "nenhuma",
                    dados.get("look") or "nenhum",
                    dados.get("headline") or "",
                    dados.get("headline_modo") or "outline",
                    bool(dados.get("zoom")),
                    dados.get("cor") or "",
                    dados.get("tipo") or "limpa",
                    bool(dados.get("trilha")),
                    bool(dados.get("zoom_animado")),
                    bool(dados.get("flash")),
                    bool(dados.get("broll")),
                    bool(dados.get("caixa_alta")),
                    dados.get("lut") or "",
                    bool(dados.get("encerramento")),
                    float(dados.get("altura_legenda") or 0.20),
                )
            except Exception as e:  # devolve o erro pra UI em vez de morrer calado
                return self._json({"erro": str(e)}, 500)
            return self._json({"ok": True, "arquivos": gerados})

        if rota == "/api/abrir-pasta":
            subprocess.Popen(["explorer", str(EDIT)])
            return self._json({"ok": True, "pasta": str(EDIT)})

        if rota == "/api/escolher-arquivo":
            # Diálogo nativo do Windows. O navegador nunca entrega o caminho
            # real de um arquivo (por segurança), e sem caminho o prep não
            # roda — então quem abre o seletor é o servidor, não a página.
            caminho = escolher_arquivo()
            return self._json({"caminho": caminho or ""})

        if rota == "/api/abrir-projeto":
            alvo = (dados.get("caminho") or "").strip().strip('"')
            if not alvo:
                return self._json({"erro": "informe o caminho do vídeo"}, 400)
            try:
                return self._json(abrir_projeto(Path(alvo)))
            except Exception as e:
                return self._json({"erro": str(e)}, 400)

        if rota == "/api/preparo":
            return self._json(estado_preparo())

        if rota == "/api/capa":
            from pipeline import thumb
            edl = carregar_edl()
            ext = ".jpg" if dados.get("formato_arquivo", "jpg") == "jpg" else ".png"
            alvo = EDIT / f"capa{ext}"
            try:
                thumb.gerar(
                    edl, alvo,
                    t=float(dados.get("t") or 0),
                    texto=dados.get("texto") or "",
                    formato=dados.get("formato") or "9:16",
                    posicao=dados.get("posicao") or "base",
                    cor=dados.get("cor") or "#EE8656",
                    destacar=dados.get("destacar") or "",
                    preset=dados.get("preset") or "impacto",
                    scrim=(None if dados.get("scrim") in (None, "")
                           else float(dados["scrim"])),
                    look=bool(dados.get("look")),
                )
            except Exception as e:
                traceback.print_exc()
                return self._json({"erro": str(e)}, 500)
            # cache-buster: sem isso o navegador mostra a capa anterior
            return self._json({"ok": True, "arquivo": alvo.name,
                               "url": f"/saida/{alvo.name}?v={alvo.stat().st_mtime_ns}"})

        self.send_error(404)


VIDEOS = {".mp4", ".mov", ".mkv", ".m4v", ".avi", ".mts"}

# estado do preparo em andamento, lido pela UI enquanto a barra roda
preparo = {"rodando": False, "etapa": "", "erro": "", "pronto": False,
           "nome": "", "inicio": 0.0, "estimativa": 0}


def _estimar(video: Path) -> int:
    """Chute grosseiro de quanto o preparo vai levar, em segundos.

    A transcricao domina o tempo e anda perto de 1x a duracao nesta maquina
    (CPU). Ter um numero, mesmo aproximado, e o que separa "esta processando"
    de "travou" na cabeca de quem espera.
    """
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(video)],
            capture_output=True, text=True)
        dur = float((r.stdout or "0").strip() or 0)
    except Exception:
        return 0
    return int(dur * 1.25 + 20)   # transcricao + proxy + thumbs


def escolher_arquivo() -> str:
    """Abre o seletor de arquivos do Windows e devolve o caminho escolhido."""
    try:
        import tkinter as tk
        from tkinter import filedialog
    except Exception:
        return ""
    raiz = tk.Tk()
    raiz.withdraw()
    raiz.attributes("-topmost", True)
    try:
        return filedialog.askopenfilename(
            title="Escolha o vídeo bruto",
            filetypes=[("Vídeo", "*.mp4 *.mov *.mkv *.m4v *.avi *.MTS"),
                       ("Todos", "*.*")]) or ""
    finally:
        raiz.destroy()


def estado_preparo() -> dict:
    return dict(preparo)


def abrir_projeto(alvo: Path) -> dict:
    """Aponta o servidor pra outro vídeo, preparando se ainda não houver EDL.

    O prep roda numa thread porque leva minutos: a UI acompanha por
    /api/preparo em vez de ficar pendurada num request.
    """
    global EDIT, EDL, FONTE

    if not alvo.exists():
        raise ValueError(f"não achei: {alvo}")
    if alvo.is_dir():
        candidatos = [p for p in sorted(alvo.iterdir())
                      if p.is_file() and p.suffix.lower() in VIDEOS]
        if not candidatos:
            raise ValueError("nenhum vídeo nessa pasta")
        alvo = max(candidatos, key=lambda p: p.stat().st_size)
    elif alvo.suffix.lower() not in VIDEOS:
        raise ValueError(f"não parece vídeo: {alvo.suffix}")

    saida = alvo.parent / "_edit-ia" / alvo.stem
    if (saida / "edl.json").exists():
        EDIT, EDL, FONTE = saida, saida / "edl.json", alvo
        preparo.update(rodando=False, etapa="", erro="", pronto=True, nome=alvo.name)
        return {"ok": True, "ja_pronto": True, "nome": alvo.name}

    def trabalhar():
        global EDIT, EDL, FONTE
        preparo.update(rodando=True, etapa="lendo o arquivo…", erro="",
                       pronto=False, nome=alvo.name, inicio=time.time(),
                       estimativa=_estimar(alvo))
        try:
            saida.mkdir(parents=True, exist_ok=True)
            # Popen em vez de run: o prep imprime a etapa em que está, e sem
            # ler linha a linha a barra fica indefinida do começo ao fim —
            # numa transcrição de 10 minutos isso parece travamento.
            p = subprocess.Popen(
                [sys.executable, "-u", str(RAIZ / "pipeline" / "prep.py"), str(alvo),
                 "--saida", str(saida)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, encoding="utf-8", errors="replace", bufsize=1)
            ultimas = []
            for linha in p.stdout:
                linha = linha.strip()
                if not linha:
                    continue
                ultimas.append(linha)
                del ultimas[:-8]
                if linha.startswith("["):          # "[3/6] transcrevendo..."
                    preparo["etapa"] = linha
            p.wait()
            if p.returncode != 0 or not (saida / "edl.json").exists():
                preparo.update(rodando=False,
                               erro="\n".join(ultimas[-4:]) or "falhou sem mensagem")
                return
            EDIT, EDL, FONTE = saida, saida / "edl.json", alvo
            preparo.update(rodando=False, etapa="", pronto=True)
        except Exception as e:
            preparo.update(rodando=False, erro=str(e))

    threading.Thread(target=trabalhar, daemon=True).start()
    return {"ok": True, "preparando": True, "nome": alvo.name}


def achar_trilha() -> Path | None:
    """Pega o primeiro audio chamado `trilha.*` na pasta do projeto.

    E o ponto de encontro entre o app e a geracao por IA: quem gerar a musica
    (o agente pelo Magnific, ou voce na mao) so precisa largar o arquivo ali.
    Assim o render nao depende de credencial nenhuma.
    """
    for ext in ("mp3", "m4a", "wav", "aac", "ogg"):
        p = EDIT / f"trilha.{ext}"
        if p.exists():
            return p
    return None


def achar_luts() -> list[Path]:
    """LUTs .cube disponiveis: os do projeto e os da pasta `luts/` da ferramenta.

    O do projeto vence quando os nomes coincidem — assim dá pra sobrescrever o
    padrão num job específico sem mexer na instalação.
    """
    achados: dict[str, Path] = {}
    for pasta in (RAIZ / "luts", EDIT):
        if pasta.exists():
            for p in sorted(pasta.glob("*.cube")):
                achados[p.stem] = p
    return list(achados.values())


def achar_encerramento() -> Path | None:
    """Card de fechamento: `encerramento.png` na pasta do projeto, ou o
    FECHAMENTO da pasta de grafismos da campanha, se existir por perto."""
    for nome in ("encerramento.png", "encerramento.jpg", "fechamento.png"):
        p = EDIT / nome
        if p.exists():
            return p
    # sobe até achar uma pasta de grafismos da campanha
    for base in list(EDIT.parents)[:4]:
        for cand in base.glob("03_grafismos/FECHAMENTO*.png"):
            return cand
    return None


def achar_referencias() -> list[Path]:
    """Imagens de apoio pra outra metade da tela dividida.

    Mesma logica da trilha: qualquer `ref*.png|jpg|webp` na pasta do projeto
    entra, em ordem alfabetica, e o render alterna entre elas. Quem gerar o
    b-roll (o agente pelo Magnific, ou voce) so precisa salvar ali.
    """
    achados: list[Path] = []
    for ext in ("png", "jpg", "jpeg", "webp"):
        achados += sorted(EDIT.glob(f"ref*.{ext}"))
    return achados


def exportar(formatos: list[str], legenda: str = "nenhuma", look: str = "nenhum",
             headline: str = "", headline_modo: str = "outline",
             zoom: bool = False, cor: str = "", tipo: str = "limpa",
             trilha: bool = False, zoom_animado: bool = False,
             flash: bool = False, broll: bool = False,
             caixa_alta: bool = False, lut: str = "",
             encerramento: bool = False,
             altura_legenda: float = 0.20) -> list[str]:
    sys.path.insert(0, str(RAIZ))
    from pipeline import export_ass, export_srt, export_xml, render

    edl = carregar_edl()
    info = edl.get("info", {})
    gerados = []

    if "xml" in formatos:
        alvo = EDIT / "sequencia.xml"
        export_xml.gerar(edl, alvo)
        gerados.append(alvo.name)

    if "srt" in formatos:
        alvo = EDIT / "master.srt"
        export_srt.gerar(edl, alvo)
        gerados.append(alvo.name)

    if "mp4" in formatos:
        ass = None
        if (legenda and legenda != "nenhuma") or headline.strip():
            ass = EDIT / "legenda.ass"
            export_ass.gerar(edl, ass, legenda if legenda != "nenhuma" else "ili-frase",
                             info.get("largura") or 1080, info.get("altura") or 1920,
                             headline=headline, headline_modo=headline_modo, cor=cor,
                             caixa_alta=caixa_alta, altura_legenda=altura_legenda)
            gerados.append(ass.name)
        alvo = EDIT / "final.mp4"
        cfg_look = dict(LOOKS.get(look or "nenhum") or {})
        if lut:
            achado = next((p for p in achar_luts() if p.stem == lut), None)
            if achado:
                cfg_look["cube"] = str(achado)
        render.gerar(edl, alvo, EDIT, legenda=ass, look=(cfg_look or None),
                     zoom=zoom, tipo=tipo, trilha=achar_trilha() if trilha else None,
                     zoom_animado=zoom_animado, flash=flash,
                     referencias=achar_referencias() if broll else None,
                     encerramento=achar_encerramento() if encerramento else None)
        gerados.append(alvo.name)

    return gerados


# Tratamentos de cor. O "ili" segue o que o INDICE.md do projeto descreve:
# imagem escura e dessaturada, com um lift leve nas sombras.
LOOKS = {
    "nenhum": None,
    "ili": {"saturacao": 0.55, "contraste": 1.06, "sombras": 0.045},
    "ili-forte": {"saturacao": 0.28, "contraste": 1.10, "sombras": 0.06},
}


def resolver(argumento: str) -> tuple[Path, Path, Path]:
    """Aceita o video, ou direto a pasta de saida que o prep gerou."""
    alvo = Path(argumento).resolve()
    if alvo.is_dir():
        edit = alvo
    elif (alvo.parent / "edl.json").exists():
        edit = alvo.parent
    else:
        edit = alvo.parent / "edit"
    edl = edit / "edl.json"
    if not edl.exists():
        raise SystemExit(f"nao achei {edl}\nrode antes: python pipeline/prep.py \"{alvo}\"")
    fonte = Path(json.loads(edl.read_text(encoding='utf-8'))["fonte"])
    if not fonte.exists():
        raise SystemExit(f"o bruto sumiu do lugar: {fonte}")
    return edit, edl, fonte


def main() -> int:
    global EDIT, EDL, FONTE
    if len(sys.argv) < 2:
        print(__doc__)
        return 1

    EDIT, EDL, FONTE = resolver(sys.argv[1])
    edl = carregar_edl()

    url = f"http://localhost:{PORTA}/"
    print(f"projeto : {edl['nome']}  ({edl['duracao']:.1f}s, {len(edl['takes'])} takes)")
    print(f"pasta   : {EDIT}")
    print(f"abrindo : {url}\n")
    print("ctrl+c para parar")

    try:
        servidor = Servidor(("127.0.0.1", PORTA), Handler)
    except OSError:
        raise SystemExit(
            f"a porta {PORTA} ja esta em uso — feche o servidor anterior antes.\n"
            f"  netstat -ano | findstr :{PORTA}    (pega o PID)\n"
            f"  taskkill /PID <pid> /F")
    if os.environ.get("SEM_BROWSER") != "1":
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\nparado")
    return 0


if __name__ == "__main__":
    sys.exit(main())

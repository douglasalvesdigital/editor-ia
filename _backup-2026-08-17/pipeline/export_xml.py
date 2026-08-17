"""EDL -> FCP7 XML (xmeml), que o Premiere importa por Arquivo > Importar.

Os clipes apontam para o BRUTO original com pontos de entrada/saida, nunca
para pedacos ja recortados em disco. E o que permite o editor arrastar a borda
de um take e recuperar material que a maquina cortou de mais.
"""

from __future__ import annotations

from pathlib import Path
from xml.sax.saxutils import escape


def _pathurl(caminho: Path) -> str:
    p = str(caminho.resolve()).replace("\\", "/")
    if len(p) > 1 and p[1] == ":":          # C:/... -> file://localhost/C:/...
        return "file://localhost/" + p
    return "file://localhost" + p


def gerar(edl: dict, destino: Path) -> Path:
    fonte = Path(edl["fonte"])
    info = edl["info"]
    fps = info.get("fps") or 30.0
    timebase = int(round(fps))
    ntsc = "TRUE" if abs(fps - timebase) > 0.001 else "FALSE"
    larg = info.get("largura") or 1920
    alt = info.get("altura") or 1080

    seg = lambda s: int(round(s * fps))  # segundos -> frames

    ativos = sorted([t for t in edl["takes"] if t.get("ativo", True)], key=lambda t: t["ini"])
    if not ativos:
        raise ValueError("nenhum take ativo — nada pra exportar")

    dur_fonte = seg(info.get("duracao") or edl["duracao"])
    nome_seq = escape(Path(edl["nome"]).stem + " — corte IA")
    url = escape(_pathurl(fonte))
    nome_arq = escape(fonte.name)

    def bloco_file(primeiro: bool) -> str:
        """O arquivo e descrito por extenso uma vez; depois so referenciado."""
        if not primeiro:
            return '<file id="f1"/>'
        return f"""<file id="f1">
      <name>{nome_arq}</name>
      <pathurl>{url}</pathurl>
      <rate><timebase>{timebase}</timebase><ntsc>{ntsc}</ntsc></rate>
      <duration>{dur_fonte}</duration>
      <media>
       <video><samplecharacteristics><width>{larg}</width><height>{alt}</height></samplecharacteristics></video>
       <audio><channelcount>2</channelcount></audio>
      </media>
     </file>"""

    itens_v, itens_a = [], []
    cursor = 0
    for i, t in enumerate(ativos):
        ent, sai = seg(t["ini"]), seg(t["fim"])
        n = max(1, sai - ent)
        ini_tl, fim_tl = cursor, cursor + n
        cursor = fim_tl
        rotulo = escape((t.get("texto") or f"take {t['id']}")[:60])
        primeiro = (i == 0)

        itens_v.append(f"""<clipitem id="v{i+1}">
      <name>{rotulo}</name>
      <duration>{n}</duration>
      <rate><timebase>{timebase}</timebase><ntsc>{ntsc}</ntsc></rate>
      <start>{ini_tl}</start><end>{fim_tl}</end>
      <in>{ent}</in><out>{sai}</out>
      {bloco_file(primeiro)}
     </clipitem>""")

        itens_a.append(f"""<clipitem id="a{i+1}">
      <name>{rotulo}</name>
      <duration>{n}</duration>
      <rate><timebase>{timebase}</timebase><ntsc>{ntsc}</ntsc></rate>
      <start>{ini_tl}</start><end>{fim_tl}</end>
      <in>{ent}</in><out>{sai}</out>
      <file id="f1"/>
      <sourcetrack><mediatype>audio</mediatype><trackindex>1</trackindex></sourcetrack>
     </clipitem>""")

    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE xmeml>
<xmeml version="4">
 <sequence id="seq1">
  <name>{nome_seq}</name>
  <duration>{cursor}</duration>
  <rate><timebase>{timebase}</timebase><ntsc>{ntsc}</ntsc></rate>
  <media>
   <video>
    <format>
     <samplecharacteristics>
      <width>{larg}</width><height>{alt}</height>
      <rate><timebase>{timebase}</timebase><ntsc>{ntsc}</ntsc></rate>
     </samplecharacteristics>
    </format>
    <track>
     {"".join(itens_v)}
    </track>
   </video>
   <audio>
    <track>
     {"".join(itens_a)}
    </track>
   </audio>
  </media>
 </sequence>
</xmeml>
"""
    destino.write_text(xml, encoding="utf-8")
    return destino

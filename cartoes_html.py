"""
cartoes_html.py  --  Página HTML com os Cartões-Programa, feita para os policiais lerem.

Gera UM arquivo .html que abre em qualquer navegador (não precisa de Python para ler):
  - abas por viatura, com a linha do dia (24 faixas coloridas pela classe);
  - mapa da faixa escolhida (hexágonos, áreas e bases de todas as viaturas);
  - alternância entre "plano base" (todas livres) e "plano atual" (depois dos empenhos);
  - cartão de cada viatura em tabela, pronto para IMPRIMIR (uma página por viatura);
  - lista dos eventos do dia, com a cobertura antes e depois de cada um.

O mapa usa a biblioteca Leaflet e os mapas de rua da Esri, que precisam de internet. Sem
internet, o mapa não aparece, mas os cartões e a linha do dia continuam funcionando.
É uma FOTOGRAFIA do plano no momento em que foi gerada: os botões "estou indo" e
"ocorrência encerrada" ficam para a interface (módulo 5).
"""
import json
from pathlib import Path

CORES_VIATURAS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b", "#e377c2"]


def _pct(medida):
    return f"prioridade {100 * medida['prioridade']:.0f}% | território {100 * medida['territorio']:.0f}%"


def _descrever_evento(rel):
    """Transforma o relatório de um evento em título e linhas de texto simples."""
    h = rel["hora"]
    if rel["evento"] == "empenho":
        a, d = rel["hora_atual"], rel["resto_do_dia"]
        return {"titulo": f"{h:02d}h: {rel['viatura']} ({rel['tipo']}) saiu para a ocorrência em {rel['ocorrencia']}",
                "linhas": [f"Regiões afetadas: {rel['hexagonos_afetados']} hexágonos que só ela cobria",
                           f"Faixa {h:02d}h, antes: {_pct(a['antes'])}",
                           f"Faixa {h:02d}h, sem ajuste: {_pct(a['sem_ajuste'])}",
                           f"Faixa {h:02d}h, com ajuste: {_pct(a['depois'])}",
                           f"Resto do dia (média), antes: {_pct(d['antes'])}",
                           f"Resto do dia (média), sem ajuste: {_pct(d['sem_ajuste'])}",
                           f"Resto do dia (média), com ajuste: {_pct(d['depois'])}"]}
    if rel["evento"] == "retorno":
        a, d = rel["hora_atual"], rel["resto_do_dia"]
        return {"titulo": f"{h:02d}h: {rel['viatura']} ({rel['tipo']}) voltou ao preventivo",
                "linhas": [f"Faixa {h:02d}h, antes: {_pct(a['antes'])}",
                           f"Faixa {h:02d}h, depois: {_pct(a['depois'])}",
                           f"Resto do dia (média), antes: {_pct(d['antes'])}",
                           f"Resto do dia (média), depois: {_pct(d['depois'])}",
                           f"Posições iguais ao plano base: {rel['posicoes_iguais_ao_plano_base']}"]}
    sugestoes = [f"{c['viatura']} ({c['tipo']}), {c['distancia_m']} m" for c in rel["sugestoes_para_reaberta"]]
    return {"titulo": f"{h:02d}h: {rel['viatura']} trocou de {rel['de']} para {rel['para']} (mais grave)",
            "linhas": [f"{rel['de']} voltou a ficar aberta.",
                       "Sugestões para ela: " + ("; ".join(sugestoes) if sugestoes else "nenhuma viatura disponível")]}


def _texto_da_entrada(e, lat, lon):
    """Frase curta, em linguagem direta, sobre o que a viatura faz na faixa."""
    if e.get("empenhada"):
        return "EMPENHADA: atendendo ocorrência (fora do preventivo)"
    raio = f"{e['raio_m'] / 1000:g} km"
    if e["minutos_base"]:
        return (f"Ponto-base de {e['minutos_base']} min em {lat:.5f}, {lon:.5f} + "
                f"{e['minutos_patrulha']} min de patrulha (raio {raio})")
    if e["quadricula"] is not None:
        return f"Patrulhar até {raio} em volta de {lat:.5f}, {lon:.5f}"
    return f"Patrulhar até {raio} em volta das bases da Classe 1 (reserva)"


def _serializar_plano(op, plano, centros, indice):
    """Plano -> estrutura simples (listas e números) que o JavaScript da página entende."""
    resultado = {}
    for v in op.ids:
        linhas = []
        for h in range(24):
            e = plano[v][h]
            q = e["quadricula"]
            lat, lon = centros[q] if q is not None else (None, None)
            tipo = "empenhada" if e.get("empenhada") else ("ciclo" if e["minutos_base"] else "poligono")
            linhas.append({
                "h": h, "faixa": e["faixa"], "classe": e["classe"], "tipo": tipo, "q": q,
                "lat": round(lat, 6) if lat is not None else None,
                "lon": round(lon, 6) if lon is not None else None,
                "raio": e["raio_m"], "txt": _texto_da_entrada(e, lat, lon),
                "area": [indice[c] for c in e["area"]],      # a área vai como números (posição de cada hexágono)
            })
        resultado[v] = linhas
    return resultado


def gerar_html(op, malha, centros, niveis, contorno, caminho, titulo="Cartões-Programa de patrulhamento preventivo",
               nomes_niveis=None, cores_niveis=None):
    """
    Grava a página e devolve o caminho dela.

    op      : a Operacao (módulo 4) com o plano e o histórico de eventos
    malha   : a MalhaHexagonal (para desenhar cada hexágono)
    centros : {hexágono: (lat, lon)}
    niveis  : {hexágono: nível de prioridade 0 a 4}
    contorno: GeoJSON do contorno da área
    caminho : onde gravar o arquivo .html
    """
    nomes_niveis = nomes_niveis or ["Sem ocorrências", "Baixa", "Média", "Alta", "Muito alta"]
    cores_niveis = cores_niveis or ["#d9d9d9", "#fff2a8", "#ffb000", "#e03c00", "#6a0f7a"]

    ids = sorted(centros)                                        # ordem fixa dos hexágonos
    indice = {c: i for i, c in enumerate(ids)}                   # hexágono -> posição
    poligonos = [[[round(lat, 6), round(lon, 6)] for lon, lat in malha.vertices(c)] for c in ids]

    planos = {"base": _serializar_plano(op, op.plano_base, centros, indice)}
    cobertura = {"base": [op.cobertura(h, op.plano_base) for h in range(24)]}
    if op.plano != op.plano_base:                                # só mostra "atual" se algo mudou
        planos["atual"] = _serializar_plano(op, op.plano, centros, indice)
        cobertura["atual"] = [op.cobertura(h, op.plano) for h in range(24)]
    cobertura = {k: [{"p": round(m["prioridade"], 3), "t": round(m["territorio"], 3)} for m in v]
                 for k, v in cobertura.items()}

    empenhadas = sorted(op.empenhos)
    dados = {
        "titulo": titulo,
        "resumo": (f"{len(op.ids)} viaturas | viaturas empenhadas agora: {', '.join(empenhadas)}" if empenhadas
                   else f"{len(op.ids)} viaturas | nenhuma empenhada agora"),
        "hora_inicial": op.historico[-1]["hora"] if op.historico else 8,
        "viaturas": [{"id": v, "tipo": op.tipos[v], "cor": CORES_VIATURAS[i % len(CORES_VIATURAS)]}
                     for i, v in enumerate(op.ids)],
        "celulas": ids, "poligonos": poligonos, "niveis": [niveis[c] for c in ids],
        "nomes_niveis": nomes_niveis, "cores_niveis": cores_niveis,
        "contorno": contorno, "planos": planos, "cobertura": cobertura,
        "eventos": [_descrever_evento(r) for r in op.historico],
    }
    # "</" dentro do JSON poderia fechar o <script> antes da hora; a barra invertida evita isso
    texto_json = json.dumps(dados, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    pagina = (_MODELO.replace("__TITULO__", titulo.replace("<", "&lt;")).replace("__DADOS__", texto_json))
    caminho = Path(caminho)
    caminho.write_text(pagina, encoding="utf-8")
    return caminho


_MODELO = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITULO__</title>
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.css">
<style>
  * { box-sizing: border-box; }
  body { font-family: Segoe UI, Arial, sans-serif; margin: 0; color: #222; background: #f4f5f7; }
  header { background: #1b2a41; color: #fff; padding: 12px 18px; display: flex; flex-wrap: wrap; align-items: center; gap: 16px; }
  header h1 { font-size: 20px; margin: 0; }
  #resumo { font-size: 14px; opacity: .85; flex: 1; }
  button { cursor: pointer; font: inherit; }
  .controles button { background: #fff; border: 0; border-radius: 4px; padding: 7px 12px; margin-left: 6px; }
  main { display: flex; flex-wrap: wrap; gap: 12px; padding: 12px; }
  #painel { flex: 0 0 330px; background: #fff; border-radius: 6px; padding: 12px; }
  #painel h2 { font-size: 14px; text-transform: uppercase; color: #667; margin: 14px 0 6px; }
  #painel h2:first-child { margin-top: 0; }
  #mapa { flex: 1 1 520px; min-height: 520px; border-radius: 6px; background: #dfe3e8; }
  .aviso { padding: 20px; color: #555; }
  .aba, .plano { display: block; width: 100%; text-align: left; background: #f1f3f6; border: 1px solid #d5d9e0; border-radius: 4px; padding: 7px 10px; margin-bottom: 5px; }
  .aba.ativa, .plano.ativo { background: #1b2a41; color: #fff; border-color: #1b2a41; }
  #hora { width: 100%; }
  #info-hora { font-size: 14px; margin: 6px 0; line-height: 1.4; }
  #linha-do-dia { display: grid; grid-template-columns: repeat(12, 1fr); gap: 3px; margin-top: 8px; }
  .bloco { color: #fff; font-size: 12px; text-align: center; padding: 8px 0; border-radius: 3px; cursor: pointer; border: 2px solid transparent; }
  .bloco.sel { border-color: #000; box-shadow: 0 0 0 2px #fff inset; font-weight: bold; }
  .legenda { font-size: 12px; margin-top: 10px; line-height: 1.7; }
  .legenda span.q { display: inline-block; width: 12px; height: 12px; margin-right: 5px; vertical-align: middle; border-radius: 2px; }
  #cartoes, #eventos { margin: 0 12px 12px; }
  .cartao { display: none; background: #fff; border-radius: 6px; padding: 14px 16px; }
  .cartao.ativo { display: block; }
  .cartao h2 { margin: 0 0 4px; font-size: 18px; }
  .cartao p { margin: 2px 0 10px; font-size: 13px; color: #555; }
  table { border-collapse: collapse; width: 100%; font-size: 13px; }
  th, td { border: 1px solid #d5d9e0; padding: 5px 8px; text-align: left; vertical-align: top; }
  th { background: #eef0f4; }
  tr.sel td { background: #fff7d6; }
  tr.empenhada td { background: #eee; color: #666; }
  .selo { display: inline-block; color: #fff; padding: 1px 7px; border-radius: 10px; font-size: 12px; }
  #eventos { background: #fff; border-radius: 6px; padding: 12px 16px; }
  #eventos h2 { font-size: 16px; margin: 0 0 8px; }
  .evento { border-left: 4px solid #1b2a41; padding: 4px 10px; margin-bottom: 10px; font-size: 13px; }
  .evento b { display: block; margin-bottom: 3px; }
  .evento div { color: #444; }
  @media print {
    header, #painel, #mapa, #eventos, .controles { display: none !important; }
    body { background: #fff; }
    #cartoes { margin: 0; }
    .cartao { display: block !important; page-break-after: always; border-radius: 0; padding: 0; }
    body.imprimir-um .cartao:not(.ativo) { display: none !important; }
    th, .selo { -webkit-print-color-adjust: exact; print-color-adjust: exact; }
  }
</style>
</head>
<body>
<header>
  <h1>__TITULO__</h1>
  <div id="resumo"></div>
  <div class="controles">
    <button id="btn-imprimir-um">Imprimir cartão da viatura</button>
    <button id="btn-imprimir-todos">Imprimir todos os cartões</button>
  </div>
</header>
<main>
  <aside id="painel">
    <h2>Viatura</h2><div id="abas"></div>
    <h2>Plano</h2><div id="planos"></div>
    <h2>Faixa horária</h2>
    <input type="range" id="hora" min="0" max="23" step="1">
    <div id="info-hora"></div>
    <div id="linha-do-dia"></div>
    <div class="legenda" id="legenda"></div>
  </aside>
  <div id="mapa"></div>
</main>
<div id="cartoes"></div>
<section id="eventos"><h2>Eventos do dia</h2><div id="lista-eventos"></div></section>

<script src="https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.9.4/leaflet.min.js"></script>
<script>
const DADOS = __DADOS__;
const COR_CLASSE = {1: "#c62828", 2: "#ef6c00", 3: "#1565c0"};
const FUNDO_EMPENHADA = "repeating-linear-gradient(45deg,#777,#777 4px,#bbb 4px,#bbb 8px)";
const estado = {plano: DADOS.planos.atual ? "atual" : "base", viatura: DADOS.viaturas[0].id, hora: DADOS.hora_inicial};
let mapa = null, camadaViaturas = null;

const dois = n => String(n).padStart(2, "0");
const pct = x => Math.round(100 * x) + "%";
const planoAtivo = () => DADOS.planos[estado.plano];
const nomePlano = p => p === "base" ? "Plano base (todas as viaturas livres)" : "Plano atual (depois dos empenhos)";

function iniciarMapa() {
  if (typeof L === "undefined") {
    document.getElementById("mapa").innerHTML =
      "<div class='aviso'>O mapa precisa de internet e não pôde ser carregado. A linha do dia e os cartões abaixo continuam funcionando.</div>";
    return;
  }
  mapa = L.map("mapa", {preferCanvas: true});
  L.tileLayer("https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
              {attribution: "Tiles © Esri", maxZoom: 19}).addTo(mapa);
  DADOS.poligonos.forEach((pol, i) => {                      // fundo: cada hexágono pela prioridade
    const n = DADOS.niveis[i];
    L.polygon(pol, {color: "#ffffff", weight: 0.4, fillColor: DADOS.cores_niveis[n],
                    fillOpacity: n === 0 ? 0.12 : 0.35, interactive: false}).addTo(mapa);
  });
  const contorno = L.geoJSON(DADOS.contorno, {style: {color: "#000", weight: 3, fill: false}}).addTo(mapa);
  mapa.fitBounds(contorno.getBounds());
  camadaViaturas = L.layerGroup().addTo(mapa);
}

function desenharViaturas() {
  if (!mapa) return;
  camadaViaturas.clearLayers();
  const plano = planoAtivo();
  // a viatura selecionada é desenhada por último, para ficar por cima das outras
  const ordem = DADOS.viaturas.slice().sort((a, b) => (a.id === estado.viatura) - (b.id === estado.viatura));
  ordem.forEach(v => {
    const e = plano[v.id][estado.hora];
    if (e.tipo === "empenhada") return;
    const sel = v.id === estado.viatura;
    e.area.forEach(i => L.polygon(DADOS.poligonos[i],
      {stroke: false, fillColor: v.cor, fillOpacity: sel ? 0.5 : 0.2, interactive: false}).addTo(camadaViaturas));
    if (e.lat !== null) {
      L.circleMarker([e.lat, e.lon], {radius: sel ? 10 : 7, color: "#000", weight: 2, fillColor: v.cor, fillOpacity: 1})
        .bindTooltip(v.id + ": " + e.txt).addTo(camadaViaturas);
    }
  });
}

function renderAbas() {
  const div = document.getElementById("abas");
  div.innerHTML = "";
  DADOS.viaturas.forEach(v => {
    const b = document.createElement("button");
    b.className = "aba" + (v.id === estado.viatura ? " ativa" : "");
    b.style.borderLeft = "8px solid " + v.cor;
    b.textContent = v.id + " (" + v.tipo + ")";
    b.onclick = () => { estado.viatura = v.id; atualizar(); };
    div.appendChild(b);
  });
}

function renderPlanos() {
  const div = document.getElementById("planos");
  div.innerHTML = "";
  Object.keys(DADOS.planos).forEach(p => {
    const b = document.createElement("button");
    b.className = "plano" + (p === estado.plano ? " ativo" : "");
    b.textContent = nomePlano(p);
    b.onclick = () => { estado.plano = p; atualizar(); };
    div.appendChild(b);
  });
}

function renderLinha() {
  const div = document.getElementById("linha-do-dia");
  div.innerHTML = "";
  planoAtivo()[estado.viatura].forEach(e => {
    const d = document.createElement("div");
    d.className = "bloco" + (e.h === estado.hora ? " sel" : "");
    d.style.background = e.tipo === "empenhada" ? FUNDO_EMPENHADA : COR_CLASSE[e.classe];
    d.title = e.faixa + ": " + e.txt;
    d.textContent = dois(e.h);
    d.onclick = () => { estado.hora = e.h; atualizar(); };
    div.appendChild(d);
  });
}

function renderInfoHora() {
  const e = planoAtivo()[estado.viatura][estado.hora];
  const c = DADOS.cobertura[estado.plano][estado.hora];
  document.getElementById("info-hora").innerHTML =
    "<b>" + e.faixa + "</b> (Classe " + e.classe + ")<br>" + e.txt +
    "<br><small>Cobertura de todas as viaturas nesta faixa: prioridade " + pct(c.p) + " | território " + pct(c.t) + "</small>";
}

function renderLegenda() {
  let html = "<b>Linha do dia:</b> " +
    "<span class='q' style='background:" + COR_CLASSE[1] + "'></span>Classe 1 " +
    "<span class='q' style='background:" + COR_CLASSE[2] + "'></span>Classe 2 " +
    "<span class='q' style='background:" + COR_CLASSE[3] + "'></span>Classe 3 " +
    "<span class='q' style='background:" + FUNDO_EMPENHADA + "'></span>Empenhada<br><b>Prioridade dos hexágonos:</b> ";
  DADOS.nomes_niveis.forEach((nome, i) => {
    html += "<span class='q' style='background:" + DADOS.cores_niveis[i] + ";border:1px solid #999'></span>" + nome + " ";
  });
  document.getElementById("legenda").innerHTML = html;
}

function renderCartoes() {
  const div = document.getElementById("cartoes");
  div.innerHTML = "";
  DADOS.viaturas.forEach(v => {
    const sec = document.createElement("section");
    sec.className = "cartao" + (v.id === estado.viatura ? " ativo" : "");
    let html = "<h2>Cartão-Programa: " + v.id + " (" + v.tipo + ")</h2>" +
      "<p>" + nomePlano(estado.plano) + ". No ciclo, a viatura fica 20 min parada no ponto-base e 40 min patrulhando em volta; " +
      "nas faixas de polígono, patrulha toda a área indicada. Coordenadas: latitude, longitude.</p>" +
      "<table><tr><th>Faixa</th><th>Classe</th><th>O que fazer</th><th>Onde</th><th>Hexágonos na área</th></tr>";
    planoAtivo()[v.id].forEach(e => {
      const onde = e.lat === null ? "-" :
        "<a href='https://www.google.com/maps?q=" + e.lat + "," + e.lon + "' target='_blank' rel='noopener'>" + e.lat.toFixed(5) + ", " + e.lon.toFixed(5) + "</a>";
      const fundo = e.tipo === "empenhada" ? FUNDO_EMPENHADA : COR_CLASSE[e.classe];
      html += "<tr class='" + (e.tipo === "empenhada" ? "empenhada" : "") + (v.id === estado.viatura && e.h === estado.hora ? " sel" : "") + "'>" +
        "<td>" + e.faixa + "</td><td><span class='selo' style='background:" + fundo + "'>" + e.classe + "</span></td>" +
        "<td>" + e.txt + "</td><td>" + onde + "</td><td>" + e.area.length + "</td></tr>";
    });
    sec.innerHTML = html + "</table>";
    div.appendChild(sec);
  });
}

function renderEventos() {
  const div = document.getElementById("lista-eventos");
  if (!DADOS.eventos.length) { div.innerHTML = "Nenhum evento registrado."; return; }
  div.innerHTML = DADOS.eventos.map(ev =>
    "<div class='evento'><b>" + ev.titulo + "</b>" + ev.linhas.map(l => "<div>" + l + "</div>").join("") + "</div>").join("");
}

function atualizar() {
  document.getElementById("hora").value = estado.hora;
  renderAbas(); renderPlanos(); renderLinha(); renderInfoHora(); renderCartoes(); desenharViaturas();
}

document.getElementById("resumo").textContent = DADOS.resumo;
document.getElementById("hora").oninput = ev => { estado.hora = parseInt(ev.target.value, 10); atualizar(); };
document.getElementById("btn-imprimir-um").onclick = () => { document.body.classList.add("imprimir-um"); window.print(); };
document.getElementById("btn-imprimir-todos").onclick = () => { document.body.classList.remove("imprimir-um"); window.print(); };
window.onafterprint = () => document.body.classList.remove("imprimir-um");
renderLegenda();
renderEventos();
iniciarMapa();
atualizar();
</script>
</body>
</html>
"""
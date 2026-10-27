"""
malha.py  --  Módulos 1 e 2: manipulação dos dados para montagem do mapa e definição das areas
prioritarias.
"""
import json
from collections import Counter
from pathlib import Path
import webbrowser

import folium
from shapely.geometry import shape, Polygon, mapping, Point
from datetime import datetime
from spatial_grid import MalhaHexagonal      # nossa malha hexagonal própria (módulo 2)
from allocation_engine import Operacao, imprimir_relatorio, imprimir_sugestoes   # alocação e despacho (módulo 4)
from cartoes_html import gerar_html          # página HTML com os cartões, para os policiais lerem
from program_cards import (
    classificar_horas, imprimir_cartao, validar_cartoes, pontuacoes_por_hora,   # cartões (módulo 3)
    para_metros, vizinhos_imediatos, ranking_por_hora,                    # geometria e ranking (módulo 3)
    exportar_cartoes,                                                     # grava os cartões em CSV e JSON
    classificar_hexagonos, NIVEIS_PRIORIDADE,                             # níveis de prioridade dos hexágonos
)

DIAMETRO_HEX_M = 200                   # diâmetro do hexágono entre vértices opostos (PDF, seção 5)
ARQ_AREA = "39_cia.geojson"
ARQ_CASOS = "ocorrencias.txt"          # <- nome do seu arquivo de casos

# 1) área e hexágonos recortados (igual à versão anterior)
with open(ARQ_AREA, encoding="utf-8") as f:
    gj = json.load(f)
geom = gj["features"][0]["geometry"]
area = shape(geom)

# a malha começa no centro da área (origem fixa = resultado sempre igual)
min_lon, min_lat, max_lon, max_lat = area.bounds
malha = MalhaHexagonal((min_lat + max_lat) / 2, (min_lon + max_lon) / 2, DIAMETRO_HEX_M)

recortados = {}                                    # hexágono -> a parte dele que está dentro da área
for c in malha.celulas_no_retangulo(min_lon, min_lat, max_lon, max_lat):
    hexa = Polygon(malha.vertices(c))              # hexágono inteiro, como polígono do shapely
    parte = hexa.intersection(area)                # só o pedaço que cai dentro do contorno
    if not parte.is_empty and parte.area > 0:
        recortados[c] = parte
print(len(recortados), "hexágonos | diâmetro medido (vértice a vértice): %.2f m" %
      malha.medir_diametro(next(iter(recortados))))

# 2) lê os casos
with open(ARQ_CASOS, encoding="utf-8-sig") as f:
    bruto = json.load(f)
casos = []
for bloco in (bruto if isinstance(bruto, list) else [bruto]):
    casos.extend(bloco["dados"])
print(len(casos), "casos lidos")

# 3) conta quantos casos caem em cada hexágono
PESOS = {"A": 4, "B": 5, "C": 1, "D": 1, "E": 2, "F": 3}   # <- troque pelos pesos reais

pontuacao = Counter()      # soma dos pesos por hexágono
n_casos = Counter()        # quantidade de casos por hexágono
na_area, so_no_hex, fora = [], [], []
natureza_desconhecida = Counter()
pontuacao_hora = Counter() # soma dos pesos por (hexágono, hora)
perfil_hora = Counter()    # soma dos pesos por hora (as 24 faixas)
casos_hora = Counter()     # quantidade de casos por hora
graves_hora = Counter()    # quantidade de casos graves (peso 4 ou mais) por hora

for caso in casos:
    lat, lon = caso["latLon"]["lat"], caso["latLon"]["lon"]
    nat = str(caso.get("natureza", "")).strip().upper()
    if nat not in PESOS:
        natureza_desconhecida[nat] += 1
        continue                              # caso sem peso definido não entra
    peso = PESOS[nat]
    pt = Point(lon, lat)
    c = malha.celula_de(lat, lon)
    if area.covers(pt):
        pontuacao[c] += peso
        n_casos[c] += 1
        # transforma o texto "31/12/2025 20:07:13" em data/hora de verdade
        data_hora = datetime.strptime(caso["dataHora"], "%d/%m/%Y %H:%M:%S")
        hora = data_hora.hour                 # pega só a hora (no exemplo, 20)
        pontuacao_hora[(c, hora)] += peso     # soma o peso naquele hexágono nessa hora
        perfil_hora[hora] += peso             # soma o peso naquela hora, no território todo
        casos_hora[hora] += 1                 # mais um caso nesta hora
        if peso >= 4:                         # peso 4 ou 5 = códigos A ou B
            graves_hora[hora] += 1
        na_area.append((lat, lon, c, peso))
    elif c in recortados:
        so_no_hex.append((lat, lon, c, peso))
    else:
        fora.append((lat, lon, c, peso))

if natureza_desconhecida:
    print("ATENÇÃO, naturezas sem peso (ignoradas):", dict(natureza_desconhecida))

print("total no arquivo:", bruto[0]["total"] if isinstance(bruto, list) else bruto["total"])
print("casos lidos:", len(casos))
print("dentro da área (contados):", len(na_area))
print("em hexágono de borda, mas fora da área:", len(so_no_hex))
print("fora de qualquer hexágono:", len(fora))

# conferências automáticas: se algo estiver errado, o programa para aqui
assert len(na_area) + len(so_no_hex) + len(fora) == len(casos)
assert sum(n_casos.values()) == len(na_area)
print("peso por hora:", dict(sorted(perfil_hora.items())))

# conferência ponto a ponto: cada caso contado está mesmo dentro do seu hexágono recortado?
erros = 0
for lat, lon, c, _ in na_area:
    if not recortados[c].buffer(1e-9).covers(Point(lon, lat)):
        erros += 1
print("conferência ponto-a-ponto, erros:", erros)

# 4) geometria dos hexágonos: centro de cada um e quem são os vizinhos
centros = {c: malha.centro(c) for c in recortados}         # (lat, lon) do centro de cada hexágono
centros_m = para_metros(centros)                          # os mesmos centros, em metros
viz = vizinhos_imediatos(centros_m)                       # os vizinhos que encostam em cada hexágono

# 5) prioridade de cada hexágono (baixa, média, alta, muito alta) e cores do mapa
pontuacao_suave, nivel_hex, limites = classificar_hexagonos(pontuacao, viz)
# cinza neutro (sem ocorrências), amarelo (baixa), laranja (média), vermelho (alta), roxo (muito alta)
CORES_NIVEL = ["#d9d9d9", "#fff2a8", "#ffb000", "#e03c00", "#6a0f7a"]
print("limites de pontuação dos níveis (Baixa/Média/Alta):", tuple(round(x, 1) for x in limites))
print("hexágonos por nível:", {NIVEIS_PRIORIDADE[n]: sum(1 for x in nivel_hex.values() if x == n) for n in range(5)})

features = [
    {"type": "Feature",
     "properties": {"id": c,
                    "nivel_num": nivel_hex[c],                          # 0 a 4 (usado para escolher a cor)
                    "nivel": NIVEIS_PRIORIDADE[nivel_hex[c]],           # texto que aparece ao passar o mouse
                    "pontuacao_suave": round(pontuacao_suave[c], 1),
                    "casos": n_casos.get(c, 0)},
     "geometry": mapping(p)}
    for c, p in recortados.items()
]
hexagonos = {"type": "FeatureCollection", "features": features}

# 6) cartões-programa (módulo 3)
candidatas = ranking_por_hora(pontuacao_hora, viz)        # melhores quadrículas de cada hora

tabela = classificar_horas(perfil_hora, casos_hora, graves_hora)   # classe de cada hora
for linha in tabela:
    print(f"{linha['posicao']:2d}º  {linha['hora']:02d}h  Classe {linha['classe']}  {linha['atividade']}")

# 7) alocação das viaturas e cenários (módulo 4)
valores = pontuacoes_por_hora(pontuacao_hora, viz)        # pontuação de cada hexágono em cada hora
# <- PLACEHOLDER: o número e os tipos reais das viaturas virão do cenário do hackathon
frota = [
    {"id": "VTR-1", "tipo": "atendimento"}, {"id": "VTR-2", "tipo": "atendimento"},
    {"id": "VTR-3", "tipo": "atendimento"}, {"id": "VTR-4", "tipo": "preventiva"},
    {"id": "VTR-5", "tipo": "preventiva"},
]
op = Operacao(frota, tabela, candidatas, valores, centros_m)   # faz a distribuição inicial
cartoes = op.plano_base                                   # cartões com todas as viaturas livres
imprimir_cartao("VTR-1", cartoes["VTR-1"])                # mostra o cartão da primeira viatura
print("validação dos cartões:", validar_cartoes(cartoes, centros_m))

# grava os cartões na mesma pasta do malha.py (CSV para o Excel, JSON para a interface)
caminhos = exportar_cartoes(cartoes, centros, Path(__file__).resolve().parent)
print("cartões exportados:", [c.name for c in caminhos])

# --- cenário 2: despacho de uma ocorrência (código F, peso 3) no hexágono mais pesado do dia, às 14h ---
mais_pesados = [c for c, _ in pontuacao.most_common(2)]   # os 2 hexágonos de maior peso do dia
op.registrar_ocorrencia(mais_pesados[0], "F", 14)
print("\nOC-1 (código F, peso 3) às 14h. Viaturas sugeridas:")
sugestoes = op.sugerir_viaturas("OC-1", 14)
imprimir_sugestoes(sugestoes)
imprimir_relatorio(op.assumir_ocorrencia("OC-1", sugestoes[0]["viatura"], 14))    # botão "estou indo"

# --- cenário 2b: chega uma ocorrência bem mais grave (código B, peso 5); uma viatura pode trocar ---
op.registrar_ocorrencia(mais_pesados[1], "B", 14)
print("\nOC-2 (código B, peso 5) às 14h. Viaturas sugeridas:")
sugestoes = op.sugerir_viaturas("OC-2", 14)
imprimir_sugestoes(sugestoes)
# escolhe de propósito uma viatura que já está em outra ocorrência (se houver), para mostrar a TROCA:
troca = next((c for c in sugestoes if c["troca"]), sugestoes[0])
imprimir_relatorio(op.assumir_ocorrencia("OC-2", troca["viatura"], 14))           # a OC-1 reabre

# a OC-1 (se reaberta) é assumida por outra viatura; depois as duas ocorrências são encerradas às 16h
reaberta = op.sugerir_viaturas("OC-1", 14)
if reaberta:
    imprimir_relatorio(op.assumir_ocorrencia("OC-1", reaberta[0]["viatura"], 14))
for id_oc in ("OC-2", "OC-1"):                           # botão "ocorrência encerrada"
    relatorio = op.encerrar_ocorrencia(id_oc, 16)
    if relatorio:
        imprimir_relatorio(relatorio)

# --- cenário 3: duas viaturas empenhadas ao mesmo tempo, às 13h ---
op3 = Operacao(frota, tabela, candidatas, valores, centros_m)
for id_oc, celula, codigo in (("OC-1", mais_pesados[0], "F"), ("OC-2", mais_pesados[1], "A")):
    op3.registrar_ocorrencia(celula, codigo, 13)
    primeira = op3.sugerir_viaturas(id_oc, 13)[0]["viatura"]
    imprimir_relatorio(op3.assumir_ocorrencia(id_oc, primeira, 13))

# página HTML com os cartões, no estado do cenário 3 (duas viaturas empenhadas), para os policiais lerem
caminho_html = gerar_html(op3, malha, centros, nivel_hex, gj, Path(__file__).resolve().parent / "cartoes_programa.html",
                          nomes_niveis=NIVEIS_PRIORIDADE, cores_niveis=CORES_NIVEL)
print("página dos cartões:", caminho_html.name)
webbrowser.open(caminho_html.as_uri())                    # abre a página no navegador

# 8) mapa
m = folium.Map(tiles=None)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
    attr="Tiles © Esri", name="Ruas",
).add_to(m)

folium.GeoJson(
    hexagonos, name="Hexágonos",
    style_function=lambda f: {
        "fillColor": CORES_NIVEL[f["properties"]["nivel_num"]],      # cor do nível do hexágono
        "color": "white", "weight": 0.5,
        "fillOpacity": 0.25 if f["properties"]["nivel_num"] == 0 else 0.7,   # sem ocorrências: bem fraco
    },
    tooltip=folium.GeoJsonTooltip(
        fields=["nivel", "pontuacao_suave", "casos"],
        aliases=["Prioridade:", "Pontuação (suavizada):", "Casos:"],
    ),
).add_to(m)

folium.GeoJson(
    gj, name="Contorno",
    style_function=lambda x: {"color": "black", "weight": 3, "fill": False},
).add_to(m)

pontos = folium.FeatureGroup(name="Casos", show=False)
repetidos = Counter((lat, lon) for lat, lon, _, _ in na_area)
pesos_coord = Counter()
for lat, lon, _, peso in na_area:
    pesos_coord[(lat, lon)] += peso

for (lat, lon), n in repetidos.items():
    folium.CircleMarker(
        [lat, lon], radius=3 + min(n, 20) * 0.6,
        color="blue", fill=True, fill_opacity=0.7,
        tooltip=f"{n} caso(s), peso total {pesos_coord[(lat, lon)]}",
    ).add_to(pontos)

for grupo, cor_ponto in ((so_no_hex, "orange"), (fora, "red")):
    for lat, lon, _, _ in grupo:
        folium.CircleMarker(
            [lat, lon], radius=3, color=cor_ponto, fill=True, fill_opacity=0.9,
        ).add_to(pontos)
pontos.add_to(m)
# legenda de cores: uma caixinha HTML fixa no canto da tela
legenda = ('<div style="position: fixed; bottom: 30px; left: 30px; z-index: 9999; background: white; '
           'padding: 8px 10px; border: 1px solid #888; border-radius: 4px; font-size: 13px;">'
           '<b>Prioridade do hexágono</b><br>')
for nome, cor_nivel in zip(NIVEIS_PRIORIDADE, CORES_NIVEL):
    legenda += (f'<span style="background:{cor_nivel}; display:inline-block; width:14px; height:14px; '
                f'margin-right:6px; border:1px solid #999"></span>{nome}<br>')
legenda += '</div>'
m.get_root().html.add_child(folium.Element(legenda))
m.fit_bounds([[min_lat, min_lon], [max_lat, max_lon]])
folium.LayerControl().add_to(m)

arquivo = Path("mapa_casos.html").resolve()
m.save(arquivo)
webbrowser.open(arquivo.as_uri())
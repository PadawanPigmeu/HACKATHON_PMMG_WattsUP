"""
pipeline.py  --  Módulos 1, 2 e 3 reunidos numa função só: carregar_dados().

Lê as ocorrências e o contorno, monta a malha hexagonal, pontua os hexágonos, classifica as horas
e prepara o ranking de quadrículas. É usado tanto pelo malha.py (terminal e mapa) quanto pelo
app.py (interface), assim a lógica fica escrita uma vez só.
"""
import json
from collections import Counter
from datetime import datetime
from pathlib import Path

from shapely.geometry import Point, Polygon, shape

from program_cards import (
    NIVEIS_PRIORIDADE, classificar_hexagonos, classificar_horas, para_metros,
    pontuacoes_por_hora, ranking_por_hora, vizinhos_imediatos,
)
from spatial_grid import MalhaHexagonal
from data_loader import carregar_ocorrencias


def carregar_dados(pasta=".", arq_area="39_cia.geojson", arq_casos="ocorrencias.txt",
                   diametro_m=200, mostrar=True):
    """
    Faz todo o processamento dos dados e devolve um dicionário com os resultados.

    pasta   : pasta onde estão o contorno e as ocorrências
    mostrar : se True, imprime no terminal as conferências (como o malha.py sempre fez)

    Chaves do dicionário devolvido: gj, area, malha, recortados, na_area, so_no_hex, fora,
    pontuacao, n_casos, pontuacao_hora, perfil_hora, casos_hora, graves_hora, centros,
    centros_m, viz, pontuacao_suave, nivel_hex, limites, candidatas, valores, tabela.
    """
    pasta = Path(pasta)

    def dizer(*partes):                                # print que respeita o parâmetro 'mostrar'
        if mostrar:
            print(*partes)

    # 1) área e hexágonos recortados -----------------------------------------------
    with open(pasta / arq_area, encoding="utf-8") as f:
        gj = json.load(f)
    area = shape(gj["features"][0]["geometry"])

    # a malha começa no centro da área (origem fixa = resultado sempre igual)
    min_lon, min_lat, max_lon, max_lat = area.bounds
    malha = MalhaHexagonal((min_lat + max_lat) / 2, (min_lon + max_lon) / 2, diametro_m)

    recortados = {}                                    # hexágono -> a parte dele que está dentro da área
    for c in malha.celulas_no_retangulo(min_lon, min_lat, max_lon, max_lat):
        hexa = Polygon(malha.vertices(c))              # hexágono inteiro, como polígono do shapely
        parte = hexa.intersection(area)                # só o pedaço que cai dentro do contorno
        if not parte.is_empty and parte.area > 0:
            recortados[c] = parte
    dizer(len(recortados), "hexágonos | diâmetro medido (vértice a vértice): %.2f m" %
          malha.medir_diametro(next(iter(recortados))))

    # 2 e 3) Ingestão isolada e mapeamento na malha --------------------------------------
    ocorrencias, natureza_desconhecida = carregar_ocorrencias(pasta / arq_casos)

    pontuacao = Counter()
    n_casos = Counter()
    na_area, so_no_hex, fora = [], [], []
    pontuacao_hora = Counter()
    perfil_hora = Counter()
    casos_hora = Counter()
    graves_hora = Counter()

    for caso in ocorrencias:
        c = malha.celula_de(caso["lat"], caso["lon"])
        if area.covers(caso["ponto"]):
            pontuacao[c] += caso["peso"]
            n_casos[c] += 1
            hora = caso["hora"]
            pontuacao_hora[(c, hora)] += caso["peso"]
            perfil_hora[hora] += caso["peso"]
            casos_hora[hora] += 1
            if caso["peso"] >= 4:
                graves_hora[hora] += 1
            na_area.append((caso["lat"], caso["lon"], c, caso["peso"]))
        elif c in recortados:
            so_no_hex.append((caso["lat"], caso["lon"], c, caso["peso"]))
        else:
            fora.append((caso["lat"], caso["lon"], c, caso["peso"]))

    if natureza_desconhecida:
        dizer("ATENÇÃO, naturezas sem peso (ignoradas):", dict(natureza_desconhecida))
    
    dizer("casos processados:", len(ocorrencias))
    dizer("dentro da área (contados):", len(na_area))
    dizer("em hexágono de borda, mas fora da área:", len(so_no_hex))
    dizer("fora de qualquer hexágono:", len(fora))

    # conferências automáticas: se algo estiver errado, o programa para aqui
    assert len(na_area) + len(so_no_hex) + len(fora) + sum(natureza_desconhecida.values()) == len(ocorrencias)
    assert sum(n_casos.values()) == len(na_area)
    dizer("peso por hora:", dict(sorted(perfil_hora.items())))

    # conferência ponto a ponto: cada caso contado está mesmo dentro do seu hexágono recortado?
    erros = 0
    for lat, lon, c, _ in na_area:
        if not recortados[c].buffer(1e-9).covers(Point(lon, lat)):
            erros += 1
    dizer("conferência ponto-a-ponto, erros:", erros)

    # 4) geometria dos hexágonos: centro de cada um e quem são os vizinhos ----------------
    centros = {c: malha.centro(c) for c in recortados}      # (lat, lon) do centro de cada hexágono
    centros_m = para_metros(centros)                         # os mesmos centros, em metros
    viz = vizinhos_imediatos(centros_m)                      # os vizinhos que encostam em cada hexágono

    # 5) prioridade de cada hexágono (baixa, média, alta, muito alta) -----------------------
    pontuacao_suave, nivel_hex, limites = classificar_hexagonos(pontuacao, viz)
    dizer("limites de pontuação dos níveis (Baixa/Média/Alta):", tuple(round(x, 1) for x in limites))
    dizer("hexágonos por nível:",
          {NIVEIS_PRIORIDADE[n]: sum(1 for x in nivel_hex.values() if x == n) for n in range(5)})

    # 6) horas e ranking de quadrículas (módulo 3) ----------------------------------------
    candidatas = ranking_por_hora(pontuacao_hora, viz)       # melhores quadrículas de cada hora
    valores = pontuacoes_por_hora(pontuacao_hora, viz)       # pontuação de cada hexágono em cada hora
    tabela = classificar_horas(perfil_hora, casos_hora, graves_hora)   # classe de cada hora
    for linha in tabela:
        dizer(f"{linha['posicao']:2d}º  {linha['hora']:02d}h  Classe {linha['classe']}  {linha['atividade']}")

    return {
        "gj": gj, "area": area, "malha": malha, "recortados": recortados,
        "na_area": na_area, "so_no_hex": so_no_hex, "fora": fora,
        "pontuacao": pontuacao, "n_casos": n_casos, "pontuacao_hora": pontuacao_hora,
        "perfil_hora": perfil_hora, "casos_hora": casos_hora, "graves_hora": graves_hora,
        "centros": centros, "centros_m": centros_m, "viz": viz,
        "pontuacao_suave": pontuacao_suave, "nivel_hex": nivel_hex, "limites": limites,
        "candidatas": candidatas, "valores": valores, "tabela": tabela,
    }
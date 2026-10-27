import json
from datetime import datetime
from shapely.geometry import Point

PESOS = {"A": 4, "B": 5, "C": 1, "D": 1, "E": 2, "F": 3}

def carregar_ocorrencias(caminho_arquivo):
    with open(caminho_arquivo, encoding="utf-8-sig") as f:
        bruto = json.load(f)
        
    casos_brutos = []
    for bloco in (bruto if isinstance(bruto, list) else [bruto]):
        casos_brutos.extend(bloco["dados"])

    ocorrencias = []
    naturezas_desconhecidas = {}

    for caso in casos_brutos:
        lat = caso["latLon"]["lat"]
        lon = caso["latLon"]["lon"]
        nat = str(caso.get("natureza", "")).strip().upper()
        
        if nat not in PESOS:
            naturezas_desconhecidas[nat] = naturezas_desconhecidas.get(nat, 0) + 1
            continue
            
        data_hora = datetime.strptime(caso["dataHora"], "%d/%m/%Y %H:%M:%S")
        
        ocorrencias.append({
            "lat": lat,
            "lon": lon,
            "ponto": Point(lon, lat),
            "natureza": nat,
            "peso": PESOS[nat],
            "data_hora": data_hora,
            "hora": data_hora.hour
        })
        
    return ocorrencias, naturezas_desconhecidas
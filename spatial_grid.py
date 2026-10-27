"""
spatial_grid.py  --  Módulo 2: malha hexagonal PRÓPRIA (sem h3), com a medida exata do PDF.

O PDF pede hexágonos de 200 m de diâmetro, medidos entre vértices opostos. O H3 só oferece
tamanhos fixos (cerca de 130 m ou 350 m), então aqui construímos a malha nós mesmos.

COMO FUNCIONA (a ideia em 4 passos)
  1. Trabalhamos em METROS: convertemos latitude/longitude para x/y a partir de um ponto de
     origem (o centro da área), usando as fórmulas do elipsóide WGS84 (erro desprezível).
  2. Hexágonos "de pé" (com uma ponta para cima) se encaixam como favo de mel. Cada um recebe
     duas coordenadas inteiras (q, r): q anda na horizontal e r anda nas linhas.
  3. Se o diâmetro entre vértices opostos é 200 m, a ARESTA mede 100 m. A distância entre os
     centros de dois hexágonos vizinhos é aresta * raiz(3) = 173,2 m.
  4. Para saber em qual hexágono um ponto cai, fazemos a conta inversa e arredondamos para o
     hexágono mais próximo.

Este arquivo não depende de nenhuma biblioteca externa (só 'math'). O corte da malha no
contorno da área (que usa shapely) fica no malha.py.
"""
import math

RAIZ3 = math.sqrt(3)


def metros_por_grau(lat):
    """
    Quantos metros vale 1 grau de latitude e 1 grau de longitude na latitude 'lat'.
    Fórmulas padrão do elipsóide WGS84 (o mesmo "formato da Terra" do GPS).
    """
    fi = math.radians(lat)
    por_grau_lat = 111132.92 - 559.82 * math.cos(2 * fi) + 1.175 * math.cos(4 * fi) - 0.0023 * math.cos(6 * fi)
    por_grau_lon = 111412.84 * math.cos(fi) - 93.5 * math.cos(3 * fi) + 0.118 * math.cos(5 * fi)
    return por_grau_lat, por_grau_lon


def distancia_geodesica_m(lat1, lon1, lat2, lon2):
    """
    Distância REAL em metros entre dois pontos da Terra, medida sobre o elipsóide WGS84
    (fórmula de Vincenty). Serve para CONFERIR a malha por um caminho independente da
    conversão que a própria malha usa. (A fórmula de haversine trata a Terra como esfera
    perfeita e erra uns 0,4% aqui, então não serve para conferir uma medida de 200 m.)
    """
    a = 6378137.0                    # raio do equador (m)
    f = 1 / 298.257223563            # achatamento da Terra
    b = (1 - f) * a                  # raio polar (m)
    L = math.radians(lon2 - lon1)
    u1 = math.atan((1 - f) * math.tan(math.radians(lat1)))
    u2 = math.atan((1 - f) * math.tan(math.radians(lat2)))
    sen_u1, cos_u1, sen_u2, cos_u2 = math.sin(u1), math.cos(u1), math.sin(u2), math.cos(u2)
    lam = L
    for _ in range(200):             # a fórmula se refina repetindo a conta até estabilizar
        sen_lam, cos_lam = math.sin(lam), math.cos(lam)
        sen_sigma = math.hypot(cos_u2 * sen_lam, cos_u1 * sen_u2 - sen_u1 * cos_u2 * cos_lam)
        if sen_sigma == 0:
            return 0.0
        cos_sigma = sen_u1 * sen_u2 + cos_u1 * cos_u2 * cos_lam
        sigma = math.atan2(sen_sigma, cos_sigma)
        sen_alfa = cos_u1 * cos_u2 * sen_lam / sen_sigma
        cos2_alfa = 1 - sen_alfa ** 2
        cos_2sm = cos_sigma - 2 * sen_u1 * sen_u2 / cos2_alfa if cos2_alfa != 0 else 0.0
        c = f / 16 * cos2_alfa * (4 + f * (4 - 3 * cos2_alfa))
        lam_anterior = lam
        lam = L + (1 - c) * f * sen_alfa * (sigma + c * sen_sigma * (cos_2sm + c * cos_sigma * (-1 + 2 * cos_2sm ** 2)))
        if abs(lam - lam_anterior) < 1e-12:
            break
    u_quadrado = cos2_alfa * (a * a - b * b) / (b * b)
    A = 1 + u_quadrado / 16384 * (4096 + u_quadrado * (-768 + u_quadrado * (320 - 175 * u_quadrado)))
    B = u_quadrado / 1024 * (256 + u_quadrado * (-128 + u_quadrado * (74 - 47 * u_quadrado)))
    delta_sigma = B * sen_sigma * (cos_2sm + B / 4 * (cos_sigma * (-1 + 2 * cos_2sm ** 2)
                  - B / 6 * cos_2sm * (-3 + 4 * sen_sigma ** 2) * (-3 + 4 * cos_2sm ** 2)))
    return b * A * (sigma - delta_sigma)


class MalhaHexagonal:
    """
    Malha de hexágonos regulares com 'diametro_m' entre vértices opostos.

    lat0, lon0 : ponto de origem da malha (usamos o centro da área). Fixar a origem faz a
                 malha ser sempre a mesma para a mesma área (resultado reproduzível).
    Cada hexágono é identificado por um texto "q_r", por exemplo "12_-5".
    """

    def __init__(self, lat0, lon0, diametro_m=200.0):
        self.lat0, self.lon0 = lat0, lon0
        self.diametro_m = diametro_m
        self.aresta = diametro_m / 2                      # num hexágono regular, aresta = raio = diâmetro / 2
        self._m_lat, self._m_lon = metros_por_grau(lat0)  # metros por grau, calculados uma vez

    # ---- conversões entre graus e metros -------------------------------------------
    def _para_metros(self, lat, lon):
        return (lon - self.lon0) * self._m_lon, (lat - self.lat0) * self._m_lat

    def _para_graus(self, x, y):
        return self.lat0 + y / self._m_lat, self.lon0 + x / self._m_lon

    # ---- identificação das células ----------------------------------------------------
    @staticmethod
    def _separar(celula):
        q, r = celula.split("_")
        return int(q), int(r)

    def celula_de(self, lat, lon):
        """Em qual hexágono o ponto (lat, lon) cai? Devolve o identificador "q_r"."""
        x, y = self._para_metros(lat, lon)
        q = (RAIZ3 / 3 * x - y / 3) / self.aresta         # coordenadas fracionadas
        r = (2 / 3 * y) / self.aresta
        # Arredondamento "cúbico": arredonda as três coordenadas (q, r, s = -q-r) e corrige
        # a que ficou com o maior erro, garantindo q + r + s = 0. Isso acha o hexágono certo.
        s = -q - r
        rq, rr, rs = round(q), round(r), round(s)
        dq, dr, ds = abs(rq - q), abs(rr - r), abs(rs - s)
        if dq > dr and dq > ds:
            rq = -rr - rs
        elif dr > ds:
            rr = -rq - rs
        return f"{int(rq)}_{int(rr)}"

    def centro(self, celula):
        """Centro do hexágono, como (lat, lon)."""
        q, r = self._separar(celula)
        x = self.aresta * RAIZ3 * (q + r / 2)
        y = self.aresta * 1.5 * r
        return self._para_graus(x, y)

    def vertices(self, celula):
        """Os 6 cantos do hexágono, como lista de (lon, lat) (a ordem que o shapely espera)."""
        q, r = self._separar(celula)
        cx = self.aresta * RAIZ3 * (q + r / 2)
        cy = self.aresta * 1.5 * r
        cantos = []
        for i in range(6):
            angulo = math.radians(60 * i - 30)            # hexágono "de pé": cantos a -30°, 30°, 90°...
            lat, lon = self._para_graus(cx + self.aresta * math.cos(angulo), cy + self.aresta * math.sin(angulo))
            cantos.append((lon, lat))
        return cantos

    def celulas_no_retangulo(self, min_lon, min_lat, max_lon, max_lat):
        """
        Todos os hexágonos que podem tocar o retângulo dado (com uma folga de 1 célula).
        Depois o malha.py descarta os que não tocam a área de verdade.
        """
        xs, ys = zip(*[self._para_metros(la, lo) for la in (min_lat, max_lat) for lo in (min_lon, max_lon)])
        r_min = math.floor(min(ys) / (1.5 * self.aresta)) - 1
        r_max = math.ceil(max(ys) / (1.5 * self.aresta)) + 1
        celulas = []
        for r in range(r_min, r_max + 1):
            q_min = math.floor(min(xs) / (RAIZ3 * self.aresta) - r / 2) - 1
            q_max = math.ceil(max(xs) / (RAIZ3 * self.aresta) - r / 2) + 1
            for q in range(q_min, q_max + 1):
                celulas.append(f"{q}_{r}")
        return celulas

    # ---- conferências de medida (úteis para a documentação) --------------------------------
    def medir_diametro(self, celula):
        """
        Mede com a distância geodésica real (independente da nossa conta) a distância entre
        vértices opostos do hexágono. Deve dar o valor pedido, por exemplo 200 m.
        """
        v = self.vertices(celula)
        medidas = [distancia_geodesica_m(v[i][1], v[i][0], v[i + 3][1], v[i + 3][0]) for i in range(3)]
        return sum(medidas) / 3

    def medir_espacamento(self, celula_a, celula_b):
        """Distância em metros entre os centros de duas células (vizinhas: aresta * raiz(3))."""
        (la1, lo1), (la2, lo2) = self.centro(celula_a), self.centro(celula_b)
        return distancia_geodesica_m(la1, lo1, la2, lo2)


if __name__ == "__main__":
    malha = MalhaHexagonal(-19.85, -44.0, 200)
    c = malha.celula_de(-19.85, -44.0)
    print("célula da origem:", c, "| centro:", malha.centro(c))
    print("diâmetro medido (vértice a vértice): %.2f m" % malha.medir_diametro(c))
    print("distância entre centros de vizinhos: %.2f m (esperado %.2f)" % (malha.medir_espacamento("0_0", "1_0"), 100 * RAIZ3))
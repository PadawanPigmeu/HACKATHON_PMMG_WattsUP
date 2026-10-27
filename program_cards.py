"""
program_cards.py  --  Módulo 3: cartões-programa.

PARTE 1  Classificar as 24 horas do dia em Classe 1, 2 e 3 (com desempates).
PARTE 2  Geometria e ranking: quais hexágonos estão num raio de X km, e qual é
         a lista de quadrículas candidatas de cada hora (com suavização).
PARTE 3  Cartão-Programa de cada viatura: escolhe a quadrícula de cada hora com
         alternância por viatura, define a área de patrulha, valida as regras e
         exporta os cartões (CSV e JSON).

Nada aqui depende de h3 nem do tipo de malha: tudo funciona com um dicionário
{hexágono: (lat, lon)} com o centro de cada quadrícula. Assim, se o grupo trocar
a malha H3 por uma malha própria de 200 m, este arquivo continua igual.
"""

import csv                             # escrever tabelas CSV (abrem no Excel)
import json                            # escrever arquivos JSON (usados pela interface)
import math                            # funções matemáticas (hipotenusa, cosseno...)
from pathlib import Path               # trabalhar com pastas e nomes de arquivo
from spatial_grid import metros_por_grau   # conversão precisa de graus para metros (módulo 2)
from collections import Counter, defaultdict   # Counter = "caderno de somas"; defaultdict = dicionário que cria listas vazias sozinho
from functools import cmp_to_key       # ferramenta para ordenar com uma regra nossa

# ---------------------------------------------------------------------------
# 1) CONSTANTES (valores que podemos ajustar sem mexer na lógica)
# ---------------------------------------------------------------------------
# Se duas horas empatam no peso e a diferença de casos for IGUAL OU MAIOR que
# este número, a quantidade de casos decide. Se for menor, decide a gravidade.
LIMIAR_CASOS = 10

# Um caso é "grave" se o peso dele for pelo menos 4 (códigos A=4 e B=5).
PESO_GRAVE = 4

# A noite crítica começa às 19h e vai até 5h. Dentro dela há duas partes:
#   - o NÚCLEO (19h às 23h): onde a proporção de casos graves é maior;
#   - a MADRUGADA (0h às 5h): risco elevado, mas sem tendência clara entre as horas.
NUCLEO_CRITICO = {19, 20, 21, 22, 23}
MADRUGADA = {0, 1, 2, 3, 4, 5}
# Hora em que a noite crítica começa (para contar "quanto da noite já passou").
INICIO_NOITE = 19

# Atividades possíveis em cada hora (textos que vão aparecer nos cartões).
ATIVIDADE_CICLO = "ponto-base 20 min + patrulha 40 min (raio 1 km)"
ATIVIDADE_2KM = "patrulhamento no entorno de até 2 km"
ATIVIDADE_3KM = "patrulhamento no entorno de até 3 km"


# ---------------------------------------------------------------------------
# 2) ÚLTIMO CRITÉRIO DE DESEMPATE (só é usado se peso, casos e gravidade empatarem)
# ---------------------------------------------------------------------------
def nivel_noite(hora):
    """
    Em que parte do dia a hora está:
      2 = núcleo crítico (19h às 23h)  -> mais forte
      1 = madrugada (0h às 5h)
      0 = fora da noite crítica (6h às 18h)
    """
    if hora in NUCLEO_CRITICO:
        return 2
    if hora in MADRUGADA:
        return 1
    return 0


def desempate_final(a, b, casos, graves):
    """
    Decide entre duas horas totalmente empatadas. Devolve -1 se 'a' vem antes.

    - Níveis diferentes: o nível maior vence (núcleo > madrugada > resto do dia).
    - As duas na madrugada: vence a de maior proporção de casos graves
      (graves / casos). Se ainda empatar, vence a hora mais próxima do núcleo
      (0h antes de 5h), porque o risco vai caindo depois do pico da noite.
      Esse último passo é uma CONVENÇÃO nossa e deve ser documentada assim.
    - As duas no núcleo: vence a mais tarde (23h vence 19h), porque o risco
      cresce ao longo do início da noite.
    - As duas fora da noite crítica: vence a mais tarde (18h vence 11h).
    """
    na, nb = nivel_noite(a), nivel_noite(b)
    if na != nb:
        return -1 if na > nb else 1

    if na == 1:  # as duas na madrugada
        # "if casos[a]" evita dividir por zero numa hora sem nenhum caso.
        prop_a = graves[a] / casos[a] if casos[a] else 0
        prop_b = graves[b] / casos[b] if casos[b] else 0
        if prop_a != prop_b:
            return -1 if prop_a > prop_b else 1
        return -1 if a < b else 1          # hora menor = mais perto do núcleo

    if na == 2:  # as duas no núcleo: conta quantas horas passaram desde as 19h
        return -1 if (a - INICIO_NOITE) % 24 > (b - INICIO_NOITE) % 24 else 1

    return -1 if a > b else 1              # fora da noite crítica: a mais tarde


# ---------------------------------------------------------------------------
# 3) COMPARAR DUAS HORAS (o "juiz" da ordenação)
# ---------------------------------------------------------------------------
def comparar_horas(a, b, peso, casos, graves):
    """
    Compara as horas a e b. Devolve:
      -1  se a deve vir ANTES (é mais incidente)
      +1  se b deve vir antes
    Os critérios são testados em ordem; o primeiro que diferenciar decide.
    (Em casos raríssimos de 3 ou mais horas empatadas, esta regra pode não ser
    perfeitamente consistente; para o nosso uso isso é aceitável.)
    """
    # Critério 1: maior peso total vence.
    if peso[a] != peso[b]:
        return -1 if peso[a] > peso[b] else 1

    # Critério 2: empate no peso. Se a diferença de casos for grande, mais casos vence.
    diferenca = casos[a] - casos[b]
    if abs(diferenca) >= LIMIAR_CASOS:
        return -1 if diferenca > 0 else 1

    # Critério 3: diferença pequena de casos, então vence quem tem mais casos graves.
    if graves[a] != graves[b]:
        return -1 if graves[a] > graves[b] else 1

    # Critério 4 (final): regra da noite crítica (ver desempate_final).
    return desempate_final(a, b, casos, graves)


# ---------------------------------------------------------------------------
# 4) FUNÇÃO PRINCIPAL DESTA PARTE
# ---------------------------------------------------------------------------
def classificar_horas(perfil_hora, casos_hora, graves_hora):
    """
    Entrada (três 'cadernos de somas', um número por hora):
      perfil_hora : soma dos pesos por hora   (já existe no malha.py)
      casos_hora  : quantidade de casos por hora
      graves_hora : quantidade de casos graves (peso >= 4) por hora

    Saída: lista com 24 itens, da hora mais incidente para a menos incidente.
    Cada item é um dicionário com: posicao, hora, classe e atividade.
    """
    # Counter(...) devolve 0 para uma hora que não aparece, em vez de dar erro.
    peso, casos, graves = Counter(perfil_hora), Counter(casos_hora), Counter(graves_hora)

    # Ordena as 24 horas usando o nosso "juiz".
    ordem = sorted(
        range(24),
        key=cmp_to_key(lambda a, b: comparar_horas(a, b, peso, casos, graves)),
    )

    resultado = []
    for posicao, hora in enumerate(ordem):      # posicao vai de 0 a 23
        if posicao < 8:                         # as 8 primeiras
            classe, atividade = 1, ATIVIDADE_CICLO
        elif posicao < 16:                      # as 8 seguintes
            classe = 2
            # Na Classe 2: as 4 mais incidentes usam o ciclo, as outras 4 usam 2 km.
            atividade = ATIVIDADE_CICLO if posicao < 12 else ATIVIDADE_2KM
        else:                                   # as 8 últimas
            classe, atividade = 3, ATIVIDADE_3KM

        resultado.append(
            {"posicao": posicao + 1, "hora": hora, "classe": classe, "atividade": atividade}
        )
    return resultado


# ---------------------------------------------------------------------------
# PARTE 2 -- GEOMETRIA E RANKING DE QUADRÍCULAS
# ---------------------------------------------------------------------------
FRACAO_VIZINHOS = 0.5   # quanto do peso dos vizinhos entra na pontuação (0 = ignora vizinhos)
TOP_CANDIDATAS = 60     # quantas quadrículas candidatas guardar por hora


def para_metros(centros_latlon):
    """
    Converte {hexágono: (lat, lon)} em {hexágono: (x, y)}, com x e y em METROS,
    contados a partir do ponto médio da área.

    Por quê? Distâncias em metros são contas simples (Pitágoras). Numa área de
    poucos km, o erro dessa conversão é muito menor que 1%.
    """
    lat0 = sum(lat for lat, lon in centros_latlon.values()) / len(centros_latlon)
    lon0 = sum(lon for lat, lon in centros_latlon.values()) / len(centros_latlon)
    # metros por grau naquela latitude (fórmulas do elipsóide WGS84, as mesmas da malha)
    metros_por_grau_lat, metros_por_grau_lon = metros_por_grau(lat0)
    return {
        hexagono: ((lon - lon0) * metros_por_grau_lon, (lat - lat0) * metros_por_grau_lat)
        for hexagono, (lat, lon) in centros_latlon.items()
    }


def hexagonos_no_raio(celula, raio_m, centros_m):
    """
    Devolve a lista de hexágonos cujo CENTRO está a até 'raio_m' metros do centro
    de 'celula' (incluindo ela mesma). Usa 1000 para 1 km, 2000 para 2 km etc.
    Como é por distância, funciona com qualquer resolução ou malha.
    """
    x0, y0 = centros_m[celula]
    return [
        outro
        for outro, (x, y) in centros_m.items()
        if math.hypot(x - x0, y - y0) <= raio_m      # hypot = distância em linha reta
    ]


def uniao_no_raio(celulas, raio_m, centros_m):
    """Hexágonos a até 'raio_m' de QUALQUER uma das 'celulas' (usado nos polígonos de 2 e 3 km)."""
    resultado = set()                                 # set = conjunto, não repete elementos
    for celula in celulas:
        resultado.update(hexagonos_no_raio(celula, raio_m, centros_m))
    return resultado


def estimar_espacamento(centros_m):
    """
    Distância típica entre um hexágono e o vizinho mais próximo (em metros).
    Olha uma amostra de até 200 hexágonos e pega a mediana.
    """
    amostra = list(centros_m)[:: max(1, len(centros_m) // 200)]
    menores = []
    for celula in amostra:
        x0, y0 = centros_m[celula]
        menores.append(min(
            math.hypot(x - x0, y - y0)
            for outro, (x, y) in centros_m.items() if outro != celula
        ))
    menores.sort()
    return menores[len(menores) // 2]                 # o valor do meio = mediana


def vizinhos_imediatos(centros_m):
    """
    Para cada hexágono, a lista dos vizinhos que encostam nele (em geral 6).
    Num hexágono, os vizinhos estão a 1 'espaçamento' e os do segundo anel a
    1,73; então um raio de 1,5 espaçamento pega exatamente o primeiro anel.
    """
    raio = 1.5 * estimar_espacamento(centros_m)
    return {
        celula: [o for o in hexagonos_no_raio(celula, raio, centros_m) if o != celula]
        for celula in centros_m
    }


NIVEIS_PRIORIDADE = ["Sem ocorrências", "Baixa", "Média", "Alta", "Muito alta"]
CORTES_PERCENTIL = (0.50, 0.80, 0.95)   # limites dos níveis, entre os hexágonos que têm pontuação


def classificar_hexagonos(pontuacao_dia, vizinhos, fracao=FRACAO_VIZINHOS, cortes=CORTES_PERCENTIL):
    """
    Dá a cada hexágono um NÍVEL DE PRIORIDADE (seção 6 do PDF), olhando o dia inteiro.

    Passo 1: pontuação suavizada = peso do hexágono + fracao * média do peso dos vizinhos
             (a mesma ideia do ranking por hora).
    Passo 2: ignora os hexágonos com pontuação 0 (nível 0, "Sem ocorrências") e ordena os
             demais. Os limites são percentis:
                 até o 50º percentil      -> nível 1, Baixa
                 do 50º ao 80º            -> nível 2, Média
                 do 80º ao 95º            -> nível 3, Alta
                 acima do 95º             -> nível 4, Muito alta
             Como os limites acompanham os dados, o critério é fácil de explicar e
             funciona com qualquer quantidade de ocorrências.

    pontuacao_dia : {hexágono: soma dos pesos} (o 'pontuacao' do malha.py)
    Devolve (pontuacao_suavizada, niveis, limites):
        pontuacao_suavizada : {hexágono: pontuação}
        niveis              : {hexágono: 0 a 4}
        limites             : (p50, p80, p95), as pontuações que separam os níveis
    """
    suavizada = {}
    for hexagono, lista_vizinhos in vizinhos.items():
        proprio = pontuacao_dia.get(hexagono, 0)
        media = sum(pontuacao_dia.get(v, 0) for v in lista_vizinhos) / len(lista_vizinhos) if lista_vizinhos else 0
        suavizada[hexagono] = proprio + fracao * media

    positivas = sorted(p for p in suavizada.values() if p > 0)
    if not positivas:
        return suavizada, {h: 0 for h in suavizada}, (0, 0, 0)
    # int(0.5 * quantidade) = posição do meio da lista ordenada; min(...) evita passar do fim
    limites = tuple(positivas[min(len(positivas) - 1, int(c * len(positivas)))] for c in cortes)

    niveis = {}
    for hexagono, p in suavizada.items():
        if p <= 0:
            niveis[hexagono] = 0
        elif p <= limites[0]:
            niveis[hexagono] = 1
        elif p <= limites[1]:
            niveis[hexagono] = 2
        elif p <= limites[2]:
            niveis[hexagono] = 3
        else:
            niveis[hexagono] = 4
    return suavizada, niveis, limites


def pontuacoes_por_hora(pontuacao_hora, vizinhos, fracao=FRACAO_VIZINHOS):
    """
    Pontuação suavizada de TODOS os hexágonos em cada hora: {hora: {hexágono: pontuação}}.

    Pontuação = peso do hexágono naquela hora + fracao * média do peso dos vizinhos naquela
    hora. Só entram hexágonos com pontuação maior que zero. É a base do ranking por hora e
    também do cálculo de cobertura do módulo 4.
    """
    por_hora = defaultdict(dict)          # hora -> {hexágono: peso}
    for (hexagono, hora), peso in pontuacao_hora.items():
        por_hora[hora][hexagono] = peso
    valores = {}
    for hora in range(24):
        base = por_hora.get(hora, {})     # pesos desta hora (vazio se não houve casos)
        pontuacoes = {}
        for hexagono, lista_vizinhos in vizinhos.items():
            proprio = base.get(hexagono, 0)
            if lista_vizinhos:
                media_vizinhos = sum(base.get(v, 0) for v in lista_vizinhos) / len(lista_vizinhos)
            else:
                media_vizinhos = 0
            total = proprio + fracao * media_vizinhos
            if total > 0:
                pontuacoes[hexagono] = total
        valores[hora] = pontuacoes
    return valores


def ranking_por_hora(pontuacao_hora, vizinhos, fracao=FRACAO_VIZINHOS, top=TOP_CANDIDATAS):
    """
    Para cada hora (0 a 23), monta a lista das melhores quadrículas, da mais
    prioritária para a menos (usa pontuacoes_por_hora).

    pontuacao_hora : {(hexágono, hora): peso}   (vem do malha.py)
    vizinhos       : saída de vizinhos_imediatos()

    Desempates: maior peso do dia inteiro, depois o nome do hexágono (só para o
    resultado ser sempre igual).

    Devolve {hora: [(hexágono, pontuação), ...]} só com pontuação maior que zero.
    """
    peso_dia = Counter()                  # peso de cada hexágono somando as 24 horas
    for (hexagono, hora), peso in pontuacao_hora.items():
        peso_dia[hexagono] += peso
    valores = pontuacoes_por_hora(pontuacao_hora, vizinhos, fracao)
    candidatas = {}
    for hora in range(24):
        ordenadas = sorted(
            valores[hora].items(),
            key=lambda item: (-item[1], -peso_dia[item[0]], str(item[0])),   # o "-" inverte: maior primeiro
        )
        candidatas[hora] = ordenadas[:top]
    return candidatas


# ---------------------------------------------------------------------------
# PARTE 3 -- CARTÃO-PROGRAMA DE CADA VIATURA
# ---------------------------------------------------------------------------
RAIO_CICLO_M = 1000     # patrulha do ciclo 20+40: até 1 km da quadrícula-base
RAIO_2KM_M = 2000       # polígono de até 2 km (4 horas da Classe 2)
RAIO_3KM_M = 3000       # polígono de até 3 km (Classe 3)
SEPARACAO_MIN_M = 1000  # bases de viaturas diferentes, na mesma hora, ficam a pelo menos isto de
                        # distância (se possível). É um primeiro cuidado com a COBERTURA; o módulo 4
                        # vai refinar o equilíbrio entre prioridade e cobertura.
# REGRA ENDURECIDA: uma viatura só pode voltar a uma quadrícula-base depois de usar pelo menos
# este número de quadrículas DISTINTAS (o PDF exige no mínimo 1; usamos 2 para ficar com folga).
OUTRAS_DISTINTAS_ANTES_DE_REPETIR = 2
# COBERTURA DA BASE: pelo menos esta fração do raio de 1 km deve cair DENTRO da área da companhia.
# Uma base encostada no contorno desperdiça metade da patrulha fora da área. Se nenhuma candidata
# cumprir isso na hora, a regra é relaxada (nunca deixamos uma viatura sem base).
COBERTURA_MIN_BASE = 0.6


def distancia_entre(a, b, centros_m):
    """Distância em metros entre os centros dos hexágonos a e b."""
    (xa, ya), (xb, yb) = centros_m[a], centros_m[b]
    return math.hypot(xa - xb, ya - yb)


def cobertura_das_celulas(centros_m, raio_m):
    """
    Para cada hexágono, que fração do raio completo cai dentro da área (de 0 a 1).

    Conta quantos hexágonos da área estão a até 'raio_m' do centro dele e divide pelo maior
    valor encontrado em toda a área (o de um hexágono bem no interior, com o círculo inteiro
    dentro). Exemplo: 59 hexágonos num raio onde o máximo é 121 dá 0,49 (49%).
    """
    contagens = {c: len(hexagonos_no_raio(c, raio_m, centros_m)) for c in centros_m}
    maximo = max(contagens.values())
    return {c: n / maximo for c, n in contagens.items()}


def escolher_quadricula(lista_candidatas, proibidas, outras_bases, centros_m, separacao_m=SEPARACAO_MIN_M,
                        cobertura=None, cobertura_min=0.0):
    """
    Escolhe a melhor quadrícula da lista (já ordenada da melhor para a pior) que
    respeite as regras:
      - não pode estar em 'proibidas' (ex.: a quadrícula da hora anterior da viatura);
      - não pode ser a mesma que outra viatura já escolheu nesta hora ('outras_bases');
      - se 'cobertura' for dada, precisa ter cobertura >= cobertura_min (não pode ficar
        encostada no contorno da área);
      - deve ficar a pelo menos 'separacao_m' das 'outras_bases'.
    As regras de cobertura e separação são DESEJÁVEIS: se nenhuma candidata cumprir tudo,
    relaxamos primeiro a separação e depois a cobertura (é melhor ter uma quadrícula do que
    nenhuma). As regras de 'proibidas' e 'outras_bases' nunca são relaxadas.
    Devolve a quadrícula ou None.
    """
    # Cada rodada é (exigir cobertura?, exigir separação?). Vai relaxando de uma para a outra.
    for exigir_cobertura, exigir_separacao in ((True, True), (True, False), (False, False)):
        for hexagono, pontuacao in lista_candidatas:
            if hexagono in proibidas or hexagono in outras_bases:
                continue                                # "continue" pula para a próxima candidata
            if exigir_cobertura and cobertura is not None and cobertura[hexagono] < cobertura_min:
                continue
            if exigir_separacao and any(
                distancia_entre(hexagono, outra, centros_m) < separacao_m for outra in outras_bases
            ):
                continue
            return hexagono
    return None


def gerar_cartoes(viaturas, classificacao, candidatas, centros_m, cobertura_min_base=COBERTURA_MIN_BASE,
                  escolher=None, fixos=None, a_partir_da_hora=0):
    """
    Monta o Cartão-Programa de cada viatura.

    viaturas      : lista de nomes, por exemplo ["VTR-1", "VTR-2", "VTR-3"]
    classificacao : saída de classificar_horas()
    candidatas    : saída de ranking_por_hora()
    centros_m     : saída de para_metros()

    Parâmetros do módulo 4 (todos opcionais):
      escolher         : função que escolhe a quadrícula de cada viatura. Se não for dada, usa
                         a regra simples "melhor candidata válida". O módulo 4 passa uma função
                         que escolhe pela COBERTURA ponderada pela prioridade.
      fixos            : cartões já existentes ({viatura: {hora: entrada}}). As horas ANTERIORES
                         a 'a_partir_da_hora' são copiadas daqui (o passado não muda).
      a_partir_da_hora : primeira hora a (re)planejar. Com 0, planeja o dia inteiro.

    Devolve {viatura: {hora: entrada}}. Cada entrada traz: hora, faixa, classe,
    atividade, quadricula (a base ou o centro do polígono), raio_m, minutos_base,
    minutos_patrulha e area (hexágonos que a viatura cobre naquela hora).

    REGRAS DE ALTERNÂNCIA (versão endurecida; valem dentro do cartão de cada viatura):
      1. Sequência de ciclo: as horas com ciclo, em ordem do relógio, formam uma sequência
         circular (depois da última do dia vem a primeira do dia seguinte). Uma base só pode
         voltar depois de pelo menos OUTRAS_DISTINTAS_ANTES_DE_REPETIR bases distintas.
      2. Relógio: a mesma quadrícula não pode aparecer em duas horas vizinhas do cartão
         (h e h+1, incluindo 23h e 0h), seja como base ou como centro de polígono.
    Assim as duas leituras possíveis de "faixas consecutivas" ficam atendidas.

    COBERTURA: a base precisa ter pelo menos 'cobertura_min_base' (60%) do raio de 1 km dentro da
    área da companhia; os polígonos de 2 e 3 km não passam por esse filtro.
    """
    if not viaturas:
        return {}
    n = len(viaturas)
    k = OUTRAS_DISTINTAS_ANTES_DE_REPETIR
    classe_de = {item["hora"]: item["classe"] for item in classificacao}
    atividade_de = {item["hora"]: item["atividade"] for item in classificacao}

    horas_ciclo = sorted(h for h in range(24) if atividade_de[h] == ATIVIDADE_CICLO)
    horas_poligono = sorted(h for h in range(24) if atividade_de[h] != ATIVIDADE_CICLO)
    horas_classe1 = [h for h in range(24) if classe_de[h] == 1]
    total_ciclo = len(horas_ciclo)
    cobertura_base = cobertura_das_celulas(centros_m, RAIO_CICLO_M)   # fração do raio de 1 km dentro da área, por hexágono

    if escolher is None:
        # Regra simples (módulo 3): a melhor candidata válida da lista.
        def escolher(hora, lista_candidatas, proibidas, outras_bases, raio_m, usar_cobertura_base):
            return escolher_quadricula(lista_candidatas, proibidas, outras_bases, centros_m,
                                       cobertura=cobertura_base if usar_cobertura_base else None,
                                       cobertura_min=cobertura_min_base)

    cartoes = {v: {} for v in viaturas}
    bases_ciclo = {v: {} for v in viaturas}          # viatura -> {posição na sequência: quadrícula}

    # O passado (horas antes de 'a_partir_da_hora') é copiado de 'fixos' ANTES de planejar o resto,
    # para que as regras de alternância enxerguem o que já aconteceu.
    if fixos:
        for v in viaturas:
            for h in range(a_partir_da_hora):
                cartoes[v][h] = fixos[v][h]

    # --- 1) Horas com ciclo 20+40 --------------------------------------------------
    for posicao, hora in enumerate(horas_ciclo):
        if hora < a_partir_da_hora:                  # passado: só registra a base usada
            for v in viaturas:
                if cartoes[v][hora].get("quadricula") is not None:
                    bases_ciclo[v][posicao] = cartoes[v][hora]["quadricula"]
            continue
        # A cada hora muda quem escolhe primeiro, para uma viatura só não ficar sempre
        # com a melhor quadrícula (a lista é "girada": [A, B, C] vira [B, C, A]).
        giro = posicao % n
        ordem = viaturas[giro:] + viaturas[:giro]
        bases_da_hora = {}                           # viatura -> quadrícula escolhida nesta hora
        for v in ordem:
            proibidas = set()
            # Regra 1: bases das posições vizinhas na sequência circular (até k posições).
            for outra_posicao, quadricula in bases_ciclo[v].items():
                diferenca = abs(posicao - outra_posicao)
                if min(diferenca, total_ciclo - diferenca) <= k:    # menor caminho em volta do "círculo"
                    proibidas.add(quadricula)
            # Regra 2: quadrículas do cartão nas horas vizinhas do relógio, se já definidas.
            for hora_vizinha in ((hora - 1) % 24, (hora + 1) % 24):
                if hora_vizinha in cartoes[v]:
                    proibidas.add(cartoes[v][hora_vizinha]["quadricula"])
            proibidas.discard(None)

            base = escolher(hora, candidatas[hora], proibidas, list(bases_da_hora.values()), RAIO_CICLO_M, True)
            bases_da_hora[v] = base
            if base is not None:
                bases_ciclo[v][posicao] = base
            cartoes[v][hora] = {
                "hora": hora, "faixa": f"{hora:02d}h-{(hora + 1) % 24:02d}h", "classe": classe_de[hora],
                "atividade": ATIVIDADE_CICLO, "quadricula": base, "raio_m": RAIO_CICLO_M,
                "minutos_base": 20, "minutos_patrulha": 40,
                "area": hexagonos_no_raio(base, RAIO_CICLO_M, centros_m) if base is not None else [],
            }

    # --- 2) Horas de polígono (Classe 2: 2 km; Classe 3: 3 km) ----------------------
    for posicao, hora in enumerate(horas_poligono):
        if hora < a_partir_da_hora:                  # passado: já foi copiado
            continue
        giro = posicao % n
        ordem = viaturas[giro:] + viaturas[:giro]
        raio = RAIO_2KM_M if atividade_de[hora] == ATIVIDADE_2KM else RAIO_3KM_M
        ancoras_da_hora = {}
        for v in ordem:
            # Regra 2 (relógio): não repetir a quadrícula das horas vizinhas do cartão.
            proibidas = {cartoes[v][h]["quadricula"] for h in ((hora - 1) % 24, (hora + 1) % 24) if h in cartoes[v]}
            proibidas.discard(None)
            ancora = escolher(hora, candidatas[hora], proibidas, list(ancoras_da_hora.values()), raio, False)
            if ancora is not None:
                ancoras_da_hora[v] = ancora
                area = hexagonos_no_raio(ancora, raio, centros_m)
            else:
                # Reserva (regra do PDF para a Classe 3): sem quadrícula identificada na hora,
                # patrulha o entorno das quadrículas que a viatura usou na Classe 1.
                bases_c1 = [cartoes[v][h]["quadricula"] for h in horas_classe1
                            if cartoes[v][h]["quadricula"] is not None]
                area = list(uniao_no_raio(bases_c1, raio, centros_m))
            cartoes[v][hora] = {
                "hora": hora, "faixa": f"{hora:02d}h-{(hora + 1) % 24:02d}h", "classe": classe_de[hora],
                "atividade": atividade_de[hora], "quadricula": ancora, "raio_m": raio,
                "minutos_base": None, "minutos_patrulha": None, "area": area,
            }
    return cartoes


def imprimir_cartao(viatura, cartao):
    """Mostra o cartão de uma viatura na tela, uma linha por faixa horária."""
    print(f"\n=== Cartão-Programa: {viatura} ===")
    for hora in range(24):
        e = cartao[hora]
        if e.get("empenhada"):
            detalhe = "EMPENHADA: atendendo ocorrência (fora do preventivo)"
        elif e["minutos_base"]:
            detalhe = f"base em {e['quadricula']}: {e['minutos_base']} min parada + {e['minutos_patrulha']} min patrulha"
        elif e["quadricula"] is not None:
            detalhe = f"patrulha de até {e['raio_m'] // 1000} km em volta de {e['quadricula']}"
        else:
            detalhe = f"patrulha de até {e['raio_m'] // 1000} km em volta das bases da Classe 1 (reserva)"
        print(f"{e['faixa']}  Classe {e['classe']}  {detalhe}  [{len(e['area'])} hexágonos]")


def exportar_cartoes(cartoes, centros_latlon, pasta="."):
    """
    Grava os cartões em dois arquivos dentro de 'pasta':

      cartoes_programa.csv  : uma linha por viatura e faixa horária, para ler no Excel
                              (separador ";" e acentos corretos).
      cartoes_programa.json : os mesmos dados, MAIS a lista de hexágonos de cada área de
                              patrulha. É o arquivo que a interface (módulo 5) vai usar.

    centros_latlon : {hexágono: (lat, lon)}, para mostrar a posição de cada quadrícula.
    Devolve os caminhos dos dois arquivos.
    """
    pasta = Path(pasta)
    caminho_csv = pasta / "cartoes_programa.csv"
    caminho_json = pasta / "cartoes_programa.json"

    colunas = ["viatura", "faixa", "classe", "atividade", "quadricula", "latitude", "longitude",
               "raio_km", "min_ponto_base", "min_patrulha", "hexagonos_na_area"]
    with open(caminho_csv, "w", newline="", encoding="utf-8-sig") as arquivo:   # utf-8-sig: o Excel entende os acentos
        escritor = csv.writer(arquivo, delimiter=";")
        escritor.writerow(colunas)
        for viatura, cartao in cartoes.items():
            for hora in range(24):
                e = cartao[hora]
                lat, lon = centros_latlon[e["quadricula"]] if e["quadricula"] is not None else ("", "")
                escritor.writerow([
                    viatura, e["faixa"], e["classe"], e["atividade"], e["quadricula"] or "",
                    f"{lat:.6f}" if lat != "" else "", f"{lon:.6f}" if lon != "" else "",
                    e["raio_m"] / 1000, e["minutos_base"] or "", e["minutos_patrulha"] or "",
                    len(e["area"]),
                ])

    dados = {
        viatura: [
            {**{k: v for k, v in cartao[hora].items() if k != "area"},   # tudo, menos a lista grande
             "area": sorted(cartao[hora]["area"])}                       # a lista de hexágonos, em ordem
            for hora in range(24)
        ]
        for viatura, cartao in cartoes.items()
    }
    with open(caminho_json, "w", encoding="utf-8") as arquivo:
        json.dump(dados, arquivo, ensure_ascii=False)
    return caminho_csv, caminho_json


def validar_cartoes(cartoes, centros_m, separacao_m=SEPARACAO_MIN_M, k=OUTRAS_DISTINTAS_ANTES_DE_REPETIR,
                    cobertura_min=COBERTURA_MIN_BASE):
    """
    Confere TODAS as regras e devolve um resumo com contagens (0 = tudo certo):
      repeticoes_consecutivas     : mesma base em duas horas seguidas da sequência de ciclo (circular)
      repeticoes_antes_do_intervalo: base que volta antes de k bases distintas (regra endurecida)
      repeticoes_horas_vizinhas   : mesma quadrícula em duas horas vizinhas do relógio (qualquer atividade)
      bases_repetidas_na_hora     : duas viaturas com a mesma base na mesma hora
      bases_sem_separacao         : duas bases na mesma hora mais próximas que 'separacao_m' (informativo
                                    no módulo 4, onde a cobertura ponderada substitui essa regra)
      horas_sem_quadricula        : horas de ciclo em que não houve candidata
      bases_com_pouca_cobertura   : bases com menos de 'cobertura_min' do raio de 1 km dentro da área
      poligonos_com_reserva       : horas de polígono que precisaram da reserva da Classe 1 (informativo)
    Horas em que a viatura está EMPENHADA (entrada com "empenhada": True) são ignoradas.
    """
    viaturas = list(cartoes)
    horas_ciclo = sorted({h for cartao in cartoes.values() for h, e in cartao.items() if e["minutos_base"]})
    consecutivas = intervalo = vizinhas = repetidas = sem_sep = sem_quad = reserva = pouca_cob = 0
    cobertura = cobertura_das_celulas(centros_m, RAIO_CICLO_M)
    for v in viaturas:
        sequencia = []                                   # bases da viatura, com None nos "buracos" do empenho
        for h in horas_ciclo:
            e = cartoes[v][h]
            if e.get("empenhada"):
                sequencia.append(None)
            else:
                sequencia.append(e["quadricula"])
                if e["quadricula"] is None:
                    sem_quad += 1
        total = len(sequencia)
        pouca_cob += sum(1 for q in sequencia if q is not None and cobertura[q] < cobertura_min)
        for i in range(total):
            for j in range(i + 1, total):
                if sequencia[i] is not None and sequencia[i] == sequencia[j]:
                    distancia = min(j - i, total - (j - i))      # distância no círculo
                    if distancia == 1:
                        consecutivas += 1
                    if distancia <= k:
                        intervalo += 1
        for h in range(24):                                      # relógio, com 23h vizinha de 0h
            e = cartoes[v][h]
            a, b = e["quadricula"], cartoes[v][(h + 1) % 24]["quadricula"]
            if a is not None and a == b:
                vizinhas += 1
            if not e["minutos_base"] and not e.get("empenhada") and a is None:
                reserva += 1
    for h in horas_ciclo:
        bases = [cartoes[v][h]["quadricula"] for v in viaturas if cartoes[v][h]["quadricula"] is not None]
        for i in range(len(bases)):
            for j in range(i + 1, len(bases)):
                if bases[i] == bases[j]:
                    repetidas += 1
                elif distancia_entre(bases[i], bases[j], centros_m) < separacao_m:
                    sem_sep += 1
    return {"repeticoes_consecutivas": consecutivas, "repeticoes_antes_do_intervalo": intervalo,
            "repeticoes_horas_vizinhas": vizinhas, "bases_repetidas_na_hora": repetidas,
            "bases_sem_separacao": sem_sep, "horas_sem_quadricula": sem_quad,
            "bases_com_pouca_cobertura": pouca_cob, "poligonos_com_reserva": reserva}


# ---------------------------------------------------------------------------
# DEMONSTRAÇÃO: roda só quando você executa ESTE arquivo diretamente
#    (usa os números reais que apareceram no seu terminal)
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    perfil_hora = {0: 109, 1: 109, 2: 163, 3: 174, 4: 98, 5: 106, 6: 146, 7: 256,
                   8: 257, 9: 257, 10: 274, 11: 228, 12: 180, 13: 211, 14: 227, 15: 188,
                   16: 218, 17: 228, 18: 231, 19: 200, 20: 272, 21: 211, 22: 210, 23: 144}
    casos_hora = {0: 39, 1: 35, 2: 52, 3: 56, 4: 31, 5: 34, 6: 48, 7: 82,
                  8: 84, 9: 86, 10: 94, 11: 77, 12: 65, 13: 71, 14: 76, 15: 64,
                  16: 72, 17: 75, 18: 76, 19: 64, 20: 88, 21: 67, 22: 67, 23: 50}
    graves_hora = {0: 5, 1: 7, 2: 11, 3: 10, 4: 7, 5: 7, 6: 3, 7: 13,
                   8: 11, 9: 7, 10: 5, 11: 7, 12: 3, 13: 11, 14: 10, 15: 5,
                   16: 10, 17: 8, 18: 13, 19: 16, 20: 17, 21: 19, 22: 21, 23: 10}

    tabela = classificar_horas(perfil_hora, casos_hora, graves_hora)
    for linha in tabela:
        print(f"{linha['posicao']:2d}º  {linha['hora']:02d}h  Classe {linha['classe']}  {linha['atividade']}")

    # ---------------- demonstração da PARTE 2 (com uma malha INVENTADA) ----------------
    print("\n--- Parte 2: malha inventada de 30 x 30 hexágonos (~114 m entre centros) ---")
    import random
    random.seed(1)
    d = 114.0                                           # distância entre centros (m)
    centros = {}
    for linha in range(30):
        for coluna in range(30):
            x = coluna * d + (d / 2 if linha % 2 else 0)   # linhas ímpares deslocadas, como favo de mel
            y = linha * d * 0.866
            m_lat, m_lon = metros_por_grau(-19.9)
            centros[(linha, coluna)] = (-19.9 + y / m_lat, -44.0 + x / m_lon)
    centros_m = para_metros(centros)
    viz = vizinhos_imediatos(centros_m)
    print("espaçamento estimado:", round(estimar_espacamento(centros_m)), "m | vizinhos do hexágono central:", len(viz[(15, 15)]))
    print("hexágonos a até 1 km do central:", len(hexagonos_no_raio((15, 15), 1000, centros_m)), "(esperado ~280)")

    pontos = {}                                         # pesos inventados: sobem perto de (15, 15) às 20h
    for celula in centros:
        pontos[(celula, 20)] = random.choice([0, 0, 1, 2])
    pontos[((15, 15), 20)] = 8
    for v in viz[(15, 15)]:
        pontos[(v, 20)] = 5
    pontos[((3, 3), 20)] = 9                            # um caso isolado, forte, mas sem vizinhos fortes
    ranking = ranking_por_hora(pontos, viz)
    print("top 3 candidatas às 20h:", [(c, round(p, 1)) for c, p in ranking[20][:3]])
    print("o isolado (3, 3) com peso 9 ficou em", [c for c, p in ranking[20]].index((3, 3)) + 1, "º lugar")

    # ---------------- demonstração da PARTE 3 (mesma malha inventada) ----------------
    print("\n--- Parte 3: cartões de 3 viaturas com pesos inventados nas 24 horas ---")
    pontos_todas = {}
    for hora in range(24):
        for celula in centros:
            pontos_todas[(celula, hora)] = random.choice([0, 0, 0, 1, 2])
        for _ in range(3):                                # 3 pontos quentes por hora
            quente = random.choice(list(centros))
            pontos_todas[(quente, hora)] = 8
            for vizinho in viz[quente]:
                pontos_todas[(vizinho, hora)] = 4
    candidatas = ranking_por_hora(pontos_todas, viz)
    cartoes = gerar_cartoes(["VTR-1", "VTR-2", "VTR-3"], tabela, candidatas, centros_m)
    imprimir_cartao("VTR-1", cartoes["VTR-1"])
    print("\nvalidação:", validar_cartoes(cartoes, centros_m))
    caminhos = exportar_cartoes(cartoes, centros, ".")      # grava os arquivos na pasta atual
    print("exportados:", [c.name for c in caminhos])

    # ---------------- demonstração dos NÍVEIS DE PRIORIDADE dos hexágonos ----------------
    dia = Counter()
    for (celula, hora), peso in pontos_todas.items():
        dia[celula] += peso
    suave, niveis, limites = classificar_hexagonos(dia, viz)
    print("\nníveis de prioridade (malha inventada): limites", tuple(round(x, 1) for x in limites),
          {NIVEIS_PRIORIDADE[n]: sum(1 for x in niveis.values() if x == n) for n in range(5)})
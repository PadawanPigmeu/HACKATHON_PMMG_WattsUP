"""
allocation_engine.py  --  Módulo 4: alocação das viaturas e reação dinâmica.

O QUE ESTE ARQUIVO FAZ
  1. DISTRIBUIÇÃO INICIAL: em cada hora, as viaturas escolhem suas bases uma de cada vez, e cada
     uma pega a candidata que cobre MAIS valor ainda descoberto dentro do raio dela. "Valor" é a
     prioridade dos hexágonos (a pontuação suavizada da hora) mais um pequeno bônus por hexágono
     novo coberto, mesmo vazio (peso do território). Assim, duas viaturas coladas rendem pouco e
     o próprio critério as espalha: é o equilíbrio entre prioridade e cobertura territorial.
  2. MEDIDAS: cobertura de prioridade (% do valor da hora dentro das áreas das viaturas) e
     cobertura territorial (% dos hexágonos cobertos).
  3. REAÇÃO, guiada por EVENTOS como no PDF (seção 12):
        sugerir_viatura()    -> qual viatura mandar (a mais próxima, com a regra das preventivas)
        confirmar_empenho()  -> botão "saiu para a ocorrência": retira a viatura do preventivo,
                                mede o impacto e replaneja as demais a partir da hora atual
        encerrar_empenho()   -> botão "ocorrência encerrada": a viatura volta e o plano é
                                refeito a partir da hora atual (as posições-base voltam)
     O passado nunca muda: o que já aconteceu fica como está, e as regras de alternância
     continuam valendo em cima desse histórico.
  4. DESPACHO POR OCORRÊNCIA (é o que os botões da interface chamam):
        registrar_ocorrencia() -> uma ocorrência nova entra na fila, com a gravidade do código A-F
        sugerir_viaturas()     -> as 3 viaturas mais indicadas, em ordem
        assumir_ocorrencia()   -> botão "estou indo": TRAVA a ocorrência para as demais. Se a viatura
                                  já está em outra ocorrência, só troca se a nova for bem mais grave;
                                  a antiga REABRE e volta a ser sugerida às outras
        encerrar_ocorrencia()  -> botão "ocorrência encerrada": a viatura volta ao plano

SIMPLIFICAÇÃO ASSUMIDA: o tempo é medido em faixas de uma hora. Um empenho ou um encerramento vale
a partir da faixa em que o botão foi clicado (um empenho às 14h30 replaneja a faixa das 14h).
"""
import copy

from program_cards import (
    COBERTURA_MIN_BASE, RAIO_CICLO_M,
    cobertura_das_celulas, distancia_entre, gerar_cartoes, hexagonos_no_raio,
)

ALFA_TERRITORIO = 0.10          # valor de cada hexágono novo coberto = 10% do valor médio de um hexágono da hora
LIMITE_PREVENTIVA = 0.5         # preventiva só é sugerida se estiver a menos da METADE da distância da de atendimento
FATOR_PREVENTIVA = 1 / LIMITE_PREVENTIVA   # no ranking de sugestões, a distância da preventiva conta em dobro
MARGEM_GRAVIDADE = 2            # uma viatura só troca de ocorrência se a nova pesar pelo menos 2 pontos a mais
PESOS_PADRAO = {"A": 4, "B": 5, "C": 1, "D": 1, "E": 2, "F": 3}   # peso de cada código de natureza (PDF)
TIPOS_VALIDOS = ("atendimento", "preventiva")
ATIVIDADE_EMPENHADA = "EMPENHADA: atendendo ocorrência (fora do preventivo)"


# ---------------------------------------------------------------------------
# 1) ESCOLHA DA QUADRÍCULA POR COBERTURA PONDERADA
# ---------------------------------------------------------------------------
def criar_escolhedor(valores, centros_m, cobertura_base, cobertura_min=COBERTURA_MIN_BASE, alfa=ALFA_TERRITORIO):
    """
    Devolve uma função 'escolher' para o gerar_cartoes() do módulo 3.

    valores        : {hora: {hexágono: pontuação}}  (saída de pontuacoes_por_hora)
    cobertura_base : {hexágono: fração do raio de 1 km dentro da área}
    alfa           : peso do território (0 = só prioridade; maior = valoriza cobrir mais hexágonos)

    Como a função decide: para cada candidata válida, soma o valor dos hexágonos do raio dela
    que NENHUMA outra viatura já cobre naquela hora; a candidata com maior soma vence.
    """
    memoria = {}                                          # guarda os raios já calculados (evita refazer a conta)

    def raio_de(celula, raio_m):
        if (celula, raio_m) not in memoria:
            memoria[(celula, raio_m)] = set(hexagonos_no_raio(celula, raio_m, centros_m))
        return memoria[(celula, raio_m)]

    # valor extra por hexágono coberto, por hora: alfa * valor médio dos hexágonos com ocorrência
    extra = {h: alfa * (sum(v.values()) / len(v)) if v else 0.0 for h, v in valores.items()}

    def escolher(hora, lista_candidatas, proibidas, outras_bases, raio_m, usar_cobertura_base):
        cobertos = set()                                  # hexágonos que as outras viaturas já cobrem nesta hora
        for outra in outras_bases:
            cobertos |= raio_de(outra, raio_m)
        valor_hora = valores[hora]
        # 1ª rodada exige a cobertura mínima da base; se ninguém cumprir, a 2ª rodada relaxa
        for exigir_cobertura in ((True, False) if usar_cobertura_base else (False,)):
            melhor, melhor_ganho = None, -1.0
            for celula, _ in lista_candidatas:
                if celula in proibidas or celula in outras_bases:
                    continue
                if exigir_cobertura and cobertura_base[celula] < cobertura_min:
                    continue
                ganho = sum(valor_hora.get(x, 0.0) + extra[hora] for x in raio_de(celula, raio_m) if x not in cobertos)
                if ganho > melhor_ganho:                  # ">" mantém a candidata mais bem ranqueada em caso de empate
                    melhor, melhor_ganho = celula, ganho
            if melhor is not None:
                return melhor
        return None

    return escolher


# ---------------------------------------------------------------------------
# 2) MEDIDAS DE COBERTURA
# ---------------------------------------------------------------------------
def cobertura_da_hora(plano, hora, valores_hora, todas_celulas):
    """
    Cobertura de uma hora, dado um plano ({viatura: {hora: entrada}}).
    Devolve {"prioridade": 0 a 1, "territorio": 0 a 1}.
      prioridade: valor dos hexágonos cobertos dividido pelo valor total da hora
      territorio: quantidade de hexágonos cobertos dividida pelo total de hexágonos da área
    Viaturas empenhadas têm área vazia, então não contam.
    """
    cobertos = set()
    for cartao in plano.values():
        cobertos.update(cartao[hora]["area"])
    total = sum(valores_hora.values())
    prioridade = sum(valores_hora.get(c, 0.0) for c in cobertos) / total if total else 1.0
    territorio = len(cobertos & todas_celulas) / len(todas_celulas)
    return {"prioridade": prioridade, "territorio": territorio}


# ---------------------------------------------------------------------------
# 3) A OPERAÇÃO: plano, empenhos e reação
# ---------------------------------------------------------------------------
class Operacao:
    """
    Guarda o plano do dia e reage aos eventos.

    frota : lista de dicionários, por exemplo
            [{"id": "VTR-1", "tipo": "atendimento"}, {"id": "VTR-4", "tipo": "preventiva"}]
    Os demais parâmetros vêm do módulo 3 (classificação das horas, candidatas, valores por hora
    e centros dos hexágonos em metros).

    Atributos úteis: plano_base (plano com todas as viaturas livres), plano (plano atual, que
    muda com os eventos) e empenhos (viaturas empenhadas agora).
    """

    def __init__(self, frota, classificacao, candidatas, valores, centros_m,
                 cobertura_min_base=COBERTURA_MIN_BASE, alfa=ALFA_TERRITORIO, pesos=PESOS_PADRAO):
        for item in frota:
            if item["tipo"] not in TIPOS_VALIDOS:
                raise ValueError(f"Tipo de viatura inválido: {item['tipo']} (use {TIPOS_VALIDOS})")
        self.ids = [item["id"] for item in frota]
        self.tipos = {item["id"]: item["tipo"] for item in frota}
        self.classificacao = classificacao
        self.classe_de = {item["hora"]: item["classe"] for item in classificacao}
        self.candidatas = candidatas
        self.valores = valores
        self.centros_m = centros_m
        self.todas_celulas = set(centros_m)
        cobertura_base = cobertura_das_celulas(centros_m, RAIO_CICLO_M)
        self.escolher = criar_escolhedor(valores, centros_m, cobertura_base, cobertura_min_base, alfa)

        # DISTRIBUIÇÃO INICIAL: todas as viaturas livres, dia inteiro
        self.plano_base = gerar_cartoes(self.ids, classificacao, candidatas, centros_m, escolher=self.escolher)
        self.plano = copy.deepcopy(self.plano_base)
        self.empenhos = {}                                # viatura -> {"hora": h, "ocorrencia": hexágono, "ocorrencia_id": ...}
        self.pesos = dict(pesos)                          # peso (gravidade) de cada código A-F
        self.ocorrencias = {}                             # id -> dados da ocorrência (status, viatura, peso...)
        self._contador = 0                                # para numerar as ocorrências: OC-1, OC-2...
        self.historico = []                               # relatórios de todos os eventos, em ordem (usado na página HTML)

    # ---- medidas ------------------------------------------------------------------
    def cobertura(self, hora, plano=None):
        return cobertura_da_hora(plano or self.plano, hora, self.valores[hora], self.todas_celulas)

    def cobertura_media(self, plano, de_hora):
        """Média da cobertura das horas de 'de_hora' até 23h."""
        medidas = [self.cobertura(h, plano) for h in range(de_hora, 24)]
        return {
            "prioridade": sum(m["prioridade"] for m in medidas) / len(medidas),
            "territorio": sum(m["territorio"] for m in medidas) / len(medidas),
        }

    # ---- sugestão de viatura -----------------------------------------------------------
    def posicao_de(self, viatura, hora):
        """Hexágono de referência da viatura na hora (a base ou o centro do polígono)."""
        cartao = self.plano[viatura]
        for h in [hora] + list(range(hora - 1, -1, -1)) + list(range(hora + 1, 24)):
            if cartao[h]["quadricula"] is not None:
                return cartao[h]["quadricula"]
        return None

    # ---- ocorrências e despacho ---------------------------------------------------------
    def registrar_ocorrencia(self, celula, codigo, hora):
        """
        Registra uma ocorrência nova (status "aberta"). 'celula' é o hexágono onde ela
        aconteceu e 'codigo' a natureza (A a F), que define a gravidade pelo peso do código.
        Devolve os dados da ocorrência, incluindo o 'id' (OC-1, OC-2...).
        """
        codigo = str(codigo).strip().upper()
        if codigo not in self.pesos:
            raise ValueError(f"Código de natureza inválido: {codigo} (use {sorted(self.pesos)})")
        if celula not in self.centros_m:
            raise ValueError(f"Hexágono {celula} não pertence à área")
        self._contador += 1
        id_ocorrencia = f"OC-{self._contador}"
        self.ocorrencias[id_ocorrencia] = {
            "id": id_ocorrencia, "celula": celula, "codigo": codigo, "peso": self.pesos[codigo],
            "hora_registro": hora, "status": "aberta", "viatura": None, "historico": [f"registrada às {hora:02d}h"],
        }
        return self.ocorrencias[id_ocorrencia]

    def ocorrencias_abertas(self):
        """Fila de ocorrências ainda sem viatura: as mais graves primeiro, e entre iguais as mais antigas."""
        abertas = [o for o in self.ocorrencias.values() if o["status"] == "aberta"]
        return sorted(abertas, key=lambda o: (-o["peso"], o["hora_registro"], o["id"]))

    def _ocorrencia(self, id_ocorrencia):
        if id_ocorrencia not in self.ocorrencias:
            raise ValueError(f"Ocorrência desconhecida: {id_ocorrencia}")
        return self.ocorrencias[id_ocorrencia]

    def sugerir_viaturas(self, id_ocorrencia, hora, n=3):
        """
        As 'n' viaturas mais indicadas para a ocorrência, da melhor para a pior.

        Ordem: pela DISTÂNCIA AJUSTADA, em que a distância da preventiva conta em dobro. Isso
        equivale à regra "preventiva só passa à frente se estiver a menos da metade da distância da
        de atendimento".
        Quem pode entrar na lista:
          - viaturas livres (a posição delas é a base/centro do polígono do plano);
          - viaturas que estão em OUTRA ocorrência menos grave (peso da nova >= peso da atual +
            MARGEM_GRAVIDADE). Elas aparecem com "troca": True, e a posição considerada é a da
            ocorrência em que estão. Se assumirem, a atual reabre.
        Ocorrência que não está aberta (já tem viatura ou foi encerrada) não recebe sugestões.
        Cada item traz: viatura, tipo, distancia_m, distancia_ajustada_m, troca, ocorrencia_atual.
        """
        oc = self._ocorrencia(id_ocorrencia)
        if oc["status"] != "aberta":
            return []
        candidatas = []
        for v in self.ids:
            atual_id = None
            if v in self.empenhos:
                atual_id = self.empenhos[v].get("ocorrencia_id")
                if atual_id is None or atual_id == id_ocorrencia:
                    continue                                # empenhada sem ocorrência registrada: não entra
                atual = self.ocorrencias[atual_id]
                if oc["peso"] < atual["peso"] + MARGEM_GRAVIDADE:
                    continue                                # a nova não é grave o bastante para tirar a viatura
                referencia = atual["celula"]
            else:
                referencia = self.posicao_de(v, hora)
            if referencia is None:
                continue
            distancia = distancia_entre(referencia, oc["celula"], self.centros_m)
            fator = FATOR_PREVENTIVA if self.tipos[v] == "preventiva" else 1
            candidatas.append({"viatura": v, "tipo": self.tipos[v], "distancia_m": round(distancia),
                               "distancia_ajustada_m": round(distancia * fator),
                               "troca": atual_id is not None, "ocorrencia_atual": atual_id})
        candidatas.sort(key=lambda c: (c["distancia_ajustada_m"], c["viatura"]))
        return candidatas[:n]

    def assumir_ocorrencia(self, id_ocorrencia, viatura, hora):
        """
        Botão "estou indo". Só funciona se a ocorrência ainda está aberta (a TRAVA: quem
        chegou primeiro leva, e ela some para as demais).
          - Viatura livre: sai do preventivo (confirmar_empenho) e o plano das outras é refeito.
          - Viatura já em outra ocorrência: TROCA, se a nova for pelo menos MARGEM_GRAVIDADE
            mais grave. A ocorrência antiga REABRE (com novas sugestões) e o plano não muda,
            porque a viatura continua fora do preventivo.
        """
        oc = self._ocorrencia(id_ocorrencia)
        if oc["status"] != "aberta":
            raise ValueError(f"{id_ocorrencia} não está aberta (status: {oc['status']}, viatura: {oc['viatura']})")
        if viatura not in self.tipos:
            raise ValueError(f"Viatura desconhecida: {viatura}")

        if viatura not in self.empenhos:
            relatorio = self.confirmar_empenho(viatura, hora, oc["celula"], ocorrencia_id=id_ocorrencia)
            oc.update(status="em_atendimento", viatura=viatura)
            oc["historico"].append(f"{viatura} assumiu às {hora:02d}h")
            relatorio["ocorrencia_id"] = id_ocorrencia
            return relatorio

        atual_id = self.empenhos[viatura].get("ocorrencia_id")
        if atual_id is None:
            raise ValueError(f"{viatura} está empenhada sem ocorrência registrada")
        atual = self.ocorrencias[atual_id]
        exigido = atual["peso"] + MARGEM_GRAVIDADE
        if oc["peso"] < exigido:
            if exigido > max(self.pesos.values()):
                motivo = "nenhuma ocorrência é grave o bastante para tirar a viatura de uma de peso " + str(atual["peso"])
            else:
                motivo = f"{id_ocorrencia} tem peso {oc['peso']} e precisaria de pelo menos {exigido}"
            raise ValueError(f"{viatura} está em {atual_id} (peso {atual['peso']}): {motivo}")
        atual.update(status="aberta", viatura=None)                      # a antiga reabre
        atual["historico"].append(f"reaberta às {hora:02d}h: {viatura} foi para {id_ocorrencia}")
        self.empenhos[viatura].update(ocorrencia=oc["celula"], ocorrencia_id=id_ocorrencia)
        oc.update(status="em_atendimento", viatura=viatura)
        oc["historico"].append(f"{viatura} assumiu às {hora:02d}h (veio de {atual_id})")
        relatorio = {"evento": "troca", "viatura": viatura, "tipo": self.tipos[viatura], "hora": hora,
                     "de": atual_id, "para": id_ocorrencia, "empenhadas_agora": sorted(self.empenhos),
                     "sugestoes_para_reaberta": self.sugerir_viaturas(atual_id, hora)}
        self.historico.append(relatorio)
        return relatorio

    def encerrar_ocorrencia(self, id_ocorrencia, hora):
        """
        Botão "ocorrência encerrada". Se havia viatura nela, ela volta ao preventivo e o plano é
        refeito (encerrar_empenho). Uma ocorrência ainda aberta também pode ser encerrada, sem viatura
        (por exemplo, resolvida por outro meio): nesse caso o plano não muda.
        """
        oc = self._ocorrencia(id_ocorrencia)
        if oc["status"] == "encerrada":
            raise ValueError(f"{id_ocorrencia} já está encerrada")
        relatorio = None
        if oc["status"] == "em_atendimento":
            relatorio = self.encerrar_empenho(oc["viatura"], hora)
            relatorio["ocorrencia_id"] = id_ocorrencia
        oc["historico"].append(f"encerrada às {hora:02d}h")
        oc.update(status="encerrada", viatura=None)
        return relatorio

    # ---- eventos ----------------------------------------------------------------------
    def _validar(self, viatura, hora, deve_estar_empenhada):
        if viatura not in self.tipos:
            raise ValueError(f"Viatura desconhecida: {viatura}")
        if not 0 <= hora <= 23:
            raise ValueError("A hora deve estar entre 0 e 23")
        if deve_estar_empenhada and viatura not in self.empenhos:
            raise ValueError(f"{viatura} não está empenhada")
        if not deve_estar_empenhada and viatura in self.empenhos:
            raise ValueError(f"{viatura} já está empenhada")

    def _entrada_empenhada(self, hora):
        return {"hora": hora, "faixa": f"{hora:02d}h-{(hora + 1) % 24:02d}h", "classe": self.classe_de[hora],
                "atividade": ATIVIDADE_EMPENHADA, "quadricula": None, "raio_m": 0,
                "minutos_base": None, "minutos_patrulha": None, "area": [], "empenhada": True}

    def _replanejar(self, hora):
        """
        Refaz o plano da 'hora' em diante com as viaturas LIVRES. O passado (horas anteriores)
        é copiado do plano atual. As empenhadas ficam marcadas como empenhadas.
        """
        livres = [v for v in self.ids if v not in self.empenhos]
        novos = gerar_cartoes(livres, self.classificacao, self.candidatas, self.centros_m,
                              escolher=self.escolher, fixos=self.plano, a_partir_da_hora=hora)
        plano_novo = {}
        for v in self.ids:
            if v in livres:
                plano_novo[v] = novos[v]
            else:
                plano_novo[v] = {h: (self.plano[v][h] if h < hora else self._entrada_empenhada(h)) for h in range(24)}
        self.plano = plano_novo

    def confirmar_empenho(self, viatura, hora, celula_ocorrencia, ocorrencia_id=None):
        """
        Botão "a viatura saiu para a ocorrência". Segue o roteiro da seção 12 do PDF:
        1) identifica a indisponibilidade, 2) retira a viatura, 3) identifica as regiões
        afetadas, 4) avalia a nova cobertura, 5) replaneja e 6) atualiza os cartões.
        Devolve um relatório com a cobertura antes, depois SEM ajuste e depois COM ajuste.
        """
        self._validar(viatura, hora, deve_estar_empenhada=False)
        plano_antes = self.plano

        # regiões afetadas: hexágonos que só essa viatura cobria nesta hora
        area_da_viatura = set(plano_antes[viatura][hora]["area"])
        cobertas_por_outras = set()
        for v, cartao in plano_antes.items():
            if v != viatura:
                cobertas_por_outras |= set(cartao[hora]["area"])
        afetadas = area_da_viatura - cobertas_por_outras
        valor_perdido = sum(self.valores[hora].get(c, 0.0) for c in afetadas)

        # "sem ajuste": só tira a viatura e deixa as outras como estavam
        plano_sem_ajuste = copy.deepcopy(plano_antes)
        for h in range(hora, 24):
            plano_sem_ajuste[viatura][h] = self._entrada_empenhada(h)

        self.empenhos[viatura] = {"hora": hora, "ocorrencia": celula_ocorrencia, "ocorrencia_id": ocorrencia_id}
        self._replanejar(hora)

        relatorio = {
            "evento": "empenho", "viatura": viatura, "tipo": self.tipos[viatura], "hora": hora,
            "ocorrencia": celula_ocorrencia, "hexagonos_afetados": len(afetadas),
            "valor_perdido": valor_perdido, "valor_total_hora": sum(self.valores[hora].values()),
            "empenhadas_agora": sorted(self.empenhos),
            "hora_atual": {"antes": self.cobertura(hora, plano_antes),
                           "sem_ajuste": self.cobertura(hora, plano_sem_ajuste),
                           "depois": self.cobertura(hora)},
            "resto_do_dia": {"antes": self.cobertura_media(plano_antes, hora),
                             "sem_ajuste": self.cobertura_media(plano_sem_ajuste, hora),
                             "depois": self.cobertura_media(self.plano, hora)},
        }
        self.historico.append(relatorio)
        return relatorio

    def encerrar_empenho(self, viatura, hora):
        """
        Botão "ocorrência encerrada": a viatura volta ao preventivo e o plano é refeito da
        'hora' em diante com todas as viaturas livres. Devolve um relatório que inclui quantas
        posições voltaram a ser exatamente as do plano-base (quando nada mais mudou).
        """
        self._validar(viatura, hora, deve_estar_empenhada=True)
        plano_antes = self.plano
        del self.empenhos[viatura]
        self._replanejar(hora)

        entradas = [(v, h) for v in self.ids if v not in self.empenhos for h in range(hora, 24)]
        iguais = sum(1 for v, h in entradas if self.plano[v][h]["quadricula"] == self.plano_base[v][h]["quadricula"])
        relatorio = {
            "evento": "retorno", "viatura": viatura, "tipo": self.tipos[viatura], "hora": hora,
            "empenhadas_agora": sorted(self.empenhos),
            "hora_atual": {"antes": self.cobertura(hora, plano_antes), "depois": self.cobertura(hora)},
            "resto_do_dia": {"antes": self.cobertura_media(plano_antes, hora),
                             "depois": self.cobertura_media(self.plano, hora)},
            # só faz sentido comparar com o plano-base quando NENHUMA viatura continua empenhada
            "posicoes_iguais_ao_plano_base": (f"{iguais} de {len(entradas)}" if not self.empenhos
                                              else "não se aplica (ainda há viaturas empenhadas)"),
        }
        self.historico.append(relatorio)
        return relatorio


# ---------------------------------------------------------------------------
# 4) RELATÓRIO NA TELA
# ---------------------------------------------------------------------------
def _pct(medida):
    return f"prioridade {100 * medida['prioridade']:.0f}% | território {100 * medida['territorio']:.0f}%"


def imprimir_relatorio(rel):
    """Mostra o relatório de um evento (empenho ou retorno) de forma legível."""
    if rel["evento"] == "empenho":
        print(f"\n>>> EMPENHO: {rel['viatura']} ({rel['tipo']}) às {rel['hora']:02d}h, ocorrência em {rel['ocorrencia']}")
        print(f"    regiões afetadas: {rel['hexagonos_afetados']} hexágonos que só ela cobria "
              f"({100 * rel['valor_perdido'] / rel['valor_total_hora']:.0f}% do valor da hora)")
        h = rel["hora_atual"]
        print(f"    faixa {rel['hora']:02d}h  antes: {_pct(h['antes'])}")
        print(f"                 sem ajuste: {_pct(h['sem_ajuste'])}")
        print(f"                 com ajuste: {_pct(h['depois'])}")
        d = rel["resto_do_dia"]
        print(f"    resto do dia (média)  antes: {_pct(d['antes'])}")
        print(f"                 sem ajuste: {_pct(d['sem_ajuste'])}")
        print(f"                 com ajuste: {_pct(d['depois'])}")
    elif rel["evento"] == "troca":
        print(f"\n<-> TROCA: {rel['viatura']} ({rel['tipo']}) às {rel['hora']:02d}h deixa {rel['de']} e vai para {rel['para']}")
        print(f"    {rel['de']} voltou a ficar ABERTA. Sugestões para ela:")
        imprimir_sugestoes(rel["sugestoes_para_reaberta"], recuo="      ")
    else:
        print(f"\n<<< RETORNO: {rel['viatura']} ({rel['tipo']}) às {rel['hora']:02d}h")
        print(f"    faixa {rel['hora']:02d}h  antes: {_pct(rel['hora_atual']['antes'])}")
        print(f"                 depois: {_pct(rel['hora_atual']['depois'])}")
        print(f"    resto do dia (média)  antes: {_pct(rel['resto_do_dia']['antes'])}")
        print(f"                 depois: {_pct(rel['resto_do_dia']['depois'])}")
        print(f"    posições iguais ao plano-base: {rel['posicoes_iguais_ao_plano_base']}")
    print(f"    empenhadas agora: {rel['empenhadas_agora'] or 'nenhuma'}")


def imprimir_sugestoes(sugestoes, recuo="    "):
    """Mostra a lista de viaturas sugeridas, em ordem."""
    if not sugestoes:
        print(f"{recuo}(nenhuma viatura disponível)")
    for posicao, c in enumerate(sugestoes, start=1):
        troca = f"  [TROCA: está em {c['ocorrencia_atual']}]" if c["troca"] else ""
        # a preventiva conta em dobro no ranking, então mostramos os dois valores para a ordem fazer sentido
        ajuste = f" (conta como {c['distancia_ajustada_m']} m)" if c["tipo"] == "preventiva" else ""
        print(f"{recuo}{posicao}º {c['viatura']} ({c['tipo']}): {c['distancia_m']} m{ajuste}{troca}")
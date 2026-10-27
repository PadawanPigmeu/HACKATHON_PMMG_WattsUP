# 🚓 Sistema de Apoio ao Policiamento Preventivo Dinâmico — PMMG

**Equipe:** WattsUP

**Integrantes:** Theo Del Rio - João Miguel Aguiar - Rodrigo Ruas Deluca

---

## 📌 Breve descrição da solução

Plataforma de apoio à decisão para **planejar, distribuir e recalcular o emprego de viaturas** no policiamento preventivo da Polícia Militar de Minas Gerais. A partir da base histórica de ocorrências anonimizadas e ponderadas por gravidade (códigos A a F), o sistema divide o território da 39ª Cia PM (18º BPM) em uma **malha hexagonal de 200 m entre vértices opostos**, mede a criticidade espacial de cada hexágono e a criticidade temporal de cada hora do dia, e gera um **Cartão-Programa** para cada viatura.

**O diferencial é a reação a eventos operacionais.** Quando uma viatura é empenhada em uma ocorrência e sai do preventivo, o sistema mede a perda de cobertura, redistribui as viaturas restantes para proteger as regiões descobertas e atualiza os cartões **da faixa horária atual em diante**, sem alterar o que já passou. Quando a ocorrência termina, a viatura volta e o plano é refeito. Uma ocorrência muito mais grave pode assumir uma viatura já empenhada (**troca por gravidade**), e a ocorrência anterior volta à fila com novas sugestões.

### Em números (execução de referência com os dados fornecidos)

| Item | Resultado |
|---|---|
| Malha hexagonal | 1.071 hexágonos ativos, **199,98 m** entre vértices opostos (medido por distância geodésica) |
| Ocorrências | 1.605 lidas; 1.553 dentro da área da companhia |
| Níveis de prioridade | Muito alta: 38 · Alta: 113 · Média: 232 · Baixa: 384 · Sem ocorrências: 304 |
| Validação automática dos cartões | 0 repetições de quadrícula, 0 bases iguais na mesma hora, 0 horas sem quadrícula, 0 bases com pouca cobertura |
| Cenário 2 (uma viatura empenhada às 14h, frota de teste de 5) | Cobertura de prioridade na faixa: 84% → 66% (sem ajuste) → **74% (com redistribuição)**; média do resto do dia: 89% → 74% → **85%** |
| Retorno da viatura às 16h | 40 de 40 posições voltaram exatamente ao plano-base |

### Requisitos do edital e onde estão atendidos

| Edital | Como foi atendido | Onde |
|---|---|---|
| Malha de hexágonos de 200 m (seção 5) | Malha própria, conferida pela distância geodésica | `spatial_grid.py` |
| Classificação dos hexágonos (seção 6) | 4 níveis de prioridade por percentis, com suavização espacial | `program_cards.py` |
| Mapa interativo (seção 7) | Interface em Streamlit, página HTML dos cartões e mapa de hexágonos | `app.py`, `cartoes_html.py`, `malha.py` |
| Distribuição e cobertura (seções 8 e 9) | Escolha das bases por ganho marginal de cobertura ponderada pela prioridade | `allocation_engine.py` |
| Regras do Cartão-Programa (seção 11) | Classes 1, 2 e 3, ciclo 20 min + 40 min, polígonos de 2 e 3 km, alternância | `program_cards.py` |
| Cartão dinâmico (seção 12) | Empenho, retorno e troca, com relatório de cobertura antes, sem ajuste e com ajuste | `allocation_engine.py` |
| Cenários 1, 2 e 3 (seção 13) | Executados automaticamente e também na interface | `malha.py`, `app.py` |
| Código aberto (seção 14) | Somente bibliotecas de código aberto | ver "Tecnologias" abaixo |

---

## 🚀 Como executar

Requer **Python 3.10+**. Coloque `ocorrencias.txt` e `39_cia.geojson` na pasta raiz do projeto.

```bash
pip install streamlit folium streamlit-folium shapely
```

**Interface interativa** (despacho ao vivo, cartões e mapa):

```bash
python -m streamlit run app.py
```

> Dica para teste no celular: com o computador e o celular na mesma rede Wi-Fi, abra no navegador do celular o endereço *Network URL* exibido no terminal.

**Execução no terminal** (conferências, os três cenários e geração dos arquivos `cartoes_programa.html`, `.csv` e `.json`):

```bash
python malha.py
```

---

## 📖 Documentação detalhada (leitura opcional)

As seções abaixo explicam a metodologia, as decisões de projeto e as limitações. Clique para expandir.

<details>
<summary><b>🧭 Arquitetura e fluxo de dados</b></summary>

```
ocorrencias.txt + 39_cia.geojson
            │
            ▼
   pipeline.carregar_dados()
   (leitura e pesos → malha hexagonal → pontuação → níveis → classificação das 24 horas → ranking)
            │
            ▼
   allocation_engine.Operacao
   (plano-base → eventos: empenho / troca / retorno → plano atual)
            │
            ├──► app.py            interface de despacho e visualização
            ├──► cartoes_html.py   página imprimível, uma página A4 por viatura
            └──► malha.py          terminal, cenários, CSV, JSON e mapa
```

Tudo é calculado uma vez em `carregar_dados()`, e tanto o terminal quanto a interface usam o mesmo resultado, o que garante consistência entre os dois.

</details>

<details>
<summary><b>🧠 Metodologia e decisões de projeto</b></summary>

### 1. Malha hexagonal própria em vez do H3 (`spatial_grid.py`)

O edital pede hexágonos regulares de aproximadamente 200 m, medidos entre vértices opostos.

- **O problema:** a biblioteca `h3` trabalha com resoluções de tamanho fixo. Na nossa latitude, as resoluções disponíveis dão cerca de 130 m ou saltam para cerca de 350 m, longe da especificação.
- **A solução:** uma malha própria, em formato de favo de mel, com hexágonos "de pé", aresta de 100 m e distância entre centros de 100 × √3 ≈ 173,2 m. Latitude e longitude são convertidas para metros pelas fórmulas do elipsoide WGS84, a partir do centro da área.
- **Conferência independente:** o diâmetro é medido pela fórmula geodésica de Vincenty. Usamos Vincenty porque a fórmula de haversine trata a Terra como esfera e erra cerca de 0,4% neste caso, o que seria inaceitável para validar uma medida de 200 m. O resultado foi 199,98 m, com variação de uns 2 cm ao longo da área.
- **Recorte:** a malha é cortada sobre o polígono oficial da companhia com a biblioteca `shapely`, resultando em 1.071 hexágonos (o corte pode gerar MultiPolygons nas bordas sinuosas, que são aceitos normalmente).

### 2. Suavização espacial: um caso isolado não faz um "ponto quente" (`program_cards.py`)

Olhar só o que aconteceu dentro dos 200 m de um hexágono distorce o resultado, porque há poucos casos por hexágono e por hora (em média, 0 a 2). Um hexágono com um único crime grave cercado de áreas tranquilas ficaria acima de um corredor comercial com criminalidade espalhada pelas esquinas vizinhas.

- A pontuação de cada hexágono é o seu próprio peso somado a 50% da média do peso dos vizinhos imediatos (`FRACAO_VIZINHOS = 0.5`). Os vizinhos imediatos são os que estão a até 1,5 espaçamento, que é exatamente o primeiro anel do favo.
- **Níveis de prioridade:** ignorando os hexágonos com pontuação zero ("Sem ocorrências"), os demais são classificados por percentis (`CORTES_PERCENTIL`): até o 50º percentil, **Baixa**; do 50º ao 80º, **Média**; do 80º ao 95º, **Alta**; acima do 95º, **Muito alta**. Os limites acompanham os dados, então o critério se adapta a qualquer volume de ocorrências. Na execução de referência os limites foram 5,3, 13,7 e 28,2.

### 3. Classificação das 24 horas e critérios de desempate (`program_cards.py`)

As 24 faixas são ordenadas da maior para a menor incidência: as 8 primeiras são a **Classe 1**, as 8 seguintes a **Classe 2** e as 8 últimas a **Classe 3**. Para que empates não decidam a classe de forma arbitrária, a ordenação segue uma cascata, e o primeiro critério que diferenciar as horas decide:

1. **Maior peso total** (A=4, B=5, C=1, D=1, E=2, F=3).
2. **Volume expressivo:** se a diferença de casos for de 10 ou mais (`LIMIAR_CASOS = 10`), vence a hora com mais casos.
3. **Gravidade:** com diferença menor que 10 casos, vence a hora com mais casos graves (naturezas A e B, peso 4 ou mais).
4. **Noite crítica (19h às 5h):** o núcleo (19h às 23h) vence a madrugada (0h às 5h), e ambos vencem o restante do dia (6h às 18h). Entre duas horas da madrugada, vence a maior proporção de casos graves e, persistindo o empate, a hora mais próxima do núcleo. No núcleo e durante o dia, vence a hora mais tarde.

Esse último critério foi definido a partir dos dados: a proporção de casos graves é de 22% na janela de 19h às 5h contra 11,8% no restante do dia, com pico entre 19h e 23h. Já o volume de casos é maior de manhã. Por isso a classificação segue o peso total, como manda o edital, e a hierarquia da noite só atua no desempate final.

Resultado na execução de referência:

| Classe | Horas |
|---|---|
| 1 | 10h, 20h, 8h, 9h, 7h, 18h, 17h, 11h |
| 2 (ciclo 20+40) | 14h, 16h, 21h, 13h |
| 2 (polígono de 2 km) | 22h, 19h, 15h, 12h |
| 3 (polígono de 3 km) | 3h, 2h, 6h, 23h, 1h, 0h, 5h, 4h |

Na Classe 2, o edital não diz quais 4 das 8 horas usam o ciclo e quais usam o polígono. Adotamos como critério que as 4 mais incidentes usam o ciclo.

### 4. Regra de borda dos 60% e relaxamento em camadas (`COBERTURA_MIN_BASE`)

Nas horas de ciclo (20 min de ponto-base e 40 min de patrulha num raio de 1 km), surgiu um problema prático: a quadrícula mais quente pode estar colada na divisa da companhia.

- **O problema:** uma base na fronteira faz com que metade do círculo de patrulha caia fora da área da unidade, desperdiçando recurso operacional.
- **A regra:** para cada hexágono, o algoritmo conta quantos hexágonos do raio de 1 km estão dentro do contorno e divide pelo máximo observado no interior da área (121). Uma célula de borda com 59 hexágonos (49%) não pode ser ponto-base, porque exigimos pelo menos 60% (`COBERTURA_MIN_BASE = 0.6`).
- **Efeito:** os pontos quentes de fronteira continuam cobertos pelo raio de 1 km das bases vizinhas e pelos polígonos de 2 e 3 km, que não passam por esse filtro.
- **Desejo, não proibição:** a cobertura mínima e a separação desejável entre viaturas são filtros desejáveis. Se numa faixa nenhuma candidata cumprir tudo, o sistema relaxa primeiro a separação e depois a cobertura de borda, para que nenhuma viatura fique sem base. As regras de alternância e a proibição de bases iguais na mesma hora **nunca** são relaxadas.

### 5. Alternância endurecida de quadrículas (`OUTRAS_DISTINTAS_ANTES_DE_REPETIR = 2`)

O edital exige que uma quadrícula não seja repetida em faixas consecutivas, com pelo menos uma outra distinta antes do retorno. Como o texto admite duas leituras de "consecutivas", endurecemos a regra e validamos as duas ao mesmo tempo, dentro do cartão de cada viatura:

- **Sequência circular de ciclo:** entre as 12 horas com ponto-base (8 da Classe 1 e 4 da Classe 2), a viatura só repete uma base depois de passar por pelo menos 2 outras bases distintas. A sequência é circular: depois da última hora de ciclo do dia vem a primeira do dia seguinte.
- **Vizinhança no relógio:** nenhuma quadrícula pode se repetir em horas adjacentes (h e h+1, incluindo 23h e 0h), seja como ponto-base ou como centro de polígono.

### 6. Alocação dinâmica e equilíbrio territorial (`allocation_engine.py`)

Para evitar que todas as viaturas se amontoem no mesmo ponto de alta criminalidade, a escolha das bases usa o ganho marginal de cobertura:

- A cada hora, as viaturas escolhem uma de cada vez, com rodízio de quem escolhe primeiro. Cada uma pega, entre as candidatas, a base que soma o maior valor de prioridade **ainda descoberto** pelas demais, mais um bônus territorial de 10% do valor médio da hora por hexágono inédito coberto (`ALFA_TERRITORIO = 0.10`). Duas viaturas coladas rendem ganho marginal baixo, então o próprio critério espalha a frota. É assim que conciliamos prioridade, cobertura territorial e recursos disponíveis.
- **Medidas de cobertura:** *prioridade* (parte do valor da hora dentro das áreas das viaturas) e *território* (parte dos hexágonos cobertos).

### 7. Reação a eventos: empenho, troca e retorno

O fluxo segue o roteiro da seção 12 do edital:

1. O operador registra uma ocorrência (hexágono e código A–F, que define a gravidade pelo peso do código).
2. O sistema sugere as **3 viaturas mais indicadas**, em ordem. A distância da viatura preventiva conta em dobro (`FATOR_PREVENTIVA = 2`), o que equivale a dizer que ela só passa à frente de uma viatura de atendimento se estiver a menos da metade da distância.
3. Ao confirmar "estou indo", a ocorrência é **travada** para as demais, a viatura sai do preventivo, o sistema identifica as regiões que só ela cobria, mede o impacto e **replaneja** as outras da faixa atual em diante. O passado é copiado do plano atual, e as regras de alternância continuam valendo sobre esse histórico. O relatório mostra a cobertura antes, depois sem ajuste e depois com ajuste.
4. **Troca por gravidade:** uma viatura já empenhada pode assumir uma ocorrência nova se o peso dela superar o da atual em pelo menos `MARGEM_GRAVIDADE = 2`. Por exemplo, uma ocorrência B (peso 5) pode tirar a viatura de uma F (peso 3) ou de uma C (peso 1), mas ocorrências de peso 4 ou 5 nunca perdem a viatura. A ocorrência anterior é reaberta e recebe novas sugestões.
5. Ao encerrar a ocorrência, a viatura volta e o plano é refeito. Quando nenhuma outra viatura continua empenhada, as posições voltam às do plano-base, desde que o histórico real de alternância permita.

</details>

<details>
<summary><b>🧪 Cenários de teste do edital</b></summary>

| Cenário | O que mostra | Como ver |
|---|---|---|
| 1. Todas as viaturas disponíveis | Mapa, classificação dos hexágonos, distribuição das viaturas, cobertura e Cartões-Programa | Aba de cartões da interface, ou `cartoes_programa.html` |
| 2. Indisponibilidade de uma viatura | Alteração da disponibilidade, impacto na cobertura, redistribuição e cartões atualizados | Botão "estou indo" da interface, ou saída de `python malha.py` |
| 3. Indisponibilidade de várias viaturas | O algoritmo continua gerando uma estratégia com recursos reduzidos | Duas ou mais ocorrências assumidas ao mesmo tempo |

Exemplo da execução de referência (frota de teste de 5 viaturas, sendo 3 de atendimento e 2 preventivas):

- **Cenário 2:** ocorrência código F às 14h, viatura sugerida a 794 m. Com o empenho, 43 hexágonos que só ela cobria ficam descobertos (18% do valor da hora). A cobertura de prioridade na faixa das 14h vai de 84% para 66% sem ajuste e se recupera para 74% com a redistribuição. A média do resto do dia vai de 89% para 74% e se recupera para 85%.
- **Cenário 3:** com duas viaturas empenhadas às 13h, a cobertura de prioridade na faixa vai de 79% para 48% sem ajuste e para 68% com a redistribuição; a média do resto do dia vai de 84% para 70% e para 77%.

A frota usada nos testes é fictícia e será substituída pelo número e pelos tipos de viaturas do cenário real.

</details>

<details>
<summary><b>🗂️ Estrutura de arquivos do repositório</b></summary>

| Arquivo | Módulo e responsabilidade |
|---|---|
| `data_loader.py` | **Módulo 1:** leitura do arquivo de ocorrências, validação dos códigos A–F, aplicação dos pesos e conversão em pontos geográficos |
| `spatial_grid.py` | **Módulo 2:** malha hexagonal regular de 200 m sobre o elipsoide WGS84 e conferência das medidas por distância geodésica (Vincenty) |
| `program_cards.py` | **Módulo 3:** ordenação e desempate das 24 horas, suavização espacial, níveis por percentis, ranking de quadrículas, geração dos Cartões-Programa, validação automática (`validar_cartoes`) e exportação em CSV e JSON |
| `allocation_engine.py` | **Módulo 4:** alocação por cobertura ponderada, métricas de prioridade e território, fila de despacho, trava de ocorrência, troca por gravidade e replanejamento dinâmico |
| `pipeline.py` | **Orquestrador:** reúne os módulos 1 a 3 na função `carregar_dados()`, garantindo o mesmo resultado no terminal e na interface |
| `app.py` | **Módulo 5:** interface em Streamlit para registrar ocorrências, assumir e encerrar atendimentos e acompanhar cartões e mapa |
| `cartoes_html.py` | **Página dos cartões:** gera um `.html` autocontido, com linha do dia, comparação entre plano-base e plano atual, eventos e layout de impressão A4 (uma página por viatura) |
| `malha.py` | **Script de demonstração e auditoria:** roda todo o fluxo no terminal, as conferências, os cenários 1, 2 e 3, e gera `cartoes_programa.html`, `.csv` e `.json` e o mapa de hexágonos |

**Arquivos de entrada:** `ocorrencias.txt` e `39_cia.geojson`.
**Arquivos gerados:** `cartoes_programa.html`, `cartoes_programa.csv`, `cartoes_programa.json` e `mapa_casos.html`.

</details>

<details>
<summary><b>🧰 Tecnologias utilizadas e parâmetros ajustáveis</b></summary>

Todas as bibliotecas são de código aberto, em conformidade com a seção 14 do edital.

| Tecnologia | Uso |
|---|---|
| Python 3.10+ | Linguagem do projeto |
| `shapely` | Recorte da malha sobre o contorno e testes geométricos |
| `folium` e `streamlit-folium` | Mapas na interface |
| `streamlit` | Interface interativa |
| Leaflet | Mapa da página HTML dos cartões |
| Biblioteca padrão do Python (`math`, `json`, `csv`, `collections`, `pathlib`) | Cálculos, leitura e exportação |

Os mapas de fundo são carregados de serviços externos de tiles, apenas para exibição; eles não fazem parte do cálculo. Sem internet, os cartões e os cálculos continuam funcionando.

**Parâmetros que podem ser ajustados sem alterar a lógica:**

| Constante | Valor | Significado |
|---|---|---|
| `FRACAO_VIZINHOS` | 0,5 | Peso dos vizinhos na suavização espacial |
| `CORTES_PERCENTIL` | 50%, 80%, 95% | Limites dos níveis Baixa, Média, Alta e Muito alta |
| `LIMIAR_CASOS` | 10 | Diferença de casos a partir da qual o volume vence a gravidade no desempate |
| `PESO_GRAVE` | 4 | Peso mínimo para um caso contar como grave (códigos A e B) |
| `COBERTURA_MIN_BASE` | 0,6 | Fração mínima do raio de 1 km que deve estar dentro da área para um hexágono ser base |
| `OUTRAS_DISTINTAS_ANTES_DE_REPETIR` | 2 | Quantas bases distintas antes de uma viatura repetir uma base |
| `ALFA_TERRITORIO` | 0,10 | Valor de cada hexágono inédito coberto, em fração do valor médio de um hexágono |
| `FATOR_PREVENTIVA` | 2 | Multiplicador da distância da viatura preventiva no ranking de sugestões |
| `MARGEM_GRAVIDADE` | 2 | Diferença mínima de peso para uma viatura trocar de ocorrência |
| `TOP_CANDIDATAS` | 60 | Quantas quadrículas candidatas são guardadas por hora |

</details>

<details>
<summary><b>⚠️ Limitações identificadas</b></summary>

- **Frota fictícia nos testes.** O número e os tipos de viaturas dos exemplos são de teste; os reais virão do cenário do hackathon.
- **Tempo em faixas de uma hora.** Um empenho ou um encerramento vale a partir da faixa horária em que o botão é acionado (um empenho às 14h30 replaneja a faixa das 14h).
- **Sem GPS nem rotas.** A posição de uma viatura é a base ou o centro do polígono do plano; uma viatura em atendimento é considerada na posição da ocorrência. As distâncias são em linha reta entre centros de hexágonos, e não por vias.
- **Gravidade pelo código.** As naturezas são anonimizadas em códigos de A a F, então a gravidade de uma ocorrência nova é o peso do código, sem distinção entre, por exemplo, tipos de crime.
- **Poucos dados por hexágono e hora.** São 1.605 ocorrências em um ano, o que dá 0 a 2 casos na maioria das combinações de hexágono e hora. A suavização espacial atenua o problema, mas não o elimina.
- **Critérios próprios onde o edital é aberto.** Dois exemplos: a escolha das 4 horas da Classe 2 que usam o ciclo (as mais incidentes) e a interpretação conjunta das duas leituras de "faixas consecutivas".
- **Polígonos de 2 e 3 km sem filtro de borda.** O filtro de cobertura de 60% vale só para as bases do ciclo; os polígonos podem ficar parcialmente recortados pelo contorno.
- **Uso por um operador.** O estado da operação vive em uma sessão do aplicativo. O uso real com vários operadores simultâneos exigiria estado compartilhado em um servidor.
- **Mapa depende de internet.** A página HTML e os mapas de fundo carregam recursos externos; sem internet, o mapa não aparece.

</details>

<details>
<summary><b>🔭 Possibilidades de evolução</b></summary>

- **Validação preditiva:** treinar com parte do ano e testar no restante, medindo quanto dos casos graves as horas e quadrículas escolhidas capturam.
- **Curva de cobertura pelo tamanho da frota**, para responder quantas viaturas são necessárias para cobrir uma dada fração da prioridade.
- **Perfis separados para dia útil e fim de semana.** Os dados indicam padrões horários diferentes entre os dois.
- **Roteamento pela malha viária** (por exemplo, com dados do OpenStreetMap) e posições em tempo real das viaturas, para tempos de deslocamento reais.
- **Fila de ocorrências mais rica**, com prioridades por tipo real de natureza e regras de troca configuráveis.
- **Otimização exata** (por exemplo, programação inteira para o problema de máxima cobertura) para comparar com a heurística gulosa atual.
- **Estado compartilhado multiusuário**, para vários operadores trabalharem sobre o mesmo plano.
- **Previsão espaço-temporal** com aprendizado de máquina, substituindo o histórico ponderado.

</details>

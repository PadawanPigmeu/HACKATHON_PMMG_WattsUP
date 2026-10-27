# 🚓 Sistema de Apoio ao Policiamento Preventivo Dinâmico — PMMG

**Equipe:** WattsUP

**Integrantes:** Theo Del Rio - João Miguel Aguiar - Rodrigo Ruas Deluca

---

## 📌 Breve descrição da solução
a
Plataforma de apoio à decisão para **planejar, distribuir e recalcular o emprego de viaturas** no policiamento preventivo da Polícia Militar de Minas Gerais. A partir da base histórica de ocorrências anonimizadas e ponderadas por gravidade (códigos A a F), o sistema divide o território da 39ª Cia PM (18º BPM) em uma **malha hexagonal de 200 m entre vértices opostos**, mede a criticidade espacial de cada hexágono e a criticidade temporal de cada hora do dia, e gera um **Cartão-Programa** para cada viatura.

**O diferencial é a reação a eventos operacionais.** Quando uma viatura é empenhada em uma ocorrência e sai do preventivo, o sistema mede a perda de cobertura, redistribui as viaturas restantes para proteger as regiões descobertas e atualiza os cartões **da faixa horária atual em diante**, sem alterar o que já passou. Quando a ocorrência termina, a viatura volta e o plano é refeito. Uma ocorrência muito mais grave pode assumir uma viatura já empenhada (**troca por gravidade**), e a ocorrência anterior volta à fila com novas sugestões.

INFORMAÇÕES DE EXECUÇÃO E DOCUMENTAÇÃO COMPLETA NO ARQUIVO "DOCUMENTAFULL.MD"

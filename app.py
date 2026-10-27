import streamlit as st
import folium
from streamlit_folium import st_folium
from pipeline import carregar_dados
from allocation_engine import Operacao

# Configuração da página (deve ser a primeira chamada)
st.set_page_config(page_title="PMMG - Policiamento Dinâmico", layout="wide")

CORES_NIVEL = ["#d9d9d9", "#fff2a8", "#ffb000", "#e03c00", "#6a0f7a"]
CORES_VIATURAS = ["#1f77b4", "#d62728", "#2ca02c", "#9467bd", "#ff7f0e", "#17becf", "#8c564b", "#e377c2"]

# Inicialização do backend em cache
@st.cache_resource
def iniciar_backend():
    dados = carregar_dados(mostrar=False)
    # Frota padrão definida para a demonstração
    frota = [
        {"id": "VTR-1", "tipo": "atendimento"},
        {"id": "VTR-2", "tipo": "atendimento"},
        {"id": "VTR-3", "tipo": "atendimento"},
        {"id": "VTR-4", "tipo": "preventiva"},
        {"id": "VTR-5", "tipo": "preventiva"},
    ]
    op = Operacao(
        frota=frota,
        classificacao=dados["tabela"],
        candidatas=dados["candidatas"],
        valores=dados["valores"],
        centros_m=dados["centros_m"]
    )
    return dados, op

dados, op = iniciar_backend()

# Memória da interface para o clique no mapa
if "celula_alvo" not in st.session_state:
    st.session_state.celula_alvo = list(dados["recortados"].keys())[0]
if "ultimo_clique" not in st.session_state:
    st.session_state.ultimo_clique = None

# ==========================================
# BARRA LATERAL (CONTROLES E REGISTRO)
# ==========================================
st.sidebar.title("Painel do Policial")
hora_atual = st.sidebar.slider("Faixa Horária Atual", 0, 23, 14)

st.sidebar.markdown("---")
st.sidebar.subheader("Camadas do Mapa")
mostrar_cores = st.sidebar.checkbox("Mostrar Níveis de Prioridade", value=True)
mostrar_viaturas = st.sidebar.checkbox("Mostrar Viaturas (Ponto-Base)", value=True)
mostrar_areas = st.sidebar.checkbox("Mostrar Áreas de Cobertura", value=True)

st.sidebar.markdown("---")
st.sidebar.subheader("Nova Ocorrência via COPOM")
st.sidebar.info("Dica: Clique em qualquer lugar no mapa para selecionar o hexágono automaticamente.")

opcoes_celulas = list(dados["recortados"].keys())
idx_celula = opcoes_celulas.index(st.session_state.celula_alvo) if st.session_state.celula_alvo in opcoes_celulas else 0

celula_alvo = st.sidebar.selectbox("Local (Hexágono)", opcoes_celulas, index=idx_celula)
st.session_state.celula_alvo = celula_alvo
codigo_nat = st.sidebar.selectbox("Natureza", ["A (Peso 4 - Grave)", "B (Peso 5 - Muito Grave)", "C (Peso 1)", "D (Peso 1)", "E (Peso 2)", "F (Peso 3)"])

if st.sidebar.button("🚨 Registrar Ocorrência", use_container_width=True):
    cod = codigo_nat[0]
    oc = op.registrar_ocorrencia(st.session_state.celula_alvo, cod, hora_atual)
    st.sidebar.success(f"{oc['id']} registrada no hexágono {st.session_state.celula_alvo}!")


# ==========================================
# ÁREA PRINCIPAL (DESPACHO E MAPA)
# ==========================================
st.title("Centro de Gerenciamento - Policiamento Dinâmico")

# 1. KPIs de Cobertura
cob = op.cobertura(hora_atual)
col_kpi1, col_kpi2, col_kpi3 = st.columns(3)
col_kpi1.metric("Cobertura da Prioridade", f"{cob['prioridade']*100:.1f}%")
col_kpi2.metric("Cobertura Territorial", f"{cob['territorio']*100:.1f}%")
col_kpi3.metric("Viaturas Disponíveis", len(op.ids) - len(op.empenhos))

st.markdown("---")

# 2. Painel de Despacho
col_pendentes, col_andamento = st.columns(2)

with col_pendentes:
    st.subheader("⚠️ Ocorrências Pendentes")
    abertas = op.ocorrencias_abertas()
    if not abertas:
        st.info("Nenhuma ocorrência aguardando viatura.")
    else:
        for oc in abertas:
            with st.expander(f"{oc['id']} - Natureza {oc['codigo']} (Peso {oc['peso']}) | Local: {oc['celula']}", expanded=True):
                sugestoes = op.sugerir_viaturas(oc["id"], hora_atual, n=3) # Mostra top 3
                if not sugestoes:
                    st.warning("Nenhuma viatura disponível para atender.")
                else:
                    for sug in sugestoes:
                        vtr = sug['viatura']
                        dist = sug['distancia_m']
                        
                        # Lógica visual para preempção (trocar ocorrência)
                        if sug['troca']:
                            label_btn = f"🚔 {vtr} (Largar {sug['ocorrencia_atual']} e assumir esta)"
                            st.write(f"*{vtr} está a {dist}m, mas atendendo ocorrência mais branda.*")
                        else:
                            label_btn = f"🚔 {vtr} ({sug['tipo']} - a {dist}m)"
                        
                        if st.button(label_btn, key=f"disp_{oc['id']}_{vtr}", use_container_width=True):
                            try:
                                op.assumir_ocorrencia(oc["id"], vtr, hora_atual)
                                st.rerun()
                            except ValueError as e:
                                st.error(str(e))

with col_andamento:
    st.subheader("🚓 Ocorrências em Andamento")
    andamento = [o for o in op.ocorrencias.values() if o["status"] == "em_atendimento"]
    if not andamento:
        st.success("Todas as viaturas estão no patrulhamento preventivo.")
    else:
        for oc in andamento:
            st.info(f"**{oc['id']}** sendo atendida por **{oc['viatura']}** no hex {oc['celula']}")
            if st.button(f"Encerrar {oc['id']} e Retornar ao Preventivo", key=f"enc_{oc['id']}", use_container_width=True):
                op.encerrar_ocorrencia(oc["id"], hora_atual)
                st.rerun()

st.markdown("---")

# ==========================================
# ABAS PRINCIPAIS: MAPA E CARTÕES
# ==========================================
tab_mapa, tab_cartoes = st.tabs(["🗺️ Mapa Dinâmico", "📋 Cartões-Programa (24h)"])

with tab_mapa:
    bounds = dados["area"].bounds
    m = folium.Map(location=[(bounds[1] + bounds[3]) / 2, (bounds[0] + bounds[2]) / 2], zoom_start=15)

    # Camada: Contorno da Área
    folium.GeoJson(dados["gj"], style_function=lambda x: {"color": "black", "weight": 3, "fill": False}).add_to(m)

    # Camada: Níveis de Prioridade
    if mostrar_cores:
        for c, pol in dados["recortados"].items():
            nivel = dados["nivel_hex"][c]
            poligonos = [pol] if pol.geom_type == 'Polygon' else pol.geoms
            for p in poligonos:
                coords = [[lat, lon] for lon, lat in p.exterior.coords]
                
                # Destacar o hexágono selecionado
                peso_borda = 3 if c == st.session_state.celula_alvo else 0.5
                cor_borda = "black" if c == st.session_state.celula_alvo else "white"
                
                folium.Polygon(
                    locations=coords,
                    color=cor_borda, weight=peso_borda,
                    fill_color=CORES_NIVEL[nivel],
                    fill_opacity=0.4 if nivel == 0 else 0.7,
                    tooltip=f"Hex: {c} | Nível: {nivel}"
                ).add_to(m)

    # Camada: Viaturas Ativas e Áreas de Cobertura
    for i, vtr in enumerate(op.ids):
        cartao = op.plano[vtr][hora_atual]
        
        if cartao.get("empenhada"):
            continue  # Se está atendendo ocorrência, sai do mapa preventivo
            
        q_base = cartao["quadricula"]
        if q_base:
            lat, lon = dados["centros"][q_base]
            cor_vtr = CORES_VIATURAS[i % len(CORES_VIATURAS)]
            
            if mostrar_viaturas:
                folium.Marker(
                    [lat, lon],
                    icon=folium.Icon(color="white", icon_color=cor_vtr, icon="car", prefix="fa"),
                    tooltip=f"{vtr} ({op.tipos[vtr]})"
                ).add_to(m)
                
            if mostrar_areas:
                for hex_area in cartao["area"]:
                    if hex_area in dados["recortados"]:
                        pol_area = dados["recortados"][hex_area]
                        pols_area = [pol_area] if pol_area.geom_type == 'Polygon' else pol_area.geoms
                        for p_area in pols_area:
                            coords_area = [[la, lo] for lo, la in p_area.exterior.coords]
                            folium.Polygon(
                                locations=coords_area,
                                color=cor_vtr, weight=2, fill=False, opacity=0.7
                            ).add_to(m)

    # Renderiza o mapa com key dinâmica para forçar recarregamento visual nos empenhos/revezamentos
    map_data = st_folium(
        m, 
        width=1200, 
        height=600, 
        key=f"mapa_{hora_atual}_{len(op.empenhos)}_{op._contador}", 
        returned_objects=["last_clicked"]
    )

    # Captura de clique no mapa para auto-seleção do hexágono
    if map_data and map_data.get("last_clicked"):
        lat_click = map_data["last_clicked"]["lat"]
        lon_click = map_data["last_clicked"]["lng"]
        celula_clicada = dados["malha"].celula_de(lat_click, lon_click)
        
        if celula_clicada in dados["recortados"] and celula_clicada != st.session_state.ultimo_clique:
            st.session_state.ultimo_clique = celula_clicada
            st.session_state.celula_alvo = celula_clicada
            st.rerun()

with tab_cartoes:
    st.subheader("Planejamento Diário")
    vtr_selecionada = st.selectbox("Selecione a Viatura para visualizar o Cartão-Programa:", op.ids)
    
    cartao_vtr = op.plano[vtr_selecionada]
    dados_tabela = []
    
    for h in range(24):
        e = cartao_vtr[h]
        status = "🚨 EMPENHADA (Fora do Preventivo)" if e.get("empenhada") else e["atividade"]
        local = e["quadricula"] if e["quadricula"] else "Reserva (Bases da Classe 1)"
        
        # Coloca uma seta na linha correspondente à hora atual no painel lateral
        faixa_texto = f"➡️ {e['faixa']}" if h == hora_atual else e['faixa']
        
        dados_tabela.append({
            "Horário": faixa_texto,
            "Classe": f"Classe {e['classe']}",
            "Ação / Atividade": status,
            "Ponto-Base (Hexágono)": local,
            "Raio de Patrulha": f"{e['raio_m']/1000:.1f} km" if e['raio_m'] else "-"
        })
        
    st.dataframe(dados_tabela, use_container_width=True, hide_index=True)
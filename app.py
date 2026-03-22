import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time
from streamlit_gsheets import GSheetsConnection

# Configuración de la página
st.set_page_config(page_title="Quiniela Cloud DB", layout="wide")

st.title("📊 Analizador de Quiniela + Base de Datos Cloud")
st.write("El script guarda los resultados en Google Sheets para crear un histórico permanente.")

# --- CONEXIÓN A GOOGLE SHEETS ---
# Esto utiliza los Secrets que configuraste en Streamlit Cloud
conn = st.connection("gsheets", type=GSheetsConnection)

# --- FUNCIONES DE SCRAPING CON CACHÉ ---
@st.cache_data(show_spinner="Extrayendo datos de la web...")
def scrape_jornada(n_jornada):
    url = f"https://www.casasdeapuestas.com/quiniela/resultados/jornada-{n_jornada}/"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36"
    }
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        
        soup = BeautifulSoup(response.text, 'html.parser')
        tabla = soup.find('table', class_='table-quiniela')
        
        if not tabla:
            return None

        partidos = []
        filas = tabla.find_all('tr')[1:]

        for fila in filas:
            cols = fila.find_all('td')
            if len(cols) < 5: continue
            
            equipo_local = cols[0].text.strip()
            equipo_visitante = cols[1].text.strip()
            resultado_final = cols[2].text.strip()
            
            try:
                c1 = float(cols[3].text.replace(',', '.'))
                cX = float(cols[4].text.replace(',', '.'))
                c2 = float(cols[5].text.replace(',', '.'))
            except:
                continue

            cuotas = {"1": c1, "X": cX, "2": c2}
            favorito = min(cuotas, key=cuotas.get)
            acierto = 1 if favorito == resultado_final else 0
            
            partidos.append({
                "Jornada": int(n_jornada),
                "Partido": f"{equipo_local} vs {equipo_visitante}",
                "Resultado": resultado_final,
                "Favorito Casa": favorito,
                "Cuota Favorito": cuotas[favorito],
                "Acierto": int(acierto)
            })
        return partidos
    except Exception as e:
        return None

# --- CARGAR DATOS ACTUALES ---
# Leemos el Excel al iniciar la app para mostrar lo que ya tenemos
try:
    df_historico = conn.read()
except:
    df_historico = pd.DataFrame()

# --- INTERFAZ DE USUARIO ---
st.sidebar.header("Control de Carga")
jornada_inicio = st.sidebar.number_input("Desde Jornada:", min_value=1, value=1)
jornada_fin = st.sidebar.number_input("Hasta Jornada:", min_value=1, value=5)

if st.sidebar.button("🚀 Scrapear y Guardar"):
    nuevos_datos_lista = []
    progreso = st.progress(0)
    
    pasos = range(jornada_inicio, jornada_fin + 1)
    for i, j_num in enumerate(pasos):
        datos = scrape_jornada(j_num)
        if datos:
            nuevos_datos_lista.extend(datos)
        
        # Barra de progreso
        progreso.progress((i + 1) / len(pasos))
        time.sleep(0.2)

    if nuevos_datos_lista:
        df_nuevo = pd.DataFrame(nuevos_datos_lista)
        
        # Unir con lo que ya existía en el Excel
        if not df_historico.empty:
            df_final = pd.concat([df_historico, df_nuevo], ignore_index=True)
        else:
            df_final = df_nuevo
        
        # LIMPIEZA: Evitar que se dupliquen partidos si scrapeamos lo mismo dos veces
        df_final = df_final.drop_duplicates(subset=['Jornada', 'Partido'], keep='last')
        
        # GUARDAR EN GOOGLE SHEETS
        conn.update(data=df_final)
        st.success("✅ ¡Base de Datos actualizada en la nube!")
        st.rerun() # Recargar para mostrar los cambios
    else:
        st.warning("No se pudieron obtener datos nuevos.")

# --- VISUALIZACIÓN ---
if not df_historico.empty:
    st.subheader("📈 Estadísticas Globales (Acumulado en DB)")
    
    col1, col2, col3 = st.columns(3)
    total_partidos = len(df_historico)
    aciertos_totales = df_historico['Acierto'].sum()
    ratio_acierto = (aciertos_totales / total_partidos) * 100
    
    col1.metric("Partidos en DB", total_partidos)
    col2.metric("Aciertos Totales", int(aciertos_totales))
    col3.metric("% Acierto Medio", f"{ratio_acierto:.2f}%")
    
    st.divider()
    
    tab1, tab2 = st.tabs(["📋 Datos Completos", "📊 Gráfico de Rendimiento"])
    
    with tab1:
        st.dataframe(df_historico, use_container_width=True)
        
    with tab2:
        # Agrupar aciertos por jornada para el gráfico
        chart_data = df_historico.groupby('Jornada')['Acierto'].mean() * 100
        st.line_chart(chart_data)
        st.caption("Evolución del % de acierto de las casas de apuestas por jornada.")

else:
    st.info("La base de datos está vacía. Usa el panel de la izquierda para cargar las primeras jornadas.")
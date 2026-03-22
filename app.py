import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import time

# Configuración de la página
st.set_page_config(page_title="Quiniela Backtesting", layout="wide")

st.title("📊 Analizador de Resultados: ¿Ganan las Casas de Apuestas?")
st.write("Este script recorre el histórico de la Quiniela y comprueba si el favorito de las cuotas acertó.")

# --- FUNCIONES DE SCRAPING ---
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
        tabla = soup.find('table', class_='table-quiniela') # Clase común en esa web
        
        if not tabla:
            return None

        partidos = []
        filas = tabla.find_all('tr')[1:] # Saltamos la cabecera

        for fila in filas:
            cols = fila.find_all('td')
            if len(cols) < 5: continue
            
            equipo_local = cols[0].text.strip()
            equipo_visitante = cols[1].text.strip()
            resultado_final = cols[2].text.strip() # Ej: "1", "X", "2"
            
            # Extraemos cuotas (suponiendo que están en las columnas siguientes)
            try:
                c1 = float(cols[3].text.replace(',', '.'))
                cX = float(cols[4].text.replace(',', '.'))
                c2 = float(cols[5].text.replace(',', '.'))
            except:
                continue # Si no hay cuotas, saltamos el partido

            # Lógica: ¿Quién era el favorito? (La cuota más baja)
            cuotas = {"1": c1, "X": cX, "2": c2}
            favorito = min(cuotas, key=cuotas.get)
            
            acierto = 1 if favorito == resultado_final else 0
            
            partidos.append({
                "Jornada": n_jornada,
                "Partido": f"{equipo_local} vs {equipo_visitante}",
                "Resultado": resultado_final,
                "Favorito Casa": favorito,
                "Cuota Favorito": cuotas[favorito],
                "Acierto": acierto
            })
        return partidos
    except Exception as e:
        st.error(f"Error en jornada {n_jornada}: {e}")
        return None

# --- INTERFAZ DE USUARIO ---
jornada_inicio = st.number_input("Desde Jornada:", min_value=1, value=1)
jornada_fin = st.number_input("Hasta Jornada:", min_value=1, value=5)

if st.button("🚀 Empezar Backtesting"):
    todos_los_datos = []
    progreso = st.progress(0)
    
    for i in range(jornada_inicio, jornada_fin + 1):
        datos = scrape_jornada(i)
        if datos:
            todos_los_datos.extend(datos)
        
        # Actualizar barra de progreso
        porcentaje = (i - jornada_inicio + 1) / (jornada_fin - jornada_inicio + 1)
        progreso.progress(porcentaje)
        time.sleep(0.5) # Pausa para evitar bloqueos

    if todos_los_datos:
        df = pd.DataFrame(todos_los_datos)
        
        # --- MÉTRICAS ---
        st.divider()
        col1, col2, col3 = st.columns(3)
        total_partidos = len(df)
        aciertos_totales = df['Acierto'].sum()
        ratio_acierto = (aciertos_totales / total_partidos) * 100
        
        col1.metric("Total Partidos", total_partidos)
        col2.metric("Aciertos Casa", aciertos_totales)
        col3.metric("% Acierto", f"{ratio_acierto:.2f}%")
        
        st.subheader("Detalle de los datos")
        st.dataframe(df)
        
        # Gráfico simple
        st.line_chart(df.groupby('Jornada')['Acierto'].mean())
    else:
        st.warning("No se encontraron datos en ese rango.")
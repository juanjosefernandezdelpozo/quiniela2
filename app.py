import re
import time

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup
from streamlit_gsheets import GSheetsConnection

# Configuración de la página
st.set_page_config(page_title="Quiniela Cloud DB", layout="wide")

st.title("📊 Analizador de Quiniela + Base de Datos Cloud")
st.write("El script guarda los resultados en Google Sheets para crear un histórico permanente.")

# --- CONEXIÓN A GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

_gsheets_error = None
try:
    df_historico = conn.read()
except Exception as e:
    df_historico = pd.DataFrame()
    _gsheets_error = str(e)


def _jornada_desde_html(soup):
    """La web muestra la jornada en un <b>Jornada N</b>; las URLs /jornada-X/ suelen redirigir a la misma página."""
    for tag in soup.find_all("b"):
        t = tag.get_text(strip=True)
        if not t.lower().startswith("jornada"):
            continue
        rest = t[7:].strip().split()
        if rest and rest[0].isdigit():
            return int(rest[0])
    return None


def scrape_jornada(n_jornada):
    """
    La tabla ya no usa class='table-quiniela'; ahora es table.lya[data-type='tips-results'].
    Cada fila tiene 5 td: partido (equipos), goles, signo, sis., una sola cuota (HTML estático).
    """
    url = f"https://www.casasdeapuestas.com/quiniela/resultados/jornada-{n_jornada}/"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }

    try:
        response = requests.get(url, headers=headers, timeout=15)
        if response.status_code != 200:
            return None

        soup = BeautifulSoup(response.text, "html.parser")
        tabla = soup.select_one('table.lya[data-type="tips-results"]')
        if not tabla:
            tabla = soup.find("table", class_="lya")

        if not tabla:
            return None

        jornada_real = _jornada_desde_html(soup)
        if jornada_real is None:
            jornada_real = int(n_jornada)

        partidos = []
        for fila in tabla.find_all("tr"):
            if "thead" in (fila.get("class") or []):
                continue
            cols = fila.find_all("td", recursive=False)
            if len(cols) < 5:
                continue

            teams = cols[0].select_one(".event-teams")
            if not teams:
                continue
            nombres = [s.strip() for s in teams.stripped_strings if s.strip()]
            if len(nombres) < 2:
                continue
            equipo_local, equipo_visitante = nombres[0], nombres[1]

            resultado_final = cols[2].get_text(strip=True)
            odd_el = cols[4].select_one(".odd-content")
            if not odd_el:
                continue
            try:
                cuota_val = float(odd_el.get_text(strip=True).replace(",", "."))
            except ValueError:
                continue

            bookie = ""
            odd_wrap = cols[4].select_one(".odd")
            oc = odd_wrap.get("onclick") if odd_wrap else None
            if oc:
                m = re.search(r"bookie:'([^']+)'", oc)
                if m:
                    bookie = m.group(1)

            partidos.append(
                {
                    "Jornada": jornada_real,
                    "Partido": f"{equipo_local} vs {equipo_visitante}",
                    "Resultado": resultado_final,
                    "Favorito Casa": "N/D",
                    "Cuota Favorito": cuota_val,
                    "Casa cuota": bookie or None,
                    "Acierto": pd.NA,
                }
            )
        return partidos if partidos else None
    except Exception:
        return None


# --- INTERFAZ DE USUARIO ---
st.sidebar.header("Control de Carga")
if _gsheets_error:
    st.sidebar.error(f"No se pudo leer Google Sheets. Revisa secrets y permisos.\n\n`{_gsheets_error}`")

st.sidebar.caption(
    "Nota: la web suele mostrar solo la **jornada actual**; "
    "las URLs jornada-1, jornada-2, etc. pueden redirigir a la misma página."
)

jornada_inicio = st.sidebar.number_input("Desde Jornada:", min_value=1, value=1)
jornada_fin = st.sidebar.number_input("Hasta Jornada:", min_value=1, value=5)

if st.sidebar.button("🚀 Scrapear y Guardar"):
    if jornada_fin < jornada_inicio:
        st.error("«Hasta Jornada» debe ser mayor o igual que «Desde Jornada».")
    else:
        nuevos_datos_lista = []
        progreso = st.progress(0)

        pasos = list(range(jornada_inicio, jornada_fin + 1))
        for i, j_num in enumerate(pasos):
            datos = scrape_jornada(j_num)
            if datos:
                nuevos_datos_lista.extend(datos)

            progreso.progress((i + 1) / len(pasos))
            time.sleep(0.2)

        if nuevos_datos_lista:
            df_nuevo = pd.DataFrame(nuevos_datos_lista)

            if not df_historico.empty:
                df_final = pd.concat([df_historico, df_nuevo], ignore_index=True)
            else:
                df_final = df_nuevo

            df_final = df_final.drop_duplicates(subset=["Jornada", "Partido"], keep="last")

            try:
                conn.update(data=df_final)
                st.success("✅ ¡Base de Datos actualizada en la nube!")
                st.rerun()
            except Exception as e:
                st.error(f"No se pudo guardar en Google Sheets: {e}")
        else:
            st.warning(
                "No se pudieron obtener datos nuevos. "
                "Comprueba la conexión, que la web no haya cambiado otra vez, o prueba más tarde."
            )

# --- VISUALIZACIÓN ---
if not df_historico.empty:
    st.subheader("📈 Estadísticas Globales (Acumulado en DB)")

    ac_numeric = pd.to_numeric(df_historico["Acierto"], errors="coerce")
    valid_ac = ac_numeric.dropna()
    total_partidos = len(df_historico)

    col1, col2, col3 = st.columns(3)
    col1.metric("Partidos en DB", total_partidos)
    if len(valid_ac) > 0:
        aciertos_totales = int(valid_ac.sum())
        ratio_acierto = float(valid_ac.mean() * 100)
        col2.metric("Aciertos Totales", aciertos_totales)
        col3.metric("% Acierto Medio", f"{ratio_acierto:.2f}%")
    else:
        col2.metric("Aciertos Totales", "N/D")
        col3.metric("% Acierto Medio", "N/D")
        st.caption(
            "Los datos cargados no incluyen aciertos comparables (la web solo publica una cuota por partido en el HTML)."
        )

    st.divider()

    tab1, tab2 = st.tabs(["📋 Datos Completos", "📊 Gráfico de Rendimiento"])

    with tab1:
        st.dataframe(df_historico, use_container_width=True)

    with tab2:
        if len(valid_ac) > 0:
            chart_data = df_historico.assign(_a=ac_numeric).groupby("Jornada")["_a"].mean() * 100
            st.line_chart(chart_data)
            st.caption("Evolución del % de acierto de las casas de apuestas por jornada.")
        else:
            st.info("No hay columna de aciertos numéricos para graficar.")

else:
    st.info("La base de datos está vacía. Usa el panel de la izquierda para cargar las primeras jornadas.")

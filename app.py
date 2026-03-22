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


def _request_headers():
    # Cabeceras de navegador: a veces evitan 403; muchas veces el bloqueo es por IP (datacenter / Cloud).
    return {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
        "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
        "Referer": "https://www.casasdeapuestas.com/",
    }


def _partidos_desde_soup(soup, n_jornada_fallback):
    """
    La tabla ya no usa class='table-quiniela'; ahora es table.lya[data-type='tips-results'].
    Cada fila tiene 5 td: partido (equipos), goles, signo, sis., una sola cuota (HTML estático).
    """
    tabla = soup.select_one('table.lya[data-type="tips-results"]')
    if not tabla:
        tabla = soup.find("table", class_="lya")
    if not tabla:
        return []

    jornada_real = _jornada_desde_html(soup)
    if jornada_real is None:
        jornada_real = int(n_jornada_fallback)

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
    return partidos


def scrape_jornada(n_jornada):
    url = f"https://www.casasdeapuestas.com/quiniela/resultados/jornada-{n_jornada}/"
    try:
        response = requests.get(url, headers=_request_headers(), timeout=15)
        if response.status_code != 200:
            return None
        soup = BeautifulSoup(response.text, "html.parser")
        partidos = _partidos_desde_soup(soup, n_jornada)
        return partidos if partidos else None
    except Exception:
        return None


# --- CONEXIÓN A GOOGLE SHEETS ---
conn = st.connection("gsheets", type=GSheetsConnection)

_gsheets_error = None
try:
    df_historico = conn.read()
except Exception as e:
    df_historico = pd.DataFrame()
    _gsheets_error = str(e)


with st.expander("🔍 Vista previa del scrape (1 fila)", expanded=True):
    st.caption(
        "Comprueba si el servidor donde corre la app puede leer la web y si el HTML sigue coincidiendo con el parser."
    )
    j_prev = st.number_input("Jornada en la URL de prueba", min_value=1, value=1, key="j_prev_preview")
    if st.button("Probar y mostrar 1ª fila", key="btn_scrape_preview"):
        url_prev = f"https://www.casasdeapuestas.com/quiniela/resultados/jornada-{j_prev}/"
        try:
            r = requests.get(url_prev, headers=_request_headers(), timeout=20)
            st.markdown(
                f"**HTTP** `{r.status_code}` · **URL final** `{r.url}` · **Tamaño HTML** `{len(r.text):,}` caracteres"
            )
            if r.status_code == 403:
                st.error(
                    "**403 Forbidden:** el servidor **no autoriza** esta petición. "
                    "Suele ser protección anti-bot o **bloqueo de IPs** (muy frecuente desde Streamlit Cloud, "
                    "Railway, Fly.io, etc.). No es un fallo del parser: **no estás recibiendo la página real de resultados**."
                )
                st.info(
                    "**Opciones:** ejecutar la app **en tu PC** (misma red que tu navegador), usar un **origen de datos** "
                    "que permita acceso automatizado, o comprobar si el sitio ofrece API / descarga oficial. "
                    "Evitar el bloqueo de terceros puede violar sus términos de uso."
                )
            elif r.status_code != 200:
                st.error(
                    f"La respuesta no es 200 OK (`{r.status_code}`). El scraper no puede leer la tabla hasta que la descarga funcione."
                )

            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                partidos_prev = _partidos_desde_soup(soup, j_prev)
                st.write(f"Filas parseadas: **{len(partidos_prev)}**")
                if partidos_prev:
                    st.success("Primera fila (mismo formato que se guardaría en la hoja):")
                    st.dataframe(pd.DataFrame([partidos_prev[0]]), use_container_width=True)
                else:
                    st.warning(
                        "HTTP 200 pero el parser no extrajo ningún partido "
                        "(HTML distinto o tabla cargada solo con JavaScript en tu entorno)."
                    )
                    tiene_lya = "lya" in r.text and "tips-results" in r.text
                    st.caption(
                        f"¿Aparece la tabla esperada en el HTML bruto? Indicio `lya` + `tips-results`: **{tiene_lya}**"
                    )
        except Exception as e:
            st.error(f"No se pudo descargar la página: `{e}`")


# --- INTERFAZ DE USUARIO ---
st.sidebar.header("Control de Carga")
if _gsheets_error:
    st.sidebar.error(f"No se pudo leer Google Sheets. Revisa secrets y permisos.\n\n`{_gsheets_error}`")

st.sidebar.caption(
    "Nota: la web suele mostrar solo la **jornada actual**; "
    "las URLs jornada-1, jornada-2, etc. pueden redirigir a la misma página."
)
st.sidebar.caption(
    "Si ves **HTTP 403** en la vista previa, el hosting (p. ej. Streamlit Cloud) suele estar **bloqueado** por el sitio; prueba en local."
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

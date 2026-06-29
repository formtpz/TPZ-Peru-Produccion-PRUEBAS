# modulos/seguimiento_calidad.py
import streamlit as st
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import pytz
from db import fetch_df

# Zona horaria
TZ = pytz.timezone('America/Guatemala')

# ============================================================
# FUNCIONES DE CARGA DE DATOS
# ============================================================

@st.cache_data(ttl=300)
def obtener_personal_asignado(supervisor_nombre):
    """Obtiene la lista de operadores a cargo del supervisor."""
    df = fetch_df(
        "SELECT nombre FROM usuarios WHERE supervisor = %s AND estado = 'Activo' ORDER BY nombre",
        params=[supervisor_nombre]
    )
    return df['nombre'].tolist() if not df.empty else []


@st.cache_data(ttl=60)
def cargar_datos_calidad(fechas, personal):
    """Carga los registros de calidad (aprobados/rechazados) para los operadores seleccionados."""
    fecha_inicio, fecha_fin = fechas
    if not personal:
        return pd.DataFrame()

    fecha_inicio_str = fecha_inicio.strftime('%Y-%m-%d')
    fecha_fin_str = fecha_fin.strftime('%Y-%m-%d')

    query = """
        SELECT 
            NULLIF(TRIM(fecha), '')::date AS fecha,
            operador_cc AS nombre,
            proceso,
            COALESCE(aprobados::int, 0) AS aprobados,
            COALESCE(rechazados::int, 0) AS rechazados
        FROM registro
        WHERE operador_cc = ANY(%s)
          AND NULLIF(TRIM(fecha), '')::date >= %s
          AND NULLIF(TRIM(fecha), '')::date <= %s
          AND operador_cc != 'N/A'
          AND tipo NOT IN ('Producción Horas Extras', 'Inspección Horas Extras', 'Reproceso Horas Extras')
    """
    df = fetch_df(query, params=[personal, fecha_inicio_str, fecha_fin_str])

    if df.empty:
        return df

    # Asegurar tipos
    df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce').dt.date
    df['aprobados'] = pd.to_numeric(df['aprobados'], errors='coerce').fillna(0).astype(int)
    df['rechazados'] = pd.to_numeric(df['rechazados'], errors='coerce').fillna(0).astype(int)

    # Agrupar por fecha, operador y proceso (por si hay múltiples registros el mismo día)
    df = df.groupby(['fecha', 'nombre', 'proceso'], as_index=False).agg({
        'aprobados': 'sum',
        'rechazados': 'sum'
    })

    return df


# ============================================================
# FUNCIÓN DE FORMATEO
# ============================================================

def color_calidad(val):
    """Retorna un color de fondo según el porcentaje de calidad."""
    if pd.isna(val):
        return ''
    if val >= 95:
        return 'background-color: #90EE90'   # verde
    elif val >= 85:
        return 'background-color: #FFD700'   # amarillo
    else:
        return 'background-color: #FF6B6B; color: white'  # rojo


# ============================================================
# RENDER PRINCIPAL
# ============================================================

def render():
    usuario = st.session_state.get("usuario")
    if not usuario:
        st.warning("Debe iniciar sesión")
        st.stop()

    nombre_supervisor = usuario.get("nombre")
    personal_asignado = obtener_personal_asignado(nombre_supervisor)

    if not personal_asignado:
        st.warning("No tiene personal a cargo para supervisar.")
        return

    st.title("📋 Control de Calidad")
    st.markdown(f"**Supervisor:** {nombre_supervisor} | **Personal a cargo:** {len(personal_asignado)}")

    # --- Filtro de fechas ---
    hoy = datetime.now(TZ).date()
    col1, col2 = st.columns(2)
    with col1:
        fecha_inicio = st.date_input("Fecha de inicio", value=hoy - timedelta(days=7), key="cc_fecha_ini")
    with col2:
        fecha_fin = st.date_input("Fecha de fin", value=hoy, key="cc_fecha_fin")

    if fecha_inicio > fecha_fin:
        st.error("La fecha de inicio no puede ser mayor a la fecha fin.")
        return

    # --- Filtro de operadores ---
    st.markdown("### 👥 Seleccionar Operadores")
    personal_filtrado = st.multiselect(
        "Operadores a revisar",
        options=personal_asignado,
        default=personal_asignado,
        key="cc_filtro_operador"
    )

    if not personal_filtrado:
        st.warning("Debe seleccionar al menos un operador.")
        return

    # --- Cargar datos ---
    with st.spinner("Cargando datos de calidad..."):
        df_calidad = cargar_datos_calidad((fecha_inicio, fecha_fin), personal_filtrado)

    if df_calidad.empty:
        st.info("No se encontraron registros de calidad en el período seleccionado.")
        return

    # --- Calcular porcentaje de calidad ---
    df_calidad['total'] = df_calidad['aprobados'] + df_calidad['rechazados']
    df_calidad['calidad'] = np.where(
        df_calidad['total'] > 0,
        (df_calidad['aprobados'] / df_calidad['total']) * 100,
        0
    )
    df_calidad['calidad'] = df_calidad['calidad'].round(1)

    # --- Ordenar y seleccionar columnas finales ---
    df_vista = df_calidad[['fecha', 'nombre', 'proceso', 'aprobados', 'rechazados', 'calidad']].copy()
    df_vista = df_vista.sort_values(['fecha', 'nombre', 'proceso']).reset_index(drop=True)
    df_vista.rename(columns={
        'fecha': 'Fecha',
        'nombre': 'Operador',
        'proceso': 'Proceso',
        'aprobados': 'Aprobados',
        'rechazados': 'Rechazados',
        'calidad': 'Calidad (%)'
    }, inplace=True)

    # --- Aplicar estilos ---
    styled = df_vista.style.map(color_calidad, subset=['Calidad (%)'])

    st.subheader("📊 Calidad por Operador y Proceso")
    st.dataframe(styled, use_container_width=True)

    # --- Resumen rápido por operador (global) ---
    st.subheader("📋 Resumen por Operador (total del período)")
    resumen = df_calidad.groupby('nombre', as_index=False).agg({
        'aprobados': 'sum',
        'rechazados': 'sum'
    })
    resumen['total'] = resumen['aprobados'] + resumen['rechazados']
    resumen['calidad'] = np.where(
        resumen['total'] > 0,
        (resumen['aprobados'] / resumen['total']) * 100,
        0
    )
    resumen['calidad'] = resumen['calidad'].round(1)
    resumen.rename(columns={
        'nombre': 'Operador',
        'aprobados': 'Aprobados',
        'rechazados': 'Rechazados',
        'calidad': 'Calidad (%)'
    }, inplace=True)
    resumen_vista = resumen[['Operador', 'Aprobados', 'Rechazados', 'Calidad (%)']]
    styled_resumen = resumen_vista.style.map(color_calidad, subset=['Calidad (%)'])
    st.dataframe(styled_resumen, use_container_width=True)

    # --- Botón de actualización ---
    st.divider()
    if st.button("🔄 Actualizar datos", type="secondary"):
        st.cache_data.clear()
        st.rerun()

# -*- coding: utf-8 -*-
"""
app.py — Bodega Municipal (prototipo, día 2)
Ejecutar con: streamlit run app.py

Arquitectura (revisada tras el diagnóstico día 2): UNA sola interfaz, con dos
vistas dentro de la misma app — Solicitante y Encargado — sobre la misma base
SQLite. Se descartó la idea de dos apps separadas: como SMC es un sistema
institucional demasiado interconectado para reemplazarlo o escribirle en
tiempo real, este sistema actúa como un buffer propio que estandariza los
datos y, por separado (ver sincronizar_smc.py), los deja listos para
entregarle a SMC de forma periódica y controlada — no en vivo.

La vista de Encargado se desbloquea con una clave simple (no es un login de
producción; para eso ver la nota en README.md).
"""

import os
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import streamlit as st

import core
import formato_impresion
from catalogo_real import PRODUCTOS

# Layout ancho: la pantalla de búsqueda y las tablas ocupan todo el ancho
# disponible, para no tener que arrastrar la barra horizontal a cada rato.
st.set_page_config(page_title="Bodega Municipal", layout="wide")

# Paleta institucional tomada de la web municipal (mtraiguen.cl), que declara
# el azul #4899CF como su color oficial. Se aplica por CSS y no solo por
# .streamlit/config.toml, porque ese archivo va en una carpeta oculta que
# suele quedarse sin subir al repositorio; así los colores se ven igual.
AZUL_MUNICIPAL = "#4899CF"
AZUL_OSCURO = "#1B4F72"

st.markdown(
    f"""
    <style>
      h1, h2, h3 {{ color: {AZUL_OSCURO}; }}
      /* barra de pestañas con el azul institucional */
      .stTabs [data-baseweb="tab-list"] {{
          border-bottom: 2px solid {AZUL_MUNICIPAL}33;
      }}
      .stTabs [aria-selected="true"] {{
          color: {AZUL_OSCURO} !important;
          border-bottom-color: {AZUL_MUNICIPAL} !important;
      }}
      /* botones principales */
      .stButton button[kind="primary"],
      .stDownloadButton button[kind="primary"] {{
          background-color: {AZUL_MUNICIPAL};
          border-color: {AZUL_MUNICIPAL};
      }}
      .stButton button[kind="primary"]:hover,
      .stDownloadButton button[kind="primary"]:hover {{
          background-color: {AZUL_OSCURO};
          border-color: {AZUL_OSCURO};
      }}
      /* franja superior */
      header[data-testid="stHeader"] {{
          border-bottom: 3px solid {AZUL_MUNICIPAL};
      }}
    </style>
    """,
    unsafe_allow_html=True,
)

CARPETA_PDF = Path("formularios")
CARPETA_PDF.mkdir(exist_ok=True)

DB_PATH = "bodega.db"
core.DB_PATH = DB_PATH

db_existia = os.path.exists(DB_PATH)
core.init_db(DB_PATH)  # idempotente: crea tablas si faltan, migra columnas si la base es antigua
if not db_existia:
    core.cargar_catalogo(PRODUCTOS, DB_PATH)
core.actualizar_precios_catalogo(DB_PATH)  # backfill seguro: no toca saldo, solo precio_unitario


# El control de acceso es la nómina de correos que autoriza el encargado
# (pestaña "Correos autorizados"), no el dominio: se aceptan direcciones de
# cualquier dominio siempre que estén autorizadas.

if "carrito" not in st.session_state:
    st.session_state.carrito = []
if "carrito_duenio" not in st.session_state:
    # A quién pertenece la lista que está en pantalla. Sin esto, la lista
    # quedaba viva al cambiar de cuenta: si el encargado agregaba un producto
    # y después entraba un solicitante en el mismo navegador, ese producto
    # aparecía dentro del pedido del solicitante.
    st.session_state.carrito_duenio = None
if "correo_registrado" not in st.session_state:
    st.session_state.correo_registrado = None  # correo de la persona ya identificada en esta sesión
if "form_nonce" not in st.session_state:
    st.session_state.form_nonce = 0  # se incrementa para limpiar los campos de búsqueda/cantidad
if "ultimo_agregado" not in st.session_state:
    st.session_state.ultimo_agregado = None
if "folio_recien_creado" not in st.session_state:
    st.session_state.folio_recien_creado = None
if "folio_recien_cerrado" not in st.session_state:
    st.session_state.folio_recien_cerrado = None
if "proceso_nonce" not in st.session_state:
    st.session_state.proceso_nonce = 0   # sirve para salir del detalle tras guardar
if "aviso_proceso" not in st.session_state:
    st.session_state.aviso_proceso = None
if "folio_preparando" not in st.session_state:
    st.session_state.folio_preparando = None
if "identidad_cache" not in st.session_state:
    st.session_state.identidad_cache = None
if "alerta_sync_vista" not in st.session_state:
    st.session_state.alerta_sync_vista = False

# La cuenta de encargado se crea sola la primera vez (ver core).
_ok_encargado, _aviso_encargado = core.asegurar_encargado_por_defecto(DB_PATH)
if not _ok_encargado:
    st.error(_aviso_encargado)

# ------------------------------------------------- identidad de la sesión
# Ya no hay selector de rol en la barra lateral: todos entran por el mismo
# login y el sistema reconoce solo si la cuenta es de encargado o no.
identidad_sesion = None
if st.session_state.correo_registrado:
    persona = core.obtener_persona(st.session_state.correo_registrado)
    if persona:
        identidad_sesion = {"correo": st.session_state.correo_registrado, **persona}
        st.session_state.identidad_cache = identidad_sesion
    elif st.session_state.get("identidad_cache"):
        # La cuenta no se encontró en la base, pero la sesión sigue abierta en
        # este navegador. En el hosting gratuito la base se borra al reiniciar
        # el servidor, y sin esto la persona quedaba expulsada en medio de un
        # pedido. Se conserva la sesión con los datos ya conocidos.
        identidad_sesion = st.session_state.identidad_cache
    else:
        st.session_state.correo_registrado = None

es_encargado = bool(identidad_sesion) and identidad_sesion.get("rol") == "encargado"


def cerrar_sesion():
    """Limpia todo el estado para que nada quede colgando entre personas."""
    st.session_state.correo_registrado = None
    st.session_state.carrito = []
    st.session_state.carrito_duenio = None
    st.session_state.folio_recien_creado = None
    st.session_state.folio_recien_cerrado = None
    st.session_state.ultimo_agregado = None


# Encabezado: título a la izquierda, sesión y cierre arriba a la derecha.
# El cierre de sesión va arriba del todo, sobre el título, para que quede
# lejos de los controles que se usan a cada rato y no se apriete sin querer.
if identidad_sesion:
    _, col_sesion = st.columns([4, 1])
    with col_sesion:
        rol_texto = "Encargado de bodega" if es_encargado else "Solicitante"
        st.caption(f"{identidad_sesion['nombre']}  \n{rol_texto}")
        if st.button("Cerrar sesión", width='stretch'):
            cerrar_sesion()
            st.rerun()
    st.divider()

st.title("Bodega Municipal")

if identidad_sesion:
    with st.sidebar:
        st.subheader("Mi cuenta")
        st.caption(identidad_sesion["correo"])
        with st.expander("Cambiar contraseña"):
            actual = st.text_input("Contraseña actual", type="password", key="pass_actual")
            nueva1 = st.text_input("Nueva contraseña", type="password", key="pass_nueva1")
            nueva2 = st.text_input("Repetir nueva contraseña", type="password", key="pass_nueva2")
            if st.button("Actualizar contraseña"):
                ok_pass, msg_pass = core.cambiar_password(
                    identidad_sesion["correo"], actual, nueva1, nueva2)
                (st.success if ok_pass else st.error)(msg_pass)

# =====================================================================
#  VISTA SOLICITANTE (común a ambos roles: el encargado también puede
#  generar solicitudes en nombre de alguien que llama por teléfono, etc.)
# =====================================================================

def color_coincidencia(score):
    """
    Color según qué tan segura es la coincidencia:
      100%      -> se marca con estrella (es el producto exacto)
      60 a 99%  -> verde    (coincidencia buena)
      45 a 59%  -> amarillo (dudosa, conviene revisar)
      menos 45% -> rojo     (muy probablemente no es lo que busca)
    """
    if score >= 60:
        return "green"
    if score >= 45:
        return "yellow"
    return "red"


def etiqueta_candidato(nombre, score, codigo=None):
    """Opción del buscador: estrella si es exacta, porcentaje coloreado si no."""
    sufijo = f"  ·  {codigo}" if codigo else ""
    if score >= 100:
        return f"⭐ **{nombre}**{sufijo}"
    color = color_coincidencia(score)
    return f":{color}[**{score:.0f}%**]  ·  {nombre}{sufijo}"


MENSAJE_SIN_RESULTADO = (
    "**NO EXISTE UN PRODUCTO REGISTRADO CON ESE NOMBRE.** "
    "Se recomienda consultar directamente al encargado por posibles discordancias "
    "en el inventario."
)
MENSAJE_AFINAR_BUSQUEDA = (
    "Si su producto no se encuentra en el motor de búsqueda, intente detallar más el "
    "producto agregando la marca, color o dimensiones."
)
MENSAJE_DERIVAR_ENCARGADO = (
    "Si el producto existe pero no aparece con ese nombre, diríjase al encargado de bodega "
    "para verificarlo manualmente. Él puede registrar esa forma de nombrarlo para que la "
    "próxima vez sí aparezca en el buscador."
)


def boton_imprimir(folio, sufijo_key="", solo_comprobante=False, editable=True):
    """
    Genera el formulario que corresponde según quién lo pide:
      - Solicitante -> SOLICITUD DE MATERIALES (la lleva a firmar).
      - Encargado   -> COMPROBANTE MOVIMIENTOS EN BODEGA, y solo al cerrar el
        proceso; a esa altura la solicitud firmada ya está en sus manos.

    En el comprobante, el encargado puede editar el texto de INFORMACIÓN
    ADICIONAL antes de descargar: viene redactado por defecto y él completa
    o corrige lo que falte, en vez de imprimir una línea en blanco.
    """
    cabecera, items = core.datos_para_impresion(folio)
    if cabecera is None:
        st.error("No se encontró la solicitud para imprimir.")
        return

    correlativo = cabecera.get("correlativo")

    if solo_comprobante and editable:
        st.markdown("**Datos editables del comprobante**")
        st.caption("Revise o corrija antes de descargar; sale impreso tal cual.")

        # El área que escribe el solicitante suele ser el nombre corto
        # ("FINANZAS") y no el nombre formal de la dirección de origen
        # ("DIRECCIÓN DE ADMINISTRACIÓN Y FINANZAS"), por eso es editable.
        depto = st.text_input(
            "Depto. origen",
            value=cabecera.get("depto_origen") or cabecera.get("area_departamento") or "",
            key=f"depto_{folio}_{sufijo_key}",
        )
        texto = st.text_area(
            "Información adicional",
            value=cabecera.get("info_adicional") or core.texto_info_adicional(cabecera),
            key=f"info_{folio}_{sufijo_key}", height=90,
        )
        if st.button("Guardar cambios", key=f"guardar_info_{folio}_{sufijo_key}"):
            core.guardar_depto_origen(folio, depto)
            core.guardar_info_adicional(folio, texto)
            st.success("Cambios guardados.")
            st.rerun()

        cabecera["depto_origen"] = depto
        cabecera["info_adicional"] = texto
        ruta = CARPETA_PDF / f"comprobante_{correlativo}.pdf"
        formato_impresion.generar_comprobante_pdf(ruta, cabecera, items)
        etiqueta = f"IMPRIMIR COMPROBANTE N° {correlativo}"
        nombre_archivo = f"comprobante_{correlativo}.pdf"
    elif solo_comprobante:
        # reimpresión desde el historial: se emite tal como quedó guardado,
        # sin volver a mostrar los campos de edición
        ruta = CARPETA_PDF / f"comprobante_{correlativo}.pdf"
        formato_impresion.generar_comprobante_pdf(ruta, cabecera, items)
        etiqueta = f"REIMPRIMIR COMPROBANTE N° {correlativo}"
        nombre_archivo = f"comprobante_{correlativo}.pdf"
    else:
        ruta = CARPETA_PDF / f"solicitud_{correlativo}.pdf"
        formato_impresion.generar_solicitud_pdf(ruta, cabecera, items)
        etiqueta = f"IMPRIMIR SOLICITUD N° {correlativo}"
        nombre_archivo = f"solicitud_{correlativo}.pdf"

    with open(ruta, "rb") as f:
        st.download_button(
            etiqueta, data=f.read(), file_name=nombre_archivo, mime="application/pdf",
            width='stretch', type="primary", key=f"print_{folio}_{sufijo_key}",
        )


def panel_acceso():
    """
    Puerta de entrada para solicitantes: pestaña de ingreso (correo +
    contraseña) y pestaña de registro por única vez. El registro exige que
    el correo esté en la nómina autorizada por el encargado; la contraseña
    se pide dos veces para asegurarse de que quedó bien escrita.
    """
    st.subheader("Acceso de solicitantes")
    tab_login, tab_registro = st.tabs(["Ingresar", "Registrarme por primera vez"])

    with tab_login:
        correo = st.text_input("Correo institucional", key="login_correo",
                               placeholder="nombre.apellido@dominio.cl")
        password = st.text_input("Contraseña", type="password", key="login_pass")
        if st.button("Ingresar", type="primary"):
            ok, mensaje = core.verificar_login(correo, password)
            if ok:
                st.session_state.correo_registrado = correo.strip().lower()
                st.rerun()
            else:
                st.error(mensaje)

    with tab_registro:
        st.caption(
            "El registro se hace una sola vez. Después entra siempre con su correo "
            "y la contraseña que cree aquí."
        )
        correo_r = st.text_input("Correo institucional", key="reg_correo",
                                 placeholder="nombre.apellido@dominio.cl")

        if not correo_r:
            return
        correo_r = correo_r.strip().lower()

        if core.obtener_persona(correo_r):
            st.info("Este correo ya está registrado. Use la pestaña 'Ingresar'.")
            return

        if not core.formato_correo_valido(correo_r):
            st.error(f'"{correo_r}" no tiene formato de correo válido.')
            return

        # El dominio correcto no prueba que el correo exista ni que sea suyo.
        # El control real es la lista de correos que el encargado autorizó.
        if not core.correo_autorizado(correo_r):
            st.error(
                f'El correo "{correo_r}" no está en la nómina de correos autorizados '
                "para hacer solicitudes."
            )
            st.info(
                "Si usted trabaja en la municipalidad y necesita acceso, solicite al "
                "encargado de bodega que agregue su correo a la nómina autorizada."
            )
            return

        st.success("Correo autorizado. Complete sus datos:")
        nombre = st.text_input("Su nombre completo", key="reg_nombre")
        area = st.text_input("Área / Departamento", key="reg_area", placeholder="ej. Finanzas")
        nombre_supervisor = st.text_input(
            "Nombre de su supervisor/jefatura", key="reg_sup",
            placeholder="ej. Cristian San Miguel",
        )
        password1 = st.text_input("Cree una contraseña", type="password", key="reg_pass1")
        password2 = st.text_input("Repita la contraseña", type="password", key="reg_pass2")

        if st.button("Completar registro", type="primary"):
            errores = []
            if not nombre.strip():
                errores.append("nombre")
            if not area.strip():
                errores.append("área/departamento")
            if not nombre_supervisor.strip():
                errores.append("nombre del supervisor")
            if errores:
                st.error("Faltan datos: " + ", ".join(errores))
                return
            ok, mensaje = core.validar_password(password1, password2)
            if not ok:
                st.error(mensaje)
                return
            core.registrar_persona(correo_r, nombre, area, nombre_supervisor, password1)
            st.session_state.correo_registrado = correo_r
            st.success("Registro completado.")
            st.rerun()


def asegurar_carrito_de(duenio):
    """
    Cada cuenta tiene su propia lista de productos. Si la lista en pantalla
    pertenece a otra cuenta (porque el encargado la armó antes, o porque
    entró otra persona en el mismo navegador), se descarta y se parte de
    cero. Sin esto, un producto agregado por el encargado terminaba metido
    dentro del pedido del siguiente usuario que iniciara sesión.
    """
    if st.session_state.carrito_duenio != duenio:
        st.session_state.carrito = []
        st.session_state.carrito_duenio = duenio
        st.session_state.folio_recien_creado = None
        st.session_state.ultimo_agregado = None


def panel_nueva_solicitud(es_encargado: bool, identidad: dict = None):
    """
    identidad: si viene (flujo solicitante ya registrado), el nombre sale del
    registro. Si es None (flujo encargado), se piden los datos a mano.

    La lista de productos queda aislada por cuenta (ver asegurar_carrito_de).
    """
    # Identificador de la cuenta dueña de esta lista: el correo del
    # solicitante, o "ENCARGADO" cuando lo arma el encargado.
    duenio = identidad["correo"] if identidad else "__ENCARGADO__"
    asegurar_carrito_de(duenio)

    st.subheader("1. Buscar producto")

    # Las claves de los widgets llevan un 'nonce' que se incrementa cada vez
    # que se agrega un producto. Al cambiar la clave, Streamlit los crea de
    # nuevo vacíos — así se limpia solo el texto buscado y la cantidad, sin
    # que la persona tenga que borrarlos a mano, y sin tocar el carrito.
    n = st.session_state.form_nonce
    busqueda = st.text_input("Escriba el producto como se le ocurra", key=f"busqueda_input_{n}")

    if busqueda:
        # umbral bajo a propósito: así también se ven las coincidencias malas
        # pintadas en rojo, en vez de esconderlas y dejar la pantalla vacía.
        candidatos = core.buscar_producto(busqueda, umbral=35, limite=7)
        if candidatos:
            opciones = [
                etiqueta_candidato(nombre, score, codigo if es_encargado else None)
                for codigo, nombre, score in candidatos
            ]
            st.caption(
                "⭐ es coincidencia exacta, pero igual se muestran las demás opciones "
                "parecidas. El porcentaje indica qué tan segura es cada una: "
                ":green[**verde**] buena · :yellow[**amarillo**] dudosa · "
                ":red[**rojo**] poco confiable."
            )
            seleccion = st.radio("Coincidencias encontradas:", opciones, key=f"radio_sel_{n}")
            cantidad = st.number_input("Cantidad", min_value=1, step=1, key=f"cant_input_{n}")

            if st.button("Agregar a la solicitud", type="primary"):
                idx = opciones.index(seleccion)
                codigo, nombre, score = candidatos[idx]
                if score < 100 and es_encargado:
                    core.registrar_alias_nuevo(busqueda, codigo)
                st.session_state.carrito.append((codigo, nombre, cantidad))
                st.session_state.ultimo_agregado = f"{nombre} x{cantidad}"
                st.session_state.form_nonce += 1  # limpia búsqueda y cantidad
                st.rerun()

            st.info(MENSAJE_AFINAR_BUSQUEDA)
        else:
            core.registrar_alias_pendiente(busqueda)
            st.error(MENSAJE_SIN_RESULTADO)
            st.info(MENSAJE_DERIVAR_ENCARGADO)

    if st.session_state.get("ultimo_agregado"):
        st.success(f"Agregado: {st.session_state.ultimo_agregado}")
        st.session_state.ultimo_agregado = None

    if st.session_state.carrito:
        st.subheader("2. Productos en esta solicitud")

        # Cada producto en su propia fila con una ✕ a la derecha para sacarlo
        # individualmente. Antes solo existía "vaciar lista", que obligaba a
        # rehacer todo el pedido por equivocarse en un solo ítem.
        for indice, (codigo, nombre, cantidad) in enumerate(list(st.session_state.carrito)):
            col_texto, col_cant, col_x = st.columns([8, 2, 1])
            etiqueta = f"**{nombre}**" + (f"  ·  {codigo}" if es_encargado else "")
            col_texto.markdown(etiqueta)
            col_cant.markdown(f"cantidad: **{cantidad}**")
            if col_x.button("✕", key=f"quitar_{indice}_{codigo}",
                            help=f"Quitar {nombre} de la solicitud"):
                st.session_state.carrito.pop(indice)
                st.rerun()
            st.divider()

        st.subheader("3. Datos de la solicitud")
        if identidad:
            # El nombre viene del registro: la persona ya se identificó al
            # entrar, no tiene por qué volver a escribirlo (ni podría cambiarlo).
            solicitante = identidad["nombre"]
            correo_solicitante = identidad["correo"]
            correo_supervisor = identidad.get("correo_supervisor") or ""
            st.markdown(f"**Solicitante:** {solicitante}")

            # Área, oficina y supervisor quedan editables: una misma persona
            # podría estar pidiendo para otro departamento, otra oficina o con
            # otra jefatura. La oficina no se pide en el registro, solo acá.
            c1, c2 = st.columns(2)
            area = c1.text_input("Área / Departamento",
                                 value=identidad.get("area_departamento") or "")
            oficina = c2.text_input("Oficina", placeholder="ej. archivo e inventario")
            supervisor = st.text_input("Supervisor / jefatura que firma",
                                       value=identidad.get("nombre_supervisor") or "")
        else:
            solicitante = st.text_input("Solicitante")
            c1, c2 = st.columns(2)
            area = c1.text_input("Área / Departamento")
            oficina = c2.text_input("Oficina", placeholder="ej. archivo e inventario")
            supervisor = st.text_input("Supervisor / jefe (firma pendiente en papel)")
            correo_solicitante = None
            correo_supervisor = None

        if st.button("Registrar solicitud (queda 'pendiente de firma')"):
            items = [(c, cant) for c, _, cant in st.session_state.carrito]
            try:
                folio = core.crear_solicitud(
                    solicitante, supervisor, area, items,
                    correo_solicitante=correo_solicitante, correo_supervisor=correo_supervisor,
                    oficina=oficina,
                )
            except ValueError as e:
                st.error(str(e))
                st.warning("La solicitud NO se guardó — complete todos los datos obligatorios e intente de nuevo.")
            else:
                st.session_state.folio_recien_creado = folio
                st.session_state.carrito = []
                st.rerun()

    # Tras registrar, se muestra el folio y el botón de impresión grande.
    if st.session_state.get("folio_recien_creado"):
        folio = st.session_state.folio_recien_creado
        cabecera, _ = core.datos_para_impresion(folio)
        st.success(
            f"Solicitud registrada — **N° {cabecera['correlativo']}**  \n"
            f"Imprima el formulario, hágalo firmar y timbrar, y llévelo a bodega."
        )
        boton_imprimir(folio, sufijo_key="nueva")
        df = core.resumen_solicitud(folio)
        for _, fila in df.iterrows():
            if fila["mensaje_sistema"]:
                st.warning(f"{fila['producto']}: {fila['mensaje_sistema']}")
        if st.button("Hacer otra solicitud"):
            st.session_state.folio_recien_creado = None
            st.rerun()


def panel_mis_solicitudes(identidad: dict):
    st.subheader("Mis solicitudes")
    df = core.solicitudes_de_correo(identidad["correo"])
    if df.empty:
        st.info("No hay solicitudes registradas con tu correo todavía.")
    else:
        etiquetas_estado = {
            "pendiente_firma": "Pendiente de que traigas el papel firmado",
            "preliminar_aceptada": "Papel recibido, en revisión en bodega",
            "editada": "En bodega, cantidades ajustadas",
            "cerrada": "Entregada",
            "anulada": "Anulada",
        }
        df["estado"] = df["estado"].map(etiquetas_estado).fillna(df["estado"])
        st.dataframe(df, width='stretch', hide_index=True)


# =====================================================================
#  VISTA ENCARGADO
# =====================================================================

def panel_solicitudes_activas():
    st.subheader("Solicitudes por procesar")
    st.caption(
        "Solo las pendientes. Al cerrar o anular una solicitud, esta sale de la pantalla "
        "y queda disponible en Pedidos completados y en el Historial."
    )

    # Comprobante de lo recién cerrado, antes de cualquier salida temprana.
    if st.session_state.get("folio_recien_cerrado"):
        st.success("Solicitud cerrada — stock descontado. Imprima el comprobante para que "
                   "quien retira firme la recepción.")
        boton_imprimir(st.session_state.folio_recien_cerrado,
                       sufijo_key="cierre", solo_comprobante=True)
        if st.button("Listo"):
            st.session_state.folio_recien_cerrado = None
            st.rerun()
        st.divider()

    atrasadas = core.contar_solicitudes_atrasadas()
    if atrasadas:
        st.error(f"⚠️ {atrasadas} solicitud(es) pendientes vienen de jornadas anteriores "
                 "— proceso tardado.")

    df_activas = core.listar_solicitudes_activas()
    if df_activas.empty:
        st.success("No hay solicitudes pendientes.")
        return

    df_vista = df_activas.copy()
    df_vista.insert(0, "", df_vista["atrasada"].map({True: "⚠️", False: ""}))
    df_vista["estado"] = df_vista["estado"].map(ETIQUETAS_ESTADO).fillna(df_vista["estado"])
    df_vista = df_vista.rename(columns={"correlativo": "N°", "n_productos": "productos",
                                        "area_departamento": "departamento"})

    def _resaltar(fila):
        return ["background-color: rgba(255,0,0,0.12)" if fila["atrasada"] else ""] * len(fila)

    st.dataframe(
        df_vista.style.apply(_resaltar, axis=1),
        width='stretch', hide_index=True,
        column_config={"atrasada": None, "folio": None, "fecha_solicitud": "fecha"},
    )
    if atrasadas:
        st.caption("⚠️ = pendiente arrastrada de una jornada anterior.")

    # ------------------------------------------------------------- procesar
    st.divider()
    st.subheader("Procesar una solicitud")

    n = st.session_state.proceso_nonce
    etiquetas = {f'N° {f.correlativo} · {f.solicitante} · {f.area_departamento}': f.folio
                 for f in df_activas.itertuples()}
    elegido = st.selectbox("Elegir solicitud", [""] + list(etiquetas.keys()),
                           key=f"folio_select_{n}")
    if not elegido:
        return
    folio = etiquetas[elegido]

    df = core.resumen_solicitud(folio)
    if df.empty:
        st.error("Solicitud no encontrada.")
        return
    estado = df.iloc[0]["estado"]
    st.info(f"Estado: **{ETIQUETAS_ESTADO.get(estado, estado)}**")

    def salir_del_proceso(mensaje=None):
        """Cierra el detalle y vuelve a la lista: lo demás se ve en el Historial."""
        if mensaje:
            st.session_state.aviso_proceso = mensaje
        st.session_state.folio_preparando = None
        st.session_state.proceso_nonce += 1
        st.rerun()

    if st.session_state.get("aviso_proceso"):
        st.success(st.session_state.aviso_proceso)
        st.session_state.aviso_proceso = None

    # ---- paso 1: esperando el papel firmado
    if estado == "pendiente_firma":
        st.dataframe(
            df[["producto", "cantidad_solicitada", "mensaje_sistema"]].rename(
                columns={"cantidad_solicitada": "solicitado", "mensaje_sistema": "observación"}),
            width='stretch', hide_index=True,
        )
        if st.button("El solicitante trajo el papel timbrado y firmado", type="primary"):
            core.aceptar_preliminar(folio)
            st.rerun()

    # ---- paso 2: ajustar cantidades (una sola tabla editable)
    elif estado in ("preliminar_aceptada", "editada"):
        st.write("Ajuste lo realmente entregado:")
        st.caption("Deje en 0 lo que no se entregue: no aparecerá en el comprobante.")
        cantidades = {}
        for _, fila in df.iterrows():
            c1, c2 = st.columns([4, 1])
            c1.markdown(f"**{fila['producto']}**"
                        + (f"  \n{fila['mensaje_sistema']}" if fila["mensaje_sistema"] else ""))
            base = fila["cantidad_entregada"]
            if base is None:
                base = fila["cantidad_solicitada"]
            cantidades[fila["producto"]] = c2.number_input(
                f"entregado — {fila['producto']}", min_value=0, step=1, value=int(base),
                key=f"ent_{n}_{fila['producto']}", label_visibility="collapsed",
            )

        def guardar_cantidades():
            conn = core.get_connection()
            for producto, cantidad in cantidades.items():
                codigo = conn.execute(
                    "SELECT codigo FROM productos WHERE nombre_estandar=?", (producto,)
                ).fetchone()[0]
                core.editar_entrega(folio, codigo, cantidad)
            conn.close()

        c1, c2 = st.columns(2)
        if c1.button("Guardar y salir", width='stretch'):
            guardar_cantidades()
            salir_del_proceso("Cantidades guardadas. Puede retomarlas cuando quiera.")

        if c2.button("Guardar y preparar comprobante", type="primary", width='stretch'):
            guardar_cantidades()
            st.session_state.folio_preparando = folio
            st.rerun()

        # ---- paso 3: comprobante primero, descuento de stock al final
        #
        # El descuento se dejó para el último paso a propósito: así el
        # encargado revisa el documento y corrige el texto ANTES de que el
        # movimiento quede firme. Si algo está mal, todavía puede volver
        # atrás sin haber tocado el inventario.
        if st.session_state.get("folio_preparando") == folio:
            st.divider()
            st.subheader("Comprobante de la entrega")
            st.caption(
                "Revise el documento y su texto. El stock **todavía no se ha descontado**: "
                "eso ocurre recién al confirmar más abajo."
            )
            boton_imprimir(folio, sufijo_key="previo", solo_comprobante=True)

            st.divider()
            c1, c2 = st.columns(2)
            if c1.button("Volver a corregir cantidades", width='stretch'):
                st.session_state.folio_preparando = None
                st.rerun()
            if c2.button("Confirmar entrega y descontar stock", type="primary",
                         width='stretch'):
                alertas = core.cerrar_solicitud(
                    folio, usuario_operacion=core.nombre_encargado())
                st.session_state.folio_recien_cerrado = folio
                st.session_state.folio_preparando = None
                for _codigo, tipo, mensaje in alertas:
                    st.session_state.aviso_proceso = f"[{tipo.upper()}] {mensaje}"
                salir_del_proceso()

    # ---- anular, disponible mientras no esté cerrada
    with st.expander("Anular esta solicitud"):
        motivo = st.text_input("Motivo de anulación", key=f"motivo_{n}")
        if st.button("Anular solicitud"):
            if not motivo:
                st.warning("Escriba un motivo antes de anular.")
            else:
                core.anular_solicitud(folio, motivo)
                salir_del_proceso("Solicitud anulada.")


def pesos(valor) -> str:
    """Formatea un número como pesos chilenos: 25487911 -> '$25.487.911'."""
    return f"${valor:,.0f}".replace(",", ".")


def panel_inventario_general():
    st.subheader("Inventario general")
    total = core.valor_total_inventario()
    st.metric("Valor de la totalidad de los bienes", pesos(total))
    st.caption("Calculado en vivo: precio unitario (derivado del corte 14/07/2026) × saldo actual de cada producto.")

    df = core.listar_inventario_general()

    # Buscador visible de entrada, sin tener que abrir el ícono de lupa
    # de la tabla. Filtra por nombre, código o categoría a la vez.
    filtro = st.text_input("Buscar en el inventario", placeholder="nombre, código o categoría")
    if filtro:
        f = core.normalizar(filtro)
        mask = (
            df["nombre_estandar"].apply(lambda x: f in core.normalizar(str(x)))
            | df["codigo"].apply(lambda x: f in core.normalizar(str(x)))
            | df["categoria"].apply(lambda x: f in core.normalizar(str(x)))
        )
        df = df[mask]
        st.caption(f"{len(df)} producto(s) coinciden con \"{filtro}\".")

    # Los valores se muestran como dinero, no como enteros pelados.
    df_vista = df.copy()
    df_vista["precio_unitario"] = df_vista["precio_unitario"].apply(pesos)
    df_vista["valor_actual"] = df_vista["valor_actual"].apply(pesos)
    df_vista = df_vista.rename(columns={
        "nombre_estandar": "producto", "unidad_medida": "unidad",
        "precio_unitario": "valor unitario", "valor_actual": "valor total",
    })
    st.dataframe(df_vista, width='stretch', hide_index=True)


def panel_inventario_critico():
    st.subheader("Inventario crítico")
    st.caption("Insumos agotados o bajo su stock crítico — los que requieren compra o renovación más urgente.")
    df = core.listar_stock_critico()
    if df.empty:
        st.success("No hay productos agotados ni bajo su stock crítico.")
    else:
        st.dataframe(df, width='stretch', hide_index=True)


ETIQUETAS_ESTADO = {
    "pendiente_firma": "Pendiente de firma",
    "preliminar_aceptada": "Aceptada preliminar",
    "editada": "Editada en bodega",
    "cerrada": "Cerrada / entregada",
    "anulada": "Anulada",
}


def panel_historial():
    st.subheader("Historial de solicitudes")
    st.caption(
        "Buscador y filtros sobre todas las solicitudes registradas. Desde acá se pueden "
        "reimprimir comprobantes y armar recopilaciones (por ejemplo, todos los movimientos "
        "de un día o de una semana) juntando de a dos por hoja."
    )

    # ---------------------------------------------------------------- filtros
    c1, c2, c3 = st.columns(3)
    agrupacion = c1.selectbox("Agrupar por", ["día", "semana", "mes", "año"], index=2)
    # Por defecto se acota a este mes: con miles de solicitudes históricas,
    # cargar "Todo" y desplegar cada una haría la pantalla inusable.
    rango = c2.selectbox(
        "Rango", ["Este mes", "Hoy", "Últimos 7 días", "Este año", "Personalizado", "Todo"],
        index=0,
    )
    estados = c3.multiselect(
        "Estado", ["pendiente_firma", "preliminar_aceptada", "editada", "cerrada", "anulada"],
        default=[],
    )

    hoy = date.today()
    desde = hasta = None
    if rango == "Hoy":
        desde = hasta = hoy
    elif rango == "Últimos 7 días":
        desde, hasta = hoy - timedelta(days=6), hoy
    elif rango == "Este mes":
        desde, hasta = hoy.replace(day=1), hoy
    elif rango == "Este año":
        desde, hasta = hoy.replace(month=1, day=1), hoy
    elif rango == "Personalizado":
        cd, ch = st.columns(2)
        desde = cd.date_input("Desde", value=hoy - timedelta(days=30))
        hasta = ch.date_input("Hasta", value=hoy)

    f1, f2, f3 = st.columns(3)
    solicitante = f1.text_input("Usuario / solicitante", placeholder="parte del nombre")
    area = f2.text_input("Departamento", placeholder="ej. finanzas")
    oficina = f3.text_input("Oficina", placeholder="ej. archivo")

    o1, o2 = st.columns([2, 1])
    ordenar_por = o1.selectbox(
        "Ordenar por",
        ["Fecha", "N° de solicitud", "Solicitante", "Departamento", "Oficina",
         "Cantidad de productos", "Unidades"],
    )
    descendente = o2.selectbox("Orden", ["Mayor a menor", "Menor a mayor"]) == "Mayor a menor"

    df = core.historial_filtrado(
        desde=desde, hasta=hasta, solicitante=solicitante, area=area,
        oficina=oficina, estados=estados or None,
    )

    if df.empty:
        st.info("No hay solicitudes que coincidan con los filtros.")
        return

    columnas_orden = {
        "Fecha": "fecha_solicitud", "N° de solicitud": "correlativo",
        "Solicitante": "solicitante", "Departamento": "area_departamento",
        "Oficina": "oficina", "Cantidad de productos": "n_productos",
        "Unidades": "total_unidades",
    }
    df = df.sort_values(columnas_orden[ordenar_por], ascending=not descendente)

    df, resumen = core.agrupar_historial(df, agrupacion)

    m1, m2, m3 = st.columns(3)
    m1.metric("Solicitudes", len(df))
    m2.metric("Líneas de producto", int(df["n_productos"].sum()))
    m3.metric("Unidades", int(df["total_unidades"].sum()))

    st.markdown(f"**Resumen por {agrupacion}**")
    st.dataframe(resumen, width='stretch', hide_index=True)

    # ------------------------------------------------- recopilador de impresión
    st.divider()
    st.markdown("**Recopilar e imprimir**")
    periodos = resumen["periodo"].tolist()
    periodo_sel = st.selectbox("Período a recopilar", ["(toda la selección)"] + periodos)

    df_imprimir = df if periodo_sel == "(toda la selección)" else df[df["periodo"] == periodo_sel]
    cerradas = df_imprimir[df_imprimir["estado"] == "cerrada"]

    st.caption(
        f"{len(df_imprimir)} solicitud(es) en la selección · {len(cerradas)} cerrada(s) "
        "con comprobante disponible."
    )

    if cerradas.empty:
        st.info("No hay solicitudes cerradas en esta selección para imprimir comprobantes.")
    else:
        comprobantes = [core.datos_para_impresion(f) for f in cerradas["folio"]]
        n_chicos = sum(1 for _, items in comprobantes
                       if formato_impresion.cabe_en_media_hoja(items))
        n_grandes = len(comprobantes) - n_chicos
        hojas = (n_chicos + 1) // 2 + n_grandes
        ahorro = len(comprobantes) - hojas

        st.caption(f"{len(comprobantes)} comprobante(s) → **{hojas} hoja(s)**"
                   + (f", ahorrando {ahorro}" if ahorro > 0 else ""))

        ruta = CARPETA_PDF / "recopilacion_comprobantes.pdf"
        formato_impresion.generar_comprobantes_pareados_pdf(ruta, comprobantes)
        with open(ruta, "rb") as f:
            st.download_button(
                f"IMPRIMIR RECOPILACIÓN ({hojas} hoja(s))", data=f.read(),
                file_name=f"comprobantes_{str(periodo_sel).replace('/', '-').replace(' ', '_')}.pdf",
                mime="application/pdf", width='stretch', type="primary",
            )

    # ------------------------------------------------------------- el detalle
    st.divider()
    st.markdown("**Solicitudes**")

    # Paginación: no se despliega el detalle de todo el historial de una vez.
    # Con más de mil solicitudes acumuladas, dibujar cada una dejaría la
    # página inutilizable; se muestran de a POR_PAGINA y se navega.
    POR_PAGINA = 25
    detalle_periodos = ([periodo_sel] if periodo_sel != "(toda la selección)"
                        else resumen["periodo"].tolist())
    df_detalle = df[df["periodo"].isin(detalle_periodos)]

    total_paginas = max(1, (len(df_detalle) + POR_PAGINA - 1) // POR_PAGINA)
    if total_paginas > 1:
        pagina = st.number_input(
            f"Página (de {total_paginas}) — {len(df_detalle)} solicitudes en la selección",
            min_value=1, max_value=total_paginas, value=1, step=1,
        )
    else:
        pagina = 1
    inicio = (int(pagina) - 1) * POR_PAGINA
    df_pagina = df_detalle.iloc[inicio:inicio + POR_PAGINA]

    for periodo in detalle_periodos:
        grupo = df_pagina[df_pagina["periodo"] == periodo]
        if grupo.empty:
            continue
        st.markdown(f"##### {periodo}  ·  {len(grupo)} en esta página")
        for _, fila in grupo.iterrows():
            etiqueta = (f'N° {fila["correlativo"]}  ·  {fila["solicitante"]}  ·  '
                        f'{fila["fecha_solicitud"]}')
            with st.expander(etiqueta):
                c1, c2, c3, c4 = st.columns(4)
                c1.markdown(f"**Departamento**  \n{fila['area_departamento'] or '—'}")
                c2.markdown(f"**Oficina**  \n{fila['oficina'] or '—'}")
                c3.markdown(f"**Supervisor**  \n{fila['supervisor'] or '—'}")
                c4.markdown(f"**Estado**  \n{ETIQUETAS_ESTADO.get(fila['estado'], fila['estado'])}")

                detalle = core.detalle_folio(fila["folio"])
                st.dataframe(
                    detalle.rename(columns={
                        "nombre_estandar": "producto", "unidad_medida": "unidad",
                        "cantidad_solicitada": "solicitado", "cantidad_entregada": "entregado",
                        "mensaje_sistema": "observación",
                    }),
                    width='stretch', hide_index=True,
                )
                # Reimpresión: útil cuando piden revisiones o se extravía el papel
                if fila["estado"] == "cerrada":
                    boton_imprimir(fila["folio"], sufijo_key=f"hist_{fila['correlativo']}",
                                   solo_comprobante=True, editable=False)


def panel_crear_alias():
    st.subheader("Crear un nuevo alias para producto existente")
    st.caption(
        "Un alias NO cambia el nombre del producto. Solo agrega otra forma de escribirlo en el "
        "buscador: si registra 'confort' para ROLLO PAPEL HIGIÉNICO, quien escriba 'confort' "
        "encontrará ese producto. Lo hace el encargado porque es quien sabe cómo le dicen "
        "realmente a cada cosa."
    )

    st.markdown("**1. Código del producto**")
    codigo = st.text_input("Código", placeholder="ej. 00204001", key="alias_codigo")

    producto = core.obtener_producto(codigo) if codigo.strip() else None

    if codigo.strip() and producto is None:
        st.error(f'No existe ningún producto activo con el código "{codigo.strip()}".')
        st.caption("Puede buscar el código correcto en la pestaña Inventario general.")

    if producto:
        st.markdown("**2. Corroboración del producto registrado en sistema**")
        st.success(
            f"**{producto['nombre_estandar']}**  \n"
            f"Categoría: {producto['categoria']} · Unidad: {producto['unidad_medida']} · "
            f"Saldo actual: {producto['saldo']}"
        )
        df_alias = core.alias_de_producto(producto["codigo"])
        if not df_alias.empty:
            st.markdown("**Alias registrados para este producto**")
            st.caption("Puede corregir el texto de cualquiera o eliminarlo.")
            for _, fila_alias in df_alias.iterrows():
                ca, cb, cc = st.columns([6, 2, 1])
                nuevo_texto = ca.text_input(
                    "alias", value=fila_alias["texto_alias"],
                    key=f"ed_{fila_alias['id']}", label_visibility="collapsed",
                )
                if cb.button("Guardar", key=f"btn_ed_{fila_alias['id']}"):
                    ok, mensaje = core.editar_alias(int(fila_alias["id"]), nuevo_texto)
                    (st.success if ok else st.error)(mensaje)
                    if ok:
                        st.rerun()
                if cc.button("✕", key=f"btn_del_{fila_alias['id']}",
                             help=f'Eliminar el alias "{fila_alias["texto_alias"]}"'):
                    ok, mensaje = core.eliminar_alias(int(fila_alias["id"]))
                    (st.success if ok else st.error)(mensaje)
                    if ok:
                        st.rerun()

        st.markdown("**3. Escribir el nuevo alias**")
        nuevo_alias = st.text_input(
            "Nuevo alias", placeholder="ej. confort", key="alias_texto"
        )
        if st.button("Registrar alias"):
            ok, mensaje = core.crear_alias_manual(producto["codigo"], nuevo_alias)
            if ok:
                st.success(mensaje)
            else:
                st.error(mensaje)

    st.divider()
    st.subheader("Carga masiva desde Excel")
    st.caption(
        "Si prefiere anotar los alias en un Excel a mano, súbalo aquí. El archivo debe tener "
        "dos columnas llamadas 'codigo' y 'alias' — una fila por cada forma en que la gente "
        "nombra un producto. Se procesa fila por fila y se muestra qué entró y qué no."
    )

    ejemplo = pd.DataFrame({
        "codigo": ["00204001", "00204001", "00205033"],
        "alias": ["confort", "papel confort", "poet"],
    })
    with st.expander("Ver formato esperado del Excel"):
        st.dataframe(ejemplo, width='stretch', hide_index=True)

    archivo = st.file_uploader("Archivo de alias (.xlsx o .csv)", type=["xlsx", "csv"])
    if archivo is not None and st.button("Procesar archivo"):
        try:
            resultados = core.importar_alias_desde_excel(archivo)
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")
        else:
            if resultados.empty:
                st.warning("El archivo no traía filas con datos.")
            else:
                creados = (resultados["resultado"] == "creado").sum()
                rechazados = (resultados["resultado"] == "rechazado").sum()
                c1, c2 = st.columns(2)
                c1.metric("Alias creados", int(creados))
                c2.metric("Filas rechazadas", int(rechazados))
                st.dataframe(resultados, width='stretch', hide_index=True)
                if rechazados:
                    st.caption("Revise la columna 'detalle' para ver por qué se rechazó cada fila.")

    st.divider()
    st.subheader("Búsquedas sin resultado (referencia)")
    st.caption(
        "Textos que alguien buscó y no encontraron nada. Sirven de pista sobre qué alias "
        "conviene crear, pero no hacen nada por sí solos."
    )
    conn = core.get_connection()
    df_pend = pd.read_sql("SELECT * FROM alias_pendientes WHERE revisado=0 ORDER BY id DESC", conn)
    conn.close()
    if df_pend.empty:
        st.info("No hay búsquedas sin resultado registradas.")
    else:
        st.dataframe(df_pend, width='stretch', hide_index=True)


def panel_pedidos_completados():
    st.subheader("Pedidos completados")
    st.caption(
        "Comprobantes de solicitudes ya cerradas. Puede imprimirlos de a dos por hoja: "
        "se juntan respetando el formato, con una línea de corte al medio, para no gastar "
        "una hoja entera en pedidos chicos."
    )

    conn = core.get_connection()
    df = pd.read_sql(
        "SELECT folio, correlativo, fecha_solicitud, solicitante, area_departamento "
        "FROM solicitudes WHERE estado='cerrada' ORDER BY correlativo DESC",
        conn,
    )
    conn.close()

    if df.empty:
        st.info("Todavía no hay solicitudes cerradas.")
        return

    # se marca cuáles caben en media hoja, para que la elección sea informada
    filas = []
    for _, fila in df.iterrows():
        _, items = core.datos_para_impresion(fila["folio"])
        filas.append({
            "N°": fila["correlativo"], "folio": fila["folio"],
            "fecha": fila["fecha_solicitud"], "solicitante": fila["solicitante"],
            "área": fila["area_departamento"], "productos": len(items),
            "media hoja": "sí" if formato_impresion.cabe_en_media_hoja(items) else "no (va sola)",
        })
    df_vista = pd.DataFrame(filas)
    st.dataframe(df_vista.drop(columns=["folio"]), width='stretch', hide_index=True)

    st.markdown("**Imprimir varios en una sola hoja**")
    opciones = {f'N° {f["N°"]} · {f["solicitante"]} ({f["productos"]} prod.)': f["folio"]
                for f in filas}
    st.info(
        "Para imprimir un solo comprobante desde esta ventana, selecciónelo en la lista y "
        "luego haga clic en cualquier espacio en blanco de la página: el botón de impresión "
        "aparecerá debajo."
    )
    elegidos = st.multiselect(
        "Elija los comprobantes a imprimir juntos", list(opciones.keys()),
        help="Se agrupan de a dos por hoja. Los que no caben en media hoja salen solos.",
    )

    if elegidos:
        comprobantes = [core.datos_para_impresion(opciones[e]) for e in elegidos]
        n_chicos = sum(1 for _, items in comprobantes
                       if formato_impresion.cabe_en_media_hoja(items))
        n_grandes = len(comprobantes) - n_chicos
        hojas = (n_chicos + 1) // 2 + n_grandes
        st.caption(f"{len(comprobantes)} comprobante(s) → **{hojas} hoja(s)**"
                   + (f" ({n_grandes} van solas por tamaño)" if n_grandes else ""))

        ruta = CARPETA_PDF / "comprobantes_agrupados.pdf"
        formato_impresion.generar_comprobantes_pareados_pdf(ruta, comprobantes)
        with open(ruta, "rb") as f:
            st.download_button(
                f"IMPRIMIR {len(comprobantes)} COMPROBANTE(S) EN {hojas} HOJA(S)",
                data=f.read(), file_name="comprobantes_agrupados.pdf",
                mime="application/pdf", width='stretch', type="primary",
            )


def panel_importar_saldos():
    st.subheader("Actualizar saldos desde SMC")

    corte = core.fecha_ultimo_corte()
    horas = core.horas_desde_ultima_importacion()
    if corte:
        c1, c2 = st.columns([2, 3])
        c1.metric("Último saldo importado desde SMC", str(corte)[:16])
        with c2:
            if horas is not None and horas >= core.HORAS_ALERTA_SYNC:
                # queda marcado acá aunque se haya cerrado el aviso de arriba
                st.error(f"⚠️ **En alerta:** {horas:.0f} horas sin sincronizar "
                         f"(el límite recomendado es {core.HORAS_ALERTA_SYNC}).")
            elif horas is not None:
                st.success(f"Al día: {horas:.1f} horas desde la última importación.")
    else:
        st.warning(
            "Todavía no se ha importado ningún saldo desde SMC. Los saldos que se muestran "
            "son los del catálogo inicial (corte 14/07/2026)."
        )

    st.caption(
        "SMC es el sistema oficial del stock; esta web no lo es. Entre una importación y la "
        "siguiente, el saldo que se ve acá es una estimación: el del último corte menos lo "
        "que se entregó desde esta web. No incluye compras, devoluciones ni ajustes hechos "
        "directamente en SMC — por eso conviene importar cada vez que llegue mercadería."
    )

    with st.expander("¿Por qué esto no puede dañar el inventario real de SMC?"):
        st.markdown(
            "- Hacia **SMC** este sistema envía solo **movimientos** "
            "(\"salieron 2 unidades del código X\"), nunca un saldo total. "
            "Si se compran 300 rollos y se registran en SMC, ese ingreso queda intacto: "
            "el movimiento de salida simplemente se resta encima.\n"
            "- Desde **SMC** este sistema **recibe** el saldo y reemplaza su estimación. "
            "Ante cualquier diferencia, gana SMC.\n"
            "- Por eso la web nunca sobrescribe el inventario real, y cualquier desvío se "
            "corrige solo en la siguiente importación."
        )

    archivo = st.file_uploader(
        "Archivo de saldos exportado desde SMC (.xlsx o .csv)", type=["xlsx", "csv"],
        key="upload_saldos",
    )
    st.caption("Debe traer al menos las columnas 'codigo' y 'saldo'; opcionalmente 'stock_critico'.")

    if archivo is not None and st.button("Importar saldos", type="primary"):
        try:
            diferencias, n = core.importar_saldos_smc(archivo)
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")
        else:
            st.success(f"{n} producto(s) actualizados con el saldo real de SMC.")
            if diferencias.empty:
                st.info("No había diferencias: la estimación local coincidía con SMC.")
            else:
                st.markdown("**Diferencias detectadas**")
                st.caption(
                    "Son movimientos que ocurrieron fuera de esta web (compras, devoluciones, "
                    "ajustes o entregas registradas directo en SMC). Ya quedaron corregidos."
                )
                st.dataframe(diferencias, width='stretch', hide_index=True)
            st.rerun()


def panel_estadisticas():
    st.subheader("Estadísticas de consumo")
    st.caption(
        "Quién consume, qué se consume y cuánto vale. Se calcula sobre las solicitudes "
        "cerradas, usando la cantidad realmente entregada."
    )

    hoy = date.today()
    c1, c2, c3 = st.columns(3)
    rango = c1.selectbox(
        "Período", ["Este año", "Últimos 12 meses", "Este mes", "Todo", "Personalizado"],
        index=0, key="rango_stats",
    )
    metrica = c2.selectbox("Medir por", ["unidades", "valor ($)", "solicitudes"], index=0)
    top_n = c3.slider("Cuántos mostrar", 5, 20, 10)

    desde = hasta = None
    if rango == "Este año":
        desde, hasta = hoy.replace(month=1, day=1), hoy
    elif rango == "Últimos 12 meses":
        desde, hasta = hoy - timedelta(days=365), hoy
    elif rango == "Este mes":
        desde, hasta = hoy.replace(day=1), hoy
    elif rango == "Personalizado":
        cd, ch = st.columns(2)
        desde = cd.date_input("Desde", value=hoy - timedelta(days=180), key="stats_desde")
        hasta = ch.date_input("Hasta", value=hoy, key="stats_hasta")

    datos = core.estadisticas_consumo(desde=desde, hasta=hasta)
    columna = {"unidades": "unidades", "valor ($)": "valor", "solicitudes": "solicitudes"}[metrica]

    if datos["departamento"].empty:
        st.info("No hay solicitudes cerradas en este período.")
        return

    # ------------------------------------------------------------------ KPIs
    total_sol = int(datos["departamento"]["solicitudes"].sum())
    total_uni = int(datos["departamento"]["unidades"].sum())
    total_val = int(datos["departamento"]["valor"].sum())
    k1, k2, k3 = st.columns(3)
    k1.metric("Solicitudes entregadas", f"{total_sol:,}".replace(",", "."))
    k2.metric("Unidades entregadas", f"{total_uni:,}".replace(",", "."))
    k3.metric("Valor consumido", pesos(total_val))

    def _grafico(df, etiqueta, titulo, ayuda=None):
        if df.empty or columna not in df:
            st.info(f"Sin datos para {titulo.lower()}.")
            return
        st.markdown(f"**{titulo}**")
        if ayuda:
            st.caption(ayuda)
        top = df.nlargest(top_n, columna)[[etiqueta, columna]].set_index(etiqueta)
        st.bar_chart(top, horizontal=True, height=min(60 + 28 * len(top), 620))
        with st.expander("Ver la tabla"):
            tabla = df.nlargest(top_n, columna).copy()
            if "valor" in tabla:
                tabla["valor"] = tabla["valor"].apply(pesos)
            st.dataframe(tabla, width='stretch', hide_index=True)

    st.divider()
    _grafico(datos["departamento"], "departamento",
             f"Departamentos que más solicitan (por {metrica})")

    st.divider()
    _grafico(datos["producto"], "producto",
             f"Productos más solicitados (por {metrica})",
             "Ordenado por lo elegido arriba. Si mide por 'valor ($)' aparecen los que "
             "más presupuesto consumen, que no siempre son los que más se piden.")

    st.divider()
    _grafico(datos["solicitante"], "solicitante",
             f"Personas que más solicitan (por {metrica})")

    st.divider()
    _grafico(datos["oficina"], "oficina", f"Oficinas que más solicitan (por {metrica})")

    st.divider()
    _grafico(datos["categoria"], "categoria", f"Consumo por categoría (por {metrica})")

    # ------------------------------------------------------- evolución mensual
    st.divider()
    st.markdown("**Evolución mes a mes**")
    df_mes = datos["mes"]
    if len(df_mes) > 1:
        st.line_chart(df_mes.set_index("mes")[[columna]], height=260)
        with st.expander("Ver la tabla"):
            tabla = df_mes.copy()
            tabla["valor"] = tabla["valor"].apply(pesos)
            st.dataframe(tabla, width='stretch', hide_index=True)
    else:
        st.info("Se necesita más de un mes con movimientos para ver la evolución.")

    st.caption(
        "Nota: estas cifras salen de lo registrado en este sistema, así que solo cubren "
        "las entregas hechas a través de él. Los movimientos cargados directamente en SMC "
        "no aparecen acá."
    )


def panel_correos_autorizados():
    st.subheader("Correos autorizados para hacer solicitudes")
    st.caption(
        "Solo los correos de esta nómina pueden registrarse y pedir insumos. Validar el dominio "
        "no basta: cualquiera podría inventar un correo del dominio municipal sin ser esa persona. "
        "Esta lista es el control real, y la administra usted."
    )

    st.markdown("**Autorizar un correo**")
    c1, c2, c3 = st.columns([2, 1.5, 1.5])
    correo_nuevo = c1.text_input("Correo institucional", key="correo_alta")
    nombre_ref = c2.text_input("Nombre (referencia)", key="nombre_alta")
    area_ref = c3.text_input("Área / Departamento", key="area_alta")
    if st.button("Autorizar correo", type="primary"):
        ok, mensaje = core.autorizar_correo(correo_nuevo, nombre_ref, area_ref)
        if ok:
            st.success(mensaje)
            st.rerun()
        else:
            st.error(mensaje)

    st.divider()
    st.markdown("**Carga masiva de la nómina municipal**")
    st.caption(
        "Suba un archivo con una columna 'correo' (opcionalmente 'nombre' y 'area'). "
        "Es la forma rápida de cargar de una vez todos los correos de la municipalidad."
    )
    archivo = st.file_uploader("Nómina de correos (.xlsx o .csv)", type=["xlsx", "csv"],
                               key="upload_correos")
    if archivo is not None and st.button("Procesar nómina"):
        try:
            resultados = core.importar_correos_desde_excel(archivo)
        except Exception as e:
            st.error(f"No se pudo leer el archivo: {e}")
        else:
            if resultados.empty:
                st.warning("El archivo no traía correos.")
            else:
                st.success(f"{(resultados['resultado'] == 'autorizado').sum()} correo(s) autorizados.")
                st.dataframe(resultados, width='stretch', hide_index=True)

    st.divider()
    st.markdown("**Nómina actual**")
    df = core.listar_correos_autorizados()
    if df.empty:
        st.warning(
            "La nómina está vacía: hoy nadie puede registrarse como solicitante. "
            "Autorice al menos un correo para habilitar el uso."
        )
        return

    filtro = st.text_input("Buscar correo", key="filtro_correos")
    if filtro:
        f = core.normalizar(filtro)
        df = df[df.apply(lambda r: f in core.normalizar(" ".join(str(v) for v in r.values)), axis=1)]

    st.dataframe(df, width='stretch', hide_index=True)

    st.markdown("**Quitar acceso**")
    activos = core.listar_correos_autorizados()
    activos = activos[activos["estado"] == "autorizado"]["correo"].tolist()
    if activos:
        a_bloquear = st.selectbox("Correo a bloquear", [""] + activos, key="sel_bloqueo")
        if a_bloquear and st.button("Bloquear este correo"):
            core.bloquear_correo(a_bloquear)
            st.success(f"{a_bloquear} quedó bloqueado — ya no puede hacer solicitudes.")
            st.rerun()


def panel_sync_smc():
    st.subheader("Sincronización con SMC")
    st.caption(
        "Hoy no está confirmado si SMC tiene una vía de integración (import de archivo, ODBC, API). "
        "Mientras se confirma, este panel deja un archivo CSV con los movimientos cerrados pendientes, "
        "listo para importarlo a SMC si esa opción existe, o como respaldo de auditoría si no."
    )
    pendientes = core.obtener_pendientes_sync()
    st.metric("Folios cerrados pendientes de sincronizar", pendientes["folio"].nunique() if not pendientes.empty else 0)

    if st.button("Generar archivo de sincronización ahora"):
        os.makedirs("sync_exports", exist_ok=True)
        ruta, n = core.generar_archivo_sync_smc("sync_exports")
        if ruta is None:
            st.info("No había movimientos pendientes.")
        else:
            st.success(f"Archivo generado: {ruta} ({n} folios).")
            st.rerun()

    st.subheader("Historial de corridas")
    st.dataframe(core.historial_sincronizacion(), width='stretch', hide_index=True)
    st.caption(
        "Para producción: programar esto cada 10 min con el Programador de tareas de Windows o cron "
        "(ver sincronizar_smc.py). Es un job aparte de esta interfaz."
    )


# =====================================================================
#  RUTEO DE TABS SEGÚN ROL
# =====================================================================

if es_encargado:
    # En un hosting gratuito el disco se borra al reiniciar la aplicación, así
    # que conviene que quede a la vista que esto todavía es una prueba y que
    # los datos no son definitivos.
    # Alerta de desactualización: si pasaron más de 6 horas desde la última
    # importación de saldos, lo que muestra el sistema puede estar lejos de la
    # realidad. Se avisa una sola vez por sesión; después queda marcado en la
    # pestaña "Actualizar saldos".
    horas_desde_corte = core.horas_desde_ultima_importacion()
    if horas_desde_corte is not None and horas_desde_corte >= core.HORAS_ALERTA_SYNC:
        if not st.session_state.alerta_sync_vista:
            c_alerta, c_cerrar = st.columns([6, 1])
            with c_alerta:
                st.error(
                    f"⚠️ **Saldos desactualizados.** Pasaron {horas_desde_corte:.0f} horas "
                    "desde la última importación desde SMC. Lo que se muestra puede no "
                    "coincidir con el inventario real — actualice en la pestaña "
                    "*Actualizar saldos*."
                )
            with c_cerrar:
                if st.button("Entendido"):
                    st.session_state.alerta_sync_vista = True
                    st.rerun()

    if os.environ.get("BODEGA_MODO", "prueba").lower() == "prueba":
        st.warning(
            "**Modo de prueba.** Los datos de esta aplicación pueden borrarse al "
            "reiniciarse el servidor. Sirve para probar la interfaz, no para registrar "
            "entregas reales todavía. Exporte lo que necesite conservar desde el Historial.",
            icon="⚠️",
        )

    # Nombre y apellido de quien procesa: va impreso en el comprobante como
    # responsable del movimiento. Se toma de la propia cuenta, pero se puede
    # ajustar si quien atiende bodega ese día es otra persona.
    if core.nombre_encargado() != identidad_sesion["nombre"]:
        core.guardar_config("nombre_encargado", identidad_sesion["nombre"])

    tabs = st.tabs([
        "Nueva solicitud", "Solicitudes activas", "Pedidos completados",
        "Inventario general", "Inventario crítico", "Actualizar saldos",
        "Historial", "Estadísticas", "Crear alias", "Correos autorizados",
        "Sincronización SMC",
    ])
    with tabs[0]:
        panel_nueva_solicitud(es_encargado=True)
    with tabs[1]:
        panel_solicitudes_activas()
    with tabs[2]:
        panel_pedidos_completados()
    with tabs[3]:
        panel_inventario_general()
    with tabs[4]:
        panel_inventario_critico()
    with tabs[5]:
        panel_importar_saldos()
    with tabs[6]:
        panel_historial()
    with tabs[7]:
        panel_estadisticas()
    with tabs[8]:
        panel_crear_alias()
    with tabs[9]:
        panel_correos_autorizados()
    with tabs[10]:
        panel_sync_smc()
elif identidad_sesion:
    tabs = st.tabs(["Nueva solicitud", "Mis solicitudes"])
    with tabs[0]:
        st.caption("Prototipo — catálogo real de 290 productos, con búsqueda por alias.")
        panel_nueva_solicitud(es_encargado=False, identidad=identidad_sesion)
    with tabs[1]:
        panel_mis_solicitudes(identidad_sesion)
else:
    # Sin sesión iniciada no se muestra ninguna pestaña: así se evita que
    # cualquiera con el link pida a nombre de un tercero.
    panel_acceso()

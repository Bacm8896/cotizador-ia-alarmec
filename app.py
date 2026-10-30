"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Cotizador ALARMEC: asistente por pasos (voz/texto -> Gemini -> revisión -> PDF -> WhatsApp).

PASO 1 Captura · PASO 2 Revisión y faltantes · PASO 3 Vista previa · PASO 4 Entrega.
Gemini solo se invoca al pulsar "Procesar con IA" (paso 1) o "Aplicar ajuste con IA" (paso 2);
revisar, completar precios, recalcular y generar el PDF es Python local.

Ejecutar:  streamlit run app.py
"""
import hmac
import io
from datetime import date

import fitz  # PyMuPDF: convierte el PDF en imagen para la vista previa
import pandas as pd
import streamlit as st

import cotizador

cotizador.recargar_si_cambio()  # tras un despliegue en caliente, evita módulos viejos con app.py nuevo

from cotizador import borrador as bd  # noqa: E402
from cotizador import catalogo as cat
from cotizador import notaventa as nv
from cotizador import numeracion
from cotizador.config import get_setting
from cotizador.extractor import Audio, ExtraccionError, ajustar, descripcion_proveedor, extraer
from cotizador import storage
from cotizador.pdf import generar_pdf, generar_pdf_nota_venta
from cotizador.storage import StorageError
from cotizador.whatsapp import enlace, mensaje, normalizar_telefono

st.set_page_config(page_title="Cotizador ALARMEC", page_icon="🧾", layout="wide")

EJEMPLO = (
    "Cotización para el arquitecto Juan Pérez Muñoz, teléfono 0991234567, "
    "sector La Floresta en Quito. Tendido de cerca eléctrica, 29 metros a 8 dólares el metro, "
    "material y mano de obra incluidos. 50% a la firma y saldo contraentrega."
)
COLUMNAS = ["cantidad", "descripcion", "precio_unitario", "total_declarado"]
VISTA_NUEVA = "📝 Nueva Cotización"
VISTA_HISTORIAL = "📂 Historial de Cotizaciones"
VISTA_CATALOGO = "💲 Catálogo y precios"
VISTA_NV = "🧾 Generar Nota de Venta"
NV_DESDE_COT = "📋 Desde una cotización existente"
NV_DIRECTA = "🆕 Nota de Venta en blanco (Directa)"
ELEGIR_COT = "— Elegir cotización —"
NV_COLUMNAS = ["cantidad", "unidad", "descripcion", "precio_unitario"]
ELEGIR = "— Elegir producto —"
PASOS = {1: "Captura", 2: "Revisión y faltantes", 3: "Vista previa", 4: "Entrega"}
TIPOS_AUDIO = ["wav", "mp3", "ogg", "flac", "aac", "m4a", "webm"]
MIME_AUDIO = {"audio/x-m4a": "audio/mp4", "audio/m4a": "audio/mp4", "audio/x-wav": "audio/wav"}

ss = st.session_state


# ------------------------------------------------------------ acceso por PIN
def _pin_correcto() -> str:
    return get_setting("APP_PIN", "1234")


if not ss.get("autenticado"):
    st.title("🔒 Cotizador ALARMEC")
    with st.form("login"):
        pin = st.text_input("PIN", type="password")
        entrar = st.form_submit_button("Ingresar")
    if entrar:
        if hmac.compare_digest(pin.encode(), _pin_correcto().encode()):
            ss.autenticado = True
            st.rerun()
        st.error("PIN incorrecto.")
    st.stop()

# ------------------------------------------------------------------- estado
ss.setdefault("vista", VISTA_NUEVA)
ss.setdefault("nv_ver", 0)
ss.setdefault("nv_edv", 0)
ss.setdefault("paso", 1)
ss.setdefault("texto", "")
ss.setdefault("datos_cotizacion", None)  # resultado de la IA; solo cambia al pulsarse un botón de IA
ss.setdefault("llamadas_ia", 0)               # cuántas veces se invocó la IA en esta sesión
ss.setdefault("borrador", None)               # datos editables (cotizador.borrador)
ss.setdefault("audio_version", 0)             # cambia la clave de los widgets de audio para limpiarlos
ss.setdefault("ver_editor", 0)
ss.setdefault("items_base", [])
ss.setdefault("pdf", None)
ss.setdefault("cot", None)

st.markdown(
    "<style>div[data-testid='stNumberInput'] input{font-size:1.4rem;height:3rem}</style>",
    unsafe_allow_html=True,
)


def _ir(paso: int) -> None:
    """Cambia de paso y descarta el estado de los widgets del paso anterior."""
    for k in list(ss.keys()):
        if k.startswith(("f_", "precio_", "editor_")):
            del ss[k]
    if paso == 2:
        ss.items_base = [dict(i) for i in ss.borrador["items"]]
        ss.ver_editor += 1
    ss.paso = paso


def _audios(*widgets) -> list[Audio]:
    out = []
    for w in widgets:
        if w is not None:
            mime = MIME_AUDIO.get(getattr(w, "type", None) or "", getattr(w, "type", None) or "audio/wav")
            out.append(Audio(w.getvalue(), mime))
    return out


def _catalogo() -> list[dict]:
    """Catálogo vigente (cache 60 s). Si no se puede leer, la lista base: la cotización nunca se bloquea por esto."""
    try:
        return cat.obtener_catalogo()
    except StorageError as e:
        ss.aviso_catalogo = str(e)
        return cat.CATALOGO_BASE


def _nuevo_borrador(ext) -> None:
    previo = ss.borrador["numero"] if ss.borrador else ""  # un ajuste con IA conserva el número ya elegido
    ss.datos_cotizacion = ext
    ss.borrador = bd.desde_extraccion(ext, _catalogo())
    ss.borrador["numero"] = previo or numeracion.siguiente(fecha.year)
    _ir(2)


@st.cache_data(ttl=300, show_spinner=False)
def _pdf_historico(folio: str) -> bytes:
    """Regenera al vuelo el PDF de una cotización guardada, desde su JSON."""
    return generar_pdf(storage.a_cotizacion(storage.cargar_cotizacion(folio)))


def _cargar_historial(folio: str) -> None:
    """Callback de «Cargar / Modificar»: inyecta la cotización guardada en la sesión y abre el paso 2."""
    try:
        reg = storage.cargar_cotizacion(folio)
    except StorageError as e:
        ss.aviso_historial = str(e)
        return
    ss.borrador = bd.desde_registro(reg)
    ss.datos_cotizacion = None
    ss.iva_pct = float(reg["iva_porcentaje"])
    ss.fecha_cot = date.fromisoformat(reg["fecha_iso"]) if reg.get("fecha_iso") else date.today()
    ss.modificando = reg["folio"]
    ss.aviso_historial = None
    ss.vista = VISTA_NUEVA
    _ir(2)


@st.cache_data(show_spinner=False)
def _paginas_png(pdf: bytes) -> list[bytes]:
    doc = fitz.open(stream=pdf, filetype="pdf")
    return [p.get_pixmap(dpi=110).tobytes("png") for p in doc]


# ------------------------------------------------------------------ sidebar
with st.sidebar:
    st.header("Opciones")
    iva = st.number_input(
        "IVA %", min_value=0.0, max_value=100.0, value=0.0, step=1.0, key="iva_pct",
        help="Por defecto 0%: el PDF indica «Precios no incluyen IVA». Con IVA > 0 se desglosa.",
    )
    fecha = st.date_input("Fecha de la cotización", value=date.today(), key="fecha_cot")
    st.caption("Los totales siempre los calculan Python; la IA solo extrae datos.")
    st.caption(f"IA: {descripcion_proveedor()}")
    st.caption(f"Llamadas a la IA en esta sesión: {ss.llamadas_ia}")

# Firma de autoría, siempre al final de la barra lateral
st.sidebar.markdown("---")
st.sidebar.caption("🛠️ **Cotizador ALARMEC** v1.0 (Beta)\n\nDesarrollado por [Byron Carvajal](https://www.linkedin.com/in/byroncarvajalia)")

st.title("🧾 Cotizador ALARMEC")
vista = st.radio("Vista", [VISTA_NUEVA, VISTA_HISTORIAL, VISTA_CATALOGO, VISTA_NV], key="vista", horizontal=True, label_visibility="collapsed")


def vista_historial() -> None:
    """Pestaña 2: buscar, descargar de nuevo el PDF o cargar una cotización guardada para modificarla."""
    st.subheader("Historial de cotizaciones")
    if ss.get("aviso_historial"):
        st.error(ss.aviso_historial)
    try:
        filas = storage.listar_cotizaciones_historicas()
    except StorageError as e:
        st.error(str(e))
        return
    if not filas:
        st.info("Aún no hay cotizaciones guardadas: se guardan al pulsar «Aprobar y Generar PDF».")
        return
    q = st.text_input("🔎 Buscar por cliente o folio", key="h_buscar").strip().lower()
    visibles = [r for r in filas if q in r["cliente"].lower() or q in r["folio"].lower()] if q else filas
    st.dataframe(
        pd.DataFrame([{
            "Folio": r["folio"],
            "Fecha": date.fromisoformat(r["fecha_iso"]).strftime("%d/%m/%Y") if r.get("fecha_iso") else r["fecha"],
            "Cliente": r["cliente"], "Teléfono": r["telefono"], "Total ($)": r["total"],
        } for r in visibles]),
        hide_index=True, width="stretch",
        column_config={"Total ($)": st.column_config.NumberColumn(format="$ %.2f")},
    )
    if not visibles:
        st.warning("Ninguna cotización coincide con la búsqueda.")
        return
    opciones = {f"{r['folio']} · {r['cliente']} · $ {r['total']:,.2f}": r for r in visibles}
    elegida = opciones[st.selectbox("Cotización seleccionada", list(opciones), key="h_elegida")]
    try:
        pdf = _pdf_historico(elegida["folio"])
    except StorageError as e:
        st.error(str(e))
        return
    c1, c2 = st.columns(2)
    c1.download_button(
        "📥 Descargar PDF", io.BytesIO(pdf), file_name=f"cotizacion_{elegida['archivo'].removesuffix('.json')}.pdf",
        mime="application/pdf", width="stretch",
    )
    c2.button("📋 Cargar / Modificar", on_click=_cargar_historial, args=(elegida["folio"],),
              width="stretch", type="primary")


def vista_catalogo() -> None:
    """Pestaña 3: ver y ajustar productos y precios sin crear una cotización."""
    st.subheader("Catálogo de productos y precios")
    try:
        productos = cat.obtener_catalogo()
    except StorageError as e:
        st.error(str(e))
        return
    st.caption("Estos productos y precios sugeridos se envían a la IA para reconocer lo que dictas y se precargan en el paso 2.")
    categorias = sorted({*cat.CATEGORIAS, *(p["categoria"] for p in productos)})
    unidades = sorted({*cat.UNIDADES, *(p["unidad"] for p in productos)})
    base = pd.DataFrame([{k: p[k] for k in ("nombre_oficial", "categoria", "unidad", "precio_unitario_sugerido")}
                         for p in productos])
    editado = st.data_editor(
        base, num_rows="dynamic", width="stretch", key=f"cat_editor_{ss.get('cat_ver', 0)}",
        column_config={
            "nombre_oficial": st.column_config.TextColumn("Producto", width="large", required=True),
            "categoria": st.column_config.SelectboxColumn("Categoría", options=categorias),
            "unidad": st.column_config.SelectboxColumn("Unidad", options=unidades),
            "precio_unitario_sugerido": st.column_config.NumberColumn("Precio sugerido ($)", min_value=0.0, format="$ %.2f"),
        },
    )
    if st.button("💾 Guardar catálogo", type="primary"):
        alias = {cat.normalizar(p["nombre_oficial"]): p.get("alias", []) for p in productos}
        nuevos = [{**f, "alias": alias.get(cat.normalizar(str(f["nombre_oficial"])), [])}
                  for f in editado.to_dict("records") if str(f.get("nombre_oficial") or "").strip()]
        try:
            cat.guardar_catalogo(nuevos)
        except StorageError as e:
            st.error(str(e))
        else:
            ss.cat_ver = ss.get("cat_ver", 0) + 1
            ss.aviso_catalogo_guardado = True
            st.rerun()
    if ss.pop("aviso_catalogo_guardado", False):
        st.success("Catálogo guardado.")


def _nv_cargar(b: dict, origen: str) -> None:
    """Deja una nota de venta nueva en la sesión (desde una cotización o en blanco) y renueva los widgets."""
    ss.nv, ss.nv_origen = b, origen
    ss.nv_items_base = [dict(i) for i in b["items"]]
    ss.nv_ver = ss.get("nv_ver", 0) + 1
    ss.nv_edv = 0


def _nv_reiniciar() -> None:
    for k in ("nv", "nv_origen", "nv_resultado", "nv_items_base", "nv_paso", "nv_folio_prov", "nv_cot_val"):
        ss.pop(k, None)
    ss.nv_ver = ss.get("nv_ver", 0) + 1


def _nv_mostrar_resultado() -> None:
    r = ss.nv_resultado
    nota = r["nota"]
    st.success(f"✅ Nota de venta {nota.folio} generada.")
    if r["error"]:
        st.warning(f"La nota NO quedó guardada en el historial: {r['error']} Descarga el PDF ahora para no perderla.")
    else:
        st.caption(f"📂 Guardada: {r['ruta']}")
    m1, m2, m3 = st.columns(3)
    m1.metric("Total", f"$ {nota.total:,.2f}")
    m2.metric("Anticipo", f"$ {nota.anticipo:,.2f}")
    m3.metric("Saldo pendiente", f"$ {nota.saldo:,.2f}")
    st.download_button(
        "📥 Descargar Nota de Venta (PDF)", io.BytesIO(r["pdf"]), file_name=f"nota_venta_{nota.folio}.pdf",
        mime="application/pdf", width="stretch", type="primary",
    )
    for png in _paginas_png(r["pdf"]):
        st.image(png, width="stretch")
    st.button("🆕 Crear otra Nota de Venta", on_click=_nv_reiniciar)


def _nv_aprobar(nota) -> None:
    """Reserva el folio NV (atómico), genera el PDF definitivo y guarda la nota en la rama de datos."""
    try:
        folio_nv = numeracion.reservar_nv(int(nota.fecha_iso[:4]))
    except StorageError as e:
        st.error(f"No se pudo asignar el folio de la nota de venta: {e}")
        return
    nota = nota.model_copy(update={"folio": folio_nv})
    pdf = generar_pdf_nota_venta(nota)
    try:
        ruta, error = storage.guardar_nota_venta(nota), None
    except StorageError as e:
        ruta, error = None, str(e)
    ss.nv_resultado = {"nota": nota, "pdf": pdf, "ruta": ruta, "error": error}
    ss.nv_paso = "editar"
    st.rerun()


def _nv_vista_previa() -> None:
    """Paso 2 de la nota de venta: el PDF tal como saldrá, con el folio sugerido (el definitivo se asigna al aprobar)."""
    b = ss.nv
    nota, errores = nv.calcular_nota(b, b["fecha"])
    if nota is None:  # los datos dejaron de ser válidos: se vuelve a la edición
        ss.nv_paso = "editar"
        st.rerun()
    nota = nota.model_copy(update={"folio": ss.nv_folio_prov})
    st.subheader("Vista previa de la Nota de Venta")
    st.caption(f"Folio sugerido {nota.folio}: el definitivo se asigna al aprobar (no se consume hasta entonces).")
    for png in _paginas_png(generar_pdf_nota_venta(nota)):
        st.image(png, width="stretch")
    m1, m2, m3 = st.columns(3)
    m1.metric("Total", f"$ {nota.total:,.2f}")
    m2.metric("Anticipo", f"$ {nota.anticipo:,.2f}")
    m3.metric("Saldo pendiente", f"$ {nota.saldo:,.2f}")
    n1, n2 = st.columns(2)
    if n1.button("← Hacer cambios"):
        ss.nv_paso = "editar"
        st.rerun()
    if n2.button("✅ Aprobar y Generar Nota de Venta (PDF)", type="primary"):
        _nv_aprobar(nota)


def vista_nota_venta() -> None:
    """Pestaña 4: nota de venta (documento de entrega y cobro) desde una cotización guardada o directa."""
    st.subheader("Generar Nota de Venta")
    if ss.get("nv_resultado"):
        _nv_mostrar_resultado()
        return
    if ss.get("nv_paso") == "previa" and ss.get("nv"):
        _nv_vista_previa()
        return
    # el estado de un widget se pierde cuando no se dibuja (p. ej. durante la vista previa): se restaura desde ss.nv_*_val
    ss.setdefault("nv_modo", ss.get("nv_modo_val", NV_DESDE_COT))
    modo = st.radio("¿Cómo deseas generar la Nota de Venta?", [NV_DESDE_COT, NV_DIRECTA], key="nv_modo", horizontal=True)
    ss.nv_modo_val = modo
    if modo == NV_DESDE_COT:
        try:
            filas = storage.listar_cotizaciones_historicas()
        except StorageError as e:
            st.error(str(e))
            return
        if not filas:
            st.info("Aún no hay cotizaciones guardadas. Crea una o genera una nota directa.")
            return
        opciones = {f"{r['folio']} · {r['cliente']} · $ {r['total']:,.2f}": r for r in filas}
        todas = [ELEGIR_COT, *opciones]
        if ss.get("nv_cot") not in todas:
            ss.nv_cot = ss.get("nv_cot_val") if ss.get("nv_cot_val") in todas else ELEGIR_COT
        elegido = st.selectbox("Cotización guardada", todas, key="nv_cot")
        ss.nv_cot_val = elegido
        if elegido == ELEGIR_COT:
            st.info("Elige una cotización: se precargan el cliente y los ítems.")
            return
        folio = opciones[elegido]["folio"]
        if ss.get("nv_origen") != folio:  # solo se lee de GitHub cuando cambia la cotización elegida
            try:
                reg = storage.cargar_cotizacion(folio)
            except StorageError as e:
                st.error(str(e))
                return
            _nv_cargar(nv.desde_cotizacion(reg, _catalogo()), folio)
    elif ss.get("nv_origen") != "directa":
        _nv_cargar(nv.vacio(), "directa")

    b, ver = ss.nv, ss.nv_ver
    if b["referencia"]:
        st.caption(f"Referencia: Cotización N° {b['referencia']}")
    c1, c2 = st.columns(2)
    b["nombre"] = c1.text_input("Cliente", b["nombre"], key=f"nv_nombre_{ver}")
    b["ci_ruc"] = c2.text_input("C.I. / RUC", b["ci_ruc"], key=f"nv_ci_{ver}")
    b["telefono"] = c1.text_input("Teléfono", b["telefono"], key=f"nv_tel_{ver}")
    b["direccion"] = c2.text_input("Dirección", b["direccion"], key=f"nv_dir_{ver}")
    b["fecha"] = fecha_nv = st.date_input("Fecha de la nota", value=b.get("fecha", date.today()), key=f"nv_fecha_{ver}")

    st.markdown("**Ítems** (ajusta las cantidades realmente entregadas)")
    df = st.data_editor(
        pd.DataFrame(ss.nv_items_base, columns=NV_COLUMNAS), num_rows="dynamic", width="stretch",
        key=f"nv_editor_{ver}_{ss.nv_edv}",
        column_config={
            "cantidad": st.column_config.NumberColumn("Cant.", min_value=0.0),
            "unidad": st.column_config.TextColumn("Unidad"),
            "descripcion": st.column_config.TextColumn("Descripción del producto / servicio", width="large"),
            "precio_unitario": st.column_config.NumberColumn("P. unitario ($)", min_value=0.0, format="%.2f"),
        },
    )
    b["items"] = items = nv.limpiar_items(df.to_dict("records"))
    with st.expander("➕ Agregar producto del catálogo"):
        productos = {p["nombre_oficial"]: p for p in _catalogo()}
        elegido_cat = st.selectbox("Producto", list(productos), key=f"nv_prod_{ver}")
        if st.button("Agregar al detalle"):
            ss.nv_items_base = [*items, nv.item_de_catalogo(productos[elegido_cat])]
            ss.nv_edv += 1
            st.rerun()

    p1, p2 = st.columns(2)
    b["iva_pct"] = p1.number_input("IVA %", min_value=0.0, max_value=100.0, value=float(b["iva_pct"]), step=1.0, key=f"nv_iva_{ver}")
    b["anticipo"] = p2.number_input("Anticipo / Abono recibido ($)", min_value=0.0, value=float(b["anticipo"]), step=5.0,
                                    format="%.2f", key=f"nv_anticipo_{ver}")
    metodos = nv.METODOS_PAGO
    b["metodo_pago"] = p1.selectbox("Método de pago", metodos, index=metodos.index(b["metodo_pago"]) if b["metodo_pago"] in metodos else 0,
                                    key=f"nv_metodo_{ver}")
    b["observaciones"] = p2.text_input("Observaciones (opcional)", b["observaciones"], key=f"nv_obs_{ver}")

    tot = nv.totales(b)
    if tot:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Subtotal", f"$ {tot['subtotal']:,.2f}")
        m2.metric(f"IVA {b['iva_pct']:g}%", f"$ {tot['iva']:,.2f}")
        m3.metric("Total", f"$ {tot['total']:,.2f}")
        m4.metric("Saldo pendiente", f"$ {tot['saldo']:,.2f}")
    nota, errores = nv.calcular_nota(b, fecha_nv)
    for e in errores:
        st.warning(e)
    if st.button("👁️ Vista previa →", type="primary", disabled=nota is None):
        ss.nv_items_base = items                      # lo editado en la tabla sobrevive a ir y volver
        ss.nv_edv += 1
        ss.nv_folio_prov = numeracion.siguiente_nv(fecha_nv.year)
        ss.nv_paso = "previa"
        st.rerun()


def vista_nueva() -> None:
    st.progress(ss.paso / 4, text=f"Paso {ss.paso} de 4 · {PASOS[ss.paso]}")

    # =============================================================== PASO 1
    if ss.paso == 1:
        col_txt, col_voz = st.columns([3, 2])
        with col_voz:
            grabado = st.audio_input("🎙️ Grabar nota de voz", key=f"audio_input_{ss.audio_version}")
            subido = st.file_uploader("…o subir un audio", type=TIPOS_AUDIO, key=f"audio_subido_{ss.audio_version}")
            if (grabado is not None or subido is not None) and st.button("🗑️ Descartar audio y regrabar"):
                ss.audio_version += 1
                st.rerun()
        with col_txt:
            if st.button("Cargar ejemplo"):
                ss.texto = EJEMPLO
            st.text_area("Texto o nota (opcional si hay audio)", key="texto", height=170,
                         placeholder="Cliente, ítems, cantidades, precios, condiciones…")

        audios = _audios(grabado, subido)
        # Llamada a Gemini: solo en la ejecución en que se pulsa este botón.
        if st.button("Procesar con IA", type="primary", disabled=not (ss.texto.strip() or audios)):
            with st.spinner("Procesando…"):
                try:
                    ss.llamadas_ia += 1
                    _nuevo_borrador(extraer(ss.texto, audios))
                except ExtraccionError as e:
                    st.error(str(e))
                else:
                    st.rerun()
        if ss.borrador is not None:
            st.info("Ya hay un borrador en curso.")
            if st.button("Volver al borrador →"):
                _ir(2)
                st.rerun()

    # =============================================================== PASO 2
    elif ss.paso == 2:
        b = ss.borrador
        if ss.get("modificando"):
            st.info(f"Modificando la cotización {ss.modificando} del historial: al aprobarla se actualizará.")
        for campo in bd.CAMPOS_TEXTO:
            ss.setdefault(f"f_{campo}", b[campo])

        st.subheader("Datos del cliente y condiciones")
        num_col, _ = st.columns([1, 3])
        num_col.text_input("Nº de cotización", key="f_numero",
                           help="Sugerido automáticamente (AÑO-NÚMERO); puedes cambiarlo.")
        a, c, d = st.columns(3)
        a.text_input("Cliente", key="f_nombre")
        c.text_input("ATN", key="f_atencion")
        d.text_input("Teléfono", key="f_telefono")
        a.text_input("Dirección", key="f_direccion")
        c.text_input("Ciudad", key="f_ciudad")
        d.text_input("Título del trabajo", key="f_titulo")
        e1, e2 = st.columns(2)
        e1.text_input("Forma de pago", key="f_forma_pago")
        e2.text_input("Saldo", key="f_saldo")
        e1.text_input("Tiempo de entrega", key="f_tiempo_entrega")
        e2.text_input("Garantía", key="f_garantia")

        st.subheader("Ítems")
        df_in = pd.DataFrame(ss.items_base, columns=COLUMNAS)
        df = st.data_editor(
            df_in, num_rows="dynamic", width="stretch", key=f"editor_{ss.ver_editor}",
            column_config={
                "cantidad": st.column_config.NumberColumn("Cantidad", min_value=0.0),
                "descripcion": st.column_config.TextColumn("Descripción", width="large"),
                "precio_unitario": st.column_config.NumberColumn("P. unitario", min_value=0.0, format="%.2f"),
                "total_declarado": None,  # oculta: solo se usa para avisar de diferencias
            },
        )
        st.text_area("Observaciones bajo la tabla (una por línea)", key="f_observaciones", height=70)
        st.text_area(
            "Notas técnicas u observaciones (opcional)", key="f_notas_tecnicas", height=90,
            placeholder="Requisitos de internet, resistencia al agua, voltaje… (una idea por línea)",
        )

        # Lo editado se guarda en el borrador (así sobrevive a ir y volver de otros pasos)
        items = bd.limpiar_items(df.to_dict("records"))
        for campo in bd.CAMPOS_TEXTO:
            b[campo] = ss[f"f_{campo}"]
        b["items"] = items
        catalogo_vigente = _catalogo()

        # Productos genéricos o ambiguos («4 cámaras»): selector con las opciones del catálogo de esa categoría
        pendientes_gen = bd.genericos(b, catalogo_vigente)
        for n in pendientes_gen:
            opciones = {o["nombre_oficial"]: o for o in cat.por_categoria(catalogo_vigente, bd.categoria_de(b, n))}
            elegido = st.selectbox(
                f"🔎 «{items[n]['descripcion']}» es genérico: elige el producto",
                [ELEGIR, *opciones, cat.OTRO], key=f"gen_{ss.ver_editor}_{n}",
            )
            if elegido != ELEGIR:
                bd.resolver_generico(b, n, opciones.get(elegido))  # «Otro / Personalizado» conserva el texto
                ss.items_base = [dict(i) for i in b["items"]]       # la tabla se recarga con el nombre formal
                ss.ver_editor += 1
                st.rerun()

        # Casillas de precio para los ítems sin precio (Python local, recalcula al instante)
        pendientes = [n for n in bd.indices_sin_precio(items) if n not in pendientes_gen]
        if pendientes:
            with st.container(border=True):
                st.markdown("### ⚠️ Completa estos datos para finalizar la cotización:")
                for n in pendientes:
                    nombre_item = items[n]["descripcion"] or f"ítem {n + 1}"
                    p = st.number_input(
                        f"💵 Precio para: {nombre_item}", min_value=0.0, step=0.5, format="%.2f",
                        key=f"precio_{ss.ver_editor}_{n}",
                    )
                    if p > 0:
                        items[n]["precio_unitario"] = p

        # Catálogo frecuente: productos nuevos o con precio distinto (discreto: desplegable cerrado)
        candidatos = bd.candidatos_catalogo(b, catalogo_vigente)
        b["guardar"] = {k: v for k, v in b["guardar"].items() if k in {cat.normalizar(c["nombre"]) for c in candidatos}}
        if candidatos:
            with st.expander(f"💾 Catálogo frecuente ({len(candidatos)} producto(s) nuevo(s) o con otro precio)"):
                for c in candidatos:
                    clave = cat.normalizar(c["nombre"])
                    detalle = "nuevo" if c["nuevo"] else f"sugerido hoy: $ {c['producto']['precio_unitario_sugerido'] or 0:.2f}"
                    marcado = st.checkbox(
                        f"Guardar / actualizar en el catálogo frecuente — {c['nombre']} a $ {c['precio']:.2f} ({detalle})",
                        value=clave in b["guardar"], key=f"gc_{ss.ver_editor}_{clave}",
                    )
                    if not marcado:
                        b["guardar"].pop(clave, None)
                        continue
                    if c["nuevo"]:
                        k1, k2 = st.columns(2)
                        previa = bd.categoria_de(b, c["n"]) or "Otros"
                        categorias = list(dict.fromkeys([*cat.CATEGORIAS, previa]))
                        categoria = k1.selectbox("Categoría", categorias, index=categorias.index(previa), key=f"gcat_{ss.ver_editor}_{clave}")
                        unidad = k2.selectbox("Unidad", cat.UNIDADES, key=f"guni_{ss.ver_editor}_{clave}")
                    else:
                        categoria, unidad = c["producto"]["categoria"], c["producto"]["unidad"]
                    b["guardar"][clave] = {"categoria": categoria, "unidad": unidad}

        # Cuadro de advertencia con lo que falta
        faltan = bd.faltantes(b)
        if faltan or b["usados_defecto"]:
            with st.container(border=True):
                if faltan:
                    st.warning("**Faltan datos:**\n\n" + "\n".join(f"- {f}" for f in faltan))
                if b["usados_defecto"]:
                    st.info("No se mencionaron " + ", ".join(b["usados_defecto"])
                            + ": se usaron los valores por defecto de la empresa (puedes editarlos arriba).")

        res = bd.calcular_borrador(b, iva)
        if not pendientes and not pendientes_gen:  # los errores de precio ya los explican los cuadros de arriba
            for m in res.errores:
                st.error(m)
        for m in res.advertencias:
            st.warning(m)
        if res.ok:
            m1, m2, m3 = st.columns(3)
            m1.metric("Subtotal", f"{res.subtotal:,.2f}")
            m2.metric(f"IVA {iva:g}%", f"{res.iva:,.2f}")
            m3.metric("Total", f"{res.total:,.2f}")

        with st.expander("✨ Instrucción de ajuste con IA (opcional)"):
            st.caption("Ej.: «agrega una sirena a 45 dólares» o «cambia la cantidad de cámaras a 6». "
                       "Cada pulsación del botón usa una llamada a Gemini.")
            instr = st.text_area("Instrucción por texto", key="f_instruccion", height=70)
            voz = st.audio_input("…o por voz", key=f"audio_ajuste_{ss.audio_version}")
            if st.button("Aplicar ajuste con IA", disabled=not (instr.strip() or voz is not None)):
                with st.spinner("Aplicando ajuste…"):
                    try:
                        ss.llamadas_ia += 1
                        _nuevo_borrador(ajustar(bd.a_extraccion(b), instr, _audios(voz)))
                    except ExtraccionError as e:
                        st.error(str(e))
                    else:
                        ss.audio_version += 1
                        st.rerun()

        n1, n2 = st.columns(2)
        if n1.button("← Volver a la captura"):
            _ir(1)
            st.rerun()
        if n2.button("Continuar a la vista previa →", type="primary", disabled=not res.ok):
            ss.cot, _ = bd.cotizacion(b, iva, fecha)
            ss.pdf = generar_pdf(ss.cot)
            _ir(3)
            st.rerun()

    # =============================================================== PASO 3
    elif ss.paso == 3:
        cot, res = bd.cotizacion(ss.borrador, iva, fecha)  # refleja cambios de IVA/fecha de la barra lateral
        ss.cot, ss.pdf = cot, generar_pdf(cot)
        st.subheader("Vista previa del documento")
        for png in _paginas_png(ss.pdf):
            st.image(png, width="stretch")
        st.metric("Total", f"$ {res.total:,.2f}")
        n1, n2 = st.columns(2)
        if n1.button("← Hacer más cambios"):
            _ir(2)
            st.rerun()
        if n2.button("✅ Aprobar y Generar PDF", type="primary"):
            # la próxima sugerencia será el siguiente número
            ss.numero_no_guardado = not numeracion.registrar(ss.cot.numero)
            try:  # historial: la cotización aprobada queda guardada como JSON en la rama de datos
                ss.historial_ruta, ss.historial_error = storage.guardar_cotizacion(ss.cot, fecha.isoformat()), None
                _pdf_historico.clear()
            except StorageError as e:
                ss.historial_ruta, ss.historial_error = None, str(e)
            cambios = bd.cambios_para_catalogo(ss.cot.lineas, ss.borrador.get("guardar", {}))
            ss.catalogo_msg = None
            if cambios:  # casillas «Guardar / actualizar en el catálogo frecuente» marcadas: una sola escritura
                try:
                    rep = cat.actualizar_o_agregar_items(cambios)
                    ss.catalogo_msg = (True, "Catálogo actualizado: " + ", ".join(
                        [f"{n} (nuevo)" for n in rep["creados"]] + [f"{n} (precio)" for n in rep["actualizados"]]))
                except StorageError as e:
                    ss.catalogo_msg = (False, f"No se pudo actualizar el catálogo: {e}")
            _ir(4)
            st.rerun()

    # =============================================================== PASO 4
    else:
        cot, pdf = ss.cot, ss.pdf
        st.success("✅ Cotización lista.")
        if ss.get("numero_no_guardado"):
            st.warning(f"No se pudo guardar el Nº {cot.numero} en la secuencia: "
                       "revisa el número sugerido en la próxima cotización.")
        if ss.get("historial_error"):
            st.warning(f"La cotización NO quedó guardada en el historial: {ss.historial_error} "
                       "Descarga el PDF ahora para no perderla.")
        elif ss.get("historial_ruta"):
            st.caption(f"📂 Guardada en el historial: {ss.historial_ruta}")
        if ss.get("catalogo_msg"):
            if ss.catalogo_msg[0]:
                st.caption(f"💲 {ss.catalogo_msg[1]}")
            else:
                st.warning(ss.catalogo_msg[1])
        nombre_archivo = "cotizacion_" + (cot.cliente_nombre.strip().replace(" ", "_") or "cliente") + ".pdf"
        col_desc, col_wa = st.columns(2)
        with col_desc:
            st.markdown("**📥 Guardar en el móvil**")
            st.download_button(
                "Descargar PDF", io.BytesIO(pdf), file_name=nombre_archivo, mime="application/pdf",
                width="stretch", type="primary",
            )
        with col_wa:
            st.markdown("**📲 Enviar por WhatsApp**")
            numero = st.text_input("WhatsApp del cliente", value=cot.cliente_telefono, key="f_whatsapp")
            st.link_button("Enviar por WhatsApp", enlace(numero, mensaje(cot)), width="stretch", type="primary")
            st.caption(
                "Se abre WhatsApp con el resumen escrito; adjunta el PDF descargado en el chat."
                if normalizar_telefono(numero) else "Número no válido o vacío: WhatsApp te dejará elegir el contacto."
            )
        st.divider()
        n1, n2 = st.columns(2)
        if n1.button("← Hacer más cambios"):
            _ir(2)
            st.rerun()
        if n2.button("🆕 Iniciar nueva cotización"):
            for k in list(ss.keys()):
                if k != "autenticado":
                    del ss[k]
            st.rerun()


{VISTA_NUEVA: vista_nueva, VISTA_HISTORIAL: vista_historial, VISTA_CATALOGO: vista_catalogo,
 VISTA_NV: vista_nota_venta}[vista]()

"""Pestaña «🧾 Generar Nota de Venta» (desde una cotización guardada o directa), sin red ni IA."""
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

import fitz
from streamlit.testing.v1 import AppTest

from cotizador import catalogo as cat
from cotizador import numeracion, storage
from cotizador.schemas import Cotizacion, Linea
from cotizador.storage import StorageError

APP = str(Path(__file__).parent.parent / "app.py")
VISTA_NV = "🧾 Generar Nota de Venta"
DESDE_COT = "📋 Desde una cotización existente"
DIRECTA = "🆕 Nota de Venta en blanco (Directa)"
ANIO = date.today().year


def _cotizacion_guardada(folio="2026-0765", cliente="PEPITO PÉREZ", iva="15"):
    lineas = [Linea(cantidad=D("4"), descripcion="CAMARA TUBO 1080P", precio_unitario=D("85.00"), total=D("340.00")),
              Linea(cantidad=D("29"), descripcion="METROS TENDIDO CERCA ELECTRICA", precio_unitario=D("8.00"), total=D("232.00"))]
    sub = D("572.00")
    imp = (sub * D(iva) / 100).quantize(D("0.01"))
    storage.guardar_cotizacion(Cotizacion(
        numero=folio, fecha="19 DE OCTUBRE DEL 2026", cliente_nombre=cliente, cliente_telefono="0999999999",
        cliente_direccion="QUITO NORTE", cliente_ciudad="QUITO", lineas=lineas, subtotal=sub, iva_porcentaje=D(iva),
        iva=imp, total=sub + imp, forma_pago="50%", saldo="CONTRAENTREGA", tiempo_entrega="3 DIAS", garantia="UN AÑO"),
        "2026-10-19")
    storage.listar_cotizaciones_historicas.clear()


def _app(modo=DESDE_COT):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["autenticado"] = True
    at.session_state["vista"] = VISTA_NV
    at.session_state["nv_modo"] = modo
    return at.run()


def _boton(at, texto):
    return next(b for b in at.button if texto in b.label)


def _ti(at, etiqueta):
    return next(t for t in at.text_input if t.label == etiqueta)


def _aprobar(at):
    """Formulario -> vista previa -> aprobar (los dos pasos de la pestaña)."""
    _boton(at, "Vista previa").click().run()
    assert not at.exception and at.get("image"), "debe mostrarse la vista previa antes de aprobar"
    _boton(at, "Aprobar y Generar Nota de Venta").click().run()


def _num(at, etiqueta):
    return next(n for n in at.number_input if n.label.startswith(etiqueta))


def _texto_pdf(at):
    return "\n".join(p.get_text() for p in fitz.open(stream=at.session_state["nv_resultado"]["pdf"], filetype="pdf"))


# ------------------------------------------------------------------ desde una cotización
def test_desde_cotizacion_precarga_cliente_items_e_iva_y_genera_el_pdf():
    _cotizacion_guardada()
    with mock.patch("cotizador.extractor.extraer") as ia, mock.patch("cotizador.extractor.ajustar") as ia2:
        at = _app()
        assert not at.exception and any("Elige una cotización" in i.value for i in at.info)
        sel = at.selectbox(key="nv_cot")
        assert sel.options[0] == "— Elegir cotización —" and "2026-0765 · PEPITO PÉREZ · $ 657.80" in sel.options
        sel.select("2026-0765 · PEPITO PÉREZ · $ 657.80").run()
        assert not at.exception
        assert _ti(at, "Cliente").value == "PEPITO PÉREZ" and _ti(at, "Teléfono").value == "0999999999"
        assert _ti(at, "Dirección").value == "QUITO NORTE" and _ti(at, "C.I. / RUC").value == ""         # C.I. a completar
        assert any("Referencia: Cotización N° 2026-0765" in c.value for c in at.caption)
        assert at.session_state["nv"]["items"][1]["unidad"] == "metro"
        assert [m.value for m in at.metric] == ["$ 572.00", "$ 85.80", "$ 657.80", "$ 657.80"]

        _ti(at, "C.I. / RUC").input("1712345678").run()
        _num(at, "Anticipo").set_value(300).run()
        at.selectbox(key=next(s.key for s in at.selectbox if s.label == "Método de pago")).select("Transferencia").run()
        assert [m.value for m in at.metric][-1] == "$ 357.80"                                            # saldo automático
        _aprobar(at)

        assert not at.exception and ia.call_count == 0 and ia2.call_count == 0
        nota = at.session_state["nv_resultado"]["nota"]
        assert nota.folio == f"NV-{ANIO}-0001" and nota.referencia == "2026-0765" and nota.saldo == D("357.80")
        t = _texto_pdf(at)
        assert f"Nº NV-{ANIO}-0001" in t and "Referencia: Cotización N° 2026-0765" in t and "C.I. / RUC: 1712345678" in t
        assert any("generada" in s.value for s in at.success) and at.get("download_button")
    guardada = storage.listar_notas_venta()
    assert [(g["folio"], g["referencia"], g["saldo"]) for g in guardada] == [(f"NV-{ANIO}-0001", "2026-0765", 357.8)]
    assert numeracion.siguiente_nv(ANIO) == f"NV-{ANIO}-0002"


def test_sin_cotizaciones_guardadas_se_avisa():
    at = _app()
    assert not at.exception and any("Aún no hay cotizaciones guardadas" in i.value for i in at.info)


def test_cambiar_de_cotizacion_recarga_los_datos():
    _cotizacion_guardada("2026-0765", "PEPITO PÉREZ")
    _cotizacion_guardada("2026-0766", "JUAN LOOR", iva="0")
    at = _app()
    sel = at.selectbox(key="nv_cot")
    sel.select(next(o for o in sel.options if "2026-0766" in o)).run()
    assert _ti(at, "Cliente").value == "JUAN LOOR" and at.session_state["nv"]["iva_pct"] == 0.0
    at.selectbox(key="nv_cot").select(next(o for o in sel.options if "2026-0765" in o)).run()
    assert _ti(at, "Cliente").value == "PEPITO PÉREZ" and at.session_state["nv"]["iva_pct"] == 15.0


# ------------------------------------------------------------------ directa
def test_nota_directa_en_blanco_con_items_del_catalogo():
    cat.actualizar_o_agregar_items([{"nombre": "SIRENA", "precio": 30}, {"nombre": "METROS TENDIDO CERCA ELECTRICA", "precio": 8}])
    at = _app(DIRECTA)
    assert not at.exception and _ti(at, "Cliente").value == "" and at.session_state["nv"]["items"] == []
    assert not any("Referencia" in c.value for c in at.caption)
    assert any("Falta el nombre del cliente" in w.value for w in at.warning)
    assert _boton(at, "Vista previa").disabled

    _ti(at, "Cliente").input("MARIA LOPEZ").run()
    for producto in ("SIRENA", "METROS TENDIDO CERCA ELECTRICA"):
        at.selectbox(key=next(s.key for s in at.selectbox if s.label == "Producto")).select(producto).run()
        _boton(at, "Agregar al detalle").click().run()
    assert [(i["descripcion"], i["unidad"], i["precio_unitario"]) for i in at.session_state["nv"]["items"]] == [
        ("SIRENA", "unidad", 30.0), ("METROS TENDIDO CERCA ELECTRICA", "metro", 8.0)]
    assert [m.value for m in at.metric][2:] == ["$ 38.00", "$ 38.00"]

    _num(at, "Anticipo").set_value(10).run()
    _aprobar(at)
    nota = at.session_state["nv_resultado"]["nota"]
    assert not at.exception and nota.folio == f"NV-{ANIO}-0001" and nota.referencia == "" and nota.saldo == D("28.00")
    t = _texto_pdf(at)
    assert "Referencia" not in t and "CLIENTE: MARIA LOPEZ" in t and "MÉTODO DE PAGO: Efectivo" in t


def test_validaciones_en_pantalla_anticipo_mayor_que_el_total():
    cat.actualizar_o_agregar_item("SIRENA", 30)
    at = _app(DIRECTA)
    _ti(at, "Cliente").input("MARIA LOPEZ").run()
    at.selectbox(key=next(s.key for s in at.selectbox if s.label == "Producto")).select("SIRENA").run()
    _boton(at, "Agregar al detalle").click().run()
    _num(at, "Anticipo").set_value(500).run()
    assert any("no puede ser mayor que el total" in w.value for w in at.warning)
    assert _boton(at, "Vista previa").disabled


# ------------------------------------------------------------------ fallos y numeración
def _nota_lista(at=None):
    cat.actualizar_o_agregar_item("SIRENA", 30)
    at = _app(DIRECTA)
    _ti(at, "Cliente").input("MARIA LOPEZ").run()
    at.selectbox(key=next(s.key for s in at.selectbox if s.label == "Producto")).select("SIRENA").run()
    _boton(at, "Agregar al detalle").click().run()
    return at


def test_si_falla_el_guardado_la_nota_se_entrega_igual_con_aviso():
    at = _nota_lista()
    with mock.patch.object(storage, "guardar_nota_venta", side_effect=StorageError("GitHub respondió 401")):
        _aprobar(at)
    assert not at.exception and at.session_state["nv_resultado"]["pdf"][:4] == b"%PDF"
    assert any("NO quedó guardada" in w.value and "401" in w.value for w in at.warning) and at.get("download_button")


def test_si_no_se_puede_reservar_el_folio_no_se_genera_la_nota():
    at = _nota_lista()
    with mock.patch.object(numeracion, "reservar_nv", side_effect=StorageError("GitHub respondió 403")):
        _aprobar(at)
    assert not at.exception and "nv_resultado" not in at.session_state
    assert any("No se pudo asignar el folio" in e.value for e in at.error)


def test_cada_nota_recibe_su_propio_folio_correlativo_y_se_puede_crear_otra():
    at = _nota_lista()
    _aprobar(at)
    assert at.session_state["nv_resultado"]["nota"].folio == f"NV-{ANIO}-0001"
    _boton(at, "Crear otra Nota de Venta").click().run()
    assert "nv_resultado" not in at.session_state and _ti(at, "Cliente").value == ""
    _ti(at, "Cliente").input("OTRO CLIENTE").run()
    at.selectbox(key=next(s.key for s in at.selectbox if s.label == "Producto")).select("SIRENA").run()
    _boton(at, "Agregar al detalle").click().run()
    _aprobar(at)
    assert at.session_state["nv_resultado"]["nota"].folio == f"NV-{ANIO}-0002"
    assert [g["folio"] for g in storage.listar_notas_venta()] == [f"NV-{ANIO}-0002", f"NV-{ANIO}-0001"]


def test_la_nota_de_venta_no_consume_el_correlativo_de_cotizaciones():
    numeracion.registrar("2026-0765")
    at = _nota_lista()
    _aprobar(at)
    assert numeracion.siguiente(2026) == "2026-0766"


def test_la_pestana_aparece_en_la_navegacion_y_no_rompe_las_otras():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["autenticado"] = True
    at.run()
    assert VISTA_NV in at.radio(key="vista").options
    for vista in at.radio(key="vista").options:
        at.radio(key="vista").set_value(vista).run()
        assert not at.exception, vista


# ------------------------------------------------------------------ vista previa (como en el cotizador)
def _a_la_vista_previa(at):
    _boton(at, "Vista previa").click().run()
    assert not at.exception and at.get("image")


def test_vista_previa_muestra_el_pdf_con_el_folio_sugerido_y_no_consume_ni_guarda_nada():
    at = _nota_lista()
    _a_la_vista_previa(at)
    assert at.session_state["nv_paso"] == "previa" and not at.get("text_input")           # el formulario se oculta
    assert any(f"Folio sugerido NV-{ANIO}-0001" in c.value for c in at.caption)
    assert [m.value for m in at.metric] == ["$ 30.00", "$ 0.00", "$ 30.00"]               # total, anticipo, saldo
    assert any("Hacer cambios" in b.label for b in at.button) and any("Aprobar y Generar" in b.label for b in at.button)
    assert "nv_resultado" not in at.session_state
    assert storage.listar_notas_venta() == [] and numeracion.siguiente_nv(ANIO) == f"NV-{ANIO}-0001"   # nada se consumió
    assert not (storage.DIR_LOCAL_NV.exists() and list(storage.DIR_LOCAL_NV.glob("*.json")))


def test_hacer_cambios_vuelve_al_formulario_con_todo_lo_escrito_en_nota_directa():
    at = _nota_lista()
    _ti(at, "Teléfono").input("0988776655").run()
    _ti(at, "C.I. / RUC").input("1712345678").run()
    _num(at, "Anticipo").set_value(10).run()
    _a_la_vista_previa(at)
    _boton(at, "Hacer cambios").click().run()
    assert not at.exception and at.session_state["nv_paso"] == "editar"
    assert _ti(at, "Cliente").value == "MARIA LOPEZ" and _ti(at, "Teléfono").value == "0988776655"
    assert _ti(at, "C.I. / RUC").value == "1712345678" and _num(at, "Anticipo").value == 10
    assert at.radio(key="nv_modo").value == DIRECTA                                       # no salta a «desde una cotización»
    assert [i["descripcion"] for i in at.session_state["nv"]["items"]] == ["SIRENA"]
    assert [m.value for m in at.metric][-1] == "$ 20.00"                                  # saldo = 30 - 10


def test_hacer_cambios_conserva_la_cotizacion_elegida_y_sus_datos():
    _cotizacion_guardada()
    at = _app()
    sel = at.selectbox(key="nv_cot")
    sel.select("2026-0765 · PEPITO PÉREZ · $ 657.80").run()
    _num(at, "Anticipo").set_value(100).run()
    _a_la_vista_previa(at)
    assert any("Referencia" in c.value or "Folio sugerido" in c.value for c in at.caption)
    _boton(at, "Hacer cambios").click().run()
    assert at.selectbox(key="nv_cot").value == "2026-0765 · PEPITO PÉREZ · $ 657.80"     # sigue elegida
    assert _ti(at, "Cliente").value == "PEPITO PÉREZ" and _num(at, "Anticipo").value == 100
    assert [m.value for m in at.metric][-1] == "$ 557.80" and any("Cotización N° 2026-0765" in c.value for c in at.caption)


def test_la_vista_previa_y_el_pdf_final_coinciden_y_aprobar_consume_el_folio():
    at = _nota_lista()
    _a_la_vista_previa(at)
    _boton(at, "Aprobar y Generar Nota de Venta").click().run()
    nota = at.session_state["nv_resultado"]["nota"]
    assert nota.folio == f"NV-{ANIO}-0001" and not at.exception
    assert any(f"Nota de venta NV-{ANIO}-0001" in s.value or "generada" in s.value for s in at.success)
    assert numeracion.siguiente_nv(ANIO) == f"NV-{ANIO}-0002" and len(storage.listar_notas_venta()) == 1
    assert at.get("image") and at.get("download_button")                                  # el resultado también muestra el PDF


def test_el_boton_de_vista_previa_exige_datos_validos():
    at = _app(DIRECTA)
    assert _boton(at, "Vista previa").disabled and not at.get("image")


def test_la_vista_previa_no_usa_la_ia():
    with mock.patch("cotizador.extractor.extraer") as ia, mock.patch("cotizador.extractor.ajustar") as ia2:
        at = _nota_lista()
        _a_la_vista_previa(at)
        _boton(at, "Hacer cambios").click().run()
        _a_la_vista_previa(at)
        assert ia.call_count == 0 and ia2.call_count == 0

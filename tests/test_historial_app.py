"""Historial en la app: guardar al aprobar, buscar, descargar el PDF y cargar para modificar (sin red ni IA)."""
from datetime import date
from decimal import Decimal as D
from pathlib import Path
from unittest import mock

import fitz
from streamlit.testing.v1 import AppTest

from cotizador import storage
from cotizador.schemas import Cotizacion, ExtraccionTrabajo, Linea
from cotizador.storage import StorageError

APP = str(Path(__file__).parent.parent / "app.py")
HISTORIAL = "📂 Historial de Cotizaciones"
NUEVA = "📝 Nueva Cotización"


def _ext():
    return ExtraccionTrabajo.model_validate({
        "cliente": {"nombre": "ING. PEREZ", "atencion": None, "telefono": "0987003533", "direccion": "LA FLORESTA",
                    "ciudad": None},
        "titulo_trabajo": "CAMARAS", "observaciones": [], "forma_pago": None, "saldo": None,
        "tiempo_entrega": None, "garantia": None, "notas_tecnicas": None, "total_declarado": None,
        "items": [{"cantidad": 2, "descripcion": "CAMARA DOMO", "precio_unitario": 5, "total_declarado": None}],
    })


def _cot(folio, cliente, cantidad="2", precio="50.00", iva="0"):
    sub = D(cantidad) * D(precio)
    imp = (sub * D(iva) / 100).quantize(D("0.01"))
    return Cotizacion(
        numero=folio, fecha="19 DE OCTUBRE DEL 2026", cliente_nombre=cliente, cliente_telefono="0999111222",
        cliente_direccion="QUITO", cliente_ciudad="QUITO-ECUADOR",
        lineas=[Linea(cantidad=D(cantidad), descripcion="CAMARA DOMO", precio_unitario=D(precio), total=sub)],
        observaciones=["MATERIAL INCLUIDO"], subtotal=sub, iva_porcentaje=D(iva), iva=imp, total=sub + imp,
        forma_pago="50% A LA FIRMA", saldo="CONTRAENTREGA", tiempo_entrega="3 DIAS", garantia="UN AÑO",
        notas_tecnicas="Requiere internet.",
    )


def _app(vista=NUEVA):
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["autenticado"] = True
    at.session_state["vista"] = vista
    return at.run()


def _boton(at, texto):
    return next(b for b in at.button if texto in b.label)


def _hasta_aprobar(at):
    at.text_area[0].input("dos domos a 5").run()
    _boton(at, "Procesar con IA").click().run()
    _boton(at, "Continuar").click().run()
    return at


# ------------------------------------------------------------------ guardar al aprobar
def test_aprobar_guarda_en_el_historial_una_sola_vez():
    with mock.patch("cotizador.extractor.extraer", return_value=_ext()), \
         mock.patch("cotizador.storage.guardar_cotizacion", return_value="cotizaciones/2026-0765_ing_perez.json") as g:
        at = _hasta_aprobar(_app())
        assert g.call_count == 0                       # ver la vista previa no guarda nada
        _boton(at, "Aprobar").click().run()
        assert g.call_count == 1 and not at.exception
        cot, fecha_iso = g.call_args.args
        assert cot.cliente_nombre == "ING. PEREZ" and cot.total == D("10.00") and fecha_iso == date.today().isoformat()
        assert any("Guardada en el historial" in c.value for c in at.caption)
        at.sidebar.number_input[0].set_value(15).run()  # tocar el IVA en el paso 4 no vuelve a guardar
        assert g.call_count == 1


def test_si_falla_el_guardado_se_avisa_pero_el_pdf_se_entrega():
    with mock.patch("cotizador.extractor.extraer", return_value=_ext()), \
         mock.patch("cotizador.storage.guardar_cotizacion", side_effect=StorageError("GitHub respondió 401")):
        at = _hasta_aprobar(_app())
        _boton(at, "Aprobar").click().run()
        assert at.session_state["paso"] == 4 and not at.exception
        assert any("NO quedó guardada" in w.value and "401" in w.value for w in at.warning)
        assert at.get("download_button")


def test_aprobacion_real_en_disco_aparece_en_el_historial():
    with mock.patch("cotizador.extractor.extraer", return_value=_ext()):
        at = _hasta_aprobar(_app())
        _boton(at, "Aprobar").click().run()
    assert [f["cliente"] for f in storage.listar_cotizaciones_historicas()] == ["ING. PEREZ"]


# ------------------------------------------------------------------ historial
def test_historial_vacio():
    at = _app(HISTORIAL)
    assert not at.exception and any("Aún no hay cotizaciones" in i.value for i in at.info)


def test_historial_tabla_buscador_y_descarga_de_pdf():
    storage.guardar_cotizacion(_cot("2026-0765", "PEPITO PÉREZ"), "2026-10-19")
    storage.guardar_cotizacion(_cot("2026-0766", "JUAN LOOR", precio="70.00"), "2026-10-21")
    storage.listar_cotizaciones_historicas.clear()
    with mock.patch("cotizador.extractor.extraer") as ext, mock.patch("cotizador.extractor.ajustar") as aj:
        at = _app(HISTORIAL)
        assert not at.exception
        tabla = at.dataframe[0].value
        assert list(tabla.columns) == ["Folio", "Fecha", "Cliente", "Teléfono", "Total ($)"]
        assert list(tabla["Folio"]) == ["2026-0766", "2026-0765"] and list(tabla["Fecha"])[0] == "21/10/2026"
        assert list(tabla["Total ($)"]) == [140.0, 100.0]

        at.text_input(key="h_buscar").input("pepito").run()                # por nombre
        assert list(at.dataframe[0].value["Folio"]) == ["2026-0765"]
        at.text_input(key="h_buscar").input("0766").run()                  # por folio
        assert list(at.dataframe[0].value["Cliente"]) == ["JUAN LOOR"]
        at.text_input(key="h_buscar").input("zzz").run()
        assert any("Ninguna cotización coincide" in w.value for w in at.warning)

        at.text_input(key="h_buscar").input("").run()
        boton_pdf = at.get("download_button")[0]                           # PDF regenerado desde el JSON
        assert "Descargar PDF" in str(boton_pdf)
        assert ext.call_count == 0 and aj.call_count == 0                  # el historial nunca usa la IA


def test_pdf_del_historial_se_regenera_con_los_datos_guardados():
    from cotizador.pdf import generar_pdf
    storage.guardar_cotizacion(_cot("2026-0765", "PEPITO PÉREZ"), "2026-10-19")
    texto = fitz.open(stream=generar_pdf(storage.a_cotizacion(storage.cargar_cotizacion("2026-0765"))), filetype="pdf")[0].get_text()
    assert "COTIZACIÓN Nº: 2026-0765" in texto and "PEPITO PÉREZ" in texto and "$ 100,00" in texto
    assert "Requiere internet." in texto


def test_cargar_modificar_inyecta_la_cotizacion_y_permite_cambiarla():
    storage.guardar_cotizacion(_cot("2026-0765", "PEPITO PÉREZ", cantidad="4", precio="85.00", iva="15"), "2026-10-19")
    storage.listar_cotizaciones_historicas.clear()
    with mock.patch("cotizador.extractor.extraer") as ext, mock.patch("cotizador.extractor.ajustar") as aj:
        at = _app(HISTORIAL)
        _boton(at, "Cargar / Modificar").click().run()
        assert not at.exception and at.session_state["vista"] == NUEVA and at.session_state["paso"] == 2
        assert at.text_input(key="f_numero").value == "2026-0765" and at.text_input(key="f_nombre").value == "PEPITO PÉREZ"
        assert at.text_area(key="f_notas_tecnicas").value == "Requiere internet."
        assert at.sidebar.number_input[0].value == 15 and at.sidebar.date_input[0].value == date(2026, 10, 19)
        assert at.session_state["borrador"]["items"][0]["cantidad"] == 4.0
        assert any("Modificando la cotización 2026-0765" in i.value for i in at.info)
        assert [m.value for m in at.metric][-1] == "391.00"               # 340 + 15% de IVA

        at.text_input(key="f_nombre").input("PEPITO PÉREZ S.A.").run()    # se cambia un dato...
        _boton(at, "Continuar").click().run()
        _boton(at, "Aprobar").click().run()                               # ...y se vuelve a generar
        assert at.session_state["paso"] == 4 and not at.exception
        assert ext.call_count == 0 and aj.call_count == 0
    filas = storage.listar_cotizaciones_historicas()
    assert [(f["folio"], f["cliente"]) for f in filas] == [("2026-0765", "PEPITO PÉREZ S.A.")]  # mismo folio, sin duplicar
    assert [p.name for p in storage.DIR_LOCAL.glob("*.json")] == ["2026-0765_pepito_perez_s_a.json"]


def test_error_al_leer_el_historial_se_muestra_sin_romper_la_app():
    with mock.patch("cotizador.storage.listar_cotizaciones_historicas", side_effect=StorageError("GitHub respondió 403 al leer el historial.")):
        at = _app(HISTORIAL)
        assert not at.exception and any("403" in e.value for e in at.error)


def test_navegacion_entre_pestañas_conserva_el_flujo_actual():
    with mock.patch("cotizador.extractor.extraer", return_value=_ext()):
        at = _app()
        at.text_area[0].input("dos domos a 5").run()
        _boton(at, "Procesar con IA").click().run()
        assert at.session_state["paso"] == 2
        at.radio(key="vista").set_value(HISTORIAL).run()
        at.radio(key="vista").set_value(NUEVA).run()
        assert at.session_state["paso"] == 2 and at.text_input(key="f_nombre").value == "ING. PEREZ"

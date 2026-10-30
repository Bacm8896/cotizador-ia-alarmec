"""Revisión inteligente con catálogo en el paso 2 y pantalla de gestión (IA y GitHub simulados)."""
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from cotizador import catalogo as cat
from cotizador.schemas import ExtraccionTrabajo
from cotizador.storage import StorageError

APP = str(Path(__file__).parent.parent / "app.py")
ELEGIR = "— Elegir producto —"


def _item(desc, precio=None, cantidad=1, generico=False, categoria=None):
    return {"cantidad": cantidad, "descripcion": desc, "precio_unitario": precio, "total_declarado": None,
            "generico": generico, "categoria": categoria}


def _ext(*items):
    return ExtraccionTrabajo.model_validate({
        "cliente": {"nombre": "ING. PEREZ", "atencion": None, "telefono": "0987003533", "direccion": "LA FLORESTA",
                    "ciudad": None},
        "titulo_trabajo": None, "observaciones": [], "forma_pago": None, "saldo": None, "tiempo_entrega": None,
        "garantia": None, "notas_tecnicas": None, "total_declarado": None, "items": list(items)})


def _boton(at, texto):
    return next(b for b in at.button if texto in b.label)


def _paso2(*items):
    """Abre la app, 'procesa' (IA simulada) y deja la app en el paso 2."""
    patcher = mock.patch("cotizador.extractor.extraer", return_value=_ext(*items))
    ext = patcher.start()
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["autenticado"] = True
    at.run()
    at.text_area[0].input("dictado").run()
    _boton(at, "Procesar con IA").click().run()
    patcher.stop()
    assert at.session_state["paso"] == 2 and not at.exception
    return at, ext


def _selector(at):
    return next((s for s in at.selectbox if "es genérico" in s.label), None)


def _total(at):
    return [m.value for m in at.metric][-1:]


# ------------------------------------------------------------------ reconocido
def test_producto_reconocido_precarga_nombre_formal_y_precio_sugerido():
    at, _ = _paso2(_item("cerco eléctrico", cantidad=29))
    assert at.session_state["borrador"]["items"][0]["descripcion"] == "METROS TENDIDO CERCA ELECTRICA"
    assert _total(at) == ["232.00"] and _selector(at) is None
    assert not any("Precio para" in n.label for n in at.number_input)


def test_el_precio_sugerido_viene_del_catalogo_actualizado():
    cat.actualizar_o_agregar_item("CAMARA DOMO", 55)
    at, _ = _paso2(_item("domo", cantidad=2))
    assert _total(at) == ["110.00"]


# ------------------------------------------------------------------ genérico
def test_generico_muestra_selector_con_las_opciones_de_su_categoria_y_aplica_la_elegida():
    at, ext = _paso2(_item("CÁMARAS", cantidad=4, generico=True, categoria="CCTV"))
    sel = _selector(at)
    assert sel is not None and not _total(at)
    assert sel.options[0] == ELEGIR and sel.options[-1] == cat.OTRO
    assert {"CAMARA TUBO 1080P", "CAMARA DOMO IP 2MP", "DVR"} <= set(sel.options) and "SIRENA" not in sel.options
    assert _boton(at, "Continuar").disabled

    sel.select("CAMARA TUBO 1080P").run()
    assert not at.exception and _selector(at) is None
    assert at.session_state["borrador"]["items"][0]["descripcion"] == "CAMARA TUBO 1080P"
    assert at.session_state["items_base"][0]["descripcion"] == "CAMARA TUBO 1080P"   # la tabla se recarga
    caja = next(n for n in at.number_input if "Precio para: CAMARA TUBO 1080P" in n.label)  # sin precio sugerido: se pide
    caja.set_value(85).run()
    assert _total(at) == ["340.00"] and not _boton(at, "Continuar").disabled
    assert ext.call_count == 1                                                        # elegir no vuelve a usar la IA


def test_al_elegir_del_catalogo_con_precio_sugerido_se_precarga():
    cat.actualizar_o_agregar_item("CAMARA TUBO 1080P", 85)
    at, _ = _paso2(_item("CÁMARAS", cantidad=4, generico=True, categoria="CCTV"))
    _selector(at).select("CAMARA TUBO 1080P").run()
    assert _total(at) == ["340.00"]


def test_otro_personalizado_conserva_el_texto_y_pide_el_precio():
    at, _ = _paso2(_item("CÁMARAS", cantidad=4, generico=True, categoria="CCTV"))
    _selector(at).select(cat.OTRO).run()
    assert at.session_state["borrador"]["items"][0]["descripcion"] == "CÁMARAS" and _selector(at) is None
    assert any("Precio para: CÁMARAS" in n.label for n in at.number_input)


def test_generico_sin_categoria_conocida_ofrece_todo_el_catalogo():
    at, _ = _paso2(_item("COSAS", generico=True, categoria=None))
    assert {"SIRENA", "DVR"} <= set(_selector(at).options)


# ------------------------------------------------------------------ guardar en el catálogo
def _casillas(at):
    return [c for c in at.checkbox if "Guardar / actualizar en el catálogo frecuente" in c.label]


def test_casilla_guardar_en_catalogo_producto_nuevo_y_precio_distinto():
    at, _ = _paso2(_item("CAMARA PTZ", 500), _item("SIRENA", 30))
    casillas = _casillas(at)
    assert len(casillas) == 2 and all(not c.value for c in casillas)             # discretas: desmarcadas por defecto
    assert "CAMARA PTZ" in casillas[0].label and "nuevo" in casillas[0].label
    assert "SIRENA" in casillas[1].label and "sugerido hoy" in casillas[1].label


def test_aprobar_con_casillas_marcadas_actualiza_el_catalogo_una_vez():
    at, _ = _paso2(_item("CAMARA PTZ", 500), _item("SIRENA", 30), _item("DVR", 120))
    ptz = next(c for c in _casillas(at) if "CAMARA PTZ" in c.label)
    ptz.check().run()
    next(s for s in at.selectbox if s.label == "Categoría").select("CCTV").run()
    next(c for c in _casillas(at) if "SIRENA" in c.label).check().run()          # y el precio de una sirena existente
    _boton(at, "Continuar").click().run()
    with mock.patch.object(cat, "actualizar_o_agregar_items", wraps=cat.actualizar_o_agregar_items) as espia:
        _boton(at, "Aprobar").click().run()
    assert espia.call_count == 1 and not at.exception
    assert espia.call_args.args[0] == [
        {"nombre": "CAMARA PTZ", "precio": 500.0, "categoria": "CCTV", "unidad": "unidad"},
        {"nombre": "SIRENA", "precio": 30.0, "categoria": "Alarma", "unidad": "unidad"}]
    guardado = {p["nombre_oficial"]: p for p in cat.obtener_catalogo()}
    assert guardado["CAMARA PTZ"]["precio_unitario_sugerido"] == 500.0 and guardado["CAMARA PTZ"]["categoria"] == "CCTV"
    assert guardado["SIRENA"]["precio_unitario_sugerido"] == 30.0 and guardado["DVR"]["precio_unitario_sugerido"] is None
    assert any("Catálogo actualizado" in c.value and "CAMARA PTZ (nuevo)" in c.value for c in at.caption)


def test_sin_casillas_marcadas_el_catalogo_no_se_toca():
    at, _ = _paso2(_item("CAMARA PTZ", 500))
    _boton(at, "Continuar").click().run()
    _boton(at, "Aprobar").click().run()
    assert at.session_state["paso"] == 4 and not cat.ARCHIVO_LOCAL.exists()


def test_si_falla_la_actualizacion_del_catalogo_se_avisa_y_la_cotizacion_sigue():
    at, _ = _paso2(_item("CAMARA PTZ", 500))
    _casillas(at)[0].check().run()
    _boton(at, "Continuar").click().run()
    with mock.patch.object(cat, "actualizar_o_agregar_items", side_effect=StorageError("GitHub respondió 403")):
        _boton(at, "Aprobar").click().run()
    assert at.session_state["paso"] == 4 and any("No se pudo actualizar el catálogo" in w.value for w in at.warning)
    assert at.get("download_button")


# ------------------------------------------------------------------ pantalla de gestión
def _vista_catalogo():
    at = AppTest.from_file(APP, default_timeout=60)
    at.session_state["autenticado"] = True
    at.session_state["vista"] = "💲 Catálogo y precios"
    return at.run()


def test_vista_catalogo_muestra_la_lista_y_guarda_sin_usar_la_ia():
    with mock.patch("cotizador.extractor.extraer") as ia, \
         mock.patch.object(cat, "guardar_catalogo", return_value={"total": 16}) as guardar:
        at = _vista_catalogo()
        assert not at.exception and list(at.dataframe[0].value["nombre_oficial"]) == [p["nombre_oficial"] for p in cat.CATALOGO_BASE]
        _boton(at, "Guardar catálogo").click().run()
        assert guardar.call_count == 1 and not at.exception
        nombres = [p["nombre_oficial"] for p in guardar.call_args.args[0]]
        assert nombres == [p["nombre_oficial"] for p in cat.CATALOGO_BASE]
        assert all("alias" in p for p in guardar.call_args.args[0])            # los alias se conservan
        assert any("Catálogo guardado" in s.value for s in at.success)
        assert ia.call_count == 0


def test_vista_catalogo_muestra_el_error_de_lectura():
    with mock.patch.object(cat, "obtener_catalogo", side_effect=StorageError("GitHub respondió 403 al leer el catálogo.")):
        at = _vista_catalogo()
        assert not at.exception and any("403" in e.value for e in at.error)


def test_si_el_catalogo_no_se_puede_leer_la_cotizacion_sigue_con_la_lista_base():
    with mock.patch.object(cat, "obtener_catalogo", side_effect=StorageError("sin red")):
        at, _ = _paso2(_item("cerco eléctrico", cantidad=29))
        assert not at.exception and _total(at) == ["232.00"]

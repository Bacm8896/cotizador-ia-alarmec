"""Catálogo dinámico: lectura, desambiguación y actualización en GitHub (API simulada, sin red)."""
import json
import urllib.error

import pytest
from fakes import GitHubFalso

from cotizador import borrador as bd
from cotizador import catalogo as cat
from cotizador import numeracion, storage
from cotizador.schemas import ExtraccionTrabajo
from cotizador.storage import StorageError

TOKEN = "ghp_token_de_prueba"
BASE = cat.CATALOGO_BASE


@pytest.fixture
def gh(monkeypatch):
    falso = GitHubFalso()
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GITHUB_REPO", "tu-usuario/cotizador-datos")
    monkeypatch.setattr(storage, "_pedir", falso)
    monkeypatch.setattr(numeracion, "_pedir", falso)
    cat.obtener_catalogo.clear()
    return falso


def _guardado(gh):
    return json.loads(gh.ramas["datos"]["catalogo.json"][0])


# ------------------------------------------------------------------ lógica pura
def test_normalizar_y_buscar_ignoran_tildes_mayusculas_y_usan_alias():
    assert cat.normalizar("  Cámara   DOMO ") == "camara domo"
    assert cat.buscar("camara domo", BASE)["id"] == "camara_domo"
    assert cat.buscar("Cerco Eléctrico", BASE)["nombre_oficial"] == "METROS TENDIDO CERCA ELECTRICA"  # alias
    assert cat.buscar("cámaras", BASE) is None and cat.buscar("", BASE) is None


def test_por_categoria_filtra_y_si_no_hay_devuelve_todo():
    cctv = {p["nombre_oficial"] for p in cat.por_categoria(BASE, "cctv")}
    assert {"CAMARA TUBO 1080P", "CAMARA DOMO IP 2MP", "DVR"} <= cctv and "SIRENA" not in cctv
    assert len(cat.por_categoria(BASE, "Inexistente")) == len(BASE) == len(cat.por_categoria(BASE, None))


def test_aplicar_cambios_crea_actualiza_y_no_duplica():
    nuevo, rep = cat.aplicar_cambios(BASE, [
        {"nombre": "camara domo", "precio": 55, "categoria": None, "unidad": None},
        {"nombre": "Cámara PTZ", "precio": 500, "categoria": "CCTV", "unidad": "unidad"},
        {"nombre": "camara ptz", "precio": 510},
    ])
    assert rep == {"creados": ["CÁMARA PTZ"], "actualizados": ["CAMARA DOMO", "CÁMARA PTZ"]}
    assert len(nuevo) == len(BASE) + 1
    assert cat.buscar("camara domo", nuevo)["precio_unitario_sugerido"] == 55.0
    ptz = cat.buscar("CÁMARA PTZ", nuevo)
    assert ptz["precio_unitario_sugerido"] == 510.0 and ptz["id"] == "camara_ptz" and ptz["categoria"] == "CCTV"
    assert cat.buscar("camara domo", BASE)["precio_unitario_sugerido"] is None  # la lista original no se muta


def test_id_unico_si_el_slug_choca():
    nuevo, _ = cat.aplicar_cambios([cat.limpiar_item({"nombre_oficial": "A-B"})], [{"nombre": "A B", "precio": 1}])
    assert len(nuevo) == 1  # mismo producto: se actualiza
    nuevo, _ = cat.aplicar_cambios([{**cat.limpiar_item({"nombre_oficial": "A B"}), "id": "a_b"}], [{"nombre": "a/b", "precio": 1}])
    assert [p["id"] for p in nuevo] == ["a_b"] and nuevo[0]["precio_unitario_sugerido"] == 1.0


def test_validar_rechaza_repetidos_y_precios_negativos():
    with pytest.raises(StorageError, match="repetido"):
        cat.validar([{"nombre_oficial": "A"}, {"nombre_oficial": "a"}])
    with pytest.raises(StorageError, match="negativo"):
        cat.validar([{"nombre_oficial": "A", "precio_unitario_sugerido": -1}])
    assert cat.validar([{"nombre_oficial": " sirena ", "precio_unitario_sugerido": float("nan")}])[0]["precio_unitario_sugerido"] is None


# ------------------------------------------------------------------ lectura (GitHub)
def test_si_no_existe_catalogo_json_usa_la_lista_base_sin_escribir(gh):
    assert cat.obtener_catalogo() == BASE
    assert all(m == "GET" for m, _, _ in gh.llamadas) and "datos" not in gh.ramas


def test_lectura_una_llamada_y_cache_de_60s(gh):
    gh.ramas["datos"] = {"catalogo.json": (json.dumps({"version": 1, "productos": [
        {"id": "x", "nombre_oficial": "x uno", "categoria": "CCTV", "unidad": "unidad", "precio_unitario_sugerido": 9}]}).encode(), "s")}
    assert cat.obtener_catalogo()[0]["nombre_oficial"] == "X UNO"
    cat.obtener_catalogo()
    assert len(gh.llamadas) == 1 and gh.llamadas[0][2] == TOKEN


def test_error_de_lectura_es_storageerror(gh):
    gh.fallar_con = 403
    with pytest.raises(StorageError, match="403"):
        cat.obtener_catalogo()


# ------------------------------------------------------------------ escritura (GitHub)
def test_agregar_item_commitea_catalogo_json_en_la_rama_datos(gh):
    rep = cat.actualizar_o_agregar_item("Cámara PTZ", 500, "CCTV", "unidad")
    assert rep == {"creados": ["CÁMARA PTZ"], "actualizados": []}
    doc = _guardado(gh)
    assert doc["version"] == 1 and len(doc["productos"]) == len(BASE) + 1
    ptz = doc["productos"][-1]
    assert ptz == {"id": "camara_ptz", "nombre_oficial": "CÁMARA PTZ", "categoria": "CCTV", "unidad": "unidad",
                   "precio_unitario_sugerido": 500.0, "alias": []}
    assert gh.ramas["main"] == {}  # solo la rama de datos
    assert cat.obtener_catalogo()[-1]["nombre_oficial"] == "CÁMARA PTZ"  # la caché se invalidó


def test_actualizar_precio_de_un_item_existente_no_duplica(gh):
    cat.actualizar_o_agregar_item("CAMARA DOMO", 55)
    cat.actualizar_o_agregar_item("cámara domo", 60)
    productos = _guardado(gh)["productos"]
    assert len(productos) == len(BASE)
    assert next(p for p in productos if p["id"] == "camara_domo")["precio_unitario_sugerido"] == 60.0


def test_varios_cambios_son_una_sola_escritura(gh):
    gh.ramas["datos"] = {}  # la rama ya existe: un único PUT
    cat.actualizar_o_agregar_items([{"nombre": "A", "precio": 1}, {"nombre": "B", "precio": 2}, {"nombre": "SIRENA", "precio": 30}])
    assert [m for m, _, _ in gh.llamadas].count("PUT") == 1
    nombres = [p["nombre_oficial"] for p in _guardado(gh)["productos"]]
    assert nombres[-2:] == ["A", "B"] and len(nombres) == len(BASE) + 2


def test_reintenta_si_otra_sesion_guardo_a_la_vez(gh):
    cat.actualizar_o_agregar_item("A", 1)            # el archivo ya existe en la rama
    original = gh.__call__
    estado = {"fallos": 1}

    def con_choque(metodo, ruta, token, cuerpo=None):
        if metodo == "PUT" and "catalogo.json" in ruta and estado["fallos"]:
            estado["fallos"] -= 1
            raise urllib.error.HTTPError("u", 409, "conflicto", {}, None)
        return original(metodo, ruta, token, cuerpo)

    import cotizador.catalogo as c
    c._gh_escribir.__globals__["_pedir"] = con_choque
    try:
        cat.actualizar_o_agregar_item("B", 2)
    finally:
        c._gh_escribir.__globals__["_pedir"] = gh
    assert {p["nombre_oficial"] for p in _guardado(gh)["productos"]} >= {"A", "B"}


@pytest.mark.parametrize("codigo", [401, 403, 500])
def test_error_al_escribir_es_storageerror_sin_filtrar_el_token(gh, codigo):
    gh.fallar_con = codigo
    with pytest.raises(StorageError) as e:
        cat.actualizar_o_agregar_item("A", 1)
    assert str(codigo) in str(e.value) and TOKEN not in str(e.value)


def test_guardar_catalogo_reemplaza_la_lista_completa(gh):
    cat.guardar_catalogo([{"nombre_oficial": "SOLO UNO", "categoria": "Alarma", "precio_unitario_sugerido": 10}])
    assert [p["nombre_oficial"] for p in _guardado(gh)["productos"]] == ["SOLO UNO"]
    assert [p["nombre_oficial"] for p in cat.obtener_catalogo()] == ["SOLO UNO"]


# ------------------------------------------------------------------ sin GitHub (uso local)
def test_sin_github_se_guarda_en_disco_local():
    assert cat.obtener_catalogo() == BASE
    cat.actualizar_o_agregar_item("CAMARA DOMO", 55, "CCTV", "unidad")
    assert cat.ARCHIVO_LOCAL.exists()
    assert cat.buscar("camara domo", cat.obtener_catalogo())["precio_unitario_sugerido"] == 55.0


# ------------------------------------------------------------------ desambiguación en el borrador
def _ext(items):
    return ExtraccionTrabajo.model_validate({
        "cliente": {"nombre": "A", "atencion": None, "telefono": "1", "direccion": "B", "ciudad": None},
        "titulo_trabajo": None, "observaciones": [], "forma_pago": None, "saldo": None, "tiempo_entrega": None,
        "garantia": None, "notas_tecnicas": None, "total_declarado": None, "items": items})


def _it(desc, precio=None, generico=False, categoria=None, cantidad=1):
    return {"cantidad": cantidad, "descripcion": desc, "precio_unitario": precio, "total_declarado": None,
            "generico": generico, "categoria": categoria}


def test_reconocido_precarga_nombre_formal_y_precio_sugerido_pero_respeta_el_dictado():
    b = bd.desde_extraccion(_ext([_it("cerco eléctrico", cantidad=29), _it("domo", precio=70)]), BASE)
    assert b["items"][0]["descripcion"] == "METROS TENDIDO CERCA ELECTRICA" and b["items"][0]["precio_unitario"] == 8.0
    assert b["items"][1]["descripcion"] == "CAMARA DOMO" and b["items"][1]["precio_unitario"] == 70  # el dictado manda
    assert b["meta"] == {}


def test_generico_se_marca_y_se_resuelve_con_una_opcion_del_catalogo():
    b = bd.desde_extraccion(_ext([_it("CÁMARAS", generico=True, categoria="CCTV", cantidad=4)]), BASE)
    assert bd.genericos(b, BASE) == [0] and bd.categoria_de(b, 0) == "CCTV"
    opcion = cat.buscar("CAMARA TUBO 1080P", BASE)
    bd.resolver_generico(b, 0, {**opcion, "precio_unitario_sugerido": 85.0})
    assert b["items"][0]["descripcion"] == "CAMARA TUBO 1080P" and b["items"][0]["precio_unitario"] == 85.0
    assert bd.genericos(b, BASE) == []


def test_otro_personalizado_conserva_el_texto_y_deja_de_ser_generico():
    b = bd.desde_extraccion(_ext([_it("CÁMARAS", generico=True, categoria="CCTV")]), BASE)
    bd.resolver_generico(b, 0, None)
    assert b["items"][0]["descripcion"] == "CÁMARAS" and bd.genericos(b, BASE) == []


def test_candidatos_nuevos_o_con_otro_precio_y_cambios_para_el_catalogo():
    from decimal import Decimal as D

    from cotizador.schemas import Linea
    b = bd.desde_extraccion(_ext([_it("CAMARA PTZ", 500), _it("DVR", 120), _it("SIRENA"), _it("CÁMARAS", generico=True)]), BASE)
    cands = bd.candidatos_catalogo(b, BASE)
    assert [(c["nombre"], c["nuevo"]) for c in cands] == [("CAMARA PTZ", True), ("DVR", False)]  # sin precio / genérico: no
    b["guardar"] = {"camara ptz": {"categoria": "CCTV", "unidad": "unidad"}, "dvr": {"categoria": "CCTV", "unidad": "unidad"}}
    lineas = [Linea(cantidad=D(1), descripcion="CAMARA PTZ", precio_unitario=D("500.00"), total=D("500.00")),
              Linea(cantidad=D(1), descripcion="SIRENA", precio_unitario=D("30.00"), total=D("30.00"))]
    assert bd.cambios_para_catalogo(lineas, b["guardar"]) == [
        {"nombre": "CAMARA PTZ", "precio": 500.0, "categoria": "CCTV", "unidad": "unidad"}]

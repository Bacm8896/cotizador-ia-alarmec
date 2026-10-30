"""Regresiones de "app.py nuevo + módulo viejo": las llamadas de app.py deben coincidir con las firmas reales."""
import ast
import inspect
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

from cotizador import borrador as bd
from cotizador import catalogo as cat
from cotizador import notaventa, numeracion, storage
from cotizador.schemas import ExtraccionTrabajo

RAIZ = Path(__file__).resolve().parent.parent
APP = str(RAIZ / "app.py")


def _ext(*items):
    return ExtraccionTrabajo.model_validate({
        "cliente": {"nombre": "ING. PEREZ", "atencion": None, "telefono": "0987003533", "direccion": "LA FLORESTA",
                    "ciudad": None},
        "titulo_trabajo": None, "observaciones": [], "forma_pago": None, "saldo": None, "tiempo_entrega": None,
        "garantia": None, "notas_tecnicas": None, "total_declarado": None, "items": list(items)})


def _item(desc, precio=None, cantidad=1):
    return {"cantidad": cantidad, "descripcion": desc, "precio_unitario": precio, "total_declarado": None,
            "generico": False, "categoria": None}


# ------------------------------------------------------------------ firma de desde_extraccion
def test_desde_extraccion_acepta_catalogo_posicional_por_nombre_o_sin_el():
    params = inspect.signature(bd.desde_extraccion).parameters
    assert list(params) == ["ext", "catalogo"] and params["catalogo"].default is None
    ext = _ext(_item("cerco eléctrico", cantidad=29))
    por_posicion = bd.desde_extraccion(ext, cat.CATALOGO_BASE)       # como lo llama app.py
    por_nombre = bd.desde_extraccion(ext, catalogo=cat.CATALOGO_BASE)
    sin_catalogo = bd.desde_extraccion(ext)                           # compatibilidad con llamadas antiguas
    assert por_posicion == por_nombre == sin_catalogo
    assert por_posicion["items"][0]["descripcion"] == "METROS TENDIDO CERCA ELECTRICA"


def test_desde_extraccion_usa_el_catalogo_recibido_no_el_base():
    propio = [{"id": "p", "nombre_oficial": "PRODUCTO DEL CLIENTE", "categoria": "Otros", "unidad": "kit",
               "precio_unitario_sugerido": 99.0, "alias": ["mi producto"]}]
    b = bd.desde_extraccion(_ext(_item("mi producto"), _item("domo")), propio)
    assert b["items"][0]["descripcion"] == "PRODUCTO DEL CLIENTE" and b["items"][0]["precio_unitario"] == 99.0
    assert b["items"][1]["descripcion"] == "domo"  # no está en ESE catálogo: se conserva lo dictado


# ------------------------------------------------------------------ app.py contra las firmas reales
def test_todas_las_llamadas_de_app_py_a_los_modulos_coinciden_con_sus_firmas():
    modulos = {"bd": bd, "cat": cat, "storage": storage, "numeracion": numeracion, "nv": notaventa}
    arbol = ast.parse((RAIZ / "app.py").read_text(encoding="utf-8"))
    revisadas = 0
    for n in ast.walk(arbol):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and isinstance(n.func.value, ast.Name) \
                and n.func.value.id in modulos and not any(isinstance(a, ast.Starred) for a in n.args):
            funcion = getattr(modulos[n.func.value.id], n.func.attr)
            func = getattr(funcion, "__wrapped__", funcion)  # st.cache_data envuelve la función
            try:
                inspect.signature(func).bind(*[object()] * len(n.args), **{k.arg: object() for k in n.keywords if k.arg})
            except TypeError as e:
                raise AssertionError(f"app.py línea {n.lineno}: {n.func.value.id}.{n.func.attr}() no coincide con su firma: {e}")
            revisadas += 1
    assert revisadas >= 25  # el recorrido realmente encontró las llamadas


# ------------------------------------------------------------------ _nuevo_borrador de punta a punta
def _app_hasta_paso2(ext):
    with mock.patch("cotizador.extractor.extraer", return_value=ext):
        at = AppTest.from_file(APP, default_timeout=60)
        at.session_state["autenticado"] = True
        at.run()
        at.text_area[0].input("cuatro cámaras y 29 metros de cerco").run()
        next(b for b in at.button if "Procesar con IA" in b.label).click().run()
    return at


def test_nuevo_borrador_llama_a_desde_extraccion_con_la_extraccion_y_el_catalogo():
    ext = _ext(_item("cerco eléctrico", cantidad=29))
    with mock.patch.object(bd, "desde_extraccion", wraps=bd.desde_extraccion) as espia:
        at = _app_hasta_paso2(ext)
    assert not at.exception and at.session_state["paso"] == 2
    assert espia.call_count == 1
    argumentos = espia.call_args.args
    assert len(argumentos) == 2 and argumentos[0] == ext and isinstance(argumentos[1], list)
    assert {p["nombre_oficial"] for p in argumentos[1]} >= {"DVR", "SIRENA"}       # el catálogo vigente
    borrador = at.session_state["borrador"]
    assert borrador["items"][0]["descripcion"] == "METROS TENDIDO CERCA ELECTRICA" and borrador["items"][0]["precio_unitario"] == 8.0
    assert borrador["numero"]  # folio sugerido


def test_nuevo_borrador_funciona_aunque_el_catalogo_no_se_pueda_leer():
    from cotizador.storage import StorageError
    with mock.patch.object(cat, "obtener_catalogo", side_effect=StorageError("sin red")):
        at = _app_hasta_paso2(_ext(_item("DVR", 120)))
    assert not at.exception and at.session_state["borrador"]["items"][0]["descripcion"] == "DVR"


# ------------------------------------------------------------------ despliegue en caliente
def test_recargar_si_cambio_reemplaza_los_modulos_viejos(tmp_path):
    """Simula Streamlit Cloud: el proceso ya cargó el paquete y luego cambia un archivo en disco."""
    copia = tmp_path / "cotizador"
    shutil.copytree(RAIZ / "cotizador", copia, ignore=shutil.ignore_patterns("__pycache__"))
    guion = textwrap.dedent('''
        import inspect, pathlib, sys
        import cotizador
        from cotizador import borrador
        assert list(inspect.signature(borrador.desde_extraccion).parameters) == ["ext", "catalogo"]
        assert cotizador.recargar_si_cambio() is False          # nada cambió: no se toca nada
        assert sys.modules["cotizador.borrador"] is borrador

        # despliegue: borrador.py cambia en disco (aquí, la firma antigua de una sola parámetro)
        ruta = pathlib.Path(borrador.__file__)
        ruta.write_text(ruta.read_text(encoding="utf-8").replace(
            "def desde_extraccion(ext: ExtraccionTrabajo, catalogo: list[dict] | None = None) -> dict:",
            "def desde_extraccion(ext: ExtraccionTrabajo) -> dict:\\n    catalogo = None"), encoding="utf-8")
        assert cotizador.recargar_si_cambio() is True            # detecta el cambio y descarta los módulos
        from cotizador import borrador as nuevo                  # lo que haría app.py a continuación
        assert nuevo is not borrador
        assert list(inspect.signature(nuevo.desde_extraccion).parameters) == ["ext"]
        assert cotizador.recargar_si_cambio() is False           # ya está al día
        print("OK")
    ''')
    r = subprocess.run([sys.executable, "-c", guion], cwd=tmp_path, capture_output=True, text=True)
    assert r.returncode == 0 and "OK" in r.stdout, r.stderr[-1500:]

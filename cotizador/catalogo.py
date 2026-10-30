"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Catálogo dinámico y persistente de productos y precios sugeridos.

Se guarda en catalogo.json de la rama de datos (NUMERACION_RAMA, por defecto "datos") del repositorio
GITHUB_REPO, con la API de GitHub y GITHUB_TOKEN (sin ellos, en data/catalogo.json). Si todavía no existe,
se usa la lista base de CATALOGO_BASE y se escribe en GitHub la primera vez que se modifica algo.

Cada producto: id, nombre_oficial, categoria, precio_unitario_sugerido (None = sin precio), unidad y alias
(cómo suelen dictarlo; ayudan a la IA a reconocerlo).
"""
import json
import re
import unicodedata
import urllib.error
from datetime import datetime, timezone

import streamlit as st

from .config import BASE_DIR
from .storage import StorageError, _gh_escribir, _gh_leer, _github

RUTA = "catalogo.json"
ARCHIVO_LOCAL = BASE_DIR / "data" / "catalogo.json"
CATEGORIAS = ["CCTV", "Alarma", "Cerco", "Accesorios", "Motores", "Portero", "Servicios", "Otros"]
UNIDADES = ["unidad", "metro", "kit", "servicio"]
OTRO = "Otro / Personalizado"


def normalizar(texto: str) -> str:
    """Clave de comparación: sin tildes, sin mayúsculas, sin signos ni espacios repetidos."""
    ascii_ = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", ascii_).strip()


def id_de(nombre: str) -> str:
    return normalizar(nombre).replace(" ", "_") or "producto"


def _item(nombre, categoria, unidad="unidad", precio=None, alias=()) -> dict:
    return {"id": id_de(nombre), "nombre_oficial": nombre, "categoria": categoria, "unidad": unidad,
            "precio_unitario_sugerido": precio, "alias": list(alias)}


# Lista base (solo el precio de la cerca eléctrica viene del Excel modelo, abril 2023; el resto se completa en la app).
CATALOGO_BASE: list[dict] = [
    _item("METROS TENDIDO CERCA ELECTRICA", "Cerco", "metro", 8.00, ("cerca eléctrica", "cerco eléctrico", "tendido de cerca")),
    _item("ENERGIZADOR DE CERCA ELECTRICA", "Cerco", "unidad", None, ("energizador", "central de cerca")),
    _item("CAMARA DOMO", "CCTV", "unidad", None, ("cámara domo", "domo")),
    _item("CAMARA DOMO IP 2MP", "CCTV", "unidad", None, ("domo ip", "domo ip 2mp")),
    _item("CAMARA TUBO", "CCTV", "unidad", None, ("cámara tubo", "cámara bullet", "tubo")),
    _item("CAMARA TUBO 1080P", "CCTV", "unidad", None, ("tubo 1080p", "cámara tubo full hd")),
    _item("DVR", "CCTV", "unidad", None, ("dvr", "grabador", "grabador de video")),
    _item("XVR 8 CANALES 1080P", "CCTV", "unidad", None, ("xvr 8 canales", "xvr de 8 canales")),
    _item("PANEL DE ALARMA", "Alarma", "unidad", None, ("panel", "central de alarma", "alarma")),
    _item("SENSOR DE MOVIMIENTO", "Alarma", "unidad", None, ("sensor", "sensor pir", "detector de movimiento")),
    _item("SIRENA", "Alarma", "unidad", None, ("sirena", "sirena exterior")),
    _item("BATERIA 12V", "Accesorios", "unidad", None, ("batería", "baterías 12 voltios", "batería de respaldo")),
    _item("MOTOR DE GARAJE", "Motores", "unidad", None, ("motor de garaje", "motor de portón", "motor de puerta")),
    _item("PORTERO ELECTRICO", "Portero", "unidad", None, ("portero", "intercomunicador", "video portero")),
    _item("MANTENIMIENTO", "Servicios", "servicio", None, ("mantenimiento", "chequeo", "revisión")),
    _item("REINSTALACION", "Servicios", "servicio", None, ("reinstalación", "reinstalar")),
]


# ------------------------------------------------------------------ lógica pura
def limpiar_item(it: dict) -> dict:
    precio = it.get("precio_unitario_sugerido")
    try:
        precio = None if precio in (None, "") or precio != precio else round(float(precio), 2)
    except (TypeError, ValueError):
        precio = None
    nombre = str(it.get("nombre_oficial") or "").strip().upper()
    return {"id": it.get("id") or id_de(nombre), "nombre_oficial": nombre,
            "categoria": str(it.get("categoria") or "Otros").strip() or "Otros",
            "unidad": str(it.get("unidad") or "unidad").strip() or "unidad",
            "precio_unitario_sugerido": precio, "alias": [str(a) for a in it.get("alias") or []]}


def buscar(nombre: str, catalogo: list[dict]) -> dict | None:
    """Producto cuyo nombre oficial (o alias exacto) coincide con el texto, sin importar tildes ni mayúsculas."""
    clave = normalizar(nombre)
    if not clave:
        return None
    for it in catalogo:
        if normalizar(it["nombre_oficial"]) == clave:
            return it
    for it in catalogo:
        if clave in (normalizar(a) for a in it.get("alias", [])):
            return it
    return None


def por_categoria(catalogo: list[dict], categoria: str | None) -> list[dict]:
    """Opciones de una categoría; si no se conoce la categoría o no tiene productos, devuelve todo el catálogo."""
    clave = normalizar(categoria or "")
    candidatos = [it for it in catalogo if normalizar(it["categoria"]) == clave] if clave else []
    return candidatos or list(catalogo)


def aplicar_cambios(catalogo: list[dict], cambios: list[dict]) -> tuple[list[dict], dict]:
    """Agrega productos nuevos o actualiza el precio de los existentes. No modifica la lista recibida."""
    nuevo = [dict(it) for it in catalogo]
    reporte = {"creados": [], "actualizados": []}
    for c in cambios:
        nombre = str(c["nombre"]).strip().upper()
        if not nombre:
            continue
        precio = c.get("precio")
        existente = buscar(nombre, nuevo)
        if existente is not None:
            if precio is not None:
                existente["precio_unitario_sugerido"] = round(float(precio), 2)
            if c.get("categoria"):
                existente["categoria"] = c["categoria"]
            if c.get("unidad"):
                existente["unidad"] = c["unidad"]
            reporte["actualizados"].append(existente["nombre_oficial"])
        else:
            it = limpiar_item({"nombre_oficial": nombre, "categoria": c.get("categoria"), "unidad": c.get("unidad"),
                               "precio_unitario_sugerido": precio})
            usados = {x["id"] for x in nuevo}
            base, n = it["id"], 2
            while it["id"] in usados:
                it["id"], n = f"{base}_{n}", n + 1
            nuevo.append(it)
            reporte["creados"].append(it["nombre_oficial"])
    return nuevo, reporte


def validar(catalogo: list[dict]) -> list[dict]:
    """Limpia y valida una lista completa (para guardarla desde la pantalla de gestión)."""
    limpio, vistos = [], set()
    for it in map(limpiar_item, catalogo):
        if not it["nombre_oficial"]:
            continue
        clave = normalizar(it["nombre_oficial"])
        if clave in vistos:
            raise StorageError(f"El producto «{it['nombre_oficial']}» está repetido.")
        if it["precio_unitario_sugerido"] is not None and it["precio_unitario_sugerido"] < 0:
            raise StorageError(f"El precio de «{it['nombre_oficial']}» no puede ser negativo.")
        vistos.add(clave)
        limpio.append(it)
    return limpio


# ------------------------------------------------------------------ persistencia
def _contenido(items: list[dict]) -> bytes:
    doc = {"version": 1, "actualizado": datetime.now(timezone.utc).isoformat(timespec="seconds"), "productos": items}
    return json.dumps(doc, ensure_ascii=False, indent=2).encode()


def _leer_persistido() -> tuple[list[dict] | None, str | None]:
    """(productos, sha) del catálogo guardado; (None, None) si todavía no existe."""
    gh = _github()
    if gh:
        crudo, sha = _gh_leer(gh, RUTA)
    else:
        crudo, sha = (ARCHIVO_LOCAL.read_bytes() if ARCHIVO_LOCAL.exists() else None), None
    if not crudo:
        return None, sha
    doc = json.loads(crudo)
    return [limpiar_item(x) for x in (doc["productos"] if isinstance(doc, dict) else doc)], sha


@st.cache_data(ttl=60, show_spinner=False)
def obtener_catalogo() -> list[dict]:
    """Catálogo vigente. Si aún no existe, la lista base (se persiste al primer cambio). Cache de 60 s."""
    try:
        items, _ = _leer_persistido()
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code} al leer el catálogo.") from e
    except (OSError, ValueError, KeyError) as e:
        raise StorageError(f"No se pudo leer el catálogo: {e.__class__.__name__}") from e
    return items if items is not None else [dict(it) for it in CATALOGO_BASE]


def _guardar(transformar) -> dict:
    """Lee el catálogo actual, aplica `transformar(lista) -> (lista, reporte)` y lo escribe (reintenta si hay choque)."""
    try:
        for _ in range(3):
            items, sha = _leer_persistido()
            if items is None:
                items = [dict(it) for it in CATALOGO_BASE]
            nuevo, reporte = transformar(items)
            gh = _github()
            if gh:
                try:
                    _gh_escribir(gh, RUTA, _contenido(nuevo), "Catálogo: actualización de productos", sha)
                except urllib.error.HTTPError as e:
                    if e.code in (409, 422):  # otra sesión guardó a la vez: se vuelve a leer
                        continue
                    raise
            else:
                ARCHIVO_LOCAL.parent.mkdir(parents=True, exist_ok=True)
                ARCHIVO_LOCAL.write_bytes(_contenido(nuevo))
            obtener_catalogo.clear()
            return reporte
        raise StorageError("No se pudo guardar el catálogo tras varios intentos.")
    except StorageError:
        raise
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code}: revisa GITHUB_TOKEN (permiso Contents: Read and write) "
                           f"y GITHUB_REPO.") from e
    except (OSError, ValueError, KeyError) as e:
        raise StorageError(f"No se pudo guardar el catálogo: {e.__class__.__name__}") from e


def actualizar_o_agregar_items(cambios: list[dict]) -> dict:
    """Varios cambios en UNA sola escritura. Cada cambio: {nombre, precio, categoria, unidad}."""
    return _guardar(lambda items: aplicar_cambios(items, cambios))


def actualizar_o_agregar_item(nombre: str, precio: float | None, categoria: str | None = None,
                              unidad: str | None = None) -> dict:
    """Agrega un producto nuevo o actualiza el precio de uno existente y lo guarda en la rama de datos."""
    return actualizar_o_agregar_items([{"nombre": nombre, "precio": precio, "categoria": categoria, "unidad": unidad}])


def guardar_catalogo(items: list[dict]) -> dict:
    """Reemplaza el catálogo completo (pantalla de gestión)."""
    nuevo = validar(items)
    return _guardar(lambda _actual: (nuevo, {"total": len(nuevo)}))

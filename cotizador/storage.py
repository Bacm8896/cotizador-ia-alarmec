"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Historial y repositorio de cotizaciones aprobadas.

Cada cotización aprobada se guarda como JSON en  cotizaciones/{folio}_{cliente_slug}.json
de la rama de datos (NUMERACION_RAMA, por defecto "datos") del repositorio GITHUB_REPO, usando la
API de GitHub y el secreto GITHUB_TOKEN. Esa rama es aparte de la principal para que guardar una
cotización no redespliegue la app. Junto a los JSON se mantiene cotizaciones/_indice.json, un resumen
(folio, fecha, cliente, teléfono, total) que permite listar el historial con UNA sola llamada.

Sin GITHUB_TOKEN/GITHUB_REPO (uso local) se guarda en data/cotizaciones/.
"""
import base64
import json
import re
import unicodedata
import urllib.error
import urllib.parse
from datetime import datetime, timezone
from decimal import Decimal

import streamlit as st

from .config import BASE_DIR
from .numeracion import _gh_crear_rama, _github, _pedir
from .schemas import Cotizacion, Linea, LineaNV, NotaVenta

CARPETA = "cotizaciones"
INDICE = f"{CARPETA}/_indice.json"
DIR_LOCAL = BASE_DIR / "data" / "cotizaciones"
CARPETA_NV = "notas_venta"
INDICE_NV = f"{CARPETA_NV}/_indice.json"
DIR_LOCAL_NV = BASE_DIR / "data" / "notas_venta"
VERSION_FORMATO = 1


class StorageError(RuntimeError):
    pass


# ------------------------------------------------------------------ formato
def slug(texto: str) -> str:
    """'ARQ. Juan Pérez Muñoz' -> 'arq_juan_perez_munoz' (seguro para nombres de archivo)."""
    ascii_ = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "_", ascii_.lower()).strip("_") or "cliente"


def folio_seguro(folio: str) -> str:
    """El folio es editable por el usuario: solo letras, dígitos y guiones llegan al nombre de archivo."""
    return re.sub(r"[^A-Za-z0-9-]+", "_", (folio or "").strip()).strip("_")


def nombre_archivo(folio: str, cliente: str) -> str:
    return f"{folio_seguro(folio)}_{slug(cliente)}.json"


def serializar(cot: Cotizacion, fecha_iso: str) -> dict:
    """Cotización completa en un dict JSON-compatible (los montos van como texto para no perder exactitud)."""
    return {
        "version": VERSION_FORMATO,
        "folio": cot.numero,
        "fecha": cot.fecha,
        "fecha_iso": fecha_iso,
        "guardado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cliente": {
            "nombre": cot.cliente_nombre, "atencion": cot.cliente_atencion, "telefono": cot.cliente_telefono,
            "direccion": cot.cliente_direccion, "ciudad": cot.cliente_ciudad,
        },
        "titulo_trabajo": cot.titulo_trabajo,
        "items": [
            {"cantidad": str(l.cantidad), "descripcion": l.descripcion,
             "precio_unitario": str(l.precio_unitario), "total": str(l.total)}
            for l in cot.lineas
        ],
        "observaciones": list(cot.observaciones),
        "subtotal": str(cot.subtotal), "iva_porcentaje": str(cot.iva_porcentaje),
        "iva": str(cot.iva), "total": str(cot.total),
        "notas_tecnicas": cot.notas_tecnicas,
        "condiciones": {
            "forma_pago": cot.forma_pago, "saldo": cot.saldo,
            "tiempo_entrega": cot.tiempo_entrega, "garantia": cot.garantia,
        },
    }


def a_cotizacion(reg: dict) -> Cotizacion:
    """Inversa de serializar: reconstruye la cotización (para regenerar el PDF al vuelo)."""
    c, cond = reg.get("cliente", {}), reg.get("condiciones", {})
    return Cotizacion(
        numero=reg["folio"], fecha=reg["fecha"],
        cliente_nombre=c.get("nombre", ""), cliente_atencion=c.get("atencion", ""),
        cliente_telefono=c.get("telefono", ""), cliente_direccion=c.get("direccion", ""),
        cliente_ciudad=c.get("ciudad", ""), titulo_trabajo=reg.get("titulo_trabajo", ""),
        lineas=[Linea(cantidad=Decimal(i["cantidad"]), descripcion=i["descripcion"],
                      precio_unitario=Decimal(i["precio_unitario"]), total=Decimal(i["total"]))
                for i in reg.get("items", [])],
        observaciones=list(reg.get("observaciones", [])),
        subtotal=Decimal(reg["subtotal"]), iva_porcentaje=Decimal(reg["iva_porcentaje"]),
        iva=Decimal(reg["iva"]), total=Decimal(reg["total"]),
        forma_pago=cond.get("forma_pago", ""), saldo=cond.get("saldo", ""),
        tiempo_entrega=cond.get("tiempo_entrega", ""), garantia=cond.get("garantia", ""),
        notas_tecnicas=reg.get("notas_tecnicas", ""),
    )


def _resumen(reg: dict, archivo: str) -> dict:
    return {
        "folio": reg["folio"], "fecha": reg["fecha"], "fecha_iso": reg.get("fecha_iso", ""),
        "cliente": reg["cliente"].get("nombre", ""), "telefono": reg["cliente"].get("telefono", ""),
        "total": float(Decimal(reg["total"])), "archivo": archivo,
    }


# ------------------------------------------------------------------ GitHub
def _ref(rama: str) -> str:
    return urllib.parse.quote(rama)


def _gh_leer(gh, ruta: str) -> tuple[bytes | None, str | None]:
    """Contenido y sha de un archivo; (None, None) si no existe."""
    token, repo, rama = gh
    try:
        r = _pedir("GET", f"/repos/{repo}/contents/{urllib.parse.quote(ruta)}?ref={_ref(rama)}", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    return base64.b64decode(r["content"]), r["sha"]


def _gh_escribir(gh, ruta: str, contenido: bytes, mensaje: str, sha: str | None) -> None:
    token, repo, rama = gh
    cuerpo = {"message": mensaje, "branch": rama, "content": base64.b64encode(contenido).decode()}
    if sha:
        cuerpo["sha"] = sha
    try:
        _pedir("PUT", f"/repos/{repo}/contents/{urllib.parse.quote(ruta)}", token, cuerpo)
    except urllib.error.HTTPError as e:
        if e.code == 404 and sha is None:  # la rama de datos aún no existe: se crea y se reintenta
            _gh_crear_rama(gh)
            _pedir("PUT", f"/repos/{repo}/contents/{urllib.parse.quote(ruta)}", token, cuerpo)
        else:
            raise


def _gh_borrar(gh, ruta: str, mensaje: str) -> None:
    token, repo, rama = gh
    _, sha = _gh_leer(gh, ruta)
    if sha:
        _pedir("DELETE", f"/repos/{repo}/contents/{urllib.parse.quote(ruta)}", token,
               {"message": mensaje, "branch": rama, "sha": sha})


def _gh_listar_archivos(gh, carpeta: str = CARPETA) -> list[str]:
    token, repo, rama = gh
    try:
        r = _pedir("GET", f"/repos/{repo}/contents/{carpeta}?ref={_ref(rama)}", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return []
        raise
    return [x["name"] for x in r if x["name"].endswith(".json") and not x["name"].startswith("_")]


def _gh_actualizar_indice(gh, resumen: dict, indice_ruta: str = INDICE) -> None:
    for _ in range(3):  # reintenta si otra sesión guardó a la vez (sha desactualizado)
        crudo, sha = _gh_leer(gh, indice_ruta)
        indice = [r for r in (json.loads(crudo) if crudo else []) if r["folio"] != resumen["folio"]]
        indice.append(resumen)
        try:
            _gh_escribir(gh, indice_ruta, json.dumps(indice, ensure_ascii=False).encode(),
                         f"Índice: {resumen['folio']}", sha)
            return
        except urllib.error.HTTPError as e:
            if e.code not in (409, 422):
                raise
    raise StorageError("No se pudo actualizar el índice del historial tras varios intentos.")


def _gh_reconstruir_indice(gh, carpeta: str = CARPETA, resumen=None) -> list[dict]:
    """Si no hay índice (archivos guardados a mano), se arma leyendo cada JSON una sola vez."""
    resumen = resumen or _resumen
    resumenes = []
    for nombre in _gh_listar_archivos(gh, carpeta):
        crudo, _ = _gh_leer(gh, f"{carpeta}/{nombre}")
        if crudo:
            resumenes.append(resumen(json.loads(crudo), nombre))
    return resumenes


# ------------------------------------------------------------------ guardar
def guardar_cotizacion(cot: Cotizacion, fecha_iso: str) -> str:
    """Guarda la cotización aprobada y actualiza el índice. Devuelve dónde quedó (ruta). Lanza StorageError."""
    if not folio_seguro(cot.numero):
        raise StorageError("La cotización no tiene folio.")
    prefijo = f"{folio_seguro(cot.numero)}_"
    reg = serializar(cot, fecha_iso)
    archivo = nombre_archivo(cot.numero, cot.cliente_nombre)
    ruta = f"{CARPETA}/{archivo}"
    contenido = json.dumps(reg, ensure_ascii=False, indent=2).encode()
    try:
        gh = _github()
        if gh:
            _, sha = _gh_leer(gh, ruta)
            _gh_escribir(gh, ruta, contenido, f"Cotización {cot.numero}", sha)
            # mismo folio con otro nombre de cliente (se editó el cliente): se reemplaza, no se duplica
            for otro in _gh_listar_archivos(gh):
                if otro.startswith(prefijo) and otro != archivo:
                    _gh_borrar(gh, f"{CARPETA}/{otro}", f"Reemplazada por {archivo}")
            _gh_actualizar_indice(gh, _resumen(reg, archivo))
        else:
            DIR_LOCAL.mkdir(parents=True, exist_ok=True)
            for otro in DIR_LOCAL.glob(f"{prefijo}*.json"):
                if otro.name != archivo:
                    otro.unlink()
            (DIR_LOCAL / archivo).write_bytes(contenido)
    except StorageError:
        raise
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code}: revisa GITHUB_TOKEN (permiso Contents: Read and write) "
                           f"y GITHUB_REPO.") from e
    except (OSError, ValueError) as e:  # sin red, disco de solo lectura, etc.
        raise StorageError(f"No se pudo guardar en el historial: {e.__class__.__name__}") from e
    listar_cotizaciones_historicas.clear()  # el historial debe mostrar la nueva cotización de inmediato
    return ruta


# ------------------------------------------------------------------ consultar
@st.cache_data(ttl=60, show_spinner=False)
def listar_cotizaciones_historicas() -> list[dict]:
    """Resumen de todas las cotizaciones guardadas (más recientes primero). Cache de 60 s."""
    try:
        gh = _github()
        if gh:
            crudo, _ = _gh_leer(gh, INDICE)
            resumenes = json.loads(crudo) if crudo else _gh_reconstruir_indice(gh)
        else:
            resumenes = [_resumen(json.loads(p.read_text(encoding="utf-8")), p.name)
                         for p in sorted(DIR_LOCAL.glob("*.json"))] if DIR_LOCAL.exists() else []
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code} al leer el historial.") from e
    except (OSError, ValueError) as e:
        raise StorageError(f"No se pudo leer el historial: {e.__class__.__name__}") from e
    return sorted(resumenes, key=lambda r: (r.get("fecha_iso", ""), r["folio"]), reverse=True)


def cargar_cotizacion(folio: str) -> dict:
    """Deserializa el JSON de una cotización por su folio. Lanza StorageError si no existe."""
    folio = folio_seguro(folio)
    try:
        gh = _github()
        if gh:
            archivos = [a for a in _gh_listar_archivos(gh) if a.startswith(f"{folio}_")]
            crudo = _gh_leer(gh, f"{CARPETA}/{archivos[0]}")[0] if archivos else None
        else:
            locales = sorted(DIR_LOCAL.glob(f"{folio}_*.json")) if DIR_LOCAL.exists() else []
            crudo = locales[0].read_bytes() if locales else None
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code} al leer la cotización {folio}.") from e
    except (OSError, ValueError) as e:
        raise StorageError(f"No se pudo leer la cotización: {e.__class__.__name__}") from e
    if not crudo:
        raise StorageError(f"No existe la cotización {folio} en el historial.")
    return json.loads(crudo)


# ================================================================== Notas de venta
# Misma mecánica que las cotizaciones, en notas_venta/{folio_nv}_{cliente_slug}.json + notas_venta/_indice.json.
def serializar_nv(nota: NotaVenta) -> dict:
    return {
        "version": VERSION_FORMATO,
        "folio": nota.folio, "fecha": nota.fecha, "fecha_iso": nota.fecha_iso,
        "referencia": nota.referencia,
        "guardado_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cliente": {"nombre": nota.cliente_nombre, "ci_ruc": nota.cliente_ci_ruc,
                    "telefono": nota.cliente_telefono, "direccion": nota.cliente_direccion},
        "items": [{"cantidad": str(l.cantidad), "unidad": l.unidad, "descripcion": l.descripcion,
                   "precio_unitario": str(l.precio_unitario), "total": str(l.total)} for l in nota.lineas],
        "subtotal": str(nota.subtotal), "iva_porcentaje": str(nota.iva_porcentaje), "iva": str(nota.iva),
        "total": str(nota.total), "anticipo": str(nota.anticipo), "saldo": str(nota.saldo),
        "metodo_pago": nota.metodo_pago, "observaciones": nota.observaciones,
    }


def a_nota_venta(reg: dict) -> NotaVenta:
    c = reg.get("cliente", {})
    return NotaVenta(
        folio=reg["folio"], fecha=reg["fecha"], fecha_iso=reg.get("fecha_iso", ""), referencia=reg.get("referencia", ""),
        cliente_nombre=c.get("nombre", ""), cliente_ci_ruc=c.get("ci_ruc", ""),
        cliente_telefono=c.get("telefono", ""), cliente_direccion=c.get("direccion", ""),
        lineas=[LineaNV(cantidad=Decimal(i["cantidad"]), unidad=i.get("unidad", "unidad"), descripcion=i["descripcion"],
                        precio_unitario=Decimal(i["precio_unitario"]), total=Decimal(i["total"]))
                for i in reg.get("items", [])],
        subtotal=Decimal(reg["subtotal"]), iva_porcentaje=Decimal(reg["iva_porcentaje"]), iva=Decimal(reg["iva"]),
        total=Decimal(reg["total"]), anticipo=Decimal(reg["anticipo"]), saldo=Decimal(reg["saldo"]),
        metodo_pago=reg.get("metodo_pago", ""), observaciones=reg.get("observaciones", ""),
    )


def _resumen_nv(reg: dict, archivo: str) -> dict:
    return {
        "folio": reg["folio"], "fecha": reg["fecha"], "fecha_iso": reg.get("fecha_iso", ""),
        "cliente": reg["cliente"].get("nombre", ""), "telefono": reg["cliente"].get("telefono", ""),
        "referencia": reg.get("referencia", ""), "total": float(Decimal(reg["total"])),
        "saldo": float(Decimal(reg["saldo"])), "archivo": archivo,
    }


def guardar_nota_venta(nota: NotaVenta) -> str:
    """Guarda la nota de venta aprobada y actualiza su índice. Devuelve la ruta. Lanza StorageError."""
    if not folio_seguro(nota.folio):
        raise StorageError("La nota de venta no tiene folio.")
    reg = serializar_nv(nota)
    archivo = nombre_archivo(nota.folio, nota.cliente_nombre)
    ruta = f"{CARPETA_NV}/{archivo}"
    contenido = json.dumps(reg, ensure_ascii=False, indent=2).encode()
    try:
        gh = _github()
        if gh:
            _, sha = _gh_leer(gh, ruta)
            _gh_escribir(gh, ruta, contenido, f"Nota de venta {nota.folio}", sha)
            _gh_actualizar_indice(gh, _resumen_nv(reg, archivo), INDICE_NV)
        else:
            DIR_LOCAL_NV.mkdir(parents=True, exist_ok=True)
            (DIR_LOCAL_NV / archivo).write_bytes(contenido)
    except StorageError:
        raise
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code}: revisa GITHUB_TOKEN (permiso Contents: Read and write) "
                           f"y GITHUB_REPO.") from e
    except (OSError, ValueError) as e:
        raise StorageError(f"No se pudo guardar la nota de venta: {e.__class__.__name__}") from e
    listar_notas_venta.clear()
    return ruta


@st.cache_data(ttl=60, show_spinner=False)
def listar_notas_venta() -> list[dict]:
    """Resumen de las notas de venta guardadas (más recientes primero). Cache de 60 s."""
    try:
        gh = _github()
        if gh:
            crudo, _ = _gh_leer(gh, INDICE_NV)
            resumenes = json.loads(crudo) if crudo else _gh_reconstruir_indice(gh, CARPETA_NV, _resumen_nv)
        else:
            resumenes = [_resumen_nv(json.loads(p.read_text(encoding="utf-8")), p.name)
                         for p in sorted(DIR_LOCAL_NV.glob("*.json"))] if DIR_LOCAL_NV.exists() else []
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code} al leer las notas de venta.") from e
    except (OSError, ValueError) as e:
        raise StorageError(f"No se pudo leer las notas de venta: {e.__class__.__name__}") from e
    return sorted(resumenes, key=lambda r: (r.get("fecha_iso", ""), r["folio"]), reverse=True)


def cargar_nota_venta(folio: str) -> dict:
    folio = folio_seguro(folio)
    try:
        gh = _github()
        if gh:
            archivos = [a for a in _gh_listar_archivos(gh, CARPETA_NV) if a.startswith(f"{folio}_")]
            crudo = _gh_leer(gh, f"{CARPETA_NV}/{archivos[0]}")[0] if archivos else None
        else:
            locales = sorted(DIR_LOCAL_NV.glob(f"{folio}_*.json")) if DIR_LOCAL_NV.exists() else []
            crudo = locales[0].read_bytes() if locales else None
    except urllib.error.HTTPError as e:
        raise StorageError(f"GitHub respondió {e.code} al leer la nota de venta {folio}.") from e
    except (OSError, ValueError) as e:
        raise StorageError(f"No se pudo leer la nota de venta: {e.__class__.__name__}") from e
    if not crudo:
        raise StorageError(f"No existe la nota de venta {folio}.")
    return json.loads(crudo)

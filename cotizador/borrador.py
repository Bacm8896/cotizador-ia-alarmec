"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Borrador editable de la cotización (estado del asistente por pasos). Lógica en Python, sin interfaz.
"""
import math
from datetime import date

from . import catalogo as cat
from .builder import construir
from .calculator import EntradaLinea, Resultado, calcular
from .config import DEFECTOS
from .schemas import Cliente, Cotizacion, ExtraccionTrabajo, ItemExtraido

CAMPOS_TEXTO = (
    "numero", "nombre", "atencion", "telefono", "direccion", "ciudad", "titulo",
    "forma_pago", "saldo", "tiempo_entrega", "garantia", "observaciones", "notas_tecnicas",
)
CONDICIONES = {  # campo -> (nombre legible, valor por defecto)
    "forma_pago": ("forma de pago", DEFECTOS.forma_pago),
    "saldo": ("saldo", DEFECTOS.saldo),
    "tiempo_entrega": ("tiempo de entrega", DEFECTOS.tiempo_entrega),
    "garantia": ("garantía", DEFECTOS.garantia),
}


def num(v) -> float | None:
    """NaN/None/'' -> None; cualquier número -> float."""
    if v is None or v == "":
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) else f


def limpiar_items(items: list[dict]) -> list[dict]:
    """Normaliza filas del editor: sin NaN y sin filas totalmente vacías."""
    out = []
    for it in items:
        fila = {
            "cantidad": num(it.get("cantidad")),
            "descripcion": str(it.get("descripcion") or "").strip(),
            "precio_unitario": num(it.get("precio_unitario")),
            "total_declarado": num(it.get("total_declarado")),
        }
        if fila["descripcion"] or fila["cantidad"] is not None or fila["precio_unitario"] is not None:
            out.append(fila)
    return out


def desde_extraccion(ext: ExtraccionTrabajo, catalogo: list[dict] | None = None) -> dict:
    """Borrador a partir de la extracción de la IA; los productos reconocidos se normalizan con el catálogo."""
    catalogo = cat.CATALOGO_BASE if catalogo is None else catalogo
    c = ext.cliente
    b = {
        "numero": "",  # lo asigna la app (sugerencia correlativa) y el usuario puede editarlo
        "nombre": c.nombre or "", "atencion": c.atencion or "", "telefono": c.telefono or "",
        "direccion": c.direccion or "", "ciudad": c.ciudad or DEFECTOS.ciudad_cliente,
        "titulo": ext.titulo_trabajo or "",
        "observaciones": "\n".join(ext.observaciones),
        "notas_tecnicas": (ext.notas_tecnicas or "").strip(),
        "items": [], "meta": {}, "guardar": {},
        "total_declarado": ext.total_declarado,
        "usados_defecto": [],
    }
    for i in ext.items:
        fila = limpiar_items([i.model_dump()])
        if not fila:
            continue
        fila = fila[0]
        oficial = cat.buscar(fila["descripcion"], catalogo)
        if oficial is not None:  # reconocido: nombre formal y precio sugerido (si la nota no dio precio)
            fila["descripcion"] = oficial["nombre_oficial"]
            if fila["precio_unitario"] is None and oficial["precio_unitario_sugerido"] is not None:
                fila["precio_unitario"] = oficial["precio_unitario_sugerido"]
        elif i.generico:  # genérico o ambiguo: se resolverá con un selector del catálogo
            b["meta"][cat.normalizar(fila["descripcion"])] = {"generico": True, "categoria": i.categoria}
        b["items"].append(fila)
    for campo, (nombre, defecto) in CONDICIONES.items():
        valor = getattr(ext, campo)
        b[campo] = valor or defecto
        if not valor:
            b["usados_defecto"].append(nombre)
    return b


def desde_registro(reg: dict) -> dict:
    """Borrador editable a partir de una cotización guardada en el historial (para modificarla)."""
    c, cond = reg.get("cliente", {}), reg.get("condiciones", {})
    return {
        "numero": reg["folio"],
        "nombre": c.get("nombre", ""), "atencion": c.get("atencion", ""), "telefono": c.get("telefono", ""),
        "direccion": c.get("direccion", ""), "ciudad": c.get("ciudad", ""),
        "titulo": reg.get("titulo_trabajo", ""),
        "forma_pago": cond.get("forma_pago", ""), "saldo": cond.get("saldo", ""),
        "tiempo_entrega": cond.get("tiempo_entrega", ""), "garantia": cond.get("garantia", ""),
        "observaciones": "\n".join(reg.get("observaciones", [])),
        "notas_tecnicas": reg.get("notas_tecnicas", ""),
        "items": [{"cantidad": float(i["cantidad"]), "descripcion": i["descripcion"],
                   "precio_unitario": float(i["precio_unitario"]), "total_declarado": None}
                  for i in reg.get("items", [])],
        "total_declarado": None, "meta": {}, "guardar": {},
        "usados_defecto": [],
    }


def a_extraccion(b: dict, con_items: bool = True) -> ExtraccionTrabajo:
    items = []
    if con_items:
        items = [
            ItemExtraido(**i)
            for i in limpiar_items(b["items"]) if i["cantidad"] is not None and i["descripcion"]
        ]
    return ExtraccionTrabajo(
        cliente=Cliente(nombre=b["nombre"], atencion=b["atencion"], telefono=b["telefono"],
                        direccion=b["direccion"], ciudad=b["ciudad"]),
        titulo_trabajo=b["titulo"] or None,
        items=items,
        observaciones=[o.strip() for o in b["observaciones"].splitlines() if o.strip()],
        forma_pago=b["forma_pago"] or None, saldo=b["saldo"] or None,
        tiempo_entrega=b["tiempo_entrega"] or None, garantia=b["garantia"] or None,
        notas_tecnicas=b["notas_tecnicas"].strip() or None,
        total_declarado=b.get("total_declarado"),
    )


def indices_sin_precio(items: list[dict]) -> list[int]:
    return [n for n, i in enumerate(items) if not i["precio_unitario"] or i["precio_unitario"] <= 0]


def faltantes(b: dict) -> list[str]:
    """Datos que suelen faltar, en lenguaje claro, para el cuadro de advertencia."""
    out = []
    if not b["nombre"].strip():
        out.append("Nombre del cliente")
    if not b["telefono"].strip():
        out.append("Teléfono del cliente")
    if not b["direccion"].strip():
        out.append("Dirección")
    if not b["items"]:
        out.append("Ningún ítem cotizado")
    for n in indices_sin_precio(b["items"]):
        out.append(f"Precio del ítem «{b['items'][n]['descripcion'] or n + 1}» (está en 0 o vacío)")
    return out


def entradas(items: list[dict]) -> list[EntradaLinea]:
    return [EntradaLinea(i["cantidad"], i["descripcion"], i["precio_unitario"], i["total_declarado"]) for i in items]


def calcular_borrador(b: dict, iva: float = 0.0) -> Resultado:
    return calcular(entradas(b["items"]), iva_porcentaje=iva, total_declarado=b.get("total_declarado"))


def cotizacion(b: dict, iva: float, fecha: date) -> tuple[Cotizacion, Resultado]:
    res = calcular_borrador(b, iva)
    cot = construir(a_extraccion(b, con_items=False), res, fecha)
    return cot.model_copy(update={"numero": b.get("numero", "").strip()}), res


# ------------------------------------------------------------------ catálogo inteligente (paso 2)
def genericos(b: dict, catalogo: list[dict]) -> list[int]:
    """Posiciones de los ítems que la IA marcó como genéricos/ambiguos y siguen sin resolverse."""
    out = []
    for n, it in enumerate(b["items"]):
        clave = cat.normalizar(it["descripcion"])
        if b["meta"].get(clave, {}).get("generico") and cat.buscar(it["descripcion"], catalogo) is None:
            out.append(n)
    return out


def categoria_de(b: dict, n: int) -> str | None:
    return b["meta"].get(cat.normalizar(b["items"][n]["descripcion"]), {}).get("categoria")


def resolver_generico(b: dict, n: int, producto: dict | None) -> None:
    """Sustituye un ítem genérico por un producto del catálogo (nombre formal y precio sugerido si no tenía).

    `producto=None` es «Otro / Personalizado»: el texto se conserva tal cual y deja de ser genérico.
    """
    it = b["items"][n]
    b["meta"].pop(cat.normalizar(it["descripcion"]), None)
    if producto is None:
        return
    it["descripcion"] = producto["nombre_oficial"]
    if not it["precio_unitario"] and producto["precio_unitario_sugerido"] is not None:
        it["precio_unitario"] = producto["precio_unitario_sugerido"]


def candidatos_catalogo(b: dict, catalogo: list[dict]) -> list[dict]:
    """Ítems que se pueden guardar en el catálogo: productos nuevos o con un precio distinto al sugerido."""
    out = []
    for n, it in enumerate(b["items"]):
        precio = it["precio_unitario"]
        if not it["descripcion"] or not precio or precio <= 0 or n in genericos(b, catalogo):
            continue
        existente = cat.buscar(it["descripcion"], catalogo)
        if existente is None:
            out.append({"n": n, "nombre": it["descripcion"], "precio": precio, "nuevo": True, "producto": None})
        elif existente["precio_unitario_sugerido"] != precio:
            out.append({"n": n, "nombre": existente["nombre_oficial"], "precio": precio, "nuevo": False,
                        "producto": existente})
    return out


def cambios_para_catalogo(lineas, guardar: dict) -> list[dict]:
    """Cambios {nombre, precio, categoria, unidad} de las líneas aprobadas cuya casilla «guardar» está marcada."""
    cambios = []
    for l in lineas:
        marca = guardar.get(cat.normalizar(l.descripcion))
        if marca:
            cambios.append({"nombre": l.descripcion, "precio": float(l.precio_unitario),
                            "categoria": marca.get("categoria"), "unidad": marca.get("unidad")})
    return cambios

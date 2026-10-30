"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Lógica de la Nota de Venta: borrador editable (desde una cotización guardada o en blanco), validación y cálculo
de subtotal, IVA, total, anticipo y saldo pendiente. Sin interfaz.
"""
from datetime import date
from decimal import Decimal

from . import catalogo as cat
from .borrador import num
from .calculator import EntradaLinea, calcular, dinero
from .renderer import fecha_larga
from .schemas import LineaNV, NotaVenta

METODOS_PAGO = ["Efectivo", "Transferencia", "Depósito", "Tarjeta de crédito / débito", "Cheque", "Otro"]
UNIDAD_DEFECTO = "unidad"


def vacio() -> dict:
    return {"referencia": "", "nombre": "", "ci_ruc": "", "telefono": "", "direccion": "", "items": [],
            "iva_pct": 0.0, "anticipo": 0.0, "metodo_pago": "", "observaciones": ""}


def limpiar_items(items: list[dict]) -> list[dict]:
    """Filas del editor sin NaN ni filas vacías. Cada ítem: cantidad, unidad, descripcion, precio_unitario."""
    out = []
    for it in items:
        fila = {"cantidad": num(it.get("cantidad")), "unidad": str(it.get("unidad") or UNIDAD_DEFECTO).strip() or UNIDAD_DEFECTO,
                "descripcion": str(it.get("descripcion") or "").strip(), "precio_unitario": num(it.get("precio_unitario"))}
        if fila["descripcion"] or fila["cantidad"] is not None or fila["precio_unitario"] is not None:
            out.append(fila)
    return out


def desde_cotizacion(reg: dict, catalogo: list[dict] | None = None) -> dict:
    """Precarga la nota con los datos del cliente y los ítems de una cotización guardada (formato simplificado)."""
    catalogo = cat.CATALOGO_BASE if catalogo is None else catalogo
    c = reg.get("cliente", {})
    b = vacio()
    b.update({"referencia": reg["folio"], "nombre": c.get("nombre", ""), "telefono": c.get("telefono", ""),
              "direccion": c.get("direccion", ""), "iva_pct": float(reg.get("iva_porcentaje", 0) or 0)})
    for i in reg.get("items", []):
        producto = cat.buscar(i["descripcion"], catalogo)
        b["items"].append({"cantidad": float(i["cantidad"]), "unidad": producto["unidad"] if producto else UNIDAD_DEFECTO,
                           "descripcion": i["descripcion"], "precio_unitario": float(i["precio_unitario"])})
    return b


def item_de_catalogo(producto: dict, cantidad: float = 1.0) -> dict:
    return {"cantidad": cantidad, "unidad": producto["unidad"], "descripcion": producto["nombre_oficial"],
            "precio_unitario": producto["precio_unitario_sugerido"]}


def calcular_nota(b: dict, fecha: date) -> tuple[NotaVenta | None, list[str]]:
    """Valida y calcula la nota. Devuelve (nota, errores); si hay errores, nota es None. El folio lo asigna la app."""
    errores = []
    if not b["nombre"].strip():
        errores.append("Falta el nombre del cliente.")
    items = limpiar_items(b["items"])
    res = calcular([EntradaLinea(i["cantidad"], i["descripcion"], i["precio_unitario"]) for i in items],
                   iva_porcentaje=b.get("iva_pct", 0) or 0)
    errores += res.errores
    anticipo = dinero(b.get("anticipo") or 0)
    if anticipo < 0:
        errores.append("El anticipo no puede ser negativo.")
    elif res.ok and anticipo > res.total:
        errores.append(f"El anticipo ($ {anticipo}) no puede ser mayor que el total ($ {res.total}).")
    if anticipo > 0 and not (b.get("metodo_pago") or "").strip():
        errores.append("Indica el método de pago del anticipo.")
    if errores:
        return None, errores
    return NotaVenta(
        fecha=fecha_larga(fecha), fecha_iso=fecha.isoformat(), referencia=b.get("referencia", ""),
        cliente_nombre=b["nombre"].strip().upper(), cliente_ci_ruc=b["ci_ruc"].strip(),
        cliente_telefono=b["telefono"].strip(), cliente_direccion=b["direccion"].strip().upper(),
        lineas=[LineaNV(cantidad=l.cantidad, unidad=i["unidad"], descripcion=l.descripcion,
                        precio_unitario=l.precio_unitario, total=l.total) for l, i in zip(res.lineas, items)],
        subtotal=res.subtotal, iva_porcentaje=res.iva_porcentaje, iva=res.iva, total=res.total,
        anticipo=anticipo, saldo=res.total - anticipo, metodo_pago=(b.get("metodo_pago") or "").strip(),
        observaciones=(b.get("observaciones") or "").strip(),
    ), []


def totales(b: dict) -> dict | None:
    """Subtotal, IVA, total y saldo (total - anticipo) para mostrar en pantalla; None si los ítems aún no son válidos."""
    res = calcular([EntradaLinea(i["cantidad"], i["descripcion"], i["precio_unitario"]) for i in limpiar_items(b["items"])],
                   iva_porcentaje=b.get("iva_pct", 0) or 0)
    if not res.ok:
        return None
    return {"subtotal": res.subtotal, "iva": res.iva, "total": res.total, "saldo": res.total - dinero(b.get("anticipo") or 0)}

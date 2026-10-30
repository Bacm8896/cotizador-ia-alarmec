"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Envío por WhatsApp sin costo: enlace wa.me (click-to-chat) con la cotización como texto.
"""
import re
from urllib.parse import quote

from .config import EMPRESA
from .renderer import money, qty
from .schemas import Cotizacion

PAIS = "593"  # Ecuador


def normalizar_telefono(telefono: str) -> str | None:
    """'098 700 3533' -> '593987003533'. None si no parece un número válido."""
    d = re.sub(r"\D", "", telefono or "")
    if d.startswith("00"):
        d = d[2:]
    if d.startswith(PAIS) and len(d) >= 11:
        return d
    if d.startswith("0") and len(d) in (9, 10):  # 09XXXXXXXX móvil, 02XXXXXXX fijo
        return PAIS + d[1:]
    if len(d) == 9 and d.startswith("9"):
        return PAIS + d
    if len(d) >= 11:  # ya trae código de otro país
        return d
    return None


def mensaje(cot: Cotizacion) -> str:
    L = [f"*COTIZACIÓN {EMPRESA.nombre}*" + (f" Nº {cot.numero}" if cot.numero else ""), f"{EMPRESA.ciudad_emision}, {cot.fecha}"]
    if cot.cliente_nombre:
        L.append(f"Cliente: {cot.cliente_nombre}")
    L.append("")
    if cot.titulo_trabajo:
        L.append(f"*{cot.titulo_trabajo}*")
    for l in cot.lineas:
        L.append(f"• {qty(l.cantidad)} {l.descripcion} x {money(l.precio_unitario)} = {money(l.total)}")
    L += [f"_{o}_" for o in cot.observaciones]
    L.append("")
    L.append(f"Subtotal: {money(cot.subtotal)}")
    if cot.iva_porcentaje > 0:
        L.append(f"IVA {qty(cot.iva_porcentaje)}%: {money(cot.iva)}")
    L.append(f"*TOTAL: {money(cot.total)}*")
    if cot.iva_porcentaje <= 0:
        L.append("_* Precios no incluyen IVA_")
    L.append("")
    if cot.notas_tecnicas:
        L.append("*Notas técnicas:*")
        L += [f"• {n.strip()}" for n in cot.notas_tecnicas.splitlines() if n.strip()]
        L.append("")
    if cot.forma_pago:
        L.append(f"Forma de pago: {cot.forma_pago}" + (f". Saldo: {cot.saldo}" if cot.saldo else ""))
    if cot.tiempo_entrega:
        L.append(f"Tiempo de entrega: {cot.tiempo_entrega}")
    if cot.garantia:
        L.append(f"Garantía: {cot.garantia}")
    L += ["", f"Atentamente,", f"{EMPRESA.firmante_nombre} - {EMPRESA.cargo}", f"Tel. {EMPRESA.telefono}"]
    return "\n".join(L)


def enlace(telefono: str, texto: str) -> str:
    """Con número válido abre el chat con el cliente; sin él, deja elegir el contacto."""
    num = normalizar_telefono(telefono)
    return f"https://wa.me/{num or ''}?text={quote(texto)}"

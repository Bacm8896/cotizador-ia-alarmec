"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Validación matemática en Python. El LLM nunca es la fuente de los totales.
"""
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from .schemas import Linea

CENTAVO = Decimal("0.01")
TOLERANCIA = Decimal("0.01")


def dinero(valor: Decimal | float | int | str) -> Decimal:
    return Decimal(str(valor)).quantize(CENTAVO, rounding=ROUND_HALF_UP)


@dataclass
class EntradaLinea:
    cantidad: float | None
    descripcion: str
    precio_unitario: float | None
    total_declarado: float | None = None


@dataclass
class Resultado:
    lineas: list[Linea] = field(default_factory=list)
    subtotal: Decimal = Decimal("0.00")
    iva_porcentaje: Decimal = Decimal("0")
    iva: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    errores: list[str] = field(default_factory=list)       # bloquean la emisión
    advertencias: list[str] = field(default_factory=list)  # informan, no bloquean

    @property
    def ok(self) -> bool:
        return not self.errores


def calcular(
    entradas: list[EntradaLinea],
    iva_porcentaje: float | Decimal = 0,
    total_declarado: float | None = None,
) -> Resultado:
    """Recalcula cada línea, subtotal, IVA y total, y compara con lo declarado."""
    res = Resultado(iva_porcentaje=Decimal(str(iva_porcentaje)))

    if not entradas:
        res.errores.append("No hay ítems en la cotización.")
        return res

    for n, e in enumerate(entradas, start=1):
        desc = (e.descripcion or "").strip()
        if not desc:
            res.errores.append(f"Ítem {n}: falta la descripción.")
        if e.cantidad is None or e.cantidad <= 0:
            res.errores.append(f"Ítem {n} ({desc or 's/d'}): la cantidad debe ser mayor que 0.")
            continue
        if e.precio_unitario is None:
            res.errores.append(f"Ítem {n} ({desc or 's/d'}): falta el precio unitario.")
            continue
        if e.precio_unitario <= 0:
            res.errores.append(f"Ítem {n} ({desc}): el precio unitario debe ser mayor que 0.")
            continue

        cantidad = Decimal(str(e.cantidad))
        pu = dinero(e.precio_unitario)
        total = dinero(cantidad * pu)
        res.lineas.append(Linea(cantidad=cantidad, descripcion=desc, precio_unitario=pu, total=total))

        if e.total_declarado is not None and abs(dinero(e.total_declarado) - total) > TOLERANCIA:
            res.advertencias.append(
                f"Ítem {n} ({desc}): el texto dice total {dinero(e.total_declarado)} "
                f"pero {cantidad} × {pu} = {total}. Se usa {total}."
            )

    res.subtotal = dinero(sum((l.total for l in res.lineas), Decimal("0")))
    res.iva = dinero(res.subtotal * res.iva_porcentaje / Decimal("100"))
    res.total = res.subtotal + res.iva

    if total_declarado is not None and abs(dinero(total_declarado) - res.total) > TOLERANCIA:
        res.advertencias.append(
            f"El texto menciona un total de {dinero(total_declarado)} "
            f"pero el total calculado es {res.total}."
        )
    return res

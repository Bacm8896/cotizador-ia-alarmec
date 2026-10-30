"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Une extracción + cálculo validado + valores por defecto de la empresa.
"""
from datetime import date

from .calculator import Resultado
from .config import DEFECTOS
from .renderer import fecha_larga
from .schemas import Cotizacion, ExtraccionTrabajo


def construir(
    ext: ExtraccionTrabajo,
    res: Resultado,
    fecha: date | None = None,
) -> Cotizacion:
    c = ext.cliente
    return Cotizacion(
        fecha=fecha_larga(fecha or date.today()),
        cliente_nombre=(c.nombre or "").upper(),
        cliente_atencion=(c.atencion or "").upper(),
        cliente_telefono=c.telefono or "",
        cliente_direccion=(c.direccion or "").upper(),
        cliente_ciudad=(c.ciudad or DEFECTOS.ciudad_cliente).upper(),
        titulo_trabajo=(ext.titulo_trabajo or "").upper(),
        lineas=res.lineas,
        observaciones=[o.upper() for o in ext.observaciones],
        subtotal=res.subtotal,
        iva_porcentaje=res.iva_porcentaje,
        iva=res.iva,
        total=res.total,
        forma_pago=(ext.forma_pago or DEFECTOS.forma_pago).upper(),
        saldo=(ext.saldo or DEFECTOS.saldo).upper(),
        tiempo_entrega=(ext.tiempo_entrega or DEFECTOS.tiempo_entrega).upper(),
        garantia=(ext.garantia or DEFECTOS.garantia).upper(),
        notas_tecnicas=(ext.notas_tecnicas or "").strip(),
    )

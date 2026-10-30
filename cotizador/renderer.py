"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Renderiza la cotización en HTML con Jinja2.
"""
import base64
from decimal import Decimal

from jinja2 import Environment, FileSystemLoader, select_autoescape

from .config import EMPRESA, LOGO_PATH, TEMPLATES_DIR
from .schemas import Cotizacion

MESES = [
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
]
MIN_FILAS = 10  # el formato del Excel reserva filas en blanco dentro de la tabla


def fecha_larga(d) -> str:
    """06 DE ABRIL DEL 2023"""
    return f"{d.day:02d} DE {MESES[d.month - 1]} DEL {d.year}"


def money(valor: Decimal) -> str:
    """1234.5 -> '1.234,50' (formato del Excel: coma decimal)."""
    s = f"{Decimal(valor):,.2f}"
    return s.replace(",", "_").replace(".", ",").replace("_", ".")


def qty(valor: Decimal) -> str:
    v = Decimal(valor)
    return str(int(v)) if v == v.to_integral_value() else money(v).rstrip("0").rstrip(",")


def _logo_data_uri() -> str:
    if not LOGO_PATH.exists():
        return ""
    return "data:image/png;base64," + base64.b64encode(LOGO_PATH.read_bytes()).decode()


_env = Environment(
    loader=FileSystemLoader(TEMPLATES_DIR),
    autoescape=select_autoescape(["html", "j2"]),
)
_env.filters["money"] = money
_env.filters["qty"] = qty


def render_html(cot: Cotizacion) -> str:
    filas_vacias = max(0, MIN_FILAS - len(cot.lineas) - len(cot.observaciones) - (1 if cot.titulo_trabajo else 0))
    return _env.get_template("cotizacion.html.j2").render(
        c=cot, e=EMPRESA, logo=_logo_data_uri(), filas_vacias=filas_vacias
    )

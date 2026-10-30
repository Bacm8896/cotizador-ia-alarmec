from decimal import Decimal
from urllib.parse import parse_qs, urlparse

import pytest

from cotizador.schemas import Cotizacion, Linea
from cotizador.whatsapp import enlace, mensaje, normalizar_telefono


@pytest.mark.parametrize("entrada,esperado", [
    ("098 700 3533", "593987003533"),
    ("0991234567", "593991234567"),
    ("991234567", "593991234567"),
    ("+593 99 123 4567", "593991234567"),
    ("00593991234567", "593991234567"),
    ("02 245 6789", "59322456789"),
    ("12345", None),
    ("", None),
])
def test_normalizar_telefono(entrada, esperado):
    assert normalizar_telefono(entrada) == esperado


def _cot():
    return Cotizacion(
        fecha="06 DE ABRIL DEL 2023", cliente_nombre="ARQ. PÉREZ", titulo_trabajo="CERCA ELECTRICA",
        lineas=[Linea(cantidad=Decimal("29"), descripcion="METROS TENDIDO", precio_unitario=Decimal("8.00"), total=Decimal("232.00"))],
        observaciones=["MATERIAL INCLUIDO"], subtotal=Decimal("232.00"), total=Decimal("232.00"),
        forma_pago="50% A LA FIRMA", saldo="CONTRAENTREGA",
    )


def test_mensaje_incluye_totales_y_formato_es():
    m = mensaje(_cot())
    assert "29 METROS TENDIDO x 8,00 = 232,00" in m and "*TOTAL: 232,00*" in m
    assert "IVA 15%" not in m


def test_enlace_con_y_sin_numero():
    u = urlparse(enlace("0987003533", "Hola & adiós\n2"))
    assert u.netloc == "wa.me" and u.path == "/593987003533"
    assert parse_qs(u.query)["text"] == ["Hola & adiós\n2"]
    assert urlparse(enlace("", "x")).path == "/"


def test_mensaje_nota_iva_y_notas_tecnicas():
    c = _cot()
    assert "Precios no incluyen IVA" in mensaje(c)  # IVA 0
    c2 = c.model_copy(update={"iva_porcentaje": Decimal(15), "iva": Decimal("34.80"), "total": Decimal("266.80"),
                              "notas_tecnicas": "Requiere internet.\nIP66."})
    m = mensaje(c2)
    assert "IVA 15%: 34,80" in m and "no incluyen IVA" not in m
    assert "*Notas técnicas:*" in m and "• Requiere internet." in m and "• IP66." in m

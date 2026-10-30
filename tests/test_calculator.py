from decimal import Decimal

from cotizador.calculator import EntradaLinea, calcular, dinero
from cotizador.renderer import money, qty


def test_caso_del_excel_modelo():
    r = calcular([EntradaLinea(29, "METROS TENDIDO CERCA ELECTRICA", 8, 232)])
    assert r.ok and r.subtotal == Decimal("232.00") and r.total == Decimal("232.00")
    assert not r.advertencias


def test_total_declarado_incorrecto_genera_advertencia_y_usa_python():
    r = calcular([EntradaLinea(29, "X", 8, 200)], total_declarado=200)
    assert r.total == Decimal("232.00")
    assert len(r.advertencias) == 2


def test_iva_y_redondeo():
    r = calcular([EntradaLinea(3, "X", 0.335)], iva_porcentaje=15)
    assert r.lineas[0].total == dinero("1.02")  # pu 0.335 -> 0.34 (HALF_UP)
    assert r.total == r.subtotal + r.iva


def test_errores_bloquean():
    r = calcular([EntradaLinea(5, "X", None), EntradaLinea(0, "Y", 1)])
    assert not r.ok and len(r.errores) == 2
    assert not calcular([]).ok


def test_precio_cero_o_negativo_es_error():
    r = calcular([EntradaLinea(1, "X", 0), EntradaLinea(1, "Y", -3)])
    assert not r.ok and len(r.errores) == 2


def test_formato_es():
    assert money(Decimal("1234.5")) == "1.234,50"
    assert money(Decimal("232")) == "232,00"
    assert qty(Decimal("29")) == "29" and qty(Decimal("2.5")) == "2,5"

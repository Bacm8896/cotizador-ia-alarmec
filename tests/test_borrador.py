from datetime import date

from cotizador import borrador as bd
from cotizador.config import DEFECTOS
from cotizador.schemas import ExtraccionTrabajo

DATOS = {
    "cliente": {"nombre": "ARQ. X", "atencion": None, "telefono": None, "direccion": None, "ciudad": None},
    "titulo_trabajo": "CERCA", "observaciones": ["MATERIAL INCLUIDO"], "forma_pago": None, "saldo": None,
    "tiempo_entrega": None, "garantia": None, "notas_tecnicas": None, "total_declarado": None,
    "items": [
        {"cantidad": 29, "descripcion": "METROS", "precio_unitario": 8, "total_declarado": None},
        {"cantidad": 1, "descripcion": "SIRENA", "precio_unitario": None, "total_declarado": None},
    ],
}


def _b():
    return bd.desde_extraccion(ExtraccionTrabajo.model_validate(DATOS))


def test_defaults_de_condiciones_y_registro_de_lo_no_mencionado():
    b = _b()
    assert b["tiempo_entrega"] == DEFECTOS.tiempo_entrega and b["forma_pago"] == DEFECTOS.forma_pago
    assert set(b["usados_defecto"]) == {"forma de pago", "saldo", "tiempo de entrega", "garantía"}
    assert b["ciudad"] == DEFECTOS.ciudad_cliente


def test_faltantes_lista_lo_que_falta():
    f = " | ".join(bd.faltantes(_b()))
    assert "Teléfono" in f and "Dirección" in f and "SIRENA" in f and "Nombre" not in f
    assert bd.faltantes({**_b(), "items": []})[-1] == "Ningún ítem cotizado"


def test_limpiar_items_quita_nan_y_filas_vacias():
    nan = float("nan")
    out = bd.limpiar_items([
        {"cantidad": nan, "descripcion": None, "precio_unitario": nan, "total_declarado": nan},
        {"cantidad": 2, "descripcion": " X ", "precio_unitario": nan},
    ])
    assert out == [{"cantidad": 2.0, "descripcion": "X", "precio_unitario": None, "total_declarado": None}]


def test_ida_y_vuelta_y_cotizacion():
    b = _b()
    b["items"][1]["precio_unitario"] = 45
    ext = bd.a_extraccion(b)
    assert [i.descripcion for i in ext.items] == ["METROS", "SIRENA"]
    cot, res = bd.cotizacion(b, iva=0, fecha=date(2023, 4, 6))
    assert res.ok and str(res.total) == "277.00" and cot.fecha == "06 DE ABRIL DEL 2023"
    assert cot.tiempo_entrega == DEFECTOS.tiempo_entrega.upper()


def test_notas_tecnicas_ida_y_vuelta():
    datos = {**DATOS, "notas_tecnicas": "Requiere internet.\nCámaras IP66."}
    b = bd.desde_extraccion(ExtraccionTrabajo.model_validate(datos))
    assert b["notas_tecnicas"] == "Requiere internet.\nCámaras IP66."
    b["notas_tecnicas"] = "  Solo una nota  "
    assert bd.a_extraccion(b).notas_tecnicas == "Solo una nota"
    b["notas_tecnicas"] = "   "
    assert bd.a_extraccion(b).notas_tecnicas is None
    cot, _ = bd.cotizacion({**b, "notas_tecnicas": "Nota X", "items": [{"cantidad": 1, "descripcion": "A", "precio_unitario": 2, "total_declarado": None}]}, 0, date(2024, 1, 1))
    assert cot.notas_tecnicas == "Nota X"

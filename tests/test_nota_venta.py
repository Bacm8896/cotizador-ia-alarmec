"""Nota de venta: folio NV independiente, lógica, PDF simplificado y persistencia (GitHub simulado, sin red)."""
import json
import urllib.error
from datetime import date
from decimal import Decimal as D

import fitz
import pytest
from fakes import GitHubFalso
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from cotizador import notaventa as nv
from cotizador import numeracion, storage
from cotizador.pdf import generar_pdf_nota_venta
from cotizador.schemas import LineaNV, NotaVenta
from cotizador.storage import StorageError

TOKEN = "ghp_token_de_prueba"


@pytest.fixture
def gh(monkeypatch):
    falso = GitHubFalso()
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GITHUB_REPO", "tu-usuario/cotizador-datos")
    monkeypatch.setattr(storage, "_pedir", falso)
    monkeypatch.setattr(numeracion, "_pedir", falso)
    storage.listar_notas_venta.clear()
    return falso


# ================================================================== folio NV independiente
def test_folio_nv_local_empieza_en_0001_y_es_correlativo():
    assert numeracion.siguiente_nv(2026) == "NV-2026-0001"
    assert numeracion.siguiente_nv(2026) == "NV-2026-0001"            # sugerir no consume
    assert numeracion.reservar_nv(2026) == "NV-2026-0001"
    assert numeracion.reservar_nv(2026) == "NV-2026-0002"
    assert numeracion.siguiente_nv(2026) == "NV-2026-0003"
    assert numeracion.reservar_nv(2027) == "NV-2027-0001"             # cada año reinicia
    assert numeracion.ARCHIVO_NV.read_text(encoding="utf-8").splitlines() == ["2026=2", "2027=1"]


def test_valor_inicial_configurable_con_nv_inicio(monkeypatch):
    monkeypatch.setenv("NV_INICIO", "NV-2026-0100")
    assert numeracion.siguiente_nv(2026) == "NV-2026-0100" and numeracion.reservar_nv(2026) == "NV-2026-0100"
    assert numeracion.reservar_nv(2026) == "NV-2026-0101"
    assert numeracion.reservar_nv(2025) == "NV-2025-0001"             # el inicio solo aplica a su año
    monkeypatch.setenv("NV_INICIO", "2026-0500")                       # también sin el prefijo NV
    assert numeracion.siguiente_nv(2026) == "NV-2026-0500"


def test_por_defecto_las_notas_de_venta_de_2026_empiezan_en_el_344(monkeypatch):
    monkeypatch.delenv("NV_INICIO", raising=False)                      # el valor por defecto real
    assert numeracion.siguiente_nv(2026) == "NV-2026-0344"
    assert numeracion.reservar_nv(2026) == "NV-2026-0344"
    assert numeracion.reservar_nv(2026) == "NV-2026-0345"
    assert numeracion.siguiente_nv(2026) == "NV-2026-0346"
    assert numeracion.reservar_nv(2027) == "NV-2027-0001"               # el 344 solo aplica a 2026
    assert numeracion.ARCHIVO_NV.read_text(encoding="utf-8").splitlines() == ["2026=345", "2027=1"]


def test_por_defecto_en_github_la_primera_nota_es_la_344(gh, monkeypatch):
    monkeypatch.delenv("NV_INICIO", raising=False)
    assert numeracion.reservar_nv(2026) == "NV-2026-0344"
    assert gh.ramas["datos"]["secuencia_nv.txt"][0].decode().strip() == "2026=344"


def test_el_contador_nv_no_comparte_numeros_con_las_cotizaciones():
    numeracion.registrar("2026-0765")
    assert numeracion.siguiente(2026) == "2026-0766" and numeracion.siguiente_nv(2026) == "NV-2026-0001"
    numeracion.reservar_nv(2026)
    assert numeracion.siguiente(2026) == "2026-0766"                   # reservar una NV no mueve las cotizaciones


def test_secuencia_nv_se_guarda_en_la_rama_datos_como_texto(gh):
    assert numeracion.reservar_nv(2026) == "NV-2026-0001"
    assert numeracion.reservar_nv(2026) == "NV-2026-0002"
    crudo, _ = gh.ramas["datos"]["secuencia_nv.txt"]
    assert crudo.decode().splitlines() == ["2026=2"]
    assert "secuencia.json" not in gh.ramas["datos"]                   # el contador de cotizaciones no se toca
    assert {t for _, _, t in gh.llamadas} == {TOKEN} and gh.ramas["main"] == {}


def test_reserva_atomica_si_otra_sesion_reserva_a_la_vez(gh):
    numeracion.reservar_nv(2026)                                       # NV-0001 existe
    original, estado = gh.__call__, {"choques": 1}

    def con_carrera(metodo, ruta, token, cuerpo=None):
        # justo antes de nuestro PUT, otra sesión reserva NV-0002 (el sha que leímos queda desactualizado)
        if metodo == "PUT" and "secuencia_nv.txt" in ruta and estado["choques"]:
            estado["choques"] -= 1
            original("PUT", ruta, token, {**cuerpo, "content": __import__("base64").b64encode(b"2026=2\n").decode(),
                                          "sha": gh.ramas["datos"]["secuencia_nv.txt"][1]})
        return original(metodo, ruta, token, cuerpo)

    storage._pedir = numeracion._pedir = con_carrera
    try:
        folio = numeracion.reservar_nv(2026)
    finally:
        storage._pedir = numeracion._pedir = gh
    assert folio == "NV-2026-0003"                                     # nunca se repite NV-2026-0002
    assert gh.ramas["datos"]["secuencia_nv.txt"][0].decode().strip() == "2026=3"


@pytest.mark.parametrize("codigo", [401, 403, 500])
def test_error_de_github_al_reservar_es_storageerror_sin_filtrar_el_token(gh, codigo):
    gh.fallar_con = codigo
    with pytest.raises(StorageError) as e:
        numeracion.reservar_nv(2026)
    assert str(codigo) in str(e.value) and TOKEN not in str(e.value)
    assert numeracion.siguiente_nv(2026) == "NV-2026-0001"            # sugerir nunca falla


# ================================================================== lógica
REG = {
    "folio": "2026-0765", "iva_porcentaje": "15",
    "cliente": {"nombre": "PEPITO PÉREZ", "telefono": "0999999999", "direccion": "QUITO NORTE", "ciudad": "QUITO"},
    "items": [{"cantidad": "4", "descripcion": "CAMARA TUBO 1080P", "precio_unitario": "85.00", "total": "340.00"},
              {"cantidad": "29", "descripcion": "METROS TENDIDO CERCA ELECTRICA", "precio_unitario": "8.00", "total": "232.00"}],
}


def test_nota_desde_cotizacion_precarga_cliente_items_unidades_e_iva():
    b = nv.desde_cotizacion(REG)
    assert (b["referencia"], b["nombre"], b["telefono"], b["direccion"], b["iva_pct"]) == (
        "2026-0765", "PEPITO PÉREZ", "0999999999", "QUITO NORTE", 15.0)
    assert [(i["cantidad"], i["unidad"], i["descripcion"], i["precio_unitario"]) for i in b["items"]] == [
        (4.0, "unidad", "CAMARA TUBO 1080P", 85.0), (29.0, "metro", "METROS TENDIDO CERCA ELECTRICA", 8.0)]


def test_nota_directa_en_blanco():
    b = nv.vacio()
    assert b["referencia"] == "" and b["items"] == [] and b["nombre"] == "" and b["anticipo"] == 0.0
    assert nv.item_de_catalogo({"unidad": "metro", "nombre_oficial": "X", "precio_unitario_sugerido": 8.0}, 5) == {
        "cantidad": 5, "unidad": "metro", "descripcion": "X", "precio_unitario": 8.0}


def _b(**cambios):
    b = nv.desde_cotizacion(REG)
    b.update({"ci_ruc": "1712345678", "anticipo": 300.0, "metodo_pago": "Transferencia", **cambios})
    return b


def test_calculo_de_la_nota_con_anticipo_y_saldo():
    nota, errores = nv.calcular_nota(_b(), date(2026, 10, 27))
    assert errores == [] and nota.referencia == "2026-0765" and nota.fecha == "27 DE OCTUBRE DEL 2026"
    assert (nota.subtotal, nota.iva, nota.total, nota.anticipo, nota.saldo) == (D("572.00"), D("85.80"), D("657.80"), D("300.00"), D("357.80"))
    assert [(l.unidad, l.total) for l in nota.lineas] == [("unidad", D("340.00")), ("metro", D("232.00"))]
    assert nv.totales(_b())["saldo"] == D("357.80")


def test_cantidades_entregadas_ajustadas_recalculan():
    b = _b()
    b["items"][0]["cantidad"] = 2.0                                    # solo se entregaron 2 cámaras
    nota, _ = nv.calcular_nota({**b, "iva_pct": 0.0, "anticipo": 0.0}, date(2026, 10, 27))
    assert nota.total == D("402.00") and nota.saldo == D("402.00")


@pytest.mark.parametrize("cambios,texto", [
    ({"nombre": " "}, "nombre del cliente"),
    ({"anticipo": 9999.0}, "no puede ser mayor"),
    ({"anticipo": -5.0}, "negativo"),
    ({"anticipo": 100.0, "metodo_pago": ""}, "método de pago"),
    ({"items": []}, "No hay ítems"),
])
def test_validaciones_de_la_nota(cambios, texto):
    nota, errores = nv.calcular_nota(_b(**cambios), date(2026, 10, 27))
    assert nota is None and any(texto in e for e in errores), errores


def test_item_sin_precio_bloquea():
    b = _b()
    b["items"][0]["precio_unitario"] = None
    assert nv.calcular_nota(b, date(2026, 10, 27))[0] is None and nv.totales(b) is None


# ================================================================== PDF simplificado
def _nota(referencia="2026-0765", iva=True, n_items=2, **extra):
    lineas = [LineaNV(cantidad=D(i + 1), unidad="unidad" if i % 2 == 0 else "metro", descripcion=f"PRODUCTO {i + 1}",
                      precio_unitario=D("10.00"), total=D(i + 1) * D("10.00")) for i in range(n_items)]
    sub = sum(l.total for l in lineas)
    imp = (sub * D("0.15")).quantize(D("0.01")) if iva else D("0.00")
    return NotaVenta(folio="NV-2026-0001", fecha="27 DE OCTUBRE DEL 2026", fecha_iso="2026-10-27", referencia=referencia,
                     cliente_nombre="PEPITO PÉREZ", cliente_ci_ruc="1712345678", cliente_telefono="0999999999",
                     cliente_direccion="QUITO NORTE", lineas=lineas, subtotal=sub, iva_porcentaje=D(15) if iva else D(0),
                     iva=imp, total=sub + imp, anticipo=D("20.00"), saldo=sub + imp - D("20.00"),
                     metodo_pago="Transferencia", **extra)


def _texto(nota):
    doc = fitz.open(stream=generar_pdf_nota_venta(nota), filetype="pdf")
    return doc, "\n".join(p.get_text() for p in doc)


def test_pdf_nota_de_venta_contenido_completo():
    doc, t = _texto(_nota())
    assert len(doc) == 1 and doc[0].parent.is_pdf
    for esperado in ("NOTA DE VENTA", "Nº NV-2026-0001", "Quito, 27 de Octubre del 2026", "CLIENTE: PEPITO PÉREZ",
                     "C.I. / RUC: 1712345678", "TELÉFONO: 0999999999", "DIRECCIÓN: QUITO NORTE",
                     "Referencia: Cotización N° 2026-0765",
                     "CANT.", "UNIDAD", "DESCRIPCIÓN DEL PRODUCTO / SERVICIO", "P. UNITARIO ($)", "TOTAL ($)",
                     "SUBTOTAL:", "IVA 15%:", "TOTAL:", "ANTICIPO / ABONO:", "SALDO PENDIENTE:", "MÉTODO DE PAGO: Transferencia",
                     "Entregado por: ALARMEC", "(Firma y Sello)", "Recibí Conforme: Cliente", "(Firma y C.I.)",
                     "ALARMEC", "Tel: 098 700 3533"):
        assert esperado in t, esperado
    assert "�" not in t


def test_pdf_sin_referencia_en_nota_directa_y_sin_iva_si_no_aplica():
    _, t = _texto(_nota(referencia="", iva=False))
    assert "Referencia" not in t and "IVA " not in t.replace("incluyen IVA", "")
    assert "SUBTOTAL:" in t and "SALDO PENDIENTE:" in t


def test_pdf_es_simplificado_sin_fichas_ni_justificaciones():
    _, t = _texto(_nota(observaciones="Entrega parcial"))
    for ausente in ("CONDICIONES COMERCIALES", "NOTAS Y REQUISITOS", "Garantía", "GARANTÍA", "ATENTAMENTE", "TIEMPO DE ENTREGA"):
        assert ausente not in t
    assert "Entrega parcial" in t


def test_pdf_muchos_items_paginan_con_las_firmas_juntas():
    doc, _ = _texto(_nota(n_items=40))
    assert len(doc) >= 2
    ultimas = doc[-1].get_text()
    assert "Entregado por" in ultimas and "Recibí Conforme" in ultimas and "SALDO PENDIENTE" in ultimas


@pytest.mark.parametrize("n", [2, 40])
def test_pdf_nota_respeta_margenes_de_20mm(n):
    margen = 20 * mm - 3
    for p in _texto(_nota(n_items=n))[0]:
        for x0, y0, x1, y1, *_ in p.get_text("blocks"):
            if y0 > A4[1] - 20 * mm:
                continue
            assert x0 >= margen and x1 <= A4[0] - margen and y0 >= margen


# ================================================================== persistencia
def test_guardar_nota_venta_en_la_rama_datos_con_indice(gh):
    nota = _nota()
    ruta = storage.guardar_nota_venta(nota)
    assert ruta == "notas_venta/NV-2026-0001_pepito_perez.json"
    reg = json.loads(gh.ramas["datos"][ruta][0])
    assert (reg["folio"], reg["referencia"], reg["total"], reg["anticipo"], reg["saldo"]) == (
        "NV-2026-0001", "2026-0765", "34.50", "20.00", "14.50")
    assert reg["cliente"] == {"nombre": "PEPITO PÉREZ", "ci_ruc": "1712345678", "telefono": "0999999999", "direccion": "QUITO NORTE"}
    indice = json.loads(gh.ramas["datos"]["notas_venta/_indice.json"][0])
    assert indice == [{"folio": "NV-2026-0001", "fecha": "27 DE OCTUBRE DEL 2026", "fecha_iso": "2026-10-27",
                       "cliente": "PEPITO PÉREZ", "telefono": "0999999999", "referencia": "2026-0765",
                       "total": float(nota.total), "saldo": float(nota.saldo), "archivo": "NV-2026-0001_pepito_perez.json"}]
    assert "cotizaciones/_indice.json" not in gh.ramas["datos"]        # carpeta y índice propios
    assert {t for _, _, t in gh.llamadas} == {TOKEN} and gh.ramas["main"] == {}


def test_listar_y_cargar_notas_de_venta(gh):
    storage.guardar_nota_venta(_nota())
    storage.guardar_nota_venta(_nota(referencia="").model_copy(update={"folio": "NV-2026-0002", "cliente_nombre": "JUAN LOOR",
                                                                      "fecha_iso": "2026-10-28"}))
    storage.listar_notas_venta.clear()
    gh.llamadas.clear()
    filas = storage.listar_notas_venta()
    assert [f["folio"] for f in filas] == ["NV-2026-0002", "NV-2026-0001"] and len(gh.llamadas) == 1
    assert storage.a_nota_venta(storage.cargar_nota_venta("NV-2026-0001")) == _nota()
    with pytest.raises(StorageError, match="No existe"):
        storage.cargar_nota_venta("NV-2026-9999")


def test_nota_venta_sin_github_se_guarda_en_disco_local():
    assert storage.listar_notas_venta() == []
    storage.guardar_nota_venta(_nota())
    assert (storage.DIR_LOCAL_NV / "NV-2026-0001_pepito_perez.json").exists()
    assert storage.listar_notas_venta()[0]["folio"] == "NV-2026-0001"
    assert storage.a_nota_venta(storage.cargar_nota_venta("NV-2026-0001")) == _nota()


@pytest.mark.parametrize("codigo", [401, 403])
def test_error_al_guardar_nota_de_venta_es_storageerror(gh, codigo):
    gh.fallar_con = codigo
    with pytest.raises(StorageError) as e:
        storage.guardar_nota_venta(_nota())
    assert str(codigo) in str(e.value) and TOKEN not in str(e.value)
    with pytest.raises(StorageError, match="folio"):
        storage.guardar_nota_venta(_nota().model_copy(update={"folio": ""}))

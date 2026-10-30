from decimal import Decimal as D

import fitz
import pytest
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm

from cotizador.pdf import generar_pdf
from cotizador.schemas import Cotizacion, Linea

BASE = dict(
    numero="2026-0007", fecha="06 DE ABRIL DEL 2023", cliente_nombre="ARQ. JUAN PÉREZ MUÑOZ", cliente_telefono="0991234567",
    cliente_direccion="LA FLORESTA", cliente_ciudad="QUITO-ECUADOR", titulo_trabajo="CERCA ELECTRICA",
    observaciones=["MATERIAL Y MANO DE OBRA INCLUIDOS"], forma_pago="50% A LA FIRMA DEL CONTRATO",
    saldo="CONTRAENTREGA", tiempo_entrega="DE 2 A 4 DIAS LABORABLES", garantia="UN AÑO EN EQUIPO E INSTALACIÓN",
)


def _cot(n_items=1, iva=False):
    lineas = [Linea(cantidad=D(i + 1), descripcion=f"ITEM {i + 1} DE PRUEBA", precio_unitario=D("8.00"),
                    total=D(i + 1) * D("8.00")) for i in range(n_items)]
    sub = sum(l.total for l in lineas)
    imp = (sub * D("0.15")).quantize(D("0.01")) if iva else D("0")
    return Cotizacion(**BASE, lineas=lineas, subtotal=sub, iva_porcentaje=D(15) if iva else D(0), iva=imp, total=sub + imp)


def _paginas(pdf: bytes):
    return fitz.open(stream=pdf, filetype="pdf")


def test_pdf_valido_una_pagina_con_los_datos():
    pdf = generar_pdf(_cot(1))
    assert pdf[:4] == b"%PDF"
    doc = _paginas(pdf)
    assert len(doc) == 1
    texto = doc[0].get_text()
    for esperado in ("COTIZACIÓN Nº: 2026-0007", "Quito, 06 de Abril del 2023", "CLIENTE: ARQ. JUAN PÉREZ MUÑOZ",
                     "TELÉFONO: 0991234567", "CANT.", "PRECIO UNIT.", "PRECIO TOTAL", "ITEM 1 DE PRUEBA", "$ 8,00",
                     "SUBTOTAL:", "CONDICIONES COMERCIALES", "ATENTAMENTE,", "Sr. Luis Carvajal V.", "ASESOR EN SEGURIDAD",
                     "Seguridad Electrónica Integral & Automatización",
                     "CCTV • Alarmas • Cercas Eléctricas • Motores de Garaje • Domótica",
                     "Dirección: Guillermo Cornejo N60-53 y Flavio Alfaro | Quito, Ecuador",
                     "Tel: 098 700 3533 | contacto@alarmec.com"):
        assert esperado in texto, esperado
    assert "* Precios no incluyen IVA" in texto and "IVA 15%" not in texto
    assert "�" not in texto and "□" not in texto  # sin caracteres rotos


def test_pdf_con_iva():
    texto = _paginas(generar_pdf(_cot(3, iva=True)))[0].get_text()
    assert "SUBTOTAL:" in texto and "IVA 15%:" in texto and "TOTAL:" in texto and "no incluyen IVA" not in texto


def test_sin_filas_vacias_el_alto_depende_de_los_items():
    # 1 y 8 ítems caben en una hoja; la tabla solo tiene filas de ítems (sin relleno tipo talonario)
    for n in (1, 8):
        assert len(_paginas(generar_pdf(_cot(n)))) == 1


def test_muchos_items_paginan_y_repiten_encabezado():
    doc = _paginas(generar_pdf(_cot(45)))
    assert len(doc) >= 2
    assert "DESCRIPCIÓN" in doc[0].get_text() and "DESCRIPCIÓN" in doc[1].get_text()
    assert "Sr. Luis Carvajal" in doc[-1].get_text() and "CONDICIONES COMERCIALES" in doc[-1].get_text()


def test_condiciones_y_firma_no_se_separan():
    for n in range(1, 16):
        paginas = [p.get_text() for p in _paginas(generar_pdf(_cot(n, iva=True)))]
        donde = [("CONDICIONES COMERCIALES" in t, "Sr. Luis Carvajal" in t) for t in paginas]
        assert sum(c for c, _ in donde) == 1 and any(c and f for c, f in donde), n


@pytest.mark.parametrize("n", [1, 8, 45])
def test_margenes_minimos_de_20mm(n):
    margen = 20 * mm - 3  # tolerancia de 1 mm por el ascendente de la tipografía
    for p in _paginas(generar_pdf(_cot(n))):
        for x0, y0, x1, y1, txt, *_ in p.get_text("blocks"):
            if y0 > A4[1] - 20 * mm:  # pie de página (número de página), fuera del marco a propósito
                continue
            assert x0 >= margen and x1 <= A4[0] - margen, txt
            assert y0 >= margen, txt
        for img in p.get_image_info():
            x0, y0, x1, y1 = img["bbox"]
            assert x0 >= margen and y0 >= margen and x1 <= A4[0] - margen


# ------------------------------------------------------------------ notas técnicas
NOTAS = "Se requiere internet estable.\nCámaras IP66 resistentes al agua."


def test_notas_tecnicas_se_renderizan_solo_si_hay_texto():
    con = _paginas(generar_pdf(_cot(2).model_copy(update={"notas_tecnicas": NOTAS})))[0].get_text()
    assert "NOTAS Y REQUISITOS TÉCNICOS" in con and "Se requiere internet estable." in con and "IP66" in con
    sin = _paginas(generar_pdf(_cot(2)))[0].get_text()
    assert "NOTAS Y REQUISITOS" not in sin


def test_sin_notas_no_deja_hueco():
    from cotizador import pdf as P
    con = P._story(_cot(2).model_copy(update={"notas_tecnicas": NOTAS}))
    sin = P._story(_cot(2))
    assert len(con) == len(sin) + 2  # separador + sección; nada más


# ------------------------------------------------------------------ logo
def _png(tmp_path, ancho, alto, nombre="logo.png"):
    from PIL import Image
    ruta = tmp_path / nombre
    Image.new("RGB", (ancho, alto), (200, 16, 46)).save(ruta)
    return ruta


@pytest.mark.parametrize("ancho,alto", [(290, 175), (1000, 200), (200, 600), (4000, 3000)])
def test_logo_mantiene_proporcion_y_cabe_en_su_caja(tmp_path, monkeypatch, ancho, alto):
    from cotizador import pdf as P
    ruta = _png(tmp_path, ancho, alto)
    monkeypatch.setattr(P, "ruta_logo", lambda: ruta)
    P._logo_png.cache_clear()
    logo = P._logo()
    assert logo.drawWidth <= P.LOGO_MAX_W + 0.01 and logo.drawHeight <= P.LOGO_MAX_H + 0.01
    assert abs(logo.drawWidth / logo.drawHeight - ancho / alto) / (ancho / alto) < 0.02
    assert len(_paginas(generar_pdf(_cot(2)))) == 1


def test_logo_grande_se_reduce_y_reemplazo_se_detecta(tmp_path, monkeypatch):
    from cotizador import pdf as P
    ruta = _png(tmp_path, 4000, 3000)
    datos, w, h = P._logo_png(str(ruta), ruta.stat().st_mtime_ns)
    assert max(w, h) <= P.LOGO_MAX_PX
    _png(tmp_path, 300, 100)  # el usuario reemplaza el archivo
    import os
    os.utime(ruta, ns=(ruta.stat().st_atime_ns, ruta.stat().st_mtime_ns + 10**9))
    assert P._logo_png(str(ruta), ruta.stat().st_mtime_ns)[1:] == (300, 100)


def test_sin_logo_el_pdf_se_genera(monkeypatch):
    from cotizador import pdf as P
    monkeypatch.setattr(P, "ruta_logo", lambda: None)
    assert _paginas(generar_pdf(_cot(1)))[0].get_text().startswith("ALARMEC")


def test_correo_por_defecto_y_se_puede_quitar_o_cambiar(monkeypatch):
    from dataclasses import replace
    from cotizador import pdf as P
    assert "Tel: 098 700 3533 | contacto@alarmec.com" in _paginas(generar_pdf(_cot(1)))[0].get_text()
    monkeypatch.setattr(P, "EMPRESA", replace(P.EMPRESA, correo="ventas@ejemplo.com"))
    assert "Tel: 098 700 3533 | ventas@ejemplo.com" in _paginas(generar_pdf(_cot(1)))[0].get_text()
    monkeypatch.setattr(P, "EMPRESA", replace(P.EMPRESA, correo=""))
    assert "Tel: 098 700 3533 |" not in _paginas(generar_pdf(_cot(1)))[0].get_text()


def test_bloque_de_datos_dos_columnas_telefono_a_la_altura_de_la_ciudad():
    doc = _paginas(generar_pdf(_cot(1)))[0]
    def caja(texto):
        return doc.search_for(texto)[0]
    num, fecha = caja("COTIZACIÓN Nº"), caja("Quito, 06 de Abril")
    cli, dire, ciudad, tel = caja("CLIENTE:"), caja("DIRECCIÓN:"), caja("CIUDAD:"), caja("TELÉFONO:")
    assert abs(ciudad.y0 - tel.y0) < 3 and abs(cli.y0 - num.y0) < 3 and abs(dire.y0 - fecha.y0) < 3
    assert num.x0 > doc.rect.width / 2 and tel.x0 > doc.rect.width / 2 and cli.x0 < doc.rect.width / 3


def test_logo_es_transparente_y_no_trae_fondo_cuadrado():
    from PIL import Image
    from cotizador.config import ruta_logo
    img = Image.open(ruta_logo())
    assert img.mode == "RGBA"
    esquinas = [img.getpixel(p)[3] for p in ((2, 2), (img.width - 3, 2), (2, img.height - 3), (img.width - 3, img.height - 3))]
    assert max(esquinas) < 30  # las esquinas son transparentes: el logo se integra al papel


def test_logo_es_solo_el_isotipo_sin_el_texto_inferior():
    from PIL import Image
    from cotizador.config import ruta_logo
    img = Image.open(ruta_logo())
    assert 1.4 < img.width / img.height < 2.1          # camara + ondas; con el texto debajo seria casi cuadrado
    # bien centrado: el dibujo opaco ocupa casi todo el recorte, con márgenes parejos
    x0, y0, x1, y1 = img.getchannel("A").point(lambda a: 255 if a > 40 else 0).getbbox()
    assert abs(x0 - (img.width - x1)) < 0.06 * img.width and abs(y0 - (img.height - y1)) < 0.06 * img.height
    assert (x1 - x0) > 0.9 * img.width and (y1 - y0) > 0.9 * img.height

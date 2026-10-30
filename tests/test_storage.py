"""Historial en la rama «datos» de GitHub, con una API de GitHub simulada en memoria (sin red)."""
import json
from decimal import Decimal as D

import pytest

from fakes import GitHubFalso

from cotizador import numeracion, storage
from cotizador.schemas import Cotizacion, Linea
from cotizador.storage import StorageError

TOKEN = "ghp_token_de_prueba"


@pytest.fixture
def gh(monkeypatch):
    falso = GitHubFalso()
    monkeypatch.setenv("GITHUB_TOKEN", TOKEN)
    monkeypatch.setenv("GITHUB_REPO", "tu-usuario/cotizador-datos")
    monkeypatch.setattr(storage, "_pedir", falso)
    monkeypatch.setattr(numeracion, "_pedir", falso)
    storage.listar_cotizaciones_historicas.clear()
    return falso


def _cot(folio="2026-0765", cliente="PEPITO PÉREZ", total="580.00", fecha="19 DE OCTUBRE DEL 2026"):
    return Cotizacion(
        numero=folio, fecha=fecha, cliente_nombre=cliente, cliente_telefono="0999999999",
        cliente_direccion="QUITO NORTE", cliente_ciudad="QUITO-ECUADOR", titulo_trabajo="CCTV",
        lineas=[Linea(cantidad=D("4"), descripcion="CÁMARA TUBO", precio_unitario=D("85.00"), total=D("340.00")),
                Linea(cantidad=D("2"), descripcion="DVR", precio_unitario=D("120.00"), total=D(total) - D("340.00"))],
        observaciones=["MATERIAL INCLUIDO"], subtotal=D(total), iva_porcentaje=D("0"), iva=D("0.00"), total=D(total),
        forma_pago="50% A LA FIRMA", saldo="CONTRAENTREGA", tiempo_entrega="2 A 4 DIAS", garantia="UN AÑO",
        notas_tecnicas="Requiere internet de 50 Mbps.",
    )


# ------------------------------------------------------------------ formato
def test_slug_y_nombre_de_archivo():
    assert storage.slug("ARQ. Juan Pérez Muñoz") == "arq_juan_perez_munoz"
    assert storage.slug("   ") == "cliente"
    assert storage.nombre_archivo("2026-0765", "Pepito Pérez") == "2026-0765_pepito_perez.json"
    assert "/" not in storage.nombre_archivo("../../x/2026 07", "A")  # el folio no puede escapar de la carpeta


def test_serializar_incluye_todo_y_se_reconstruye_igual():
    cot = _cot()
    reg = storage.serializar(cot, "2026-10-19")
    json.dumps(reg)  # JSON puro
    assert {"folio", "fecha", "cliente", "items", "subtotal", "iva_porcentaje", "iva", "total",
            "notas_tecnicas", "condiciones", "observaciones"} <= reg.keys()
    assert reg["folio"] == "2026-0765" and reg["cliente"]["telefono"] == "0999999999" and reg["fecha_iso"] == "2026-10-19"
    assert reg["condiciones"]["forma_pago"] == "50% A LA FIRMA" and reg["items"][0]["precio_unitario"] == "85.00"
    assert storage.a_cotizacion(reg) == cot


# ------------------------------------------------------------------ guardar
def test_guardar_sube_el_json_a_la_rama_datos_con_el_token(gh):
    ruta = storage.guardar_cotizacion(_cot(), "2026-10-19")
    assert ruta == "cotizaciones/2026-0765_pepito_perez.json"
    assert "datos" in gh.ramas and "main" in gh.ramas  # la rama de datos se creó a partir de la principal
    contenido = json.loads(gh.ramas["datos"][ruta][0])
    assert contenido["folio"] == "2026-0765" and contenido["total"] == "580.00"
    assert json.loads(gh.ramas["datos"]["cotizaciones/_indice.json"][0])[0]["cliente"] == "PEPITO PÉREZ"
    assert {t for _, _, t in gh.llamadas} == {TOKEN}
    assert gh.ramas["main"] == {}  # nada se escribió en la rama principal


def test_guardar_de_nuevo_actualiza_sin_duplicar(gh):
    storage.guardar_cotizacion(_cot(total="580.00"), "2026-10-19")
    storage.guardar_cotizacion(_cot(total="600.00"), "2026-10-19")
    datos = gh.ramas["datos"]
    assert [r for r in datos if r.endswith("_pepito_perez.json")] == ["cotizaciones/2026-0765_pepito_perez.json"]
    indice = json.loads(datos["cotizaciones/_indice.json"][0])
    assert len(indice) == 1 and indice[0]["total"] == 600.0


def test_mismo_folio_con_otro_cliente_reemplaza_el_archivo_anterior(gh):
    storage.guardar_cotizacion(_cot(cliente="PEPITO PÉREZ"), "2026-10-19")
    storage.guardar_cotizacion(_cot(cliente="JUAN LOOR"), "2026-10-19")
    archivos = [r for r in gh.ramas["datos"] if r.endswith(".json") and "_indice" not in r]
    assert archivos == ["cotizaciones/2026-0765_juan_loor.json"]
    assert [r["cliente"] for r in storage.listar_cotizaciones_historicas()] == ["JUAN LOOR"]


@pytest.mark.parametrize("codigo", [401, 403, 500])
def test_error_de_github_es_storageerror_y_no_filtra_el_token(gh, codigo):
    gh.fallar_con = codigo
    with pytest.raises(StorageError) as e:
        storage.guardar_cotizacion(_cot(), "2026-10-19")
    assert str(codigo) in str(e.value) and TOKEN not in str(e.value)


def test_sin_folio_no_se_guarda(gh):
    with pytest.raises(StorageError, match="folio"):
        storage.guardar_cotizacion(_cot(folio="  "), "2026-10-19")
    assert gh.llamadas == []


# ------------------------------------------------------------------ consultar
def test_listar_usa_una_sola_llamada_ordena_y_cachea(gh):
    storage.guardar_cotizacion(_cot("2026-0765", "PEPITO PÉREZ", "580.00"), "2026-10-19")
    storage.guardar_cotizacion(_cot("2026-0766", "JUAN LOOR", "700.00"), "2026-10-21")
    storage.listar_cotizaciones_historicas.clear()
    gh.llamadas.clear()
    filas = storage.listar_cotizaciones_historicas()
    assert len(gh.llamadas) == 1 and gh.llamadas[0][0] == "GET"          # índice: una sola llamada
    assert [f["folio"] for f in filas] == ["2026-0766", "2026-0765"]     # más reciente primero
    assert filas[0] == {"folio": "2026-0766", "fecha": "19 DE OCTUBRE DEL 2026", "fecha_iso": "2026-10-21",
                        "cliente": "JUAN LOOR", "telefono": "0999999999", "total": 700.0,
                        "archivo": "2026-0766_juan_loor.json"}
    storage.listar_cotizaciones_historicas()
    assert len(gh.llamadas) == 1                                          # segunda lectura: desde la caché (ttl 60 s)


def test_guardar_invalida_la_cache_del_historial(gh):
    assert storage.listar_cotizaciones_historicas() == []
    storage.guardar_cotizacion(_cot(), "2026-10-19")
    assert [f["folio"] for f in storage.listar_cotizaciones_historicas()] == ["2026-0765"]


def test_listar_reconstruye_el_indice_si_no_existe(gh):
    gh.ramas["datos"] = {}
    for folio, cli in (("2026-0001", "A"), ("2026-0002", "B")):
        reg = storage.serializar(_cot(folio, cli), "2026-10-19")
        gh.ramas["datos"][f"cotizaciones/{folio}_{cli.lower()}.json"] = (json.dumps(reg).encode(), "s")
    assert {f["folio"] for f in storage.listar_cotizaciones_historicas()} == {"2026-0001", "2026-0002"}


def test_cargar_cotizacion_deserializa_el_json_exacto(gh):
    cot = _cot()
    storage.guardar_cotizacion(cot, "2026-10-19")
    reg = storage.cargar_cotizacion("2026-0765")
    assert storage.a_cotizacion(reg) == cot and reg["fecha_iso"] == "2026-10-19"
    with pytest.raises(StorageError, match="No existe"):
        storage.cargar_cotizacion("2026-9999")


# ------------------------------------------------------------------ sin GitHub (uso local)
def test_sin_github_usa_el_disco_local():
    storage.listar_cotizaciones_historicas.clear()
    assert storage.listar_cotizaciones_historicas() == []
    ruta = storage.guardar_cotizacion(_cot(), "2026-10-19")
    assert (storage.DIR_LOCAL / "2026-0765_pepito_perez.json").exists() and ruta.startswith("cotizaciones/")
    assert storage.listar_cotizaciones_historicas()[0]["total"] == 580.0
    assert storage.a_cotizacion(storage.cargar_cotizacion("2026-0765")) == _cot()
    storage.guardar_cotizacion(_cot(cliente="JUAN LOOR"), "2026-10-19")
    assert [p.name for p in storage.DIR_LOCAL.glob("*.json")] == ["2026-0765_juan_loor.json"]

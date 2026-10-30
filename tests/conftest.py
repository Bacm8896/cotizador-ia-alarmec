"""Ningún test debe consumir la API real de Gemini."""
from unittest import mock

import pytest


@pytest.fixture(autouse=True)
def sin_gemini_real(monkeypatch, tmp_path):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    for var in ("GITHUB_TOKEN", "GITHUB_REPO"):  # ningún test toca GitHub: se simula o se usa disco temporal
        monkeypatch.delenv(var, raising=False)
    from cotizador import catalogo, numeracion, storage
    monkeypatch.setattr(numeracion, "ARCHIVO", tmp_path / "data" / "secuencia.json")
    monkeypatch.setattr(storage, "DIR_LOCAL", tmp_path / "data" / "cotizaciones")
    monkeypatch.setattr(storage, "DIR_LOCAL_NV", tmp_path / "data" / "notas_venta")
    monkeypatch.setattr(numeracion, "ARCHIVO_NV", tmp_path / "data" / "secuencia_nv.txt")
    monkeypatch.setenv("NV_INICIO", "NV-2026-0001")  # base de los tests; el valor por defecto real (0344) tiene su propio test
    monkeypatch.setattr(catalogo, "ARCHIVO_LOCAL", tmp_path / "data" / "catalogo.json")
    storage.listar_cotizaciones_historicas.clear()
    storage.listar_notas_venta.clear()
    catalogo.obtener_catalogo.clear()

    def sin_red(*a, **k):
        raise AssertionError("Un test intentó abrir una conexión de red real.")

    monkeypatch.setattr("urllib.request.urlopen", sin_red)
    monkeypatch.delenv("NUMERACION_INICIO", raising=False)

    def prohibido(*a, **k):
        raise AssertionError("Un test intentó crear un cliente real de Gemini; usa un mock.")

    with mock.patch("cotizador.extractor.genai.Client", side_effect=prohibido):
        with mock.patch("groq.Groq", side_effect=prohibido):
            yield

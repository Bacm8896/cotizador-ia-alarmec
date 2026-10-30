"""Proveedor Groq (Whisper + Llama JSON) con clientes simulados: nunca se llama a la API real."""
import json
from types import SimpleNamespace
from unittest import mock

import groq
import httpx
import pytest

from cotizador import extractor as ex
from cotizador.extractor import Audio, ExtraccionError, ajustar, extraer, proveedor
from cotizador.schemas import ExtraccionTrabajo

COMPLETO = {
    "cliente": {"nombre": "ING. PEREZ", "atencion": None, "telefono": "0999", "direccion": None, "ciudad": None},
    "titulo_trabajo": "CAMARAS", "observaciones": [], "forma_pago": None, "saldo": None, "tiempo_entrega": None,
    "garantia": None, "notas_tecnicas": "Requiere internet.", "total_declarado": None,
    "items": [{"cantidad": 2, "descripcion": "CAMARA DOMO", "precio_unitario": 50, "total_declarado": None}],
}


def _cliente(contenido=None, transcripcion="dos cámaras a cincuenta"):
    texto = contenido if isinstance(contenido, str) else json.dumps(COMPLETO if contenido is None else contenido)
    respuesta = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=texto))])
    return SimpleNamespace(
        audio=SimpleNamespace(transcriptions=SimpleNamespace(create=mock.Mock(return_value=SimpleNamespace(text=transcripcion)))),
        chat=SimpleNamespace(completions=SimpleNamespace(create=mock.Mock(return_value=respuesta))),
    )


@pytest.fixture
def con_groq(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "gsk_falsa")


def test_proveedor_segun_la_clave(monkeypatch):
    assert proveedor() == "gemini"
    monkeypatch.setenv("GROQ_API_KEY", "gsk_falsa")
    assert proveedor() == "groq"
    assert "whisper-large-v3-turbo" in ex.descripcion_proveedor() and "openai/gpt-oss-120b" in ex.descripcion_proveedor()


def test_solo_texto_una_llamada_de_chat_en_modo_json_sin_transcribir(con_groq):
    c = _cliente()
    r = extraer("dos domos a 50", client=c)
    assert isinstance(r, ExtraccionTrabajo) and r.items[0].precio_unitario == 50 and r.notas_tecnicas
    c.audio.transcriptions.create.assert_not_called()
    c.chat.completions.create.assert_called_once()
    kw = c.chat.completions.create.call_args.kwargs
    assert kw["model"] == "openai/gpt-oss-120b" and kw["response_format"] == {"type": "json_object"}
    assert kw["temperature"] == 0
    sistema, usuario = (m["content"] for m in kw["messages"])
    assert "JSON" in sistema and "notas_tecnicas" in sistema and "METROS TENDIDO CERCA ELECTRICA" in sistema
    assert "dos domos a 50" in usuario


def test_audio_se_transcribe_con_whisper_y_luego_una_sola_extraccion(con_groq):
    c = _cliente()
    extraer("y entrega en 3 días", [Audio(b"RIFF", "audio/wav"), ], client=c)
    c.audio.transcriptions.create.assert_called_once()
    kw = c.audio.transcriptions.create.call_args.kwargs
    assert kw["model"] == "whisper-large-v3-turbo" and kw["language"] == "es" and kw["file"] == ("nota.wav", b"RIFF")
    c.chat.completions.create.assert_called_once()
    usuario = c.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "dos cámaras a cincuenta" in usuario and "y entrega en 3 días" in usuario


def test_json_incompleto_de_llama_se_completa_y_valida(con_groq):
    c = _cliente({"cliente": {"nombre": "A"}, "items": [{"cantidad": 1, "descripcion": "DVR"}]})
    r = extraer("un dvr", client=c)
    assert r.cliente.telefono is None and r.observaciones == [] and r.items[0].precio_unitario is None
    assert c.chat.completions.create.call_count == 1  # no reintenta


@pytest.mark.parametrize("basura", ["no es json", "[1, 2]", json.dumps({"items": "mal"})])
def test_respuesta_invalida_da_error_claro_sin_reintentar(con_groq, basura):
    c = _cliente(basura)
    with pytest.raises(ExtraccionError, match="JSON"):
        extraer("algo", client=c)
    assert c.chat.completions.create.call_count == 1


def test_limite_de_groq_es_un_error_amable(con_groq):
    c = _cliente()
    resp = httpx.Response(429, request=httpx.Request("POST", "http://x"))
    c.chat.completions.create.side_effect = groq.RateLimitError("x", response=resp, body=None)
    with pytest.raises(ExtraccionError, match="límite de Groq"):
        extraer("algo", client=c)
    assert c.chat.completions.create.call_count == 1


def test_ajustar_con_groq_envia_el_json_actual(con_groq):
    c = _cliente()
    actual = ExtraccionTrabajo.model_validate(COMPLETO)
    ajustar(actual, "agrega una sirena a 45", client=c)
    c.chat.completions.create.assert_called_once()
    usuario = c.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert actual.model_dump_json() in usuario and "agrega una sirena a 45" in usuario
    with pytest.raises(ExtraccionError):
        ajustar(actual, " ", client=c)


def test_sin_texto_ni_audio_no_llama_a_nadie(con_groq):
    c = _cliente()
    with pytest.raises(ExtraccionError):
        extraer("  ", [], client=c)
    c.chat.completions.create.assert_not_called()


def test_modelo_de_chat_se_puede_sobrescribir_con_la_variable(monkeypatch):
    from cotizador.config import groq_chat_model
    assert groq_chat_model() == "openai/gpt-oss-120b"
    monkeypatch.setenv("GROQ_CHAT_MODEL", "llama-3.3-70b-versatile")
    assert groq_chat_model() == "llama-3.3-70b-versatile"


def test_groq_devuelve_la_bandera_de_producto_generico(con_groq):
    datos = {**COMPLETO, "items": [{"cantidad": 4, "descripcion": "CÁMARAS", "precio_unitario": None,
                                    "total_declarado": None, "generico": True, "categoria": "CCTV"}]}
    c = _cliente(datos)
    r = extraer("cuatro cámaras", client=c, catalogo=[])
    assert r.items[0].generico is True and r.items[0].categoria == "CCTV"
    sistema = c.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "generico" in sistema and "categoria" in sistema            # el esquema JSON viaja en el prompt


def test_groq_recibe_los_nombres_del_catalogo_en_el_system_prompt(con_groq):
    c = _cliente()
    catalogo = [{"id": "p", "nombre_oficial": "CAMARA TUBO 1080P", "categoria": "CCTV", "unidad": "unidad",
                 "precio_unitario_sugerido": 85.0, "alias": ["tubo 1080p"]}]
    extraer("cámaras tubo", client=c, catalogo=catalogo)
    sistema = c.chat.completions.create.call_args.kwargs["messages"][0]["content"]
    assert "- CAMARA TUBO 1080P | CCTV | unidad | tubo 1080p | 85.00" in sistema


def test_item_sin_banderas_de_llama_se_asume_especifico(con_groq):
    c = _cliente({**COMPLETO, "items": [{"cantidad": 1, "descripcion": "DVR"}]})
    it = extraer("un dvr", client=c, catalogo=[]).items[0]
    assert it.generico is False and it.categoria is None

import pytest

from cotizador.extractor import Audio, ExtraccionError, construir_prompt, extraer
from cotizador.schemas import ExtraccionTrabajo

BASE = {
    "cliente": {"nombre": "A", "atencion": None, "telefono": None, "direccion": None, "ciudad": None},
    "titulo_trabajo": None, "items": [], "observaciones": [], "forma_pago": None, "saldo": None,
    "tiempo_entrega": None, "garantia": None, "notas_tecnicas": None, "total_declarado": None,
}


class _Resp:
    def __init__(self, **extra):
        self.parsed = ExtraccionTrabajo.model_validate({**BASE, **extra})


class _Cliente:
    def __init__(self, **extra):
        self.llamadas = []
        self.models = self
        self._extra = extra

    def generate_content(self, **kw):
        self.llamadas.append(kw)
        return _Resp(**self._extra)


def test_prompt_usa_catalogo_y_no_pide_preguntas():
    p = construir_prompt()
    assert "METROS TENDIDO CERCA ELECTRICA" in p and "clarificacion" not in p
    assert "preguntas_clarificacion" not in ExtraccionTrabajo.model_json_schema()["properties"]


@pytest.mark.parametrize("texto,audios,n_partes", [
    ("hola", None, 1),
    ("", [Audio(b"x", "audio/wav")], 1),
    ("hola", [Audio(b"x"), Audio(b"y", "audio/webm")], 3),
])
def test_texto_audio_o_ambos(texto, audios, n_partes):
    c = _Cliente()
    extraer(texto, audios, client=c)
    assert len(c.llamadas) == 1  # una sola llamada por extracción
    assert len(c.llamadas[0]["contents"]) == n_partes


def test_sin_entrada_falla():
    with pytest.raises(ExtraccionError):
        extraer("  ", [], client=_Cliente())


def test_ajustar_hace_una_llamada_con_el_json_actual_y_la_instruccion():
    from cotizador.extractor import ajustar

    c = _Cliente()
    actual = ExtraccionTrabajo.model_validate(BASE)
    ajustar(actual, "agrega una sirena a 45", [Audio(b"x")], client=c)
    assert len(c.llamadas) == 1
    contenido = c.llamadas[0]["contents"]
    assert actual.model_dump_json() in contenido and "agrega una sirena a 45" in contenido
    assert len(contenido) == 5  # 3 textos + audio + instrucción
    with pytest.raises(ExtraccionError):
        ajustar(actual, "  ", [], client=c)
    assert len(c.llamadas) == 1


def test_gemini_rechaza_modelos_pro_sin_llamar(monkeypatch):
    monkeypatch.setenv("GEMINI_MODEL", "gemini-2.5-pro")
    c = _Cliente()
    with pytest.raises(ExtraccionError, match="no está permitido"):
        extraer("hola", client=c)
    assert c.llamadas == []


def test_gemini_audio_y_texto_en_una_unica_llamada_con_modelo_flash():
    c = _Cliente()
    extraer("entrega en 3 días", [Audio(b"RIFF")], client=c)
    assert len(c.llamadas) == 1
    kw = c.llamadas[0]
    assert "flash" in kw["model"] and "pro" not in kw["model"]
    assert len(kw["contents"]) == 2 and kw["config"].response_schema is ExtraccionTrabajo


def test_prompt_incluye_el_catalogo_dinamico_y_las_reglas_de_ambiguedad():
    from cotizador.extractor import construir_prompt
    propio = [{"id": "x", "nombre_oficial": "CAMARA PTZ", "categoria": "CCTV", "unidad": "unidad",
               "precio_unitario_sugerido": 500.0, "alias": ["ptz", "domo motorizado"]}]
    p = construir_prompt(propio)
    assert "- CAMARA PTZ | CCTV | unidad | ptz, domo motorizado | 500.00" in p
    assert "- METROS TENDIDO CERCA ELECTRICA |" not in p        # solo el catálogo recibido
    assert "generico=true" in p and "NOMBRE OFICIAL" in p and "4 cámaras" in p
    assert "- METROS TENDIDO CERCA ELECTRICA |" in construir_prompt()  # sin argumento: el catálogo vigente (base)


def test_esquema_exige_las_banderas_de_ambiguedad_y_tolera_que_falten():
    from cotizador.schemas import ItemExtraido
    assert {"generico", "categoria"} <= set(ExtraccionTrabajo.model_json_schema()["$defs"]["ItemExtraido"]["required"])
    it = ItemExtraido.model_validate({"cantidad": 1, "descripcion": "X", "precio_unitario": None, "total_declarado": None})
    assert it.generico is False and it.categoria is None


def test_extraer_usa_el_catalogo_recibido_en_la_llamada_a_gemini():
    c = _Cliente()
    propio = [{"id": "x", "nombre_oficial": "PRODUCTO RARO", "categoria": "Otros", "unidad": "kit",
               "precio_unitario_sugerido": None, "alias": []}]
    extraer("hola", client=c, catalogo=propio)
    assert "PRODUCTO RARO" in c.llamadas[0]["config"].system_instruction

"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Extracción de la cotización con IA: Groq (si hay GROQ_API_KEY) o Google Gemini.

* Gemini: UNA sola llamada unificada (audio y/o texto -> JSON con cliente, ítems y notas).
  Modelo flash obligatorio (nunca "pro"). Salida estructurada con el esquema Pydantic.
* Groq: el audio se transcribe con Whisper y el texto se extrae con Llama en modo JSON
  (2 llamadas si hay audio, 1 si solo hay texto). Se valida con el mismo esquema Pydantic.
Ninguna ruta reintenta automáticamente: cada reintento gastaría cuota gratuita.
"""
import json
from typing import NamedTuple

from google import genai
from google.genai import errors, types
from pydantic import ValidationError

from . import catalogo as cat
from .config import gemini_model, get_setting, groq_chat_model, groq_stt_model
from .schemas import ExtraccionTrabajo

__all__ = ["Audio", "ExtraccionError", "ajustar", "construir_prompt", "extraer", "proveedor", "descripcion_proveedor"]

SYSTEM_PROMPT = """\
Eres el asistente de cotizaciones de una empresa de seguridad electrónica en Quito, Ecuador \
(alarmas, CCTV, cercas eléctricas, porteros, motores de garaje, domótica).

Recibirás una nota (texto escrito y/o nota de voz) con los datos de un trabajo. \
Extrae el cliente, los ítems con sus cantidades y precios, y las condiciones comerciales.

Reglas:
- Extrae solo lo que la nota dice. Si un dato no aparece, devuelve null (o lista vacía); nunca lo inventes.
- NO calcules totales ni subtotales: solo copia 'total_declarado' si la nota lo menciona literalmente.
- Escribe descripciones, título y observaciones en MAYÚSCULAS, como en las cotizaciones de la empresa.
- Incluye la unidad en la descripción del ítem ('METROS TENDIDO CERCA ELECTRICA', 'CAMARAS DOMO 2MP').
- Si la nota dice 'material y mano de obra incluidos' (o similar), ponlo en observaciones.
- Si se mencionan requisitos o especificaciones técnicas (conexión a internet, resistencia al agua, voltaje, ubicación o altura de instalación, etc.), ponlos en 'notas_tecnicas', una idea por línea y en oraciones normales (no en mayúsculas). No repitas ahí las observaciones comerciales ni las condiciones de pago.
- En audio, interpreta cifras habladas ('veintinueve' = 29, 'ocho dólares' = 8).

Catálogo de productos (NOMBRE OFICIAL | categoría | unidad | cómo suelen dictarlo | precio sugerido):
{catalogo}

Uso del catálogo (cada ítem lleva las banderas 'generico' y 'categoria'):
- Si el producto dictado coincide con uno del catálogo, usa su NOMBRE OFICIAL exacto en 'descripcion' (conservando la cantidad dictada), generico=false y categoria=null.
- Si la nota da un precio, respétalo. Usa el precio sugerido del catálogo solo cuando la nota no dice precio y el catálogo lo tiene. Si dice 'sin precio', deja precio_unitario en null.
- Si el término es GENÉRICO o AMBIGUO y podría ser varios productos del catálogo (p. ej. '4 cámaras' sin decir el tipo, 'un sensor'), conserva el término dictado en MAYÚSCULAS, pon generico=true, precio_unitario=null y categoria con la categoría del catálogo más cercana (CCTV, Alarma, Cerco, Accesorios, …). No elijas tú el producto.
- Si es un producto específico que NO está en el catálogo, conserva textualmente lo dictado, generico=false y categoria=null. No fuerces una coincidencia dudosa.
"""

PROMPT_AJUSTE = """Recibirás la cotización ACTUAL en JSON y una INSTRUCCIÓN DE AJUSTE del usuario (texto y/o voz). Devuelve la cotización COMPLETA actualizada aplicando únicamente lo que pide la instrucción; todo lo demás se mantiene exactamente igual. Si pide agregar un ítem, añádelo al final; si pide quitar o cambiar uno, modifica solo ese. No inventes datos que no se mencionen. Mantén las mayúsculas y las reglas del catálogo de abajo.

"""

EXTENSION_AUDIO = {
    "audio/wav": "wav", "audio/x-wav": "wav", "audio/mpeg": "mp3", "audio/mp3": "mp3", "audio/ogg": "ogg",
    "audio/webm": "webm", "audio/mp4": "m4a", "audio/x-m4a": "m4a", "audio/m4a": "m4a", "audio/flac": "flac",
    "audio/aac": "m4a",
}


def _catalogo_vigente(catalogo: list[dict] | None) -> list[dict]:
    """El catálogo persistente; si no se puede leer, la lista base (la extracción nunca se bloquea por esto)."""
    if catalogo is not None:
        return catalogo
    try:
        return cat.obtener_catalogo()
    except Exception:
        return cat.CATALOGO_BASE


def _texto_catalogo(catalogo: list[dict]) -> str:
    lineas = []
    for it in catalogo:
        precio = it.get("precio_unitario_sugerido")
        lineas.append(" | ".join([
            f"- {it['nombre_oficial']}", it["categoria"], it["unidad"],
            ", ".join(it.get("alias", [])) or "—", f"{precio:.2f}" if precio is not None else "sin precio",
        ]))
    return "\n".join(lineas)


def construir_prompt(catalogo: list[dict] | None = None) -> str:
    return SYSTEM_PROMPT.format(catalogo=_texto_catalogo(_catalogo_vigente(catalogo)))


class ExtraccionError(RuntimeError):
    pass


class Audio(NamedTuple):
    data: bytes
    mime: str = "audio/wav"


# ------------------------------------------------------------------ proveedor
def proveedor() -> str:
    """'groq' si existe GROQ_API_KEY (secrets o entorno); si no, 'gemini'."""
    return "groq" if get_setting("GROQ_API_KEY") else "gemini"


def descripcion_proveedor() -> str:
    if proveedor() == "groq":
        return f"Groq · {groq_stt_model()} + {groq_chat_model()}"
    return f"Gemini · {gemini_model()}"


def _con_audio(audios: list[Audio] | None) -> list[Audio]:
    return [a for a in audios or [] if a.data]


# ------------------------------------------------------------------ Gemini
def _modelo_gemini() -> str:
    modelo = gemini_model()
    if "pro" in modelo.lower():
        raise ExtraccionError(
            f"El modelo «{modelo}» no está permitido: usa un modelo flash (p. ej. gemini-3.5-flash) para no agotar la cuota."
        )
    return modelo


def _partes_gemini(texto: str, audios: list[Audio] | None) -> list:
    partes: list = [types.Part.from_bytes(data=a.data, mime_type=a.mime) for a in _con_audio(audios)]
    if texto.strip():
        partes.append(texto.strip())
    return partes


def _generar_gemini(partes: list, system: str, client: genai.Client | None) -> ExtraccionTrabajo:
    """UNA llamada unificada a Gemini: audio y texto juntos -> un único JSON validado."""
    modelo = _modelo_gemini()
    config = types.GenerateContentConfig(
        system_instruction=system,
        response_mime_type="application/json",
        response_schema=ExtraccionTrabajo,
        temperature=0,
    )
    try:
        client = client or genai.Client(
            api_key=get_setting("GEMINI_API_KEY"),
            http_options=types.HttpOptions(retry_options=types.HttpRetryOptions(attempts=1)),
        )
        resp = client.models.generate_content(model=modelo, contents=partes, config=config)
    except ValueError as e:  # el SDK lo lanza si no hay API key
        raise ExtraccionError("Falta la API key de Gemini (GEMINI_API_KEY) ni de Groq (GROQ_API_KEY).") from e
    except errors.ClientError as e:
        if e.code == 429:
            raise ExtraccionError(
                "Se alcanzó el límite de la capa gratuita de Gemini. Espera, o configura GROQ_API_KEY para usar Groq."
            ) from e
        if e.code in (400, 401, 403):
            raise ExtraccionError(f"Solicitud o API key rechazada por Gemini: {e.message}") from e
        raise ExtraccionError(f"Error de Gemini ({e.code}): {e.message}") from e
    except errors.ServerError as e:
        raise ExtraccionError("Gemini no está disponible por ahora; reintenta.") from e

    ext = resp.parsed
    if not isinstance(ext, ExtraccionTrabajo):
        raise ExtraccionError("Gemini no devolvió un JSON válido; reintenta o reformula la nota.")
    return ext


# ------------------------------------------------------------------ Groq
def _cliente_groq(client):
    if client is not None:
        return client
    try:
        from groq import Groq
    except ImportError as e:
        raise ExtraccionError("Falta el paquete 'groq' (pip install groq).") from e
    return Groq(api_key=get_setting("GROQ_API_KEY"), max_retries=0)  # sin reintentos automáticos


def _llamar_groq(fn):
    """Ejecuta una llamada a Groq traduciendo sus errores a mensajes claros."""
    try:
        import groq
    except ImportError as e:
        raise ExtraccionError("Falta el paquete 'groq' (pip install groq).") from e
    try:
        return fn()
    except groq.RateLimitError as e:
        raise ExtraccionError("Se alcanzó el límite de Groq; espera un momento y reintenta.") from e
    except groq.AuthenticationError as e:
        raise ExtraccionError("API key de Groq inválida (GROQ_API_KEY).") from e
    except groq.APIConnectionError as e:
        raise ExtraccionError("No se pudo conectar con Groq.") from e
    except groq.APIStatusError as e:
        raise ExtraccionError(f"Error de Groq ({e.status_code}): {e.message}") from e


def _transcribir(client, audio: Audio) -> str:
    ext = EXTENSION_AUDIO.get(audio.mime, "wav")
    resp = _llamar_groq(lambda: client.audio.transcriptions.create(
        file=(f"nota.{ext}", audio.data), model=groq_stt_model(), language="es", temperature=0,
    ))
    return (getattr(resp, "text", "") or "").strip()


def _completar(datos: dict) -> dict:
    """Llama no siempre incluye las claves nulas: se rellenan antes de validar con Pydantic."""
    out = dict(datos)
    for nombre, campo in ExtraccionTrabajo.model_fields.items():
        if nombre not in out:
            out[nombre] = [] if campo.annotation is list or str(campo.annotation).startswith("list") else None
    cliente = dict(out.get("cliente") or {})
    for k in ("nombre", "atencion", "telefono", "direccion", "ciudad"):
        cliente.setdefault(k, None)
    out["cliente"] = cliente
    out["items"] = [{"total_declarado": None, "precio_unitario": None, **i} for i in out.get("items") or []]
    return out


def _generar_groq(contenido: str, system: str, client) -> ExtraccionTrabajo:
    """UNA llamada de chat en modo JSON (la validación del esquema se hace en Python)."""
    esquema = json.dumps(ExtraccionTrabajo.model_json_schema(), ensure_ascii=False)
    sistema = (
        f"{system}\n\nResponde SOLO con un objeto JSON válido que cumpla este JSON Schema "
        f"(incluye todas las claves; usa null o [] si no hay dato):\n{esquema}"
    )
    resp = _llamar_groq(lambda: client.chat.completions.create(
        model=groq_chat_model(),
        messages=[{"role": "system", "content": sistema}, {"role": "user", "content": contenido}],
        response_format={"type": "json_object"},
        temperature=0,
    ))
    try:
        return ExtraccionTrabajo.model_validate(_completar(json.loads(resp.choices[0].message.content)))
    except (ValueError, ValidationError, TypeError, AttributeError, IndexError) as e:
        raise ExtraccionError("Groq no devolvió un JSON válido; reintenta o reformula la nota.") from e


def _contenido_groq(client, texto: str, audios: list[Audio] | None) -> str:
    bloques = []
    for a in _con_audio(audios):
        transcripcion = _transcribir(client, a)
        if transcripcion:
            bloques.append(f"NOTA DE VOZ (transcripción):\n{transcripcion}")
    if texto.strip():
        bloques.append(f"NOTA ESCRITA:\n{texto.strip()}")
    return "\n\n".join(bloques)


# ------------------------------------------------------------------ API pública
def extraer(
    texto: str = "",
    audios: list[Audio] | None = None,
    client=None,
    catalogo: list[dict] | None = None,
) -> ExtraccionTrabajo:
    if not (texto.strip() or _con_audio(audios)):
        raise ExtraccionError("Escribe un texto o graba una nota de voz.")
    if proveedor() == "groq":
        cliente = _cliente_groq(client)
        contenido = _contenido_groq(cliente, texto, audios)
        if not contenido:
            raise ExtraccionError("No se pudo transcribir el audio; intenta de nuevo o escribe la nota.")
        return _generar_groq(contenido, construir_prompt(catalogo), cliente)
    return _generar_gemini(_partes_gemini(texto, audios), construir_prompt(catalogo), client)


def ajustar(
    actual: ExtraccionTrabajo,
    instruccion: str = "",
    audios: list[Audio] | None = None,
    client=None,
    catalogo: list[dict] | None = None,
) -> ExtraccionTrabajo:
    """Aplica una instrucción de ajuste a la cotización actual. Una llamada por pulsación del usuario."""
    if not (instruccion.strip() or _con_audio(audios)):
        raise ExtraccionError("Escribe o dicta la instrucción de ajuste.")
    system = PROMPT_AJUSTE + construir_prompt(catalogo)
    if proveedor() == "groq":
        cliente = _cliente_groq(client)
        instr = _contenido_groq(cliente, instruccion, audios)
        contenido = f"COTIZACIÓN ACTUAL (JSON):\n{actual.model_dump_json()}\n\nINSTRUCCIÓN DE AJUSTE:\n{instr}"
        return _generar_groq(contenido, system, cliente)
    partes: list = ["COTIZACIÓN ACTUAL (JSON):", actual.model_dump_json(), "INSTRUCCIÓN DE AJUSTE:"]
    partes += _partes_gemini(instruccion, audios)  # audio(s) y/o texto
    return _generar_gemini(partes, system, client)

"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Configuración y datos fijos de la empresa (tomados del Excel modelo).
"""
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

TEMPLATES_DIR = BASE_DIR / "templates"
LOGO_CANDIDATOS = [BASE_DIR / "assets" / n for n in ("logo.png", "logo.jpg", "logo.jpeg", "logo_alarmec.png")]


def ruta_logo() -> Path | None:
    """Logo institucional: reemplaza assets/logo.png y el PDF lo toma sin tocar código."""
    return next((r for r in LOGO_CANDIDATOS if r.exists()), None)


LOGO_PATH = ruta_logo() or LOGO_CANDIDATOS[0]  # usado por el HTML heredado



def get_setting(nombre: str, defecto: str | None = None) -> str | None:
    """Lee st.secrets primero (Streamlit Cloud) y luego variables de entorno / .env."""
    try:
        import streamlit as st

        valor = st.secrets.get(nombre)
    except Exception:  # sin streamlit o sin secrets.toml
        valor = None
    valor = str(valor).strip() if valor else (os.getenv(nombre) or "").strip()
    return valor or defecto  # strip: un espacio o salto de línea al pegar invalida la clave


def gemini_model() -> str:
    """Modelo flash de la capa gratuita (gemini-1.5/2.0-flash ya fueron retirados; nunca 'pro')."""
    return get_setting("GEMINI_MODEL", "gemini-3.5-flash")


def groq_chat_model() -> str:
    return get_setting("GROQ_CHAT_MODEL", "openai/gpt-oss-120b")


def groq_stt_model() -> str:
    return get_setting("GROQ_STT_MODEL", "whisper-large-v3-turbo")  # alternativa: whisper-large-v3


@dataclass(frozen=True)
class Empresa:
    """Membrete y firma que aparecen en toda cotización."""

    nombre: str = "ALARMEC"
    giro: str = (
        "Sistemas de alarmas: venta instalación, reinstalación, chequeos, "
        "mantenimientos, porteros eléctricos CCTV, Cercas eléctricas, "
        "motores de garaje, domótica."
    )
    direccion: str = "GUILLERMO CORNEJO N60-53 Y FLAVIO ALFARO"
    telefono: str = "098 700 3533"
    eslogan: str = "Seguridad Electrónica Integral & Automatización"
    especialidades: str = "CCTV • Alarmas • Cercas Eléctricas • Motores de Garaje • Domótica"
    direccion_pdf: str = "Guillermo Cornejo N60-53 y Flavio Alfaro"
    correo: str = "contacto@alarmec.com"  # se puede cambiar con EMPRESA_CORREO; vacío = no se imprime
    ciudad_emision: str = "Quito"
    firmante: str = "Sr LUIS CARVAJAL"
    firmante_nombre: str = "LUIS CARVAJAL V."
    cargo: str = "ASESOR EN SEGURIDAD"


@dataclass(frozen=True)
class CondicionesPorDefecto:
    """Textos que el Excel modelo repite en cada cotización."""

    forma_pago: str = "50% A LA FIRMA DEL CONTRATO"
    saldo: str = "CONTRAENTREGA"
    tiempo_entrega: str = (
        "DE 2 A 4 DIAS LABORABLES DEPENDIENDO INCONVENIENTES CLIMATICOS"
    )
    garantia: str = (
        "UN AÑO EN EQUIPO E INSTALACIÓN,EXCEPTO POR VARIACIONES DE VOLTAJE, "
        "SABOTAJE O MAL USO DE LOS MISMOS"
    )
    ciudad_cliente: str = "QUITO-ECUADOR"


@dataclass(frozen=True)
class ItemCatalogo:
    descripcion: str                      # texto oficial que sale en la cotización
    alias: tuple[str, ...] = ()           # cómo suelen dictarlo
    precio_unitario: float | None = None  # None = sin precio oficial; completar


# Catálogo base. Solo el precio de la cerca eléctrica viene del Excel modelo (abril 2023);
# los demás están en None: complétalos con tus precios vigentes.
CATALOGO_ALARMEC: list[ItemCatalogo] = [
    ItemCatalogo("METROS TENDIDO CERCA ELECTRICA", ("cerca eléctrica", "cerco eléctrico", "tendido de cerca"), 8.00),
    ItemCatalogo("BATERIA 12V", ("batería", "baterías 12 voltios", "batería de respaldo")),
    ItemCatalogo("CAMARA DOMO", ("cámara domo", "domo")),
    ItemCatalogo("CAMARA TUBO", ("cámara tubo", "cámara bullet", "tubo")),
    ItemCatalogo("DVR", ("dvr", "grabador", "grabador de video")),
    ItemCatalogo("MOTOR DE GARAJE", ("motor de garaje", "motor de portón", "motor de puerta")),
    ItemCatalogo("ENERGIZADOR DE CERCA ELECTRICA", ("energizador", "central de cerca")),
    ItemCatalogo("SIRENA", ("sirena", "sirena exterior")),
    ItemCatalogo("SENSOR DE MOVIMIENTO", ("sensor", "sensor pir", "detector de movimiento")),
    ItemCatalogo("PANEL DE ALARMA", ("panel", "central de alarma", "alarma")),
    ItemCatalogo("PORTERO ELECTRICO", ("portero", "intercomunicador", "video portero")),
    ItemCatalogo("MANTENIMIENTO", ("mantenimiento", "chequeo", "revisión")),
    ItemCatalogo("REINSTALACION", ("reinstalación", "reinstalar")),
]


EMPRESA = Empresa(correo=get_setting("EMPRESA_CORREO", Empresa.correo) or "")
DEFECTOS = CondicionesPorDefecto()

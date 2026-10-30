"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)
"""
import sys
from pathlib import Path

_CARPETA = Path(__file__).parent


def _huella() -> dict[str, int]:
    return {p.name: p.stat().st_mtime_ns for p in _CARPETA.glob("*.py")}


_CARGADO = _huella()  # estado de los archivos cuando este proceso cargó el paquete


def recargar_si_cambio() -> bool:
    """Descarta los módulos de `cotizador` si algún .py cambió desde que se cargaron.

    Streamlit Cloud actualiza los archivos al desplegar, pero el proceso en marcha puede seguir con módulos
    viejos mientras `app.py` ya es el nuevo (ImportError/TypeError por firmas distintas). `app.py` llama a esta
    función antes de importar el paquete: si hubo cambios, los submódulos se vuelven a importar desde disco.
    """
    global _CARGADO
    actual = _huella()
    if actual == _CARGADO:
        return False
    paquete = sys.modules[__name__]
    for nombre in [n for n in sys.modules if n.startswith(__name__ + ".")]:
        del sys.modules[nombre]
        if hasattr(paquete, nombre.rsplit(".", 1)[1]):  # `from cotizador import x` miraría este atributo primero
            delattr(paquete, nombre.rsplit(".", 1)[1])
    _CARGADO = actual
    return True

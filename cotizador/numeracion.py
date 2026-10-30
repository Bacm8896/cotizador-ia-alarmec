"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Número correlativo de cotización (AÑO-NÚMERO).

Dónde se guarda la secuencia:
- Con GITHUB_TOKEN y GITHUB_REPO: en secuencia.json de la rama NUMERACION_RAMA ("datos") del repo.
  Es la opción para Streamlit Cloud, cuyo disco se borra al reiniciar la app. Es una rama aparte
  para que guardar un número no redespliegue la app (Streamlit vigila la rama principal).
- Sin ellos: en data/secuencia.json (uso local).

NUMERACION_INICIO ("2026-0765") fija el primer número de ese año; el número sigue siendo editable en el paso 2.
"""
import base64
import json
import re
import urllib.error
import urllib.parse
import urllib.request

from .config import BASE_DIR, get_setting

ARCHIVO = BASE_DIR / "data" / "secuencia.json"
RUTA_GITHUB = "secuencia.json"
API = "https://api.github.com"
PATRON = re.compile(r"(\d{4})-(\d+)")


# ------------------------------------------------------------------ GitHub
def _github() -> tuple[str, str, str] | None:
    token, repo = get_setting("GITHUB_TOKEN"), get_setting("GITHUB_REPO")
    return (token, repo, get_setting("NUMERACION_RAMA", "datos")) if token and repo else None


def _pedir(metodo: str, ruta: str, token: str, cuerpo: dict | None = None) -> dict:
    req = urllib.request.Request(
        API + ruta, method=metodo,
        data=json.dumps(cuerpo).encode() if cuerpo is not None else None,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                 "X-GitHub-Api-Version": "2022-11-28"},
    )
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read() or b"{}")


def _gh_leer(gh) -> tuple[dict, str | None]:
    token, repo, rama = gh
    try:
        r = _pedir("GET", f"/repos/{repo}/contents/{RUTA_GITHUB}?ref={urllib.parse.quote(rama)}", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:  # aún no hay archivo (o rama): secuencia vacía
            return {}, None
        raise
    return json.loads(base64.b64decode(r["content"])), r["sha"]


def _gh_crear_rama(gh) -> None:
    token, repo, rama = gh
    principal = _pedir("GET", f"/repos/{repo}", token)["default_branch"]
    sha = _pedir("GET", f"/repos/{repo}/git/ref/heads/{principal}", token)["object"]["sha"]
    _pedir("POST", f"/repos/{repo}/git/refs", token, {"ref": f"refs/heads/{rama}", "sha": sha})


def _gh_guardar(gh, anio: str, n: int, numero: str) -> None:
    token, repo, rama = gh
    for _ in range(3):  # reintenta si otra sesión guardó a la vez (sha desactualizado)
        datos, sha = _gh_leer(gh)
        if n <= int(datos.get(anio, 0)):
            return
        datos[anio] = n
        cuerpo = {"message": f"Cotización {numero}", "branch": rama,
                  "content": base64.b64encode(json.dumps(datos).encode()).decode()}
        if sha:
            cuerpo["sha"] = sha
        try:
            _pedir("PUT", f"/repos/{repo}/contents/{RUTA_GITHUB}", token, cuerpo)
            return
        except urllib.error.HTTPError as e:
            if e.code == 404 and sha is None:
                _gh_crear_rama(gh)  # primera vez: la rama de datos no existe
            elif e.code not in (409, 422):
                raise
    raise RuntimeError("No se pudo guardar la secuencia en GitHub tras varios intentos.")


# ------------------------------------------------------------------ local
def _leer_local() -> dict:
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _guardar_local(anio: str, n: int) -> None:
    datos = _leer_local()
    if n > int(datos.get(anio, 0)):
        datos[anio] = n
        ARCHIVO.parent.mkdir(parents=True, exist_ok=True)
        ARCHIVO.write_text(json.dumps(datos), encoding="utf-8")


# ------------------------------------------------------------------ API
def _leer() -> dict:
    gh = _github()
    if gh:
        try:
            return _gh_leer(gh)[0]
        except Exception:  # sin red o token inválido: se sugiere con lo local; el número es editable
            pass
    return _leer_local()


def _minimo(anio: int) -> int:
    """Último número que se considera usado según NUMERACION_INICIO (solo para su año)."""
    m = PATRON.fullmatch(get_setting("NUMERACION_INICIO", "2026-0765") or "")
    return int(m.group(2)) - 1 if m and int(m.group(1)) == anio else 0


def siguiente(anio: int) -> str:
    """Sugerencia: el siguiente número del año (no se consume hasta registrar)."""
    ultimo = max(int(_leer().get(str(anio), 0)), _minimo(anio))
    return f"{anio}-{ultimo + 1:04d}"


def registrar(numero: str) -> bool:
    """Marca un número como usado para que la próxima sugerencia sea la siguiente.

    Devuelve False si no se pudo guardar (la app lo avisa). Un formato libre no se registra.
    """
    m = PATRON.fullmatch((numero or "").strip())
    if not m:
        return True
    anio, n = m.group(1), int(m.group(2))
    try:
        gh = _github()
        if gh:
            _gh_guardar(gh, anio, n, numero.strip())
        else:
            _guardar_local(anio, n)
    except Exception:
        return False
    return True


# ------------------------------------------------------------------ Notas de venta (contador independiente)
# Serie propia «NV-AAAA-NNNN», guardada en secuencia_nv.txt (una línea «AAAA=último» por año) de la rama de datos,
# o en data/secuencia_nv.txt en local. No comparte contador con las cotizaciones.
RUTA_NV = "secuencia_nv.txt"
ARCHIVO_NV = BASE_DIR / "data" / "secuencia_nv.txt"
NV_INICIO_DEFECTO = "NV-2026-0344"
PATRON_NV = re.compile(r"(?:NV-)?(\d{4})-(\d+)")


def _leer_txt(texto: str) -> dict[str, int]:
    datos = {}
    for linea in (texto or "").splitlines():
        anio, _, n = linea.partition("=")
        if anio.strip().isdigit() and n.strip().isdigit():
            datos[anio.strip()] = int(n)
    return datos


def _escribir_txt(datos: dict[str, int]) -> str:
    return "".join(f"{a}={n}" + chr(10) for a, n in sorted(datos.items()))


def _minimo_nv(anio: int) -> int:
    """Último número que se considera usado según NV_INICIO (por defecto «NV-2026-0344»: la primera nota de 2026 es la 344).

    Solo aplica al año indicado; los demás años empiezan en 0001. Se cambia con la variable/secreto NV_INICIO.
    """
    m = PATRON_NV.fullmatch(get_setting("NV_INICIO", NV_INICIO_DEFECTO) or "")
    return int(m.group(2)) - 1 if m and int(m.group(1)) == anio else 0


def _folio_nv(anio: int, n: int) -> str:
    return f"NV-{anio}-{n:04d}"


def _leer_nv() -> tuple[dict[str, int], str | None]:
    """(contadores por año, sha). En GitHub si hay credenciales; si falla, lo local (solo para sugerir)."""
    from . import storage

    gh = _github()
    if gh:
        crudo, sha = storage._gh_leer(gh, RUTA_NV)
        return _leer_txt(crudo.decode() if crudo else ""), sha
    try:
        return _leer_txt(ARCHIVO_NV.read_text(encoding="utf-8")), None
    except OSError:
        return {}, None


def siguiente_nv(anio: int) -> str:
    """Sugerencia (no consume nada): el próximo folio de nota de venta del año."""
    try:
        ultimo = _leer_nv()[0].get(str(anio), 0)
    except Exception:  # sin red / token inválido: el folio definitivo lo asigna reservar_nv()
        ultimo = 0
    return _folio_nv(anio, max(int(ultimo), _minimo_nv(anio)) + 1)


def reservar_nv(anio: int) -> str:
    """Asigna el siguiente folio de forma ATÓMICA y lo deja consumido. Lanza StorageError si no se pudo.

    En GitHub la escritura usa el sha del archivo: si otra sesión reservó a la vez, el PUT falla (409) y se
    vuelve a leer, así que dos notas nunca reciben el mismo folio.
    """
    from . import storage

    gh = _github()
    try:
        for _ in range(5):
            datos, sha = _leer_nv() if gh else (_leer_nv()[0], None)
            n = max(int(datos.get(str(anio), 0)), _minimo_nv(anio)) + 1
            datos[str(anio)] = n
            if gh:
                try:
                    storage._gh_escribir(gh, RUTA_NV, _escribir_txt(datos).encode(), f"Nota de venta {_folio_nv(anio, n)}", sha)
                except urllib.error.HTTPError as e:
                    if e.code in (409, 422):  # otra sesión se adelantó: se vuelve a leer
                        continue
                    raise
            else:
                ARCHIVO_NV.parent.mkdir(parents=True, exist_ok=True)
                ARCHIVO_NV.write_text(_escribir_txt(datos), encoding="utf-8")
            return _folio_nv(anio, n)
        raise storage.StorageError("No se pudo reservar el folio de la nota de venta tras varios intentos.")
    except storage.StorageError:
        raise
    except urllib.error.HTTPError as e:
        raise storage.StorageError(f"GitHub respondió {e.code} al reservar el folio de la nota de venta.") from e
    except (OSError, ValueError) as e:
        raise storage.StorageError(f"No se pudo reservar el folio de la nota de venta: {e.__class__.__name__}") from e

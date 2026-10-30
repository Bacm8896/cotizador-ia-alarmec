import base64
import io
import json
import urllib.error

from cotizador import numeracion


def test_secuencia_sugiere_registra_y_persiste(tmp_path, monkeypatch):
    monkeypatch.setattr(numeracion, "ARCHIVO", tmp_path / "data" / "secuencia.json")
    monkeypatch.setenv("NUMERACION_INICIO", "2020-0001")
    assert numeracion.siguiente(2026) == "2026-0001"
    assert numeracion.siguiente(2026) == "2026-0001"          # sugerir no consume
    assert numeracion.registrar("2026-0001")
    assert numeracion.siguiente(2026) == "2026-0002"
    numeracion.registrar("2026-1023")                          # el usuario edita el número
    assert numeracion.siguiente(2026) == "2026-1024"
    numeracion.registrar("2026-0005")                          # uno menor no retrocede
    assert numeracion.siguiente(2026) == "2026-1024"
    assert numeracion.siguiente(2027) == "2027-0001"           # cada año reinicia


def test_numeracion_inicio_solo_aplica_a_su_anio(tmp_path, monkeypatch):
    monkeypatch.setattr(numeracion, "ARCHIVO", tmp_path / "s.json")
    assert numeracion.siguiente(2026) == "2026-0765"           # por defecto empieza en 765
    numeracion.registrar("2026-0765")
    assert numeracion.siguiente(2026) == "2026-0766"
    assert numeracion.siguiente(2027) == "2027-0001"
    monkeypatch.setenv("NUMERACION_INICIO", "2027-0050")
    assert numeracion.siguiente(2027) == "2027-0050"


def test_registrar_ignora_formatos_libres_y_avisa_si_no_guarda(tmp_path, monkeypatch):
    monkeypatch.setattr(numeracion, "ARCHIVO", tmp_path / "s.json")
    assert numeracion.registrar("ABC-1")
    numeracion.registrar("")
    assert not (tmp_path / "s.json").exists()
    monkeypatch.setattr(numeracion, "ARCHIVO", tmp_path / "nada" / "x" / "s.json")
    monkeypatch.setattr(type(numeracion.ARCHIVO), "write_text", lambda *a, **k: (_ for _ in ()).throw(OSError()), raising=False)
    assert numeracion.registrar("2026-0003") is False          # no lanza, pero avisa


class GitHubFalso:
    """Simula la API de contenidos de GitHub en memoria."""

    def __init__(self, rama_existe=True):
        self.rama_existe, self.archivo, self.llamadas = rama_existe, None, []

    def __call__(self, metodo, ruta, token, cuerpo=None):
        self.llamadas.append((metodo, ruta))
        if metodo == "GET" and "/contents/" in ruta:
            if not self.archivo:
                raise _error(404)
            return {"content": base64.b64encode(json.dumps(self.archivo[0]).encode()).decode(), "sha": self.archivo[1]}
        if metodo == "PUT":
            if not self.rama_existe:
                raise _error(404)
            assert cuerpo["branch"] == "datos" and cuerpo.get("sha") == (self.archivo[1] if self.archivo else None)
            self.archivo = (json.loads(base64.b64decode(cuerpo["content"])), f"sha{len(self.llamadas)}")
            return {}
        if ruta == "/repos/yo/repo":
            return {"default_branch": "main"}
        if ruta.endswith("/git/ref/heads/main"):
            return {"object": {"sha": "abc"}}
        if metodo == "POST":
            assert cuerpo == {"ref": "refs/heads/datos", "sha": "abc"}
            self.rama_existe = True
            return {}
        raise AssertionError(ruta)


def _error(codigo):
    return urllib.error.HTTPError("u", codigo, "x", {}, io.BytesIO(b""))


def _con_github(monkeypatch, gh):
    monkeypatch.setenv("GITHUB_TOKEN", "t")
    monkeypatch.setenv("GITHUB_REPO", "yo/repo")
    monkeypatch.setattr(numeracion, "_pedir", gh)


def test_github_crea_la_rama_y_persiste_entre_reinicios(tmp_path, monkeypatch):
    monkeypatch.setattr(numeracion, "ARCHIVO", tmp_path / "s.json")
    gh = GitHubFalso(rama_existe=False)
    _con_github(monkeypatch, gh)
    assert numeracion.siguiente(2026) == "2026-0765"
    assert numeracion.registrar("2026-0765")
    assert ("POST", "/repos/yo/repo/git/refs") in gh.llamadas
    assert numeracion.registrar("2026-0766")                   # actualiza con el sha vigente
    assert gh.archivo[0] == {"2026": 766}
    assert numeracion.siguiente(2026) == "2026-0767"
    assert not (tmp_path / "s.json").exists()                  # no depende del disco del servidor


def test_github_caido_no_rompe_la_app(tmp_path, monkeypatch):
    monkeypatch.setattr(numeracion, "ARCHIVO", tmp_path / "s.json")

    def caido(*a, **k):
        raise urllib.error.URLError("sin red")

    _con_github(monkeypatch, caido)
    assert numeracion.siguiente(2026) == "2026-0765"
    assert numeracion.registrar("2026-0765") is False

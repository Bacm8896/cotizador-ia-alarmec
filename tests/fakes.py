"""API de GitHub simulada en memoria, compartida por los tests de storage y catálogo."""
import base64
import urllib.error


class GitHubFalso:
    """Imita lo mínimo de la API REST de GitHub (contents, repos, git refs) y cuenta las llamadas."""

    def __init__(self):
        self.ramas = {"main": {}}
        self.llamadas = []
        self.fallar_con = None

    def _error(self, codigo):
        return urllib.error.HTTPError("https://api.github.com", codigo, "x", {}, None)

    def __call__(self, metodo, ruta, token, cuerpo=None):
        self.llamadas.append((metodo, ruta.split("?")[0], token))
        if self.fallar_con:
            raise self._error(self.fallar_con)
        base, _, consulta = ruta.partition("?")
        partes = base.strip("/").split("/")  # repos/<dueño>/<repo>/...
        if partes[3:] == []:
            return {"default_branch": "main"}
        if partes[3:5] == ["git", "ref"]:
            return {"object": {"sha": "sha-main"}}
        if partes[3:5] == ["git", "refs"]:
            self.ramas[cuerpo["ref"].split("/")[-1]] = {}
            return {}
        assert partes[3] == "contents"
        archivo = "/".join(partes[4:]).replace("%2F", "/")
        if metodo == "GET":
            rama = self.ramas.get(consulta.removeprefix("ref="))
            if rama is None:
                raise self._error(404)
            if archivo in rama:
                return {"content": base64.b64encode(rama[archivo][0]).decode(), "sha": rama[archivo][1]}
            hijos = [{"name": r.split("/")[-1]} for r in rama if r.startswith(archivo + "/")]
            if hijos:
                return hijos
            raise self._error(404)
        rama = self.ramas.get(cuerpo["branch"])
        if rama is None:
            raise self._error(404)
        actual = rama.get(archivo)
        if metodo == "PUT":
            if actual and cuerpo.get("sha") != actual[1]:
                raise self._error(409)
            rama[archivo] = (base64.b64decode(cuerpo["content"]), f"sha{len(self.llamadas)}")
        elif metodo == "DELETE":
            if not actual or cuerpo.get("sha") != actual[1]:
                raise self._error(409)
            del rama[archivo]
        return {}

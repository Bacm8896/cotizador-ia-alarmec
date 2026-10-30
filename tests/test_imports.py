"""Importa lo que app.py necesita en un proceso limpio (detecta ImportError y ciclos)."""
import subprocess
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent


def test_imports_de_app_en_proceso_limpio():
    codigo = (
        "from cotizador.extractor import Audio, ExtraccionError, extraer\n"
        "from cotizador.config import DEFECTOS, get_setting\n"
        "from cotizador.builder import construir\n"
        "from cotizador.renderer import render_html\n"
    )
    r = subprocess.run([sys.executable, "-c", codigo], cwd=RAIZ, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_app_usa_el_pdf_actual_y_no_cachea_su_generacion():
    """El PDF de la cotización en curso siempre sale de cotizador.pdf.generar_pdf, sin caché."""
    import ast

    arbol = ast.parse((RAIZ / "app.py").read_text(encoding="utf-8"))
    importa = any(isinstance(n, ast.ImportFrom) and n.module == "cotizador.pdf" and any(a.name == "generar_pdf" for a in n.names)
                  for n in ast.walk(arbol))
    cacheadas = [n.name for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) and any(
        "cache" in ast.unparse(d) for d in n.decorator_list)]
    # cacheadas: la miniatura PNG (por bytes) y el PDF del historial (regenerado desde su JSON, se invalida al guardar)
    assert importa and sorted(cacheadas) == ["_paginas_png", "_pdf_historico"]
    assert "generar_pdf" not in ast.unparse(next(n for n in ast.walk(arbol) if isinstance(n, ast.FunctionDef) and n.name == "_paginas_png"))

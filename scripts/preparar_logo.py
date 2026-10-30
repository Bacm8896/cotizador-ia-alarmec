"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Convierte el logo con fondo rojo cuadrado (assets/logo_fuente.png) en un logo transparente (assets/logo.png).

El fondo es un degradado rojo oscuro; se elimina rellenando desde los bordes con tolerancia local
(el degradado cambia suavemente, los contornos del dibujo no). Además se descarta el texto
"ALARMEC" de la parte inferior: queda solo el isotipo (cámara con ondas), recortado al contenido.
Uso:  python scripts/preparar_logo.py
"""
from pathlib import Path

import cv2
import numpy as np

RAIZ = Path(__file__).resolve().parent.parent
FUENTE = RAIZ / "assets" / "logo_fuente.png"
SALIDA = RAIZ / "assets" / "logo.png"
TOLERANCIA = 7        # cambio máximo entre píxeles vecinos que aún cuenta como fondo
HUECO_MIN = 12        # filas vacías seguidas que separan el isotipo del texto inferior
OCUPACION_MIN = 0.004  # una fila con menos de este % de píxeles opacos cuenta como vacía


def main() -> None:
    bgr = cv2.imread(str(FUENTE), cv2.IMREAD_COLOR)
    h, w = bgr.shape[:2]
    suavizado = cv2.GaussianBlur(bgr, (3, 3), 0)
    # solo puede ser fondo un píxel rojizo (el contorno negro de la cámara no lo es, aunque sea oscuro)
    b, g, r = (suavizado[..., i].astype(int) for i in range(3))
    rojizo = (r - np.maximum(g, b)) > 22
    suavizado[~rojizo] = (0, 255, 0)  # barrera: el relleno no atraviesa lo que no es rojizo

    # 1) fondo = región conectada al borde cuyo color cambia suavemente
    mascara = np.zeros((h + 2, w + 2), np.uint8)
    tol = (TOLERANCIA,) * 3
    semillas = [(x, 0) for x in range(0, w, 25)] + [(x, h - 1) for x in range(0, w, 25)] + \
               [(0, y) for y in range(0, h, 25)] + [(w - 1, y) for y in range(0, h, 25)]
    for sx, sy in semillas:
        if mascara[sy + 1, sx + 1] == 0:
            cv2.floodFill(suavizado.copy(), mascara, (sx, sy), 0, tol, tol, cv2.FLOODFILL_MASK_ONLY | 4 | (255 << 8))
    fondo = mascara[1:-1, 1:-1] > 0

    # 2) los huecos pequeños de fondo dentro del dibujo no se tocan; se suaviza el borde del recorte
    alfa = np.where(fondo, 0, 255).astype(np.uint8)
    alfa = cv2.morphologyEx(alfa, cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))   # quita motas sueltas
    alfa = cv2.GaussianBlur(alfa, (3, 3), 0)

    # 3) quitar el texto inferior: se busca el primer hueco horizontal vacío por debajo del isotipo
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    ocupacion = (alfa > 40).mean(axis=1)
    primera = int(np.argmax(ocupacion > OCUPACION_MIN))  # primera fila con dibujo
    vacias, corte = 0, h
    for y in range(primera, h):
        vacias = vacias + 1 if ocupacion[y] <= OCUPACION_MIN else 0
        if vacias >= HUECO_MIN:
            corte = y - vacias + 1
            break
    alfa[corte:, :] = 0
    print(f"Isotipo: filas {primera}-{corte} de {h} (se descarta el texto inferior)")

    # 4) recorte al contenido, centrado y con un pequeño margen
    ys, xs = np.where(alfa > 40)
    m = 14
    y0, y1, x0, x1 = max(ys.min() - m, 0), min(ys.max() + m, h), max(xs.min() - m, 0), min(xs.max() + m, w)
    rgba = np.dstack([rgb.astype(np.float32), alfa.astype(np.float32)])[y0:y1, x0:x1].clip(0, 255).astype(np.uint8)
    cv2.imwrite(str(SALIDA), cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA))
    print(f"Logo transparente: {SALIDA.name} {rgba.shape[1]}x{rgba.shape[0]}")


if __name__ == "__main__":
    main()

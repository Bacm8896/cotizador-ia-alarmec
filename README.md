# Cotizador IA · ALARMEC

Aplicación web que convierte una **nota de voz o de texto** en una **cotización comercial en PDF**, lista para enviar por WhatsApp.
Está en uso real en ALARMEC, una empresa de seguridad electrónica en Quito (alarmas, CCTV, cercas eléctricas, motores de garaje).

> Copia pública del proyecto para portafolio: los datos de clientes son ficticios y la app en producción usa un repositorio privado.

## El problema

Las cotizaciones se hacían a mano en Excel después de cada visita técnica: lento, con errores de cálculo y sin numeración ni historial.
Ahora el técnico dicta en el celular «29 metros de cerca eléctrica a 8 dólares, 50% a la firma…» y en un minuto tiene el PDF corporativo.

## Cómo funciona

```
Voz / texto ──► Whisper (Groq) ──► LLM extrae JSON validado con Pydantic
            ──► Python calcula totales con Decimal (la IA nunca suma)
            ──► revisión y edición humana ──► PDF (ReportLab) ──► WhatsApp
```

- **IA acotada:** el LLM solo extrae datos a un esquema estricto; los importes, el IVA y los totales los calcula Python de forma determinista.
- **Revisión humana:** asistente en 4 pasos (Captura → Revisión → Vista previa → Entrega) que marca los datos faltantes antes de generar el PDF.
- **Catálogo dinámico:** los productos y precios del catálogo se envían en el *prompt* para que la IA use los nombres oficiales; los precios se actualizan desde la app.
- **Persistencia sin base de datos:** historial, catálogo y folios correlativos (`2026-0765`, `NV-2026-0344`) se guardan como JSON en un repositorio privado de GitHub mediante su API, con control de concurrencia por `sha`.
- **Notas de venta:** a partir de una cotización, con anticipo, saldo y recuadro de firmas.
- **189 tests** con mocks: ninguno consume APIs reales.

## Tecnologías

Python 3.11 · Streamlit · Groq (Whisper + LLM) / Google Gemini · Pydantic · ReportLab · PyMuPDF · pandas · pytest · GitHub REST API · Streamlit Community Cloud

## Estructura

```
app.py                      asistente por pasos y pestañas (historial, catálogo, notas de venta)
cotizador/
  config.py                 empresa, condiciones por defecto, get_setting (secrets → entorno)
  schemas.py                esquema del LLM (ExtraccionTrabajo) + modelo Cotizacion
  extractor.py              Groq (Whisper + LLM JSON) o Gemini: extraer() y ajustar()
  borrador.py               estado editable, datos faltantes y cálculo (Python puro)
  calculator.py             cálculo con Decimal, advertencias y errores
  pdf.py                    PDF A4 con ReportLab
  whatsapp.py               enlace wa.me con el resumen de la cotización
  numeracion.py             folio correlativo AÑO-NÚMERO persistente
  storage.py                historial: cada cotización aprobada se guarda como JSON
  catalogo.py               catálogo de productos y precios
  notaventa.py              nota de venta: anticipo, saldo y validación
tests/                      pytest con mocks
```

## Ejecutar en local

```
pip install -r requirements.txt
copy .env.example .env      # completar GROQ_API_KEY (o GEMINI_API_KEY)
streamlit run app.py
python -m pytest
```

Sin `GITHUB_TOKEN` todo se guarda en `data/` en local. Para Streamlit Cloud, en *Settings → Secrets*:

```
GROQ_API_KEY = "gsk_..."
APP_PIN      = "..."
GITHUB_TOKEN = "github_pat_..."              # fine-grained, «Contents: Read and write» solo sobre el repo de datos
GITHUB_REPO  = "tu-usuario/cotizador-datos"  # repo PRIVADO donde se guardan cotizaciones y catálogo
```

## Autor

**Byron Carvajal** · [LinkedIn](https://www.linkedin.com/in/byroncarvajalia) · [GitHub @Bacm8896](https://github.com/Bacm8896)

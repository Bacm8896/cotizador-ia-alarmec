"""
Cotizador ALARMEC - Sistema automatizado de cotizaciones comerciales
Desarrollado por: Byron Carvajal (https://www.linkedin.com/in/byroncarvajalia)
Versión: 1.0 (Beta)

Modelos Pydantic.

`ExtraccionTrabajo` es el esquema JSON que el LLM está obligado a devolver
(Structured Outputs). Los demás modelos son el resultado ya validado en Python.
"""
from decimal import Decimal

from pydantic import BaseModel, Field, model_validator


# ---------------------------------------------------------------- LLM output
class Cliente(BaseModel):
    nombre: str | None = Field(description="Nombre del cliente, con título si lo dice (ARQ., ING., SR.)")
    atencion: str | None = Field(description="Persona de contacto (ATN), si es distinta del cliente")
    telefono: str | None = Field(description="Teléfono del cliente")
    direccion: str | None = Field(description="Dirección o sector de la obra")
    ciudad: str | None = Field(description="Ciudad, si se menciona")


class ItemExtraido(BaseModel):
    cantidad: float = Field(description="Cantidad numérica (metros, unidades, etc.)")
    descripcion: str = Field(description="Descripción del ítem en MAYÚSCULAS, incluyendo la unidad (p. ej. 'METROS TENDIDO CERCA ELECTRICA')")
    precio_unitario: float | None = Field(description="Precio unitario si se dijo explícitamente; null si no")
    total_declarado: float | None = Field(
        description="Total de la línea SOLO si el texto lo menciona literalmente; no lo calcules"
    )
    generico: bool = Field(
        description="true si el producto es genérico o ambiguo (p. ej. '4 cámaras' sin decir el tipo) y hay que "
                    "elegirlo del catálogo; false si es específico o coincide con un producto del catálogo"
    )
    categoria: str | None = Field(
        description="Categoría del catálogo más cercana (CCTV, Alarma, Cerco, Accesorios…) cuando generico es true; "
                    "null en los demás casos"
    )

    @model_validator(mode="before")
    @classmethod
    def _tolerar_faltantes(cls, datos):
        """Los modelos pequeños a veces omiten las banderas: se asume 'específico'. (El esquema las sigue exigiendo.)"""
        if isinstance(datos, dict):
            return {"generico": False, "categoria": None, **datos}
        return datos


class ExtraccionTrabajo(BaseModel):
    cliente: Cliente
    titulo_trabajo: str | None = Field(description="Título de la sección, en MAYÚSCULAS (p. ej. 'CERCA ELECTRICA')")
    items: list[ItemExtraido]
    observaciones: list[str] = Field(
        description="Notas al pie de los ítems en MAYÚSCULAS (p. ej. 'MATERIAL Y MANO DE OBRA INCLUIDOS')"
    )
    forma_pago: str | None = Field(description="Forma de pago si se menciona (p. ej. '50% A LA FIRMA DEL CONTRATO')")
    saldo: str | None = Field(description="Condición del saldo si se menciona (p. ej. 'CONTRAENTREGA')")
    tiempo_entrega: str | None = Field(description="Tiempo de entrega si se menciona")
    garantia: str | None = Field(description="Garantía si se menciona")
    notas_tecnicas: str | None = Field(
        description="Requisitos o especificaciones técnicas mencionados (internet, resistencia al agua, voltaje, "
                    "ubicación de equipos…), una idea por línea, en oraciones normales; null si no hay"
    )
    total_declarado: float | None = Field(
        description="Total general SOLO si el texto lo menciona literalmente; no lo calcules"
    )


# ------------------------------------------------------- Resultado validado
class Linea(BaseModel):
    cantidad: Decimal
    descripcion: str
    precio_unitario: Decimal
    total: Decimal


class Cotizacion(BaseModel):
    """Todo lo que necesita la plantilla HTML y el PDF."""

    numero: str = ""
    fecha: str
    cliente_nombre: str = ""
    cliente_atencion: str = ""
    cliente_telefono: str = ""
    cliente_direccion: str = ""
    cliente_ciudad: str = ""
    titulo_trabajo: str = ""
    lineas: list[Linea] = []
    observaciones: list[str] = []
    subtotal: Decimal = Decimal("0.00")
    iva_porcentaje: Decimal = Decimal("0")
    iva: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    forma_pago: str = ""
    saldo: str = ""
    tiempo_entrega: str = ""
    garantia: str = ""
    notas_tecnicas: str = ""


# ------------------------------------------------------------------ Nota de venta
class LineaNV(BaseModel):
    cantidad: Decimal
    unidad: str = "unidad"
    descripcion: str
    precio_unitario: Decimal
    total: Decimal


class NotaVenta(BaseModel):
    """Todo lo que necesita el PDF de la nota de venta (documento de entrega/cobro, más simple que la cotización)."""

    folio: str = ""                 # NV-AAAA-NNNN
    fecha: str = ""                 # texto largo: «27 DE OCTUBRE DEL 2026»
    fecha_iso: str = ""
    referencia: str = ""            # folio de la cotización de origen; vacío si es una nota directa
    cliente_nombre: str = ""
    cliente_ci_ruc: str = ""
    cliente_telefono: str = ""
    cliente_direccion: str = ""
    lineas: list[LineaNV] = []
    subtotal: Decimal = Decimal("0.00")
    iva_porcentaje: Decimal = Decimal("0")
    iva: Decimal = Decimal("0.00")
    total: Decimal = Decimal("0.00")
    anticipo: Decimal = Decimal("0.00")
    saldo: Decimal = Decimal("0.00")
    metodo_pago: str = ""
    observaciones: str = ""

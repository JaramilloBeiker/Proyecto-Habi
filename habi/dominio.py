"""Modelos y errores del dominio. No dependen de la consola ni de SQLite (RNF-S-01)."""

from dataclasses import dataclass


# ---------- Errores (RNF-U-01: cada fallo lleva un motivo legible) ----------

class HabiError(Exception):
    """Error de negocio esperado. Su mensaje se muestra tal cual al usuario."""


class ErrorValidacion(HabiError):
    """Dato de entrada inválido (RNF-U-03). Indica el campo que falló."""

    def __init__(self, campo: str, mensaje: str):
        self.campo = campo
        self.mensaje = mensaje  # sin el nombre del campo, para mostrarlo junto al input
        super().__init__(f"{campo}: {mensaje}")


class ErrorAutenticacion(HabiError):
    """Usuario o contraseña incorrectos, o no hay sesión (RNF-SEC-01)."""


class ErrorAutorizacion(HabiError):
    """El usuario intenta operar sobre una cuenta que no es suya (RNF-SEC-02)."""


class NoEncontrado(HabiError):
    """La cuenta o usuario referido no existe."""


class SaldoInsuficiente(HabiError):
    """La cuenta origen no tiene saldo para la operación (RF-04)."""


# ---------- Modelos ----------

@dataclass(frozen=True)
class Usuario:
    id: int
    nombre: str
    cuenta_id: int


@dataclass(frozen=True)
class Movimiento:
    id: int
    operacion_id: int
    tipo_operacion: str      # 'CARGA' | 'TRANSFERENCIA'
    monto: int               # con signo: + entra, - sale
    contraparte: str         # nombre del otro usuario o 'FONDEO'
    creado_en: str           # ISO 8601


@dataclass(frozen=True)
class ResultadoOperacion:
    operacion_id: int
    tipo: str
    monto: int
    creada_en: str
    clave_idempotencia: str | None = None
    repetida: bool = False   # True si se devolvió el resultado de una clave ya usada (RNF-R-03)

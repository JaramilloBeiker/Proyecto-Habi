"""Lógica de negocio: reglas de saldo, cargas y transferencias.

No usa input/print ni escribe SQL directamente (RNF-S-01). Recibe una
conexión ya abierta; cada hilo/proceso usa la suya.
Las funciones de cuenta reciben el `usuario` autenticado (RNF-SEC-01/02).
"""

import sqlite3

from habi import config
from habi.dominio import Movimiento, ResultadoOperacion, Usuario


# ---------- Validaciones (RNF-U-03, RNF-D-02) ----------

def validar_monto(monto: object, campo: str = "monto") -> int:
    """Devuelve el monto como int si es válido; si no, lanza ErrorValidacion(campo, motivo).

    Reglas: entero (no bool, no float, no texto), entre
    config.MONTO_MINIMO y config.MONTO_MAXIMO, ambos inclusive.
    """
    raise NotImplementedError


def validar_credenciales_registro(nombre: str, password: str) -> None:
    """Nombre no vacío; password con al menos config.LONGITUD_MINIMA_PASSWORD caracteres."""
    raise NotImplementedError


# ---------- Cuentas (RF-01, RF-02) ----------

def registrar_usuario(conn: sqlite3.Connection, nombre: str, password: str) -> Usuario:
    """RF-01. Valida, guarda el hash (security.hash_password) y crea la cuenta con saldo 0.

    Usuario y cuenta se crean en la misma transacción.
    Si el nombre ya existe -> ErrorValidacion('nombre', ...).
    """
    raise NotImplementedError


def iniciar_sesion(conn: sqlite3.Connection, nombre: str, password: str) -> Usuario:
    """RF-02. Devuelve el Usuario si las credenciales son correctas; si no, ErrorAutenticacion.

    Usar el mismo mensaje para "no existe" y "contraseña incorrecta".
    """
    raise NotImplementedError


# ---------- Saldo e historial (RF-05, RF-06) ----------

def consultar_saldo(conn: sqlite3.Connection, usuario: Usuario) -> int:
    """RF-05. Saldo en COP de la cuenta del usuario autenticado."""
    raise NotImplementedError


def consultar_historial(conn: sqlite3.Connection, usuario: Usuario, pagina: int = 0) -> list[Movimiento]:
    """RF-06. Bloque `pagina` (desde 0) de config.TAMANO_PAGINA_HISTORIAL movimientos, más reciente primero."""
    raise NotImplementedError


# ---------- Dinero (RF-03, RF-04) ----------

def cargar_saldo(conn: sqlite3.Connection, usuario: Usuario, monto: int) -> ResultadoOperacion:
    """RF-03. Carga simulada desde la cuenta de fondeo.

    En UNA transacción (db.transaccion):
      1. crear operación 'CARGA'
      2. movimiento -monto en fondeo y +monto en la cuenta del usuario (suman 0, RNF-D-05)
      3. ajustar ambos saldos
    """
    raise NotImplementedError


def transferir(
    conn: sqlite3.Connection, usuario: Usuario, nombre_destino: str, monto: int, clave_idempotencia: str
) -> ResultadoOperacion:
    """RF-04. Transfiere desde la cuenta del usuario autenticado a otra cuenta.

    Antes de tocar datos: validar monto, que el destino exista y sea distinto al origen.
    En UNA transacción (db.transaccion, BEGIN IMMEDIATE):
      1. si la clave ya existe -> devolver el resultado original con repetida=True (RNF-R-03)
      2. debitar_si_alcanza(origen); si False -> SaldoInsuficiente (rollback, sin movimientos)
      3. acreditar destino
      4. crear operación 'TRANSFERENCIA' y los dos movimientos (-monto / +monto)
    La clave la genera la capa que inicia la transferencia (uuid.uuid4()).
    """
    raise NotImplementedError

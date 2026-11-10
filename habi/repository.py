"""Acceso a datos: solo SQL, sin reglas de negocio (RNF-S-01).

Ninguna función abre ni cierra transacciones: eso lo decide la capa de
servicios con `db.transaccion()`, para que una operación completa sea atómica.
"""

import sqlite3


# ---------- Usuarios y cuentas ----------

def crear_usuario(conn: sqlite3.Connection, nombre: str, password_hash: str, creado_en: str) -> int:
    """INSERT en usuarios. Devuelve el id. Lanza sqlite3.IntegrityError si el nombre ya existe."""
    raise NotImplementedError


def crear_cuenta_usuario(conn: sqlite3.Connection, usuario_id: int, creada_en: str) -> int:
    """INSERT en cuentas con tipo 'USUARIO' y saldo 0. Devuelve el id de la cuenta."""
    raise NotImplementedError


def obtener_usuario_por_nombre(conn: sqlite3.Connection, nombre: str) -> sqlite3.Row | None:
    """SELECT usuario + cuenta_id (JOIN cuentas) por nombre. None si no existe."""
    raise NotImplementedError


def obtener_cuenta_de_usuario(conn: sqlite3.Connection, usuario_id: int) -> sqlite3.Row | None:
    """SELECT de la cuenta que pertenece al usuario."""
    raise NotImplementedError


def obtener_cuenta_fondeo_id(conn: sqlite3.Connection) -> int:
    """Id de la única cuenta con tipo 'FONDEO'."""
    raise NotImplementedError


# ---------- Saldos ----------

def obtener_saldo(conn: sqlite3.Connection, cuenta_id: int) -> int:
    """SELECT saldo FROM cuentas WHERE id = ?"""
    raise NotImplementedError


def debitar_si_alcanza(conn: sqlite3.Connection, cuenta_id: int, monto: int) -> bool:
    """UPDATE cuentas SET saldo = saldo - ? WHERE id = ? AND saldo >= ?

    Devuelve True si se afectó una fila. La condición va en el mismo UPDATE
    para que la verificación y el débito sean un solo paso (RNF-R-04).
    """
    raise NotImplementedError


def ajustar_saldo(conn: sqlite3.Connection, cuenta_id: int, delta: int) -> None:
    """UPDATE cuentas SET saldo = saldo + ? WHERE id = ?  (créditos y cuenta de fondeo)."""
    raise NotImplementedError


# ---------- Operaciones y movimientos ----------

def crear_operacion(
    conn: sqlite3.Connection, tipo: str, monto: int, creada_en: str, clave_idempotencia: str | None = None
) -> int:
    """INSERT en operaciones. Devuelve el id."""
    raise NotImplementedError


def obtener_operacion_por_clave(conn: sqlite3.Connection, clave_idempotencia: str) -> sqlite3.Row | None:
    """SELECT de la operación asociada a una clave de idempotencia (RNF-R-03)."""
    raise NotImplementedError


def crear_movimiento(conn: sqlite3.Connection, operacion_id: int, cuenta_id: int, monto: int, creado_en: str) -> int:
    """INSERT en movimientos (solo INSERT: la tabla es inmutable, RNF-D-04)."""
    raise NotImplementedError


def listar_movimientos(conn: sqlite3.Connection, cuenta_id: int, limite: int, desplazamiento: int) -> list[sqlite3.Row]:
    """Movimientos de la cuenta, del más reciente al más antiguo (ORDER BY id DESC), paginados (RF-06).

    Debe incluir el tipo de operación y el nombre de la contraparte.
    """
    raise NotImplementedError

"""Acceso a datos: solo SQL, sin reglas de negocio (RNF-S-01).

Ninguna función abre ni cierra transacciones: eso lo decide la capa de
servicios con `db.transaccion()`, para que una operación completa sea atómica.
"""

import sqlite3


# ---------- Usuarios y cuentas ----------

def crear_usuario(conn: sqlite3.Connection, nombre: str, password_hash: str, creado_en: str) -> int:
    """INSERT en usuarios. Devuelve el id. Lanza sqlite3.IntegrityError si el nombre ya existe."""
    cursor = conn.execute(
        "INSERT INTO usuarios (nombre, password_hash, creado_en) VALUES (?, ?, ?)",
        (nombre, password_hash, creado_en),
    )
    return cursor.lastrowid


def crear_cuenta_usuario(conn: sqlite3.Connection, usuario_id: int, creada_en: str) -> int:
    """INSERT en cuentas con tipo 'USUARIO' y saldo 0. Devuelve el id de la cuenta."""
    cursor = conn.execute(
        "INSERT INTO cuentas (usuario_id, tipo, saldo, creada_en) VALUES (?, 'USUARIO', 0, ?)",
        (usuario_id, creada_en),
    )
    return cursor.lastrowid


def obtener_usuario_por_nombre(conn: sqlite3.Connection, nombre: str) -> sqlite3.Row | None:
    """SELECT usuario + cuenta_id (JOIN cuentas) por nombre. None si no existe."""
    return conn.execute(
        "SELECT u.id, u.nombre, u.password_hash, u.creado_en, c.id AS cuenta_id "
        "FROM usuarios u JOIN cuentas c ON c.usuario_id = u.id "
        "WHERE u.nombre = ?",
        (nombre,),
    ).fetchone()


def obtener_cuenta_de_usuario(conn: sqlite3.Connection, usuario_id: int) -> sqlite3.Row | None:
    """SELECT de la cuenta que pertenece al usuario."""
    return conn.execute(
        "SELECT id, usuario_id, tipo, saldo, creada_en FROM cuentas WHERE usuario_id = ?",
        (usuario_id,),
    ).fetchone()


def obtener_cuenta_fondeo_id(conn: sqlite3.Connection) -> int:
    """Id de la única cuenta con tipo 'FONDEO'."""
    fila = conn.execute("SELECT id FROM cuentas WHERE tipo = 'FONDEO'").fetchone()
    if fila is None:
        raise RuntimeError("No existe la cuenta de fondeo: la base de datos no fue inicializada")
    return fila["id"]


# ---------- Sesiones ----------

def crear_sesion(conn: sqlite3.Connection, token: str, usuario_id: int, expira_en: str) -> None:
    """INSERT en sesiones."""
    conn.execute(
        "INSERT INTO sesiones (token, usuario_id, expira_en) VALUES (?, ?, ?)",
        (token, usuario_id, expira_en),
    )


def obtener_sesion(conn: sqlite3.Connection, token: str) -> sqlite3.Row | None:
    """Sesión + datos del usuario y su cuenta. None si el token no existe."""
    return conn.execute(
        "SELECT s.expira_en, u.id AS usuario_id, u.nombre, c.id AS cuenta_id "
        "FROM sesiones s "
        "JOIN usuarios u ON u.id = s.usuario_id "
        "JOIN cuentas c ON c.usuario_id = u.id "
        "WHERE s.token = ?",
        (token,),
    ).fetchone()


def eliminar_sesion(conn: sqlite3.Connection, token: str) -> None:
    """DELETE de la sesión (cerrar sesión)."""
    conn.execute("DELETE FROM sesiones WHERE token = ?", (token,))


# ---------- Saldos ----------

def obtener_saldo(conn: sqlite3.Connection, cuenta_id: int) -> int:
    """SELECT saldo FROM cuentas WHERE id = ?"""
    fila = conn.execute("SELECT saldo FROM cuentas WHERE id = ?", (cuenta_id,)).fetchone()
    if fila is None:
        raise LookupError(f"La cuenta {cuenta_id} no existe")
    return fila["saldo"]


def debitar_si_alcanza(conn: sqlite3.Connection, cuenta_id: int, monto: int) -> bool:
    """UPDATE cuentas SET saldo = saldo - ? WHERE id = ? AND saldo >= ?

    Devuelve True si se afectó una fila. La condición va en el mismo UPDATE
    para que la verificación y el débito sean un solo paso (RNF-R-04).
    """
    cursor = conn.execute(
        "UPDATE cuentas SET saldo = saldo - ? WHERE id = ? AND saldo >= ?",
        (monto, cuenta_id, monto),
    )
    return cursor.rowcount == 1


def ajustar_saldo(conn: sqlite3.Connection, cuenta_id: int, delta: int) -> None:
    """UPDATE cuentas SET saldo = saldo + ? WHERE id = ?  (créditos y cuenta de fondeo)."""
    cursor = conn.execute("UPDATE cuentas SET saldo = saldo + ? WHERE id = ?", (delta, cuenta_id))
    if cursor.rowcount != 1:
        raise LookupError(f"La cuenta {cuenta_id} no existe")


# ---------- Operaciones y movimientos ----------

def crear_operacion(
    conn: sqlite3.Connection, tipo: str, monto: int, creada_en: str, clave_idempotencia: str | None = None
) -> int:
    """INSERT en operaciones. Devuelve el id."""
    cursor = conn.execute(
        "INSERT INTO operaciones (tipo, clave_idempotencia, monto, creada_en) VALUES (?, ?, ?, ?)",
        (tipo, clave_idempotencia, monto, creada_en),
    )
    return cursor.lastrowid


def obtener_operacion_por_clave(conn: sqlite3.Connection, clave_idempotencia: str) -> sqlite3.Row | None:
    """SELECT de la operación asociada a una clave de idempotencia (RNF-R-03)."""
    return conn.execute(
        "SELECT id, tipo, clave_idempotencia, monto, creada_en FROM operaciones WHERE clave_idempotencia = ?",
        (clave_idempotencia,),
    ).fetchone()


def crear_movimiento(conn: sqlite3.Connection, operacion_id: int, cuenta_id: int, monto: int, creado_en: str) -> int:
    """INSERT en movimientos (solo INSERT: la tabla es inmutable, RNF-D-04)."""
    cursor = conn.execute(
        "INSERT INTO movimientos (operacion_id, cuenta_id, monto, creado_en) VALUES (?, ?, ?, ?)",
        (operacion_id, cuenta_id, monto, creado_en),
    )
    return cursor.lastrowid


def movimientos_de_operacion(conn: sqlite3.Connection, operacion_id: int) -> list[sqlite3.Row]:
    """Los movimientos (cuenta_id, monto) que componen una operación."""
    return conn.execute(
        "SELECT cuenta_id, monto FROM movimientos WHERE operacion_id = ? ORDER BY id",
        (operacion_id,),
    ).fetchall()


def listar_movimientos(conn: sqlite3.Connection, cuenta_id: int, limite: int, desplazamiento: int) -> list[sqlite3.Row]:
    """Movimientos de la cuenta, del más reciente al más antiguo (ORDER BY id DESC), paginados (RF-06).

    Incluye el tipo de operación y el nombre de la contraparte: el usuario dueño
    del otro movimiento de la misma operación, o 'FONDEO' si es la cuenta del sistema.
    """
    return conn.execute(
        """
        SELECT m.id, m.operacion_id, o.tipo AS tipo_operacion, m.monto, m.creado_en,
               COALESCE(u.nombre, 'FONDEO') AS contraparte
        FROM movimientos m
        JOIN operaciones o ON o.id = m.operacion_id
        JOIN movimientos otro ON otro.operacion_id = m.operacion_id AND otro.id <> m.id
        JOIN cuentas c ON c.id = otro.cuenta_id
        LEFT JOIN usuarios u ON u.id = c.usuario_id
        WHERE m.cuenta_id = ?
        ORDER BY m.id DESC
        LIMIT ? OFFSET ?
        """,
        (cuenta_id, limite, desplazamiento),
    ).fetchall()

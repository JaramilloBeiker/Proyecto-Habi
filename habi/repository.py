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

    Incluye el tipo de operación y la contraparte (dueña del otro movimiento de la
    misma operación): el nombre del usuario, el nombre del bolsillo, o 'FONDEO'
    si es la cuenta del sistema. `contraparte_tipo` dice cuál de los tres es.
    """
    return conn.execute(
        """
        SELECT m.id, m.operacion_id, o.tipo AS tipo_operacion, m.monto, m.creado_en,
               COALESCE(u.nombre, b.nombre, 'FONDEO') AS contraparte,
               c.tipo AS contraparte_tipo
        FROM movimientos m
        JOIN operaciones o ON o.id = m.operacion_id
        JOIN movimientos otro ON otro.operacion_id = m.operacion_id AND otro.id <> m.id
        JOIN cuentas c ON c.id = otro.cuenta_id
        LEFT JOIN usuarios u ON u.id = c.usuario_id
        LEFT JOIN bolsillos b ON b.cuenta_id = c.id
        WHERE m.cuenta_id = ?
        ORDER BY m.id DESC
        LIMIT ? OFFSET ?
        """,
        (cuenta_id, limite, desplazamiento),
    ).fetchall()


# ---------- Juntia: bolsillos y miembros ----------

def crear_cuenta_bolsillo(conn: sqlite3.Connection, creada_en: str) -> int:
    """INSERT en cuentas con tipo 'BOLSILLO', sin dueño y saldo 0. Devuelve el id de la cuenta."""
    cursor = conn.execute(
        "INSERT INTO cuentas (usuario_id, tipo, saldo, creada_en) VALUES (NULL, 'BOLSILLO', 0, ?)",
        (creada_en,),
    )
    return cursor.lastrowid


def crear_bolsillo(
    conn: sqlite3.Connection, cuenta_id: int, nombre: str, meta: int, creador_id: int, creado_en: str
) -> int:
    """INSERT en bolsillos. Devuelve el id."""
    cursor = conn.execute(
        "INSERT INTO bolsillos (cuenta_id, nombre, meta, creador_id, creado_en) VALUES (?, ?, ?, ?, ?)",
        (cuenta_id, nombre, meta, creador_id, creado_en),
    )
    return cursor.lastrowid


def obtener_bolsillo(conn: sqlite3.Connection, bolsillo_id: int) -> sqlite3.Row | None:
    """Bolsillo + saldo, monto reservado por retiros pendientes y creador. None si no existe."""
    return conn.execute(
        "SELECT b.id, b.cuenta_id, b.nombre, b.meta, b.creado_en, c.saldo, u.nombre AS creador, "
        "COALESCE((SELECT SUM(r.monto) FROM retiros r WHERE r.bolsillo_id = b.id AND r.estado = 'PENDIENTE'), 0) AS reservado "
        "FROM bolsillos b "
        "JOIN cuentas c ON c.id = b.cuenta_id "
        "JOIN usuarios u ON u.id = b.creador_id "
        "WHERE b.id = ?",
        (bolsillo_id,),
    ).fetchone()


def guardar_miembro(
    conn: sqlite3.Connection, bolsillo_id: int, usuario_id: int, estado: str,
    invitado_por: int | None, actualizado_en: str,
) -> None:
    """Crea la fila del miembro o, si ya existe, cambia su estado (INSERT ... ON CONFLICT)."""
    conn.execute(
        "INSERT INTO miembros_bolsillo (bolsillo_id, usuario_id, estado, invitado_por, actualizado_en) "
        "VALUES (?, ?, ?, ?, ?) "
        "ON CONFLICT (bolsillo_id, usuario_id) DO UPDATE SET "
        "estado = excluded.estado, invitado_por = excluded.invitado_por, actualizado_en = excluded.actualizado_en",
        (bolsillo_id, usuario_id, estado, invitado_por, actualizado_en),
    )


def cambiar_estado_miembro(
    conn: sqlite3.Connection, bolsillo_id: int, usuario_id: int, estado_actual: str, estado_nuevo: str,
    actualizado_en: str,
) -> bool:
    """UPDATE del estado solo si el miembro está en `estado_actual`. True si se cambió."""
    cursor = conn.execute(
        "UPDATE miembros_bolsillo SET estado = ?, actualizado_en = ? "
        "WHERE bolsillo_id = ? AND usuario_id = ? AND estado = ?",
        (estado_nuevo, actualizado_en, bolsillo_id, usuario_id, estado_actual),
    )
    return cursor.rowcount == 1


def obtener_estado_miembro(conn: sqlite3.Connection, bolsillo_id: int, usuario_id: int) -> str | None:
    """Estado del usuario en el bolsillo, o None si nunca fue invitado."""
    fila = conn.execute(
        "SELECT estado FROM miembros_bolsillo WHERE bolsillo_id = ? AND usuario_id = ?",
        (bolsillo_id, usuario_id),
    ).fetchone()
    return fila["estado"] if fila else None


def listar_miembros(conn: sqlite3.Connection, bolsillo_id: int) -> list[sqlite3.Row]:
    """Miembros activos e invitados del bolsillo (nombre, estado, total aportado)."""
    return conn.execute(
        """
        SELECT u.id AS usuario_id, u.nombre, m.estado, c.id AS cuenta_id,
               (SELECT COALESCE(SUM(-mu.monto), 0)
                FROM movimientos mu
                JOIN movimientos mb ON mb.operacion_id = mu.operacion_id AND mb.id <> mu.id
                WHERE mu.cuenta_id = c.id AND mu.monto < 0 AND mb.cuenta_id = b.cuenta_id) AS aportado
        FROM miembros_bolsillo m
        JOIN usuarios u ON u.id = m.usuario_id
        JOIN cuentas c ON c.usuario_id = u.id
        JOIN bolsillos b ON b.id = m.bolsillo_id
        WHERE m.bolsillo_id = ? AND m.estado IN ('ACTIVO', 'INVITADO')
        ORDER BY m.estado, m.actualizado_en, u.nombre
        """,
        (bolsillo_id,),
    ).fetchall()


def total_aportado(conn: sqlite3.Connection, cuenta_bolsillo_id: int, cuenta_usuario_id: int) -> int:
    """Suma de lo que la cuenta del usuario ha enviado a la cuenta del bolsillo.

    Un aporte es una operación cuyo movimiento negativo es del usuario y el
    positivo del bolsillo (lo que el bolsillo le paga en un retiro no cuenta).
    """
    fila = conn.execute(
        """
        SELECT COALESCE(SUM(-mu.monto), 0) AS total
        FROM movimientos mu
        JOIN movimientos mb ON mb.operacion_id = mu.operacion_id AND mb.id <> mu.id
        WHERE mu.cuenta_id = ? AND mu.monto < 0 AND mb.cuenta_id = ?
        """,
        (cuenta_usuario_id, cuenta_bolsillo_id),
    ).fetchone()
    return fila["total"]


def listar_bolsillos_activos(conn: sqlite3.Connection, usuario_id: int) -> list[sqlite3.Row]:
    """Bolsillos donde el usuario es miembro activo, del más nuevo al más viejo."""
    return conn.execute(
        "SELECT b.id, b.nombre, b.meta, b.creado_en, c.saldo, u.nombre AS creador, "
        "COALESCE((SELECT SUM(r.monto) FROM retiros r WHERE r.bolsillo_id = b.id AND r.estado = 'PENDIENTE'), 0) AS reservado "
        "FROM miembros_bolsillo m "
        "JOIN bolsillos b ON b.id = m.bolsillo_id "
        "JOIN cuentas c ON c.id = b.cuenta_id "
        "JOIN usuarios u ON u.id = b.creador_id "
        "WHERE m.usuario_id = ? AND m.estado = 'ACTIVO' "
        "ORDER BY b.id DESC",
        (usuario_id,),
    ).fetchall()


def listar_invitaciones(conn: sqlite3.Connection, usuario_id: int) -> list[sqlite3.Row]:
    """Invitaciones pendientes del usuario: bolsillo, quién invitó y cuándo. Sin saldo."""
    return conn.execute(
        "SELECT b.id AS bolsillo_id, b.nombre AS bolsillo_nombre, u.nombre AS invitado_por, "
        "m.actualizado_en AS fecha "
        "FROM miembros_bolsillo m "
        "JOIN bolsillos b ON b.id = m.bolsillo_id "
        "JOIN usuarios u ON u.id = m.invitado_por "
        "WHERE m.usuario_id = ? AND m.estado = 'INVITADO' "
        "ORDER BY m.actualizado_en DESC",
        (usuario_id,),
    ).fetchall()


# ---------- Juntia: retiros y votos ----------

def expirar_retiros_vencidos(conn: sqlite3.Connection, ahora: str) -> int:
    """Marca EXPIRADO todo retiro PENDIENTE cuya fecha límite ya pasó. Devuelve cuántos.

    Las fechas se guardan en ISO 8601 UTC con el mismo formato, así que se
    pueden comparar como texto.
    """
    cursor = conn.execute(
        "UPDATE retiros SET estado = 'EXPIRADO', cerrado_en = ? WHERE estado = 'PENDIENTE' AND expira_en <= ?",
        (ahora, ahora),
    )
    return cursor.rowcount


def crear_retiro(
    conn: sqlite3.Connection, bolsillo_id: int, proponente_id: int, destino_id: int, monto: int,
    motivo: str, creado_en: str, expira_en: str,
) -> int:
    """INSERT de una propuesta de retiro en estado PENDIENTE. Devuelve el id."""
    cursor = conn.execute(
        "INSERT INTO retiros (bolsillo_id, proponente_id, destino_id, monto, motivo, estado, creado_en, expira_en) "
        "VALUES (?, ?, ?, ?, ?, 'PENDIENTE', ?, ?)",
        (bolsillo_id, proponente_id, destino_id, monto, motivo, creado_en, expira_en),
    )
    return cursor.lastrowid


def usuarios_activos_de_bolsillo(conn: sqlite3.Connection, bolsillo_id: int) -> list[int]:
    """Ids de los miembros ACTIVO del bolsillo en este momento."""
    filas = conn.execute(
        "SELECT usuario_id FROM miembros_bolsillo WHERE bolsillo_id = ? AND estado = 'ACTIVO' ORDER BY usuario_id",
        (bolsillo_id,),
    ).fetchall()
    return [f["usuario_id"] for f in filas]


def crear_voto(conn: sqlite3.Connection, retiro_id: int, usuario_id: int, voto: str | None, votado_en: str | None) -> None:
    """INSERT de la fila de voto de un miembro (voto NULL = pendiente)."""
    conn.execute(
        "INSERT INTO votos_retiro (retiro_id, usuario_id, voto, votado_en) VALUES (?, ?, ?, ?)",
        (retiro_id, usuario_id, voto, votado_en),
    )


def obtener_retiro(conn: sqlite3.Connection, retiro_id: int) -> sqlite3.Row | None:
    """Retiro + nombres de proponente y destino + cuenta del destino. None si no existe."""
    return conn.execute(
        """
        SELECT r.id, r.bolsillo_id, r.monto, r.motivo, r.estado, r.creado_en, r.expira_en, r.cerrado_en,
               r.destino_id, d.nombre AS destino, cd.id AS destino_cuenta_id, p.nombre AS proponente
        FROM retiros r
        JOIN usuarios d ON d.id = r.destino_id
        JOIN cuentas cd ON cd.usuario_id = d.id
        JOIN usuarios p ON p.id = r.proponente_id
        WHERE r.id = ?
        """,
        (retiro_id,),
    ).fetchone()


def listar_retiros(conn: sqlite3.Connection, bolsillo_id: int, limite: int) -> list[sqlite3.Row]:
    """Retiros del bolsillo: primero los pendientes, luego los más recientes."""
    return conn.execute(
        """
        SELECT r.id, r.bolsillo_id, r.monto, r.motivo, r.estado, r.creado_en, r.expira_en, r.cerrado_en,
               d.nombre AS destino, p.nombre AS proponente
        FROM retiros r
        JOIN usuarios d ON d.id = r.destino_id
        JOIN usuarios p ON p.id = r.proponente_id
        WHERE r.bolsillo_id = ?
        ORDER BY (r.estado = 'PENDIENTE') DESC, r.id DESC
        LIMIT ?
        """,
        (bolsillo_id, limite),
    ).fetchall()


def listar_votos(conn: sqlite3.Connection, retiro_id: int) -> list[sqlite3.Row]:
    """Votos del retiro (nombre, voto) de quienes estaban activos al proponerlo."""
    return conn.execute(
        "SELECT u.nombre, v.usuario_id, v.voto, v.votado_en "
        "FROM votos_retiro v JOIN usuarios u ON u.id = v.usuario_id "
        "WHERE v.retiro_id = ? ORDER BY u.nombre",
        (retiro_id,),
    ).fetchall()


def obtener_voto(conn: sqlite3.Connection, retiro_id: int, usuario_id: int) -> sqlite3.Row | None:
    """Fila de voto del usuario. None si no estaba activo cuando se propuso el retiro."""
    return conn.execute(
        "SELECT voto FROM votos_retiro WHERE retiro_id = ? AND usuario_id = ?",
        (retiro_id, usuario_id),
    ).fetchone()


def registrar_voto(conn: sqlite3.Connection, retiro_id: int, usuario_id: int, voto: str, votado_en: str) -> bool:
    """UPDATE del voto solo si aún no había votado. True si se registró."""
    cursor = conn.execute(
        "UPDATE votos_retiro SET voto = ?, votado_en = ? WHERE retiro_id = ? AND usuario_id = ? AND voto IS NULL",
        (voto, votado_en, retiro_id, usuario_id),
    )
    return cursor.rowcount == 1


def contar_votos(conn: sqlite3.Connection, retiro_id: int) -> sqlite3.Row:
    """Totales del retiro: cuántos deben votar, cuántos a favor y cuántos en contra."""
    return conn.execute(
        "SELECT COUNT(*) AS total, "
        "COALESCE(SUM(voto = 'A_FAVOR'), 0) AS a_favor, "
        "COALESCE(SUM(voto = 'EN_CONTRA'), 0) AS en_contra "
        "FROM votos_retiro WHERE retiro_id = ?",
        (retiro_id,),
    ).fetchone()


def cerrar_retiro(
    conn: sqlite3.Connection, retiro_id: int, estado: str, cerrado_en: str, operacion_id: int | None = None
) -> bool:
    """Pasa un retiro PENDIENTE a EJECUTADO o RECHAZADO. True si estaba pendiente."""
    cursor = conn.execute(
        "UPDATE retiros SET estado = ?, cerrado_en = ?, operacion_id = ? WHERE id = ? AND estado = 'PENDIENTE'",
        (estado, cerrado_en, operacion_id, retiro_id),
    )
    return cursor.rowcount == 1


def tiene_voto_pendiente(conn: sqlite3.Connection, bolsillo_id: int, usuario_id: int) -> bool:
    """True si el usuario debe votar algún retiro PENDIENTE del bolsillo."""
    fila = conn.execute(
        "SELECT 1 FROM votos_retiro v JOIN retiros r ON r.id = v.retiro_id "
        "WHERE r.bolsillo_id = ? AND r.estado = 'PENDIENTE' AND v.usuario_id = ? AND v.voto IS NULL",
        (bolsillo_id, usuario_id),
    ).fetchone()
    return fila is not None

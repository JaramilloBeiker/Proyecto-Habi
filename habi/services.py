"""Lógica de negocio: reglas de saldo, cargas y transferencias.

No usa input/print ni escribe SQL directamente (RNF-S-01). Recibe una
conexión ya abierta; cada hilo/proceso usa la suya.
Las funciones de cuenta reciben el `usuario` autenticado (RNF-SEC-01/02).
"""

import sqlite3

from habi import config, db, repository, security
from habi.dominio import (
    ErrorAutenticacion,
    ErrorValidacion,
    Movimiento,
    NoEncontrado,
    ResultadoOperacion,
    SaldoInsuficiente,
    Usuario,
)

MENSAJE_CREDENCIALES_INVALIDAS = "Usuario o contraseña incorrectos."


# ---------- Validaciones (RNF-U-03, RNF-D-02) ----------

def validar_monto(monto: object, campo: str = "monto") -> int:
    """Devuelve el monto como int si es válido; si no, lanza ErrorValidacion(campo, motivo).

    Reglas: entero (no bool, no float, no texto), entre
    config.MONTO_MINIMO y config.MONTO_MAXIMO, ambos inclusive.
    """
    # bool es subclase de int: True no puede colarse como 1 COP.
    if isinstance(monto, bool) or not isinstance(monto, int):
        raise ErrorValidacion(campo, "debe ser un número entero de pesos (sin decimales)")
    if monto < config.MONTO_MINIMO:
        raise ErrorValidacion(campo, f"debe ser mayor o igual a {config.MONTO_MINIMO}")
    if monto > config.MONTO_MAXIMO:
        raise ErrorValidacion(campo, f"no puede superar {config.MONTO_MAXIMO}")
    return monto


def validar_credenciales_registro(nombre: str, password: str) -> None:
    """Nombre no vacío; password con al menos config.LONGITUD_MINIMA_PASSWORD caracteres."""
    if not isinstance(nombre, str) or not nombre.strip():
        raise ErrorValidacion("nombre", "no puede estar vacío")
    if nombre.strip().upper() == "FONDEO":
        raise ErrorValidacion("nombre", "es un nombre reservado del sistema")
    if not isinstance(password, str) or len(password) < config.LONGITUD_MINIMA_PASSWORD:
        raise ErrorValidacion(
            "password", f"debe tener al menos {config.LONGITUD_MINIMA_PASSWORD} caracteres"
        )


def _cuenta_propia(conn: sqlite3.Connection, usuario: Usuario) -> int:
    """Id de la cuenta del usuario autenticado, leída de la BD (RNF-SEC-02).

    No se confía en `usuario.cuenta_id`: se resuelve a partir del id del usuario,
    así un objeto Usuario manipulado no permite operar sobre otra cuenta.
    """
    if not isinstance(usuario, Usuario):
        raise ErrorAutenticacion("Debes iniciar sesión.")
    cuenta = repository.obtener_cuenta_de_usuario(conn, usuario.id)
    if cuenta is None:
        raise ErrorAutenticacion("Debes iniciar sesión.")
    return cuenta["id"]


# ---------- Cuentas (RF-01, RF-02) ----------

def registrar_usuario(conn: sqlite3.Connection, nombre: str, password: str) -> Usuario:
    """RF-01. Valida, guarda el hash (security.hash_password) y crea la cuenta con saldo 0.

    Usuario y cuenta se crean en la misma transacción.
    Si el nombre ya existe -> ErrorValidacion('nombre', ...).
    """
    validar_credenciales_registro(nombre, password)
    nombre = nombre.strip()
    password_hash = security.hash_password(password)  # fuera de la transacción: es lento
    ahora = db.ahora_iso()
    try:
        with db.transaccion(conn):
            usuario_id = repository.crear_usuario(conn, nombre, password_hash, ahora)
            cuenta_id = repository.crear_cuenta_usuario(conn, usuario_id, ahora)
    except sqlite3.IntegrityError as e:
        if "usuarios.nombre" in str(e):
            raise ErrorValidacion("nombre", f"'{nombre}' ya está registrado") from e
        raise
    return Usuario(id=usuario_id, nombre=nombre, cuenta_id=cuenta_id)


def iniciar_sesion(conn: sqlite3.Connection, nombre: str, password: str) -> Usuario:
    """RF-02. Devuelve el Usuario si las credenciales son correctas; si no, ErrorAutenticacion.

    Usar el mismo mensaje para "no existe" y "contraseña incorrecta".
    """
    fila = repository.obtener_usuario_por_nombre(conn, (nombre or "").strip())
    if fila is None or not security.verificar_password(password or "", fila["password_hash"]):
        raise ErrorAutenticacion(MENSAJE_CREDENCIALES_INVALIDAS)
    return Usuario(id=fila["id"], nombre=fila["nombre"], cuenta_id=fila["cuenta_id"])


# ---------- Saldo e historial (RF-05, RF-06) ----------

def consultar_saldo(conn: sqlite3.Connection, usuario: Usuario) -> int:
    """RF-05. Saldo en COP de la cuenta del usuario autenticado."""
    return repository.obtener_saldo(conn, _cuenta_propia(conn, usuario))


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
    monto = validar_monto(monto)
    cuenta_id = _cuenta_propia(conn, usuario)
    ahora = db.ahora_iso()
    with db.transaccion(conn):
        fondeo_id = repository.obtener_cuenta_fondeo_id(conn)
        operacion_id = repository.crear_operacion(conn, "CARGA", monto, ahora)
        repository.crear_movimiento(conn, operacion_id, fondeo_id, -monto, ahora)
        repository.crear_movimiento(conn, operacion_id, cuenta_id, monto, ahora)
        repository.ajustar_saldo(conn, fondeo_id, -monto)
        repository.ajustar_saldo(conn, cuenta_id, monto)
    return ResultadoOperacion(operacion_id=operacion_id, tipo="CARGA", monto=monto, creada_en=ahora)


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
    monto = validar_monto(monto)
    if not isinstance(clave_idempotencia, str) or not clave_idempotencia.strip():
        raise ErrorValidacion("clave_idempotencia", "es obligatoria")
    origen_id = _cuenta_propia(conn, usuario)
    destino = repository.obtener_usuario_por_nombre(conn, (nombre_destino or "").strip())
    if destino is None:
        raise NoEncontrado(f"El usuario destino '{nombre_destino}' no existe.")
    if destino["cuenta_id"] == origen_id:
        raise ErrorValidacion("destino", "no puedes transferirte a ti mismo")

    ahora = db.ahora_iso()
    with db.transaccion(conn):
        previa = repository.obtener_operacion_por_clave(conn, clave_idempotencia)
        if previa is not None:
            return _resultado_repetido(conn, previa, origen_id, destino["cuenta_id"], monto)
        if not repository.debitar_si_alcanza(conn, origen_id, monto):
            raise SaldoInsuficiente(
                f"Saldo insuficiente: tienes {repository.obtener_saldo(conn, origen_id)} COP "
                f"y quieres transferir {monto} COP."
            )
        repository.ajustar_saldo(conn, destino["cuenta_id"], monto)
        operacion_id = repository.crear_operacion(conn, "TRANSFERENCIA", monto, ahora, clave_idempotencia)
        repository.crear_movimiento(conn, operacion_id, origen_id, -monto, ahora)
        repository.crear_movimiento(conn, operacion_id, destino["cuenta_id"], monto, ahora)
    return ResultadoOperacion(
        operacion_id=operacion_id,
        tipo="TRANSFERENCIA",
        monto=monto,
        creada_en=ahora,
        clave_idempotencia=clave_idempotencia,
    )


def _resultado_repetido(
    conn: sqlite3.Connection, previa: sqlite3.Row, origen_id: int, destino_id: int, monto: int
) -> ResultadoOperacion:
    """RNF-R-03: la clave ya se usó. Solo se devuelve el resultado original si
    corresponde a la misma transferencia; reutilizar una clave para otra cosa es un error."""
    cuentas = {
        fila["cuenta_id"]: fila["monto"] for fila in repository.movimientos_de_operacion(conn, previa["id"])
    }
    misma = (
        previa["tipo"] == "TRANSFERENCIA"
        and previa["monto"] == monto
        and cuentas == {origen_id: -monto, destino_id: monto}
    )
    if not misma:
        raise ErrorValidacion("clave_idempotencia", "ya fue usada para otra operación")
    return ResultadoOperacion(
        operacion_id=previa["id"],
        tipo=previa["tipo"],
        monto=previa["monto"],
        creada_en=previa["creada_en"],
        clave_idempotencia=previa["clave_idempotencia"],
        repetida=True,
    )

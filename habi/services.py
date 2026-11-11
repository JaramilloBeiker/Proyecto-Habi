"""Lógica de negocio: reglas de saldo, cargas y transferencias.

No usa input/print ni escribe SQL directamente (RNF-S-01). Recibe una
conexión ya abierta; cada hilo/proceso usa la suya.
Las funciones de cuenta reciben el `usuario` autenticado (RNF-SEC-01/02).
"""

import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from habi import config, db, repository, security
from habi.formato import formatear_cop
from habi.dominio import (
    Bolsillo,
    ErrorAutenticacion,
    ErrorAutorizacion,
    ErrorValidacion,
    Invitacion,
    MiembroBolsillo,
    Movimiento,
    NoEncontrado,
    OperacionNoPermitida,
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
        raise ErrorValidacion(campo, f"debe ser mayor o igual a {formatear_cop(config.MONTO_MINIMO)}")
    if monto > config.MONTO_MAXIMO:
        raise ErrorValidacion(campo, f"no puede superar {formatear_cop(config.MONTO_MAXIMO)}")
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


# ---------- Sesiones (RF-02, RNF-SEC-01) ----------

def crear_sesion(conn: sqlite3.Connection, usuario: Usuario) -> str:
    """Abre una sesión para el usuario y devuelve su token (va dentro de la cookie firmada)."""
    token = secrets.token_urlsafe(32)
    expira = datetime.now(timezone.utc) + timedelta(minutes=config.DURACION_SESION_MINUTOS)
    with db.transaccion(conn):
        repository.crear_sesion(conn, token, usuario.id, expira.isoformat(timespec="seconds"))
    return token


def usuario_de_sesion(conn: sqlite3.Connection, token: str | None) -> Usuario:
    """Devuelve el usuario dueño del token. Si no existe o expiró -> ErrorAutenticacion."""
    if not token:
        raise ErrorAutenticacion("Debes iniciar sesión.")
    fila = repository.obtener_sesion(conn, token)
    if fila is None:
        raise ErrorAutenticacion("Debes iniciar sesión.")
    if datetime.fromisoformat(fila["expira_en"]) <= datetime.now(timezone.utc):
        cerrar_sesion(conn, token)
        raise ErrorAutenticacion("Tu sesión expiró. Inicia sesión de nuevo.")
    return Usuario(id=fila["usuario_id"], nombre=fila["nombre"], cuenta_id=fila["cuenta_id"])


def cerrar_sesion(conn: sqlite3.Connection, token: str | None) -> None:
    """Borra la sesión: la cookie anterior deja de dar acceso."""
    if token:
        with db.transaccion(conn):
            repository.eliminar_sesion(conn, token)


# ---------- Saldo e historial (RF-05, RF-06) ----------

def consultar_saldo(conn: sqlite3.Connection, usuario: Usuario) -> int:
    """RF-05. Saldo en COP de la cuenta del usuario autenticado."""
    return repository.obtener_saldo(conn, _cuenta_propia(conn, usuario))


def consultar_historial(conn: sqlite3.Connection, usuario: Usuario, pagina: int = 0) -> list[Movimiento]:
    """RF-06. Bloque `pagina` (desde 0) de config.TAMANO_PAGINA_HISTORIAL movimientos, más reciente primero."""
    _validar_pagina(pagina)
    return _movimientos_de_cuenta(conn, _cuenta_propia(conn, usuario), pagina)


def _validar_pagina(pagina: object) -> None:
    if isinstance(pagina, bool) or not isinstance(pagina, int) or pagina < 0:
        raise ErrorValidacion("pagina", "debe ser un entero mayor o igual a 0")


def _movimientos_de_cuenta(conn: sqlite3.Connection, cuenta_id: int, pagina: int) -> list[Movimiento]:
    """Bloque `pagina` de movimientos de una cuenta (personal o de bolsillo)."""
    tamano = config.TAMANO_PAGINA_HISTORIAL
    filas = repository.listar_movimientos(conn, cuenta_id, tamano, pagina * tamano)
    return [
        Movimiento(
            id=f["id"],
            operacion_id=f["operacion_id"],
            tipo_operacion=f["tipo_operacion"],
            monto=f["monto"],
            contraparte=f["contraparte"],
            creado_en=f["creado_en"],
            contraparte_tipo=f["contraparte_tipo"],
        )
        for f in filas
    ]


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
    if not isinstance(nombre_destino, str) or not nombre_destino.strip():
        raise ErrorValidacion("destino", "es obligatorio")
    origen_id = _cuenta_propia(conn, usuario)
    destino = repository.obtener_usuario_por_nombre(conn, (nombre_destino or "").strip())
    if destino is None:
        raise NoEncontrado(f"El usuario destino '{nombre_destino}' no existe.")
    if destino["cuenta_id"] == origen_id:
        raise ErrorValidacion("destino", "no puedes transferirte a ti mismo")

    with db.transaccion(conn):
        return _mover_dinero(conn, origen_id, destino["cuenta_id"], monto, clave_idempotencia)


def _mover_dinero(
    conn: sqlite3.Connection, origen_id: int, destino_id: int, monto: int, clave_idempotencia: str,
    verbo: str = "transferir",
) -> ResultadoOperacion:
    """Núcleo de una transferencia entre dos cuentas. Debe llamarse DENTRO de db.transaccion.

    Lo usan las transferencias entre personas y Juntia (aportes y retiros):
      1. si la clave ya existe -> resultado original con repetida=True (RNF-R-03)
      2. debitar_si_alcanza(origen); si False -> SaldoInsuficiente (rollback, sin movimientos)
      3. acreditar destino
      4. crear operación 'TRANSFERENCIA' y los dos movimientos (-monto / +monto)
    """
    ahora = db.ahora_iso()
    previa = repository.obtener_operacion_por_clave(conn, clave_idempotencia)
    if previa is not None:
        return _resultado_repetido(conn, previa, origen_id, destino_id, monto)
    if not repository.debitar_si_alcanza(conn, origen_id, monto):
        raise SaldoInsuficiente(
            f"Saldo insuficiente: tienes {formatear_cop(repository.obtener_saldo(conn, origen_id))} "
            f"y quieres {verbo} {formatear_cop(monto)}."
        )
    repository.ajustar_saldo(conn, destino_id, monto)
    operacion_id = repository.crear_operacion(conn, "TRANSFERENCIA", monto, ahora, clave_idempotencia)
    repository.crear_movimiento(conn, operacion_id, origen_id, -monto, ahora)
    repository.crear_movimiento(conn, operacion_id, destino_id, monto, ahora)
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


# ---------- Juntia: bolsillos, miembros e invitaciones ----------
#
# Un bolsillo es una cuenta compartida (tipo BOLSILLO). Quien lo crea queda como
# miembro ACTIVO; a los demás se les invita y deben aceptar para ver el saldo.

def _validar_datos_bolsillo(nombre: object, meta: object) -> tuple[str, int]:
    if not isinstance(nombre, str) or not nombre.strip():
        raise ErrorValidacion("nombre", "no puede estar vacío")
    nombre = nombre.strip()
    if len(nombre) > config.LONGITUD_MAXIMA_NOMBRE_BOLSILLO:
        raise ErrorValidacion(
            "nombre", f"no puede tener más de {config.LONGITUD_MAXIMA_NOMBRE_BOLSILLO} caracteres"
        )
    if isinstance(meta, bool) or not isinstance(meta, int):
        raise ErrorValidacion("meta", "debe ser un número entero de pesos (sin decimales)")
    if meta < config.MONTO_MINIMO:
        raise ErrorValidacion("meta", f"debe ser mayor o igual a {formatear_cop(config.MONTO_MINIMO)}")
    if meta > config.META_MAXIMA_BOLSILLO:
        raise ErrorValidacion("meta", f"no puede superar {formatear_cop(config.META_MAXIMA_BOLSILLO)}")
    return nombre, meta


def _bolsillo_de_miembro_activo(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int) -> sqlite3.Row:
    """Devuelve el bolsillo si el usuario es miembro activo; si no, el error adecuado.

    A quien no fue invitado se le responde que no existe, para no revelar bolsillos ajenos.
    """
    _cuenta_propia(conn, usuario)  # exige sesión válida
    bolsillo = repository.obtener_bolsillo(conn, bolsillo_id)
    estado = repository.obtener_estado_miembro(conn, bolsillo_id, usuario.id) if bolsillo else None
    if bolsillo is None or estado is None:
        raise NoEncontrado("El bolsillo no existe.")
    if estado == "INVITADO":
        raise ErrorAutorizacion("Debes aceptar la invitación para ver este bolsillo.")
    if estado != "ACTIVO":
        raise ErrorAutorizacion("Ya no eres miembro de este bolsillo.")
    return bolsillo


def _a_bolsillo(fila: sqlite3.Row, reservado: int = 0) -> Bolsillo:
    return Bolsillo(
        id=fila["id"],
        nombre=fila["nombre"],
        meta=fila["meta"],
        saldo=fila["saldo"],
        reservado=reservado,
        creador=fila["creador"],
        creado_en=fila["creado_en"],
    )


def crear_bolsillo(conn: sqlite3.Connection, usuario: Usuario, nombre: str, meta: int) -> Bolsillo:
    """Crea el bolsillo con su cuenta (saldo 0) y deja al creador como miembro ACTIVO."""
    nombre, meta = _validar_datos_bolsillo(nombre, meta)
    _cuenta_propia(conn, usuario)
    ahora = db.ahora_iso()
    with db.transaccion(conn):
        cuenta_id = repository.crear_cuenta_bolsillo(conn, ahora)
        bolsillo_id = repository.crear_bolsillo(conn, cuenta_id, nombre, meta, usuario.id, ahora)
        repository.guardar_miembro(conn, bolsillo_id, usuario.id, "ACTIVO", None, ahora)
    return ver_bolsillo(conn, usuario, bolsillo_id)


def ver_bolsillo(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int) -> Bolsillo:
    """Detalle del bolsillo con su saldo. Solo para miembros activos."""
    return _a_bolsillo(_bolsillo_de_miembro_activo(conn, usuario, bolsillo_id))


def listar_bolsillos(conn: sqlite3.Connection, usuario: Usuario) -> list[Bolsillo]:
    """Bolsillos donde el usuario es miembro activo."""
    _cuenta_propia(conn, usuario)
    return [_a_bolsillo(f) for f in repository.listar_bolsillos_activos(conn, usuario.id)]


def listar_invitaciones(conn: sqlite3.Connection, usuario: Usuario) -> list[Invitacion]:
    """Invitaciones pendientes del usuario (sin saldo: aún no las acepta)."""
    _cuenta_propia(conn, usuario)
    return [
        Invitacion(
            bolsillo_id=f["bolsillo_id"],
            bolsillo_nombre=f["bolsillo_nombre"],
            invitado_por=f["invitado_por"],
            fecha=f["fecha"],
        )
        for f in repository.listar_invitaciones(conn, usuario.id)
    ]


def miembros_de_bolsillo(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int) -> list[MiembroBolsillo]:
    """Miembros activos e invitados pendientes. Solo para miembros activos."""
    _bolsillo_de_miembro_activo(conn, usuario, bolsillo_id)
    return [
        MiembroBolsillo(nombre=f["nombre"], estado=f["estado"], aportado=f["aportado"])
        for f in repository.listar_miembros(conn, bolsillo_id)
    ]


def invitar_a_bolsillo(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int, nombre_invitado: str) -> None:
    """Un miembro activo invita a otro usuario de Habi.

    Se puede volver a invitar a quien rechazó o salió; no a quien ya es miembro
    o tiene una invitación pendiente.
    """
    if not isinstance(nombre_invitado, str) or not nombre_invitado.strip():
        raise ErrorValidacion("invitado", "es obligatorio")
    nombre_invitado = nombre_invitado.strip()
    _bolsillo_de_miembro_activo(conn, usuario, bolsillo_id)
    invitado = repository.obtener_usuario_por_nombre(conn, nombre_invitado)
    if invitado is None:
        raise NoEncontrado(f"El usuario '{nombre_invitado}' no existe.")

    ahora = db.ahora_iso()
    with db.transaccion(conn):
        estado = repository.obtener_estado_miembro(conn, bolsillo_id, invitado["id"])
        if estado == "ACTIVO":
            raise ErrorValidacion("invitado", "ya es miembro del bolsillo")
        if estado == "INVITADO":
            raise ErrorValidacion("invitado", "ya tiene una invitación pendiente")
        repository.guardar_miembro(conn, bolsillo_id, invitado["id"], "INVITADO", usuario.id, ahora)


def _responder_invitacion(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int, estado_nuevo: str) -> None:
    _cuenta_propia(conn, usuario)
    if repository.obtener_bolsillo(conn, bolsillo_id) is None:
        raise NoEncontrado("El bolsillo no existe.")
    with db.transaccion(conn):
        cambiado = repository.cambiar_estado_miembro(
            conn, bolsillo_id, usuario.id, "INVITADO", estado_nuevo, db.ahora_iso()
        )
        if not cambiado:
            raise OperacionNoPermitida("No tienes una invitación pendiente para este bolsillo.")


def aceptar_invitacion(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int) -> Bolsillo:
    """El invitado pasa a miembro ACTIVO y desde ahí puede ver el saldo."""
    _responder_invitacion(conn, usuario, bolsillo_id, "ACTIVO")
    return ver_bolsillo(conn, usuario, bolsillo_id)


def rechazar_invitacion(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int) -> None:
    _responder_invitacion(conn, usuario, bolsillo_id, "RECHAZADO")


# ---------- Juntia: aportes, historial y salida ----------

def aportar_a_bolsillo(
    conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int, monto: int, clave_idempotencia: str
) -> ResultadoOperacion:
    """Un miembro activo pasa dinero de su cuenta personal al bolsillo.

    Es una transferencia normal hacia la cuenta del bolsillo: misma validación de
    monto, misma verificación de saldo y misma clave de idempotencia (RNF-R-03).
    """
    monto = validar_monto(monto)
    if not isinstance(clave_idempotencia, str) or not clave_idempotencia.strip():
        raise ErrorValidacion("clave_idempotencia", "es obligatoria")
    bolsillo = _bolsillo_de_miembro_activo(conn, usuario, bolsillo_id)
    origen_id = _cuenta_propia(conn, usuario)
    with db.transaccion(conn):
        # Se vuelve a mirar dentro de la transacción: pudo haber salido del bolsillo justo antes.
        if repository.obtener_estado_miembro(conn, bolsillo_id, usuario.id) != "ACTIVO":
            raise ErrorAutorizacion("Ya no eres miembro de este bolsillo.")
        return _mover_dinero(conn, origen_id, bolsillo["cuenta_id"], monto, clave_idempotencia, "aportar")


def historial_bolsillo(
    conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int, pagina: int = 0
) -> list[Movimiento]:
    """Movimientos del bolsillo (aportes y retiros), más reciente primero. Solo miembros activos."""
    _validar_pagina(pagina)
    bolsillo = _bolsillo_de_miembro_activo(conn, usuario, bolsillo_id)
    return _movimientos_de_cuenta(conn, bolsillo["cuenta_id"], pagina)


def salir_de_bolsillo(conn: sqlite3.Connection, usuario: Usuario, bolsillo_id: int) -> None:
    """Un miembro activo deja el bolsillo. Quien ya aportó no puede salir."""
    bolsillo = _bolsillo_de_miembro_activo(conn, usuario, bolsillo_id)
    cuenta_id = _cuenta_propia(conn, usuario)
    with db.transaccion(conn):
        if repository.total_aportado(conn, bolsillo["cuenta_id"], cuenta_id) > 0:
            raise OperacionNoPermitida("Ya aportaste a este bolsillo, así que no puedes salir.")
        if not repository.cambiar_estado_miembro(conn, bolsillo_id, usuario.id, "ACTIVO", "SALIO", db.ahora_iso()):
            raise ErrorAutorizacion("Ya no eres miembro de este bolsillo.")

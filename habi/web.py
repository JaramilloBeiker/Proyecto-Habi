"""Rutas web con Flask (API JSON).

Esta capa solo traduce HTTP <-> services: lee los datos de la petición,
llama a la función de negocio y devuelve JSON. No tiene reglas de dinero
ni SQL (RNF-S-01).

Respuestas:
    éxito -> {"ok": true, "mensaje": "...", ...datos}
    error -> {"ok": false, "error": "motivo", "campo": "monto" | null}   (RNF-U-01, RNF-U-03)
"""

import uuid
from datetime import timedelta

from flask import Blueprint, Flask, current_app, g, jsonify, request, session

from habi import config, db, services
from habi.dominio import (
    ErrorAutenticacion,
    ErrorAutorizacion,
    ErrorValidacion,
    HabiError,
    NoEncontrado,
    OperacionNoPermitida,
    SaldoInsuficiente,
)
from habi.formato import formatear_cop

api = Blueprint("api", __name__, url_prefix="/api")


# ---------- Creación de la app ----------

def crear_app(ruta_db=None, secret_key=None) -> Flask:
    """Crea la aplicación Flask. Las pruebas pasan su propia base de datos."""
    app = Flask(__name__)
    app.config["DB_PATH"] = ruta_db or config.DB_PATH
    app.config["SECRET_KEY"] = secret_key or config.SECRET_KEY
    # RNF-SEC-01: cookie firmada que expira a los 60 minutos.
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=config.DURACION_SESION_MINUTOS)
    app.config["SESSION_COOKIE_HTTPONLY"] = True
    app.config["SESSION_COOKIE_SAMESITE"] = "Lax"

    # Crea las tablas y la cuenta de fondeo si no existen.
    conn = db.conectar(app.config["DB_PATH"])
    db.inicializar(conn)
    conn.close()

    app.register_blueprint(api)
    # Páginas HTML. Se importa aquí porque paginas.py usa utilidades de este módulo.
    from habi.paginas import paginas

    app.register_blueprint(paginas)
    app.add_template_filter(formatear_cop, "cop")
    app.teardown_appcontext(cerrar_conexion)
    app.register_error_handler(HabiError, manejar_error_negocio)
    return app


# ---------- Utilidades ----------

def obtener_conexion():
    """Una conexión SQLite por petición (cada hilo usa la suya)."""
    if "conn" not in g:
        g.conn = db.conectar(current_app.config["DB_PATH"])
    return g.conn


def cerrar_conexion(_error=None) -> None:
    conn = g.pop("conn", None)
    if conn is not None:
        conn.close()


def leer_datos() -> dict:
    """Cuerpo de la petición como dict. Acepta JSON o formulario HTML."""
    datos = request.get_json(silent=True)
    if isinstance(datos, dict):
        return datos
    return request.form.to_dict()


def leer_texto(datos: dict, campo: str) -> str:
    """Devuelve el campo como texto; si no viene o no es texto, ''."""
    valor = datos.get(campo, "")
    return valor if isinstance(valor, str) else ""


def leer_entero(valor, campo: str):
    """Convierte texto de un formulario ('50000') a int.

    Si el texto no es un entero sin signo ni separadores -> ErrorValidacion(campo).
    Si ya viene como número (JSON), se deja igual: el rango y los decimales
    los valida services.validar_monto.
    """
    if isinstance(valor, str):
        texto = valor.strip()
        if not (texto.isascii() and texto.isdigit()):
            raise ErrorValidacion(campo, "debe ser un número entero positivo, sin decimales ni separadores")
        return int(texto)
    return valor


def movimiento_a_dict(m) -> dict:
    """Movimiento listo para mostrar: monto con signo y en COP, fecha ISO 8601."""
    return {
        "id": m.id,
        "operacion_id": m.operacion_id,
        "tipo": m.tipo_operacion,
        "monto": m.monto,
        "monto_cop": ("+" if m.monto > 0 else "") + formatear_cop(m.monto),
        "contraparte": m.contraparte,
        "contraparte_tipo": m.contraparte_tipo,
        "fecha": m.creado_en,
    }


def leer_clave(datos: dict) -> str:
    """Clave de idempotencia del formulario. Debe ser un uuid4 entregado por el sistema (RNF-R-03)."""
    clave = leer_texto(datos, "clave_idempotencia").strip()
    try:
        uuid.UUID(clave)
    except ValueError:
        raise ErrorValidacion("clave_idempotencia", "no es válida; pide una nueva al sistema")
    return clave


def bolsillo_a_dict(b) -> dict:
    return {
        "id": b.id,
        "nombre": b.nombre,
        "meta": b.meta,
        "saldo": b.saldo,
        "reservado": b.reservado,
        "disponible": b.disponible,
        "saldo_cop": formatear_cop(b.saldo),
        "disponible_cop": formatear_cop(b.disponible),
        "creador": b.creador,
        "creado_en": b.creado_en,
    }


def retiro_a_dict(r) -> dict:
    return {
        "id": r.id,
        "monto": r.monto,
        "monto_cop": formatear_cop(r.monto),
        "destino": r.destino,
        "proponente": r.proponente,
        "motivo": r.motivo,
        "estado": r.estado,
        "creado_en": r.creado_en,
        "expira_en": r.expira_en,
        "cerrado_en": r.cerrado_en,
        "votos": [{"nombre": v.nombre, "voto": v.voto} for v in r.votos],
    }


def abrir_sesion(conn, usuario) -> None:
    """Guarda en la cookie firmada el token de una sesión nueva (RF-02).

    Si ya había una sesión en este navegador, se cierra antes de abrir la nueva.
    """
    services.cerrar_sesion(conn, session.get("token"))
    session.clear()
    session.permanent = True
    session["token"] = services.crear_sesion(conn, usuario)


def usuario_actual():
    """Usuario de la sesión iniciada. Sin sesión válida -> ErrorAutenticacion (401)."""
    return services.usuario_de_sesion(obtener_conexion(), session.get("token"))


def respuesta_ok(mensaje: str, codigo: int = 200, **datos):
    return jsonify({"ok": True, "mensaje": mensaje, **datos}), codigo


def manejar_error_negocio(error: HabiError):
    """Convierte los errores de negocio en JSON con el motivo y el código HTTP adecuado."""
    if isinstance(error, ErrorValidacion):
        codigo = 400
    elif isinstance(error, ErrorAutenticacion):
        codigo = 401
    elif isinstance(error, ErrorAutorizacion):
        codigo = 403
    elif isinstance(error, NoEncontrado):
        codigo = 404
    elif isinstance(error, (SaldoInsuficiente, OperacionNoPermitida)):
        codigo = 409
    else:
        codigo = 400
    campo = getattr(error, "campo", None)
    return jsonify({"ok": False, "error": str(error), "campo": campo}), codigo


# ---------- Registro y sesión (RF-01, RF-02) ----------

@api.post("/registro")
def registro():
    datos = leer_datos()
    usuario = services.registrar_usuario(
        obtener_conexion(), leer_texto(datos, "nombre"), leer_texto(datos, "password")
    )
    return respuesta_ok(
        f"Cuenta creada para '{usuario.nombre}'.", 201, usuario={"nombre": usuario.nombre}
    )


@api.post("/login")
def login():
    datos = leer_datos()
    conn = obtener_conexion()
    usuario = services.iniciar_sesion(conn, leer_texto(datos, "nombre"), leer_texto(datos, "password"))
    abrir_sesion(conn, usuario)
    return respuesta_ok(f"Bienvenido, {usuario.nombre}.", usuario={"nombre": usuario.nombre})


@api.post("/logout")
def logout():
    services.cerrar_sesion(obtener_conexion(), session.get("token"))
    session.clear()
    return respuesta_ok("Sesión cerrada.")


@api.get("/sesion")
def sesion_actual():
    usuario = usuario_actual()
    return respuesta_ok("Sesión activa.", usuario={"nombre": usuario.nombre})


# ---------- Saldo, carga e historial (RF-03, RF-05, RF-06) ----------

@api.get("/saldo")
def saldo():
    saldo_actual = services.consultar_saldo(obtener_conexion(), usuario_actual())
    return respuesta_ok("Saldo consultado.", saldo=saldo_actual, saldo_cop=formatear_cop(saldo_actual))


@api.post("/cargas")
def cargar():
    usuario = usuario_actual()
    monto = leer_entero(leer_datos().get("monto"), "monto")
    conn = obtener_conexion()
    resultado = services.cargar_saldo(conn, usuario, monto)
    saldo_actual = services.consultar_saldo(conn, usuario)
    return respuesta_ok(
        f"Carga de {formatear_cop(resultado.monto)} registrada.",
        201,
        operacion_id=resultado.operacion_id,
        monto=resultado.monto,
        fecha=resultado.creada_en,
        saldo=saldo_actual,
        saldo_cop=formatear_cop(saldo_actual),
    )


@api.get("/historial")
def historial():
    usuario = usuario_actual()
    pagina = leer_entero(request.args.get("pagina", "0"), "pagina")
    movimientos = services.consultar_historial(obtener_conexion(), usuario, pagina)
    return respuesta_ok(
        "Historial consultado.",
        pagina=pagina,
        tamano_pagina=config.TAMANO_PAGINA_HISTORIAL,
        hay_mas=len(movimientos) == config.TAMANO_PAGINA_HISTORIAL,
        movimientos=[movimiento_a_dict(m) for m in movimientos],
    )


# ---------- Transferencias (RF-04, RNF-R-03) ----------

@api.get("/transferencias/nueva")
def nueva_transferencia():
    """Entrega la clave única que el formulario de transferencia debe reenviar (RNF-R-03)."""
    usuario_actual()
    return respuesta_ok("Clave de transferencia generada.", clave_idempotencia=str(uuid.uuid4()))


@api.post("/transferencias")
def transferir():
    usuario = usuario_actual()
    datos = leer_datos()
    destino = leer_texto(datos, "destino")
    monto = leer_entero(datos.get("monto"), "monto")
    clave = leer_clave(datos)

    conn = obtener_conexion()
    resultado = services.transferir(conn, usuario, destino, monto, clave)
    saldo_actual = services.consultar_saldo(conn, usuario)
    if resultado.repetida:
        mensaje = "Esta transferencia ya se había realizado; no se repitió."
    else:
        mensaje = f"Transferencia de {formatear_cop(resultado.monto)} a '{destino.strip()}' realizada."
    return respuesta_ok(
        mensaje,
        200 if resultado.repetida else 201,
        operacion_id=resultado.operacion_id,
        monto=resultado.monto,
        fecha=resultado.creada_en,
        clave_idempotencia=resultado.clave_idempotencia,
        repetida=resultado.repetida,
        saldo=saldo_actual,
        saldo_cop=formatear_cop(saldo_actual),
    )


# ---------- Juntia: bolsillos compartidos ----------

@api.get("/juntias")
def juntias():
    usuario = usuario_actual()
    conn = obtener_conexion()
    return respuesta_ok(
        "Bolsillos consultados.",
        bolsillos=[bolsillo_a_dict(b) for b in services.listar_bolsillos(conn, usuario)],
        invitaciones=[
            {"bolsillo_id": i.bolsillo_id, "bolsillo": i.bolsillo_nombre, "invitado_por": i.invitado_por, "fecha": i.fecha}
            for i in services.listar_invitaciones(conn, usuario)
        ],
    )


@api.post("/juntias")
def crear_juntia():
    usuario = usuario_actual()
    datos = leer_datos()
    meta = leer_entero(datos.get("meta"), "meta")
    bolsillo = services.crear_bolsillo(obtener_conexion(), usuario, leer_texto(datos, "nombre"), meta)
    return respuesta_ok(f"Bolsillo '{bolsillo.nombre}' creado.", 201, bolsillo=bolsillo_a_dict(bolsillo))


@api.get("/juntias/<int:bolsillo_id>")
def ver_juntia(bolsillo_id):
    usuario = usuario_actual()
    conn = obtener_conexion()
    bolsillo = services.ver_bolsillo(conn, usuario, bolsillo_id)
    return respuesta_ok(
        "Bolsillo consultado.",
        bolsillo=bolsillo_a_dict(bolsillo),
        miembros=[
            {"nombre": m.nombre, "estado": m.estado, "aportado": m.aportado}
            for m in services.miembros_de_bolsillo(conn, usuario, bolsillo_id)
        ],
        retiros=[retiro_a_dict(r) for r in services.listar_retiros(conn, usuario, bolsillo_id)],
    )


@api.post("/juntias/<int:bolsillo_id>/invitaciones")
def invitar(bolsillo_id):
    usuario = usuario_actual()
    invitado = leer_texto(leer_datos(), "invitado")
    services.invitar_a_bolsillo(obtener_conexion(), usuario, bolsillo_id, invitado)
    return respuesta_ok(f"Invitación enviada a '{invitado.strip()}'.", 201)


@api.post("/juntias/<int:bolsillo_id>/aceptar")
def aceptar(bolsillo_id):
    bolsillo = services.aceptar_invitacion(obtener_conexion(), usuario_actual(), bolsillo_id)
    return respuesta_ok(f"Ahora eres miembro de '{bolsillo.nombre}'.", bolsillo=bolsillo_a_dict(bolsillo))


@api.post("/juntias/<int:bolsillo_id>/rechazar")
def rechazar(bolsillo_id):
    services.rechazar_invitacion(obtener_conexion(), usuario_actual(), bolsillo_id)
    return respuesta_ok("Invitación rechazada.")


@api.post("/juntias/<int:bolsillo_id>/salir")
def salir_de_juntia(bolsillo_id):
    services.salir_de_bolsillo(obtener_conexion(), usuario_actual(), bolsillo_id)
    return respuesta_ok("Saliste del bolsillo.")


@api.get("/juntias/<int:bolsillo_id>/aportes/nueva")
def nuevo_aporte(bolsillo_id):
    """Clave única que el formulario de aporte debe reenviar (RNF-R-03)."""
    services.ver_bolsillo(obtener_conexion(), usuario_actual(), bolsillo_id)
    return respuesta_ok("Clave de aporte generada.", clave_idempotencia=str(uuid.uuid4()))


@api.post("/juntias/<int:bolsillo_id>/aportes")
def aportar(bolsillo_id):
    usuario = usuario_actual()
    datos = leer_datos()
    monto = leer_entero(datos.get("monto"), "monto")
    clave = leer_clave(datos)
    conn = obtener_conexion()
    resultado = services.aportar_a_bolsillo(conn, usuario, bolsillo_id, monto, clave)
    bolsillo = services.ver_bolsillo(conn, usuario, bolsillo_id)
    if resultado.repetida:
        mensaje = "Este aporte ya se había realizado; no se repitió."
    else:
        mensaje = f"Aporte de {formatear_cop(resultado.monto)} a '{bolsillo.nombre}' realizado."
    return respuesta_ok(
        mensaje,
        200 if resultado.repetida else 201,
        operacion_id=resultado.operacion_id,
        monto=resultado.monto,
        repetida=resultado.repetida,
        bolsillo=bolsillo_a_dict(bolsillo),
    )


@api.get("/juntias/<int:bolsillo_id>/historial")
def historial_juntia(bolsillo_id):
    usuario = usuario_actual()
    pagina = leer_entero(request.args.get("pagina", "0"), "pagina")
    movimientos = services.historial_bolsillo(obtener_conexion(), usuario, bolsillo_id, pagina)
    return respuesta_ok(
        "Historial del bolsillo consultado.",
        pagina=pagina,
        tamano_pagina=config.TAMANO_PAGINA_HISTORIAL,
        hay_mas=len(movimientos) == config.TAMANO_PAGINA_HISTORIAL,
        movimientos=[movimiento_a_dict(m) for m in movimientos],
    )


@api.post("/juntias/<int:bolsillo_id>/retiros")
def proponer_retiro(bolsillo_id):
    usuario = usuario_actual()
    datos = leer_datos()
    monto = leer_entero(datos.get("monto"), "monto")
    retiro = services.proponer_retiro(
        obtener_conexion(), usuario, bolsillo_id, leer_texto(datos, "destino"), monto, leer_texto(datos, "motivo")
    )
    if retiro.estado == "EJECUTADO":
        mensaje = f"Retiro de {formatear_cop(retiro.monto)} a '{retiro.destino}' realizado."
    else:
        mensaje = f"Retiro de {formatear_cop(retiro.monto)} propuesto; espera los votos de los demás miembros."
    return respuesta_ok(mensaje, 201, retiro=retiro_a_dict(retiro))


@api.post("/juntias/<int:bolsillo_id>/retiros/<int:retiro_id>/votos")
def votar(bolsillo_id, retiro_id):
    usuario = usuario_actual()
    voto = leer_texto(leer_datos(), "voto").strip().upper()
    retiro = services.votar_retiro(obtener_conexion(), usuario, bolsillo_id, retiro_id, voto)
    return respuesta_ok(mensaje_de_voto(retiro), retiro=retiro_a_dict(retiro))


def mensaje_de_voto(retiro) -> str:
    """Texto para el usuario según cómo quedó el retiro después de su voto."""
    if retiro.estado == "EJECUTADO":
        return f"Todos votaron a favor: se enviaron {formatear_cop(retiro.monto)} a {retiro.destino}."
    if retiro.estado == "RECHAZADO":
        return "Votaste en contra: el retiro se canceló y el dinero reservado quedó libre."
    return "Voto registrado; faltan votos de otros miembros."

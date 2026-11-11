"""Rutas web con Flask (API JSON).

Esta capa solo traduce HTTP <-> services: lee los datos de la petición,
llama a la función de negocio y devuelve JSON. No tiene reglas de dinero
ni SQL (RNF-S-01).

Respuestas:
    éxito -> {"ok": true, "mensaje": "...", ...datos}
    error -> {"ok": false, "error": "motivo", "campo": "monto" | null}   (RNF-U-01, RNF-U-03)
"""

from datetime import timedelta

from flask import Blueprint, Flask, current_app, g, jsonify, request, session

from habi import config, db, services
from habi.dominio import (
    ErrorAutenticacion,
    ErrorAutorizacion,
    ErrorValidacion,
    HabiError,
    NoEncontrado,
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
        "fecha": m.creado_en,
    }


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
    elif isinstance(error, SaldoInsuficiente):
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
    # Si ya había una sesión en este navegador, se cierra antes de abrir la nueva.
    services.cerrar_sesion(conn, session.get("token"))
    session.clear()
    session.permanent = True
    session["token"] = services.crear_sesion(conn, usuario)
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

"""Páginas HTML con plantillas Jinja2.

Igual que la API, esta capa no tiene reglas de dinero ni SQL (RNF-S-01):
lee el formulario, llama a services y muestra el resultado en la página.

Patrón de cada formulario:
    - si la operación sale bien -> mensaje de éxito y redirección (así recargar
      la página no reenvía el formulario);
    - si falla -> se vuelve a mostrar la página con el motivo y el campo marcado
      (RNF-U-01, RNF-U-03).
"""

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from habi import services
from habi.dominio import ErrorAutenticacion, ErrorValidacion, HabiError
from habi.formato import formatear_cop
from habi.web import abrir_sesion, leer_entero, obtener_conexion

paginas = Blueprint("paginas", __name__)


# ---------- Utilidades ----------

def usuario_o_none():
    """Usuario de la sesión iniciada, o None si no hay sesión válida (RNF-SEC-01)."""
    token = session.get("token")
    if not token:
        return None
    try:
        return services.usuario_de_sesion(obtener_conexion(), token)
    except ErrorAutenticacion as error:
        session.clear()
        flash(str(error), "error")
        return None


def ir_a_entrar():
    return redirect(url_for("paginas.entrar"))


def errores_de(error: HabiError) -> dict:
    """Errores por campo para marcarlos en el formulario.

    Si el error no corresponde a un campo, se muestra como aviso general.
    """
    if isinstance(error, ErrorValidacion):
        flash("Revisa los datos marcados.", "error")
        return {error.campo: error.mensaje}
    flash(str(error), "error")
    return {}


# ---------- Inicio ----------

@paginas.get("/")
def inicio():
    if usuario_o_none() is None:
        return ir_a_entrar()
    return redirect(url_for("paginas.cuenta"))


# ---------- Acceso (RF-01, RF-02) ----------

@paginas.route("/registro", methods=["GET", "POST"])
def registro():
    if request.method == "GET":
        return render_template("registro.html", errores={}, nombre="")

    nombre = request.form.get("nombre", "")
    conn = obtener_conexion()
    try:
        usuario = services.registrar_usuario(conn, nombre, request.form.get("password", ""))
    except HabiError as error:
        return render_template("registro.html", errores=errores_de(error), nombre=nombre), 400

    abrir_sesion(conn, usuario)
    flash(f"Cuenta creada. Bienvenido, {usuario.nombre}.", "exito")
    return redirect(url_for("paginas.cuenta"))


@paginas.route("/entrar", methods=["GET", "POST"])
def entrar():
    if request.method == "GET":
        return render_template("entrar.html", nombre="")

    nombre = request.form.get("nombre", "")
    conn = obtener_conexion()
    try:
        usuario = services.iniciar_sesion(conn, nombre, request.form.get("password", ""))
    except HabiError as error:
        flash(str(error), "error")
        return render_template("entrar.html", nombre=nombre), 401

    abrir_sesion(conn, usuario)
    return redirect(url_for("paginas.cuenta"))


@paginas.post("/salir")
def salir():
    services.cerrar_sesion(obtener_conexion(), session.get("token"))
    session.clear()
    flash("Cerraste sesión.", "exito")
    return ir_a_entrar()


# ---------- Cuenta (RF-03, RF-05) ----------

def mostrar_cuenta(usuario, formulario=None, errores=None, valores=None, codigo=200):
    """Panel de la cuenta.

    `formulario` indica cuál formulario falló ('carga' o 'transferencia'),
    para marcar sus campos y conservar lo que el usuario escribió.
    """
    saldo = services.consultar_saldo(obtener_conexion(), usuario)
    return render_template(
        "cuenta.html",
        usuario=usuario,
        saldo=saldo,
        formulario=formulario,
        errores=errores or {},
        valores=valores or {},
    ), codigo


@paginas.get("/cuenta")
def cuenta():
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()
    return mostrar_cuenta(usuario)


@paginas.post("/cuenta/cargar")
def cargar():
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()

    texto_monto = request.form.get("monto", "")
    try:
        monto = leer_entero(texto_monto, "monto")
        resultado = services.cargar_saldo(obtener_conexion(), usuario, monto)
    except HabiError as error:
        return mostrar_cuenta(usuario, "carga", errores_de(error), {"monto": texto_monto}, 400)

    flash(f"Carga de {formatear_cop(resultado.monto)} registrada.", "exito")
    return redirect(url_for("paginas.cuenta"))

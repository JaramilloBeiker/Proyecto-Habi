"""Páginas HTML con plantillas Jinja2.

Igual que la API, esta capa no tiene reglas de dinero ni SQL (RNF-S-01):
lee el formulario, llama a services y muestra el resultado en la página.

Patrón de cada formulario:
    - si la operación sale bien -> mensaje de éxito y redirección (así recargar
      la página no reenvía el formulario);
    - si falla -> se vuelve a mostrar la página con el motivo y el campo marcado
      (RNF-U-01, RNF-U-03).
"""

import uuid

from flask import Blueprint, flash, redirect, render_template, request, session, url_for

from habi import config, services
from habi.dominio import ErrorAutenticacion, ErrorValidacion, HabiError, NoEncontrado
from habi.formato import formatear_cop
from habi.web import abrir_sesion, leer_entero, mensaje_de_voto, obtener_conexion

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


# ---------- Cuenta (RF-03, RF-04, RF-05) ----------

def mostrar_cuenta(usuario, formulario=None, errores=None, valores=None, codigo=200):
    """Panel de la cuenta.

    `formulario` indica cuál formulario falló ('carga' o 'transferencia'),
    para marcar sus campos y conservar lo que el usuario escribió.
    """
    valores = valores or {}
    conn = obtener_conexion()
    saldo = services.consultar_saldo(conn, usuario)
    recientes = services.consultar_historial(conn, usuario, 0)[:5]
    # RNF-R-03: cada formulario de transferencia lleva una clave única generada aquí.
    # Si el formulario falló se conserva su clave: esa transferencia no llegó a hacerse.
    clave = valores.get("clave_idempotencia") or str(uuid.uuid4())
    return render_template(
        "cuenta.html",
        usuario=usuario,
        saldo=saldo,
        recientes=recientes,
        clave=clave,
        formulario=formulario,
        errores=errores or {},
        valores=valores,
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


@paginas.post("/cuenta/transferir")
def transferir():
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()

    valores = {
        "destino": request.form.get("destino", ""),
        "monto": request.form.get("monto", ""),
        "clave_idempotencia": request.form.get("clave_idempotencia", ""),
    }
    try:
        try:
            uuid.UUID(valores["clave_idempotencia"])
        except ValueError:
            raise ErrorValidacion("clave_idempotencia", "no es válida")
        monto = leer_entero(valores["monto"], "monto")
        resultado = services.transferir(
            obtener_conexion(), usuario, valores["destino"], monto, valores["clave_idempotencia"]
        )
    except ErrorValidacion as error:
        if error.campo == "clave_idempotencia":
            # El formulario es viejo o ya se usó para otra cosa: se entrega uno con clave nueva.
            flash("Este formulario ya no es válido. Revisa los datos y envíalo de nuevo.", "error")
            valores["clave_idempotencia"] = ""
            return mostrar_cuenta(usuario, "transferencia", {}, valores, 400)
        return mostrar_cuenta(usuario, "transferencia", errores_de(error), valores, 400)
    except NoEncontrado:
        flash("Revisa los datos marcados.", "error")
        errores = {"destino": "no existe un usuario con ese nombre"}
        return mostrar_cuenta(usuario, "transferencia", errores, valores, 404)
    except HabiError as error:
        return mostrar_cuenta(usuario, "transferencia", errores_de(error), valores, 409)

    if resultado.repetida:
        flash("Esta transferencia ya se había realizado; no se repitió.", "exito")
    else:
        destino = valores["destino"].strip()
        flash(f"Transferencia de {formatear_cop(resultado.monto)} a {destino} realizada.", "exito")
    return redirect(url_for("paginas.cuenta"))


# ---------- Historial (RF-06) ----------

@paginas.get("/historial")
def historial():
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()

    try:
        pagina = leer_entero(request.args.get("pagina", "0"), "pagina")
        movimientos = services.consultar_historial(obtener_conexion(), usuario, pagina)
    except ErrorValidacion:
        flash("La página pedida no es válida.", "error")
        return redirect(url_for("paginas.historial"))

    return render_template(
        "historial.html",
        usuario=usuario,
        movimientos=movimientos,
        pagina=pagina,
        hay_mas=len(movimientos) == config.TAMANO_PAGINA_HISTORIAL,
    )


# ---------- Juntia: bolsillos compartidos ----------

@paginas.get("/juntias")
def juntias():
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()
    return mostrar_juntias(usuario)


def mostrar_juntias(usuario, errores=None, valores=None, codigo=200):
    """Lista de bolsillos del usuario, sus invitaciones y el formulario para crear uno."""
    conn = obtener_conexion()
    return render_template(
        "juntias.html",
        usuario=usuario,
        bolsillos=services.listar_bolsillos(conn, usuario),
        invitaciones=services.listar_invitaciones(conn, usuario),
        errores=errores or {},
        valores=valores or {},
    ), codigo


@paginas.post("/juntias/crear")
def crear_juntia():
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()

    valores = {"nombre": request.form.get("nombre", ""), "meta": request.form.get("meta", "")}
    try:
        meta = leer_entero(valores["meta"], "meta")
        bolsillo = services.crear_bolsillo(obtener_conexion(), usuario, valores["nombre"], meta)
    except HabiError as error:
        return mostrar_juntias(usuario, errores_de(error), valores, 400)

    flash(f"Bolsillo {bolsillo.nombre} creado. Ya puedes invitar a los demás.", "exito")
    return redirect(url_for("paginas.juntia", bolsillo_id=bolsillo.id))


@paginas.post("/juntias/<int:bolsillo_id>/aceptar")
def aceptar_juntia(bolsillo_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()
    try:
        bolsillo = services.aceptar_invitacion(obtener_conexion(), usuario, bolsillo_id)
    except HabiError as error:
        flash(str(error), "error")
        return redirect(url_for("paginas.juntias"))
    return volver_a_juntia(bolsillo_id, f"Ahora eres miembro de {bolsillo.nombre}.")


@paginas.post("/juntias/<int:bolsillo_id>/rechazar")
def rechazar_juntia(bolsillo_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()
    try:
        services.rechazar_invitacion(obtener_conexion(), usuario, bolsillo_id)
        flash("Rechazaste la invitación.", "exito")
    except HabiError as error:
        flash(str(error), "error")
    return redirect(url_for("paginas.juntias"))


def mostrar_juntia(usuario, bolsillo_id, formulario=None, errores=None, valores=None, codigo=200):
    """Detalle de un bolsillo. Como en el panel de cuenta, `formulario` indica cuál
    formulario falló ('aporte', 'retiro' o 'invitacion') para marcar sus campos."""
    valores = valores or {}
    conn = obtener_conexion()
    try:
        pagina = leer_entero(request.args.get("pagina", "0"), "pagina")
    except ErrorValidacion:
        pagina = 0
    bolsillo = services.ver_bolsillo(conn, usuario, bolsillo_id)
    movimientos = services.historial_bolsillo(conn, usuario, bolsillo_id, pagina)
    return render_template(
        "juntia.html",
        usuario=usuario,
        bolsillo=bolsillo,
        miembros=services.miembros_de_bolsillo(conn, usuario, bolsillo_id),
        retiros=services.listar_retiros(conn, usuario, bolsillo_id),
        movimientos=movimientos,
        pagina=pagina,
        hay_mas=len(movimientos) == config.TAMANO_PAGINA_HISTORIAL,
        # RNF-R-03: clave única por formulario de aporte (se conserva si el envío falló).
        clave=valores.get("clave_idempotencia") or str(uuid.uuid4()),
        dias_expiracion=config.DIAS_EXPIRACION_RETIRO,
        formulario=formulario,
        errores=errores or {},
        valores=valores,
    ), codigo


@paginas.get("/juntias/<int:bolsillo_id>")
def juntia(bolsillo_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()
    try:
        return mostrar_juntia(usuario, bolsillo_id)
    except HabiError as error:
        # No es miembro activo o el bolsillo no existe: vuelve a la lista con el motivo.
        flash(str(error), "error")
        return redirect(url_for("paginas.juntias"))


def volver_a_juntia(bolsillo_id, mensaje):
    flash(mensaje, "exito")
    return redirect(url_for("paginas.juntia", bolsillo_id=bolsillo_id))


def error_en_juntia(usuario, bolsillo_id, error, formulario, valores, codigo=409):
    """Muestra el detalle con el motivo del error; si ya no puede verlo, vuelve a la lista."""
    try:
        return mostrar_juntia(usuario, bolsillo_id, formulario, errores_de(error), valores, codigo)
    except HabiError as otro:
        flash(str(otro), "error")
        return redirect(url_for("paginas.juntias"))


def usuario_no_existe(usuario, bolsillo_id, campo, formulario, valores):
    """El nombre escrito no corresponde a ningún usuario: se marca el campo."""
    flash("Revisa los datos marcados.", "error")
    errores = {campo: "no existe un usuario con ese nombre"}
    return mostrar_juntia(usuario, bolsillo_id, formulario, errores, valores, 404)


@paginas.post("/juntias/<int:bolsillo_id>/aportar")
def aportar_juntia(bolsillo_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()

    valores = {
        "monto": request.form.get("monto", ""),
        "clave_idempotencia": request.form.get("clave_idempotencia", ""),
    }
    try:
        try:
            uuid.UUID(valores["clave_idempotencia"])
        except ValueError:
            raise ErrorValidacion("clave_idempotencia", "no es válida")
        monto = leer_entero(valores["monto"], "monto")
        resultado = services.aportar_a_bolsillo(
            obtener_conexion(), usuario, bolsillo_id, monto, valores["clave_idempotencia"]
        )
    except ErrorValidacion as error:
        if error.campo == "clave_idempotencia":
            # Formulario viejo o clave usada para otra cosa: se entrega uno con clave nueva.
            flash("Este formulario ya no es válido. Revisa los datos y envíalo de nuevo.", "error")
            valores["clave_idempotencia"] = ""
            return mostrar_juntia(usuario, bolsillo_id, "aporte", {}, valores, 400)
        return error_en_juntia(usuario, bolsillo_id, error, "aporte", valores, 400)
    except HabiError as error:
        return error_en_juntia(usuario, bolsillo_id, error, "aporte", valores)

    if resultado.repetida:
        return volver_a_juntia(bolsillo_id, "Este aporte ya se había realizado; no se repitió.")
    return volver_a_juntia(bolsillo_id, f"Aporte de {formatear_cop(resultado.monto)} realizado.")


@paginas.post("/juntias/<int:bolsillo_id>/invitar")
def invitar_juntia(bolsillo_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()

    invitado = request.form.get("invitado", "")
    valores = {"invitado": invitado}
    try:
        services.invitar_a_bolsillo(obtener_conexion(), usuario, bolsillo_id, invitado)
    except ErrorValidacion as error:
        return error_en_juntia(usuario, bolsillo_id, error, "invitacion", valores, 400)
    except NoEncontrado as error:
        if str(error).startswith("El usuario"):
            return usuario_no_existe(usuario, bolsillo_id, "invitado", "invitacion", valores)
        return error_en_juntia(usuario, bolsillo_id, error, "invitacion", valores, 404)
    except HabiError as error:
        return error_en_juntia(usuario, bolsillo_id, error, "invitacion", valores)

    return volver_a_juntia(bolsillo_id, f"Invitación enviada a {invitado.strip()}.")


@paginas.post("/juntias/<int:bolsillo_id>/retiros")
def proponer_retiro_juntia(bolsillo_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()

    valores = {
        "destino": request.form.get("destino", ""),
        "monto": request.form.get("monto", ""),
        "motivo": request.form.get("motivo", ""),
    }
    try:
        monto = leer_entero(valores["monto"], "monto")
        retiro = services.proponer_retiro(
            obtener_conexion(), usuario, bolsillo_id, valores["destino"], monto, valores["motivo"]
        )
    except ErrorValidacion as error:
        return error_en_juntia(usuario, bolsillo_id, error, "retiro", valores, 400)
    except NoEncontrado as error:
        if str(error).startswith("El usuario"):
            return usuario_no_existe(usuario, bolsillo_id, "destino", "retiro", valores)
        return error_en_juntia(usuario, bolsillo_id, error, "retiro", valores, 404)
    except HabiError as error:
        return error_en_juntia(usuario, bolsillo_id, error, "retiro", valores)

    if retiro.estado == "EJECUTADO":
        mensaje = f"Retiro de {formatear_cop(retiro.monto)} a {retiro.destino} realizado."
    else:
        mensaje = f"Retiro de {formatear_cop(retiro.monto)} propuesto. El monto queda reservado mientras votan."
    return volver_a_juntia(bolsillo_id, mensaje)


@paginas.post("/juntias/<int:bolsillo_id>/retiros/<int:retiro_id>/votar")
def votar_retiro_juntia(bolsillo_id, retiro_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()
    try:
        retiro = services.votar_retiro(
            obtener_conexion(), usuario, bolsillo_id, retiro_id, request.form.get("voto", "")
        )
    except HabiError as error:
        flash(str(error), "error")
        return redirect(url_for("paginas.juntia", bolsillo_id=bolsillo_id))
    return volver_a_juntia(bolsillo_id, mensaje_de_voto(retiro))


@paginas.post("/juntias/<int:bolsillo_id>/salir")
def salir_juntia(bolsillo_id):
    usuario = usuario_o_none()
    if usuario is None:
        return ir_a_entrar()
    try:
        services.salir_de_bolsillo(obtener_conexion(), usuario, bolsillo_id)
    except HabiError as error:
        flash(str(error), "error")
        return redirect(url_for("paginas.juntia", bolsillo_id=bolsillo_id))
    flash("Saliste del bolsillo.", "exito")
    return redirect(url_for("paginas.juntias"))

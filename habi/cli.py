"""Interfaz de consola (input/print). Solo presenta datos y llama a services."""

import uuid

from habi import config, db, services
from habi.dominio import ErrorValidacion, HabiError, Usuario


# ---------- Presentación (RNF-U-02) ----------

def formatear_cop(monto: int) -> str:
    """50000 -> '50.000 COP'."""
    return f"{monto:,}".replace(",", ".") + " COP"


def pedir_texto(etiqueta: str) -> str:
    return input(f"{etiqueta}: ").strip()


def pedir_monto(etiqueta: str = "Monto (COP, sin puntos)") -> int:
    """Convierte la entrada a int. El rango lo valida services.validar_monto."""
    texto = pedir_texto(etiqueta)
    if not texto.isdigit():
        raise ErrorValidacion("monto", "debe ser un número entero positivo, sin decimales ni separadores")
    return int(texto)


def ok(mensaje: str) -> None:
    print(f"[OK] {mensaje}")


def error(mensaje: str) -> None:
    print(f"[ERROR] {mensaje}")


# ---------- Acciones ----------

def accion_registrar(conn) -> None:
    usuario = services.registrar_usuario(conn, pedir_texto("Nombre de usuario"), pedir_texto("Contraseña"))
    ok(f"Cuenta creada para '{usuario.nombre}'. Saldo inicial: {formatear_cop(0)}")


def accion_iniciar_sesion(conn) -> Usuario:
    usuario = services.iniciar_sesion(conn, pedir_texto("Nombre de usuario"), pedir_texto("Contraseña"))
    ok(f"Bienvenido, {usuario.nombre}")
    return usuario


def accion_cargar(conn, usuario: Usuario) -> None:
    resultado = services.cargar_saldo(conn, usuario, pedir_monto())
    ok(f"Carga de {formatear_cop(resultado.monto)} registrada ({resultado.creada_en})")


def accion_transferir(conn, usuario: Usuario) -> None:
    destino = pedir_texto("Usuario destino")
    monto = pedir_monto()
    resultado = services.transferir(conn, usuario, destino, monto, clave_idempotencia=str(uuid.uuid4()))
    ok(f"Transferencia de {formatear_cop(resultado.monto)} a '{destino}' realizada ({resultado.creada_en})")


def accion_saldo(conn, usuario: Usuario) -> None:
    ok(f"Saldo actual: {formatear_cop(services.consultar_saldo(conn, usuario))}")


def accion_historial(conn, usuario: Usuario) -> None:
    pagina = 0
    while True:
        movimientos = services.consultar_historial(conn, usuario, pagina)
        if not movimientos:
            print("No hay más movimientos." if pagina else "No hay movimientos.")
            return
        for m in movimientos:
            signo = "+" if m.monto > 0 else "-"
            print(f"{m.creado_en}  {m.tipo_operacion:<13} {signo}{formatear_cop(abs(m.monto)):>16}  {m.contraparte}")
        if len(movimientos) < config.TAMANO_PAGINA_HISTORIAL or pedir_texto("¿Ver más? (s/n)").lower() != "s":
            return
        pagina += 1


# ---------- Menús ----------

MENU_INICIO = {
    "1": ("Registrarse", accion_registrar),
    "2": ("Iniciar sesión", accion_iniciar_sesion),
}

MENU_CUENTA = {
    "1": ("Cargar saldo", accion_cargar),
    "2": ("Transferir", accion_transferir),
    "3": ("Consultar saldo", accion_saldo),
    "4": ("Ver historial", accion_historial),
}


def mostrar_menu(titulo: str, opciones: dict, salida: str) -> str:
    print(f"\n=== {titulo} ===")
    for clave, (texto, _) in opciones.items():
        print(f"{clave}. {texto}")
    print(f"0. {salida}")
    return pedir_texto("Opción")


def ejecutar(funcion, *args):
    """Ejecuta una acción mostrando éxito o motivo del error (RNF-U-01)."""
    try:
        return funcion(*args)
    except HabiError as e:
        error(str(e))
    except NotImplementedError:
        error("Funcionalidad pendiente de implementar.")


def main() -> None:
    conn = db.conectar()
    db.inicializar(conn)
    usuario: Usuario | None = None
    try:
        while True:
            if usuario is None:
                opcion = mostrar_menu("Habi - Inicio", MENU_INICIO, "Salir")
                if opcion == "0":
                    break
                if opcion in MENU_INICIO:
                    resultado = ejecutar(MENU_INICIO[opcion][1], conn)
                    if isinstance(resultado, Usuario):
                        usuario = resultado
                else:
                    error("Opción inválida.")
            else:
                opcion = mostrar_menu(f"Cuenta de {usuario.nombre}", MENU_CUENTA, "Cerrar sesión")
                if opcion == "0":
                    usuario = None
                elif opcion in MENU_CUENTA:
                    ejecutar(MENU_CUENTA[opcion][1], conn, usuario)
                else:
                    error("Opción inválida.")
    except (KeyboardInterrupt, EOFError):
        print()
    finally:
        conn.close()
        print("Hasta luego.")

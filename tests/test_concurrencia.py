"""RNF-R-04 Concurrencia."""

import threading
import uuid

from habi import db, services
from habi.dominio import SaldoInsuficiente


def test_20_transferencias_simultaneas_desde_10000(ruta_db):
    """RNF-R-04: cuenta con 10.000 COP, 20 hilos transfieren 1.000 COP cada uno
    (cada hilo con su propia conexión db.conectar(ruta_db) y su propia clave uuid).
    Esperado: 10 exitosas, 10 SaldoInsuficiente, saldo final 0.
    """
    conn = db.conectar(ruta_db)
    ana = services.registrar_usuario(conn, "ana", "clave-segura")
    beto = services.registrar_usuario(conn, "beto", "clave-segura")
    services.cargar_saldo(conn, ana, 10_000)

    hilos = 20
    barrera = threading.Barrier(hilos)
    resultados: list[str] = []
    candado = threading.Lock()

    def trabajador():
        c = db.conectar(ruta_db)
        try:
            barrera.wait()
            try:
                services.transferir(c, ana, "beto", 1_000, str(uuid.uuid4()))
                resultado = "ok"
            except SaldoInsuficiente:
                resultado = "insuficiente"
            except Exception as e:  # cualquier otro error haría fallar la prueba
                resultado = f"error: {e!r}"
            with candado:
                resultados.append(resultado)
        finally:
            c.close()

    threads = [threading.Thread(target=trabajador) for _ in range(hilos)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert sorted(resultados) == ["insuficiente"] * 10 + ["ok"] * 10
    assert services.consultar_saldo(conn, ana) == 0
    assert services.consultar_saldo(conn, beto) == 10_000
    transferencias = conn.execute("SELECT COUNT(*) FROM operaciones WHERE tipo = 'TRANSFERENCIA'").fetchone()[0]
    assert transferencias == 10
    conn.close()

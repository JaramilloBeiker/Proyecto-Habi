import pytest

from habi import config, db, services


@pytest.fixture(autouse=True)
def hash_rapido(monkeypatch):
    """Menos iteraciones de PBKDF2 en pruebas para que la suite sea rápida."""
    monkeypatch.setattr(config, "PBKDF2_ITERACIONES", 1_000)


@pytest.fixture
def ruta_db(tmp_path):
    """Base de datos nueva y aislada por prueba."""
    ruta = tmp_path / "test.db"
    conn = db.conectar(ruta)
    db.inicializar(conn)
    conn.close()
    return ruta


@pytest.fixture
def conn(ruta_db):
    conexion = db.conectar(ruta_db)
    yield conexion
    conexion.close()


@pytest.fixture
def crear_usuario(conn):
    """Fábrica: crea un usuario (y opcionalmente le carga saldo)."""

    def _crear(nombre: str = "ana", password: str = "clave-segura", saldo: int = 0):
        usuario = services.registrar_usuario(conn, nombre, password)
        if saldo:
            services.cargar_saldo(conn, usuario, saldo)
        return usuario

    return _crear

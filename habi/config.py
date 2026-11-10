"""Configuración central del sistema. Valores sobreescribibles por variables de entorno."""

import os
from pathlib import Path

RAIZ_PROYECTO = Path(__file__).resolve().parent.parent

# Base de datos (RNF-R-01: persistencia en archivo local)
DB_PATH = Path(os.environ.get("HABI_DB_PATH", RAIZ_PROYECTO / "data" / "habi.db"))
DB_TIMEOUT_SEGUNDOS = 10  # espera máxima por el lock de escritura (RNF-R-04)

# Reglas de montos (RNF-D-01, RNF-D-02, RF-03, RF-04)
MONTO_MINIMO = 1
MONTO_MAXIMO = 5_000_000

# Usuarios (RF-01)
LONGITUD_MINIMA_PASSWORD = 8

# Historial (RF-06)
TAMANO_PAGINA_HISTORIAL = 20

# Contraseñas (RNF-SEC-01). En pruebas se baja para que la suite sea rápida.
PBKDF2_ALGORITMO = "sha256"
PBKDF2_ITERACIONES = int(os.environ.get("HABI_PBKDF2_ITERACIONES", 600_000))

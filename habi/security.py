"""Hash y verificación de contraseñas con hashlib.pbkdf2_hmac (RNF-SEC-01)."""

import hashlib
import hmac
import secrets

from habi import config


def hash_password(password: str) -> str:
    """Devuelve 'pbkdf2_<alg>$<iteraciones>$<salt_hex>$<hash_hex>'. Nunca la contraseña en claro."""
    salt = secrets.token_bytes(16)
    iteraciones = config.PBKDF2_ITERACIONES
    derivada = hashlib.pbkdf2_hmac(config.PBKDF2_ALGORITMO, password.encode("utf-8"), salt, iteraciones)
    return f"pbkdf2_{config.PBKDF2_ALGORITMO}${iteraciones}${salt.hex()}${derivada.hex()}"


def verificar_password(password: str, almacenado: str) -> bool:
    """Compara en tiempo constante la contraseña ingresada contra el hash guardado."""
    try:
        esquema, iteraciones, salt_hex, hash_hex = almacenado.split("$")
        algoritmo = esquema.removeprefix("pbkdf2_")
        derivada = hashlib.pbkdf2_hmac(
            algoritmo, password.encode("utf-8"), bytes.fromhex(salt_hex), int(iteraciones)
        )
    except ValueError:
        return False
    return hmac.compare_digest(derivada.hex(), hash_hex)

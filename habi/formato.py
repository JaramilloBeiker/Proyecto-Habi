"""Formato de montos para mostrar al usuario (RNF-U-02). Lo usan la consola y la web."""


def formatear_cop(monto: int) -> str:
    """50000 -> '50.000 COP'.  -1500 -> '-1.500 COP'."""
    return f"{monto:,}".replace(",", ".") + " COP"

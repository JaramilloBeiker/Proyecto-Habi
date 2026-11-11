"""python -m habi -> servidor web local en http://127.0.0.1:5000

Usa el servidor de desarrollo de Flask: solo para uso local, nunca en internet.
"""

from habi.web import crear_app

if __name__ == "__main__":
    app = crear_app()
    app.run(host="127.0.0.1", port=5000, debug=False)

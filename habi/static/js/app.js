// Habi — mejoras puntuales con JavaScript sin frameworks.
// Todo funciona igual sin JavaScript: el servidor valida y protege cada operación.

// Da formato COP a un número entero escrito como texto: "50000" -> "50.000 COP".
function formatearCop(texto) {
    return texto.replace(/\B(?=(\d{3})+(?!\d))/g, ".") + " COP";
}

// 1. Evitar el doble envío: al enviar un formulario se deshabilita su botón.
//    (Si aun así llegara dos veces, la clave de idempotencia evita repetir la transferencia.)
document.querySelectorAll("form").forEach(function (formulario) {
    formulario.addEventListener("submit", function () {
        const boton = formulario.querySelector('button[type="submit"]');
        if (boton) {
            boton.dataset.textoOriginal = boton.textContent;
            boton.textContent = "Procesando…";
            boton.disabled = true;
        }
    });
});

// Si el usuario vuelve con el botón "atrás", el navegador puede mostrar la página
// guardada con los botones deshabilitados: se vuelven a habilitar.
window.addEventListener("pageshow", function () {
    document.querySelectorAll("button[data-texto-original]").forEach(function (boton) {
        boton.textContent = boton.dataset.textoOriginal;
        boton.disabled = false;
    });
});

// 2. Vista previa del monto en COP mientras se escribe (RNF-U-02).
document.querySelectorAll('input[name="monto"], input[name="meta"]').forEach(function (campo) {
    const vista = document.createElement("p");
    vista.className = "campo__vista";
    campo.insertAdjacentElement("afterend", vista);

    function actualizar() {
        const valor = campo.value.trim();
        vista.textContent = /^\d+$/.test(valor) ? formatearCop(valor) : "";
    }

    campo.addEventListener("input", actualizar);
    actualizar();
});

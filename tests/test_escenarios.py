# tests/test_escenarios.py — Prueba SofIA con varios escenarios reales
"""
Simula conversaciones tipicas de doctores con SofIA.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generar_respuesta
from agent.memory import inicializar_db, guardar_mensaje, obtener_historial, limpiar_historial


def safe_print(text):
    """Imprime evitando errores de codificacion en Windows."""
    print(text.encode('utf-8', errors='replace').decode('utf-8', errors='replace'))


async def simular_conversacion(telefono, mensajes, titulo):
    """Simula una conversacion completa con varios turnos."""
    await limpiar_historial(telefono)

    print()
    print("=" * 70)
    safe_print(f"  ESCENARIO: {titulo}")
    print("=" * 70)

    for i, msg_usuario in enumerate(mensajes, 1):
        print(f"\n[Doctor]: {msg_usuario}")

        historial = await obtener_historial(telefono)
        respuesta = await generar_respuesta(msg_usuario, historial)

        safe_print(f"\n[SofIA]: {respuesta}")

        await guardar_mensaje(telefono, "user", msg_usuario)
        await guardar_mensaje(telefono, "assistant", respuesta)


async def main():
    await inicializar_db()

    # ESCENARIO 1: Doctor frio, primer contacto
    await simular_conversacion(
        "test-001",
        ["Hola, vi su publicidad. Que hacen ustedes?"],
        "1. Doctor curioso (primer contacto)"
    )

    # ESCENARIO 2: Doctor caliente, especifico
    await simular_conversacion(
        "test-002",
        [
            "Buenas tardes, soy odontologo en Ibague con clinica propia",
            "Cuanto cuesta su servicio de marketing?",
        ],
        "2. Odontologo de Ibague preguntando precio"
    )

    # ESCENARIO 3: Doctor frustrado
    await simular_conversacion(
        "test-003",
        [
            "He probado 3 agencias de marketing y ninguna me trajo resultados",
            "Estoy harto, voy a desistir",
        ],
        "3. Doctor frustrado con malas experiencias previas"
    )

    # ESCENARIO 4: Cliente activo con duda operativa
    await simular_conversacion(
        "test-004",
        [
            "Hola, soy cliente de ustedes. Cuando me envian el reporte mensual?",
        ],
        "4. Cliente activo preguntando por reporte"
    )

    # ESCENARIO 5: Lead muy bueno
    await simular_conversacion(
        "test-005",
        [
            "Soy cirujano plastico en Medellin, tengo 15 anos de experiencia y quiero crecer",
        ],
        "5. Lead VIP (cirujano plastico Medellin)"
    )

    print("\n" + "=" * 70)
    print("  Test completado. Revisa las respuestas de SofIA arriba.")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())

# tests/test_local.py — Simulador de chat de SofIA en terminal
# Generado por AgentKit

"""
Prueba SofIA sin necesitar WhatsApp.
Simula una conversacion en la terminal como si fueras un doctor escribiendo.

Uso:
    python tests/test_local.py
"""

import asyncio
import sys
import os

# Agregar el directorio raiz al path para que los imports funcionen
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generar_respuesta
from agent.memory import (
    inicializar_db,
    guardar_mensaje,
    obtener_historial,
    limpiar_historial,
)

TELEFONO_TEST = "test-local-001"


async def main():
    """Loop principal del chat de prueba."""
    await inicializar_db()

    print()
    print("=" * 60)
    print("   SofIA (Lapora) - Modo Test Local")
    print("=" * 60)
    print()
    print("  Habla con SofIA como si fueras un doctor.")
    print("  Comandos especiales:")
    print("    'limpiar'  - borra el historial de esta conversacion")
    print("    'salir'    - termina el test")
    print()
    print("-" * 60)
    print()

    while True:
        try:
            mensaje = input("Tu: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nTest finalizado.")
            break

        if not mensaje:
            continue

        if mensaje.lower() == "salir":
            print("\nTest finalizado.")
            break

        if mensaje.lower() == "limpiar":
            await limpiar_historial(TELEFONO_TEST)
            print("[Historial borrado]\n")
            continue

        # Obtener historial ANTES de guardar (brain.py agrega el mensaje actual)
        historial = await obtener_historial(TELEFONO_TEST)

        # Generar respuesta
        print("\nSofIA: ", end="", flush=True)
        respuesta = await generar_respuesta(mensaje, historial)
        print(respuesta)
        print()

        # Guardar mensaje del usuario y respuesta del agente
        await guardar_mensaje(TELEFONO_TEST, "user", mensaje)
        await guardar_mensaje(TELEFONO_TEST, "assistant", respuesta)


if __name__ == "__main__":
    asyncio.run(main())

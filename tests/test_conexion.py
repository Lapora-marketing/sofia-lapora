# tests/test_conexion.py — Test rapido de conexion con Claude API
"""
Verifica que SofIA puede conectarse a Claude antes del test interactivo.
"""

import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.brain import generar_respuesta
from agent.memory import inicializar_db


async def main():
    print("=" * 60)
    print("Test de conexion con Claude API")
    print("=" * 60)

    # Inicializar BD
    print("\n[1/3] Inicializando base de datos...")
    await inicializar_db()
    print("      OK - BD inicializada")

    # Test simple
    print("\n[2/3] Enviando mensaje de prueba a SofIA...")
    mensaje_test = "Hola, soy doctor Garcia. Tengo un consultorio en Bogota."
    print(f"      Mensaje: {mensaje_test}")

    respuesta = await generar_respuesta(mensaje_test, [])

    print("\n[3/3] Respuesta de SofIA:")
    print("-" * 60)
    # Encode/decode para evitar errores de codificacion en Windows
    respuesta_safe = respuesta.encode('utf-8', errors='replace').decode('utf-8', errors='replace')
    print(respuesta_safe)
    print("-" * 60)

    print("\nTest completado. SofIA esta lista!")


if __name__ == "__main__":
    asyncio.run(main())

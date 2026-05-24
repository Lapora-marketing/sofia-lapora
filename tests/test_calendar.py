# tests/test_calendar.py — Test de integracion con Google Calendar
"""
Prueba la integracion con Google Calendar.

USO:
    python tests/test_calendar.py
"""

import sys
import os
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from agent.calendar_service import (
    verificar_disponibilidad,
    agendar_cita,
    listar_citas_proximas,
)


def main():
    print("=" * 60)
    print("  Test de Google Calendar Integration")
    print("=" * 60)
    print()

    # Verificar que las credenciales estan configuradas
    if not os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"):
        print("ERROR: GOOGLE_SERVICE_ACCOUNT_JSON no configurado en .env")
        print()
        print("Para configurarlo:")
        print("1. Crea un proyecto en https://console.cloud.google.com/")
        print("2. Habilita Google Calendar API")
        print("3. Crea un Service Account")
        print("4. Descarga el JSON de la key")
        print("5. Pega el contenido del JSON en .env como GOOGLE_SERVICE_ACCOUNT_JSON")
        print("6. Comparte tu calendario con el email del service account")
        sys.exit(1)

    if not os.getenv("GOOGLE_CALENDAR_ID"):
        print("ERROR: GOOGLE_CALENDAR_ID no configurado en .env")
        sys.exit(1)

    # Test 1: Verificar disponibilidad para manana 3pm
    print("[1] Verificando disponibilidad para manana 3pm...")
    resultado = verificar_disponibilidad("manana", "3pm")
    print(f"    Resultado: {resultado}")
    print()

    # Test 2: Listar citas proximas
    print("[2] Listando citas proximas (7 dias)...")
    citas = listar_citas_proximas(dias=7)
    print(f"    Total: {citas.get('total', 0)} citas")
    for cita in citas.get("citas", [])[:5]:
        print(f"    - {cita['inicio']}: {cita['titulo']}")
    print()

    # Test 3: Agendar una cita de prueba (solo si confirmas)
    print("[3] Test de agendamiento (cita de prueba)...")
    respuesta = input("    ¿Quieres crear una cita real de prueba para manana 6pm? (s/n): ")
    if respuesta.lower() == "s":
        resultado = agendar_cita(
            fecha="manana",
            hora="6pm",
            nombre_doctor="Dr. Test SofIA",
            email_doctor=os.getenv("GOOGLE_CALENDAR_ID"),
            telefono="573209989552",
            especialidad="Odontologia",
            ciudad="Ibague",
            notas="Cita de prueba creada por test automatico de SofIA. Puedes borrarla.",
        )
        print(f"    Resultado: {resultado}")
    else:
        print("    Skipped.")
    print()

    print("=" * 60)
    print("  Test completado")
    print("=" * 60)


if __name__ == "__main__":
    main()

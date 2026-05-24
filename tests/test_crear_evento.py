# tests/test_crear_evento.py — Crear un evento real de prueba en Google Calendar
import sys
import os
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

from agent.calendar_service import verificar_disponibilidad, agendar_cita

print("=" * 60)
print("  TEST CREAR EVENTO REAL EN GOOGLE CALENDAR")
print("=" * 60)

# Verificar disponibilidad para manana 6pm
print("\n[1] Verificando disponibilidad manana 6pm...")
disp = verificar_disponibilidad("manana", "6pm")
print(f"   {disp}")

if not disp.get("disponible"):
    print("\nNo se puede agendar. Razon:", disp.get("mensaje"))
    sys.exit(0)

# Agendar la cita
print("\n[2] Agendando cita de prueba...")
result = agendar_cita(
    fecha="manana",
    hora="6pm",
    nombre_doctor="Dr. Test SofIA",
    email_doctor=os.getenv("GOOGLE_CALENDAR_ID"),
    telefono="573209989552",
    especialidad="Odontologia",
    ciudad="Ibague",
    notas="Cita de prueba creada automaticamente por test de SofIA. Puedes borrarla.",
)

if result.get("exito"):
    print(f"\nEXITO!")
    print(f"   Mensaje: {result.get('mensaje')}")
    print(f"   Link Calendar: {result.get('link_calendar')}")
    if result.get("link_meet"):
        print(f"   Link Meet: {result.get('link_meet')}")
    print(f"\n   Revisa tu Google Calendar y veras la cita.")
else:
    print(f"\nERROR: {result.get('mensaje')}")

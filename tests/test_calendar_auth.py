# tests/test_calendar_auth.py — Verificar autenticacion con Google Calendar
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)

print("=" * 60)
print("  Verificacion Google Calendar")
print("=" * 60)

cal_id = os.getenv("GOOGLE_CALENDAR_ID")
json_str = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")

print(f"GOOGLE_CALENDAR_ID: {cal_id}")
print(f"JSON length: {len(json_str)} caracteres")
print()

if not json_str:
    print("ERROR: JSON no cargado")
    sys.exit(1)

print("[1] Probando listar eventos...")
try:
    from agent.calendar_service import listar_citas_proximas
    result = listar_citas_proximas(dias=7)
    if result.get("exito"):
        print(f"   OK - {result.get('total', 0)} eventos en los proximos 7 dias")
        for cita in result.get("citas", [])[:5]:
            print(f"   - {cita['inicio']}: {cita['titulo']}")
    else:
        print(f"   ERROR: {result.get('mensaje')}")
except Exception as e:
    print(f"   ERROR: {e}")
    print()
    print("Esto puede ser porque no compartiste el calendar con el bot todavia.")
    print(f"Comparte tu calendar con: sofia-calendar-bot@lapora-sofia-bot.iam.gserviceaccount.com")

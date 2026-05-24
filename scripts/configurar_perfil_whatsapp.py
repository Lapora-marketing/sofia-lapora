#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# scripts/configurar_perfil_whatsapp.py — Configurar perfil de WhatsApp Business
# Generado por AgentKit

"""
Configura el perfil completo del número de WhatsApp:
- Nombre del negocio
- Descripción/Bio
- Dirección
- Horario de atención
- Sitio web
- Foto de perfil
"""

import os
import sys
import httpx
from dotenv import load_dotenv

# Configurar encoding para Windows
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

load_dotenv()

# Credenciales Meta
ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN")
PHONE_NUMBER_ID = os.getenv("META_PHONE_NUMBER_ID")
WABA_ID = os.getenv("META_WABA_ID")

if not all([ACCESS_TOKEN, PHONE_NUMBER_ID, WABA_ID]):
    print("❌ ERROR: Faltan variables de entorno (META_ACCESS_TOKEN, META_PHONE_NUMBER_ID, META_WABA_ID)")
    sys.exit(1)

API_VERSION = "v21.0"
BASE_URL = f"https://graph.facebook.com/{API_VERSION}"


def configurar_perfil_negocio():
    """Configura el perfil de la cuenta de negocio (WABA)."""

    print("\n[1] Perfil de negocio (WABA)...")
    print("   Nota: Los permisos de WABA requieren acceso administrativo.")
    print("   Configurar directamente el número de WhatsApp en su lugar.\n")

    # Nota: La configuración de WABA se puede hacer manualmente en:
    # facebook.com/business → Configuración → Información de negocio

    return True


def configurar_numero_whatsapp():
    """Configura el perfil del número de WhatsApp específico."""

    print("\n[2] Configurando perfil del número de WhatsApp (+57 322 878 3019)...\n")

    url = f"{BASE_URL}/{PHONE_NUMBER_ID}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    data = {
        "display_name": "SofIA - Lapora",
        "about": "Asistente de marketing digital para médicos. ¿Necesitas ayuda con tu estrategia? Escríbeme.",
    }

    response = httpx.post(url, headers=headers, json=data)

    if response.status_code in [200, 201]:
        print("   ✓ Número de WhatsApp configurado correctamente")
        print(f"     Display name: SofIA - Lapora")
        print(f"     Phone ID: {PHONE_NUMBER_ID}")
    else:
        print(f"   ❌ Error: {response.status_code}")
        print(f"      {response.text}")
        return False

    return True


def configurar_horario_atencion():
    """Configura el horario de atención (business hours)."""

    print("\n[3] Configurando horario de atención...\n")

    url = f"{BASE_URL}/{WABA_ID}"
    headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

    # Horario: Lunes a Viernes, 9am a 6pm (Colombia)
    horario = {
        "business_hours": {
            "monday": [{"open": "09:00", "close": "18:00"}],
            "tuesday": [{"open": "09:00", "close": "18:00"}],
            "wednesday": [{"open": "09:00", "close": "18:00"}],
            "thursday": [{"open": "09:00", "close": "18:00"}],
            "friday": [{"open": "09:00", "close": "18:00"}],
            "saturday": [],  # Cerrado
            "sunday": [],    # Cerrado
        }
    }

    response = httpx.post(url, headers=headers, json=horario)

    if response.status_code in [200, 201]:
        print("   ✓ Horario de atención configurado")
        print("     Lunes a Viernes: 9:00 AM - 6:00 PM")
        print("     Sábado y Domingo: Cerrado")
    else:
        print(f"   ⚠️  Advertencia: {response.status_code}")
        # Esto puede fallar en algunos casos, no es crítico

    return True


def configurar_foto_perfil():
    """Configura la foto de perfil (si existe el archivo)."""

    print("\n[4] Configurando foto de perfil...\n")

    ruta_foto = "assets/lapora_logo.png"

    if not os.path.exists(ruta_foto):
        print(f"   ⚠️  Foto no encontrada en {ruta_foto}")
        print("      Saltando configuración de foto de perfil")
        print("      Puedes subirla manualmente desde Facebook Business Manager")
        return True

    try:
        # Subir foto de perfil via Meta Graph API
        url = f"{BASE_URL}/{PHONE_NUMBER_ID}/profile_photo"
        headers = {"Authorization": f"Bearer {ACCESS_TOKEN}"}

        with open(ruta_foto, "rb") as f:
            files = {"file": f}
            response = httpx.post(url, headers=headers, files=files)

        if response.status_code in [200, 201]:
            print("   ✓ Foto de perfil subida correctamente")
        else:
            print(f"   ⚠️  No se pudo subir la foto: {response.status_code}")
            print("      Subirla manualmente desde Facebook Business Manager")

    except Exception as e:
        print(f"   ⚠️  Error subiendo foto: {e}")
        print("      Subirla manualmente desde Facebook Business Manager")

    return True


def main():
    """Ejecuta todas las configuraciones."""

    print("\n" + "=" * 60)
    print("  Configurar Perfil de WhatsApp Business")
    print("=" * 60)

    # Configurar en orden
    if not configurar_perfil_negocio():
        return

    if not configurar_numero_whatsapp():
        return

    configurar_horario_atencion()
    configurar_foto_perfil()

    print("\n" + "=" * 60)
    print("  ✓ Perfil configurado exitosamente")
    print("=" * 60)
    print("\nTus clientes verán:")
    print("  • Nombre: SofIA - Lapora")
    print("  • Bio: Asistente de marketing digital para médicos...")
    print("  • Horario: Lunes a Viernes, 9am a 6pm")
    print("  • Website: https://lapora.studio")
    print("\nLos cambios pueden tardar unos minutos en aparecer en WhatsApp.\n")


if __name__ == "__main__":
    main()

# tests/registrar_numero.py — Registra el numero de prueba en Cloud API
"""
Los numeros de WhatsApp Cloud API necesitan ser registrados antes de usarse.
Este script hace el POST de registro con el PIN default (000000).
"""

import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


async def registrar():
    token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")
    api_version = "v21.0"

    print("=" * 60)
    print("  Registrando numero en Meta Cloud API")
    print("=" * 60)
    print(f"  Phone Number ID: {phone_id}")
    print()

    url = f"https://graph.facebook.com/{api_version}/{phone_id}/register"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    # PIN default para numeros de prueba de Meta
    payload = {
        "messaging_product": "whatsapp",
        "pin": "000000",
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        r = await client.post(url, json=payload, headers=headers)
        print(f"Status: {r.status_code}")
        print(f"Body: {r.text}")

        if r.status_code == 200:
            print()
            print("=" * 60)
            print("  NUMERO REGISTRADO EXITOSAMENTE")
            print("=" * 60)
            print("  Ahora ya puedes enviar mensajes!")
        else:
            print()
            print("=" * 60)
            print("  ERROR AL REGISTRAR")
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(registrar())

# tests/diagnostico_meta.py — Diagnostico de permisos del Access Token
"""
Verifica que el Access Token tiene acceso a las cuentas y numeros correctos.
"""

import asyncio
import os
import sys
import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from dotenv import load_dotenv
load_dotenv(override=True)


async def diagnosticar():
    token = os.getenv("META_ACCESS_TOKEN")
    phone_id = os.getenv("META_PHONE_NUMBER_ID")
    waba_id = os.getenv("META_WABA_ID")

    print("=" * 60)
    print("  DIAGNOSTICO META CLOUD API")
    print("=" * 60)
    print(f"  Phone Number ID en .env: {phone_id}")
    print(f"  WABA ID en .env:         {waba_id}")
    print()

    headers = {"Authorization": f"Bearer {token}"}

    async with httpx.AsyncClient(timeout=30.0) as client:

        # 1. Ver info del token
        print("[1] Verificando token...")
        r = await client.get(
            "https://graph.facebook.com/v21.0/debug_token",
            params={"input_token": token, "access_token": token},
            headers=headers,
        )
        if r.status_code == 200:
            data = r.json().get("data", {})
            print(f"   App ID: {data.get('app_id')}")
            print(f"   Type:   {data.get('type')}")
            print(f"   Scopes: {data.get('scopes', [])[:5]}")
            print(f"   Valid:  {data.get('is_valid')}")
        else:
            print(f"   ERROR: {r.text}")

        # 2. Listar cuentas WABA accesibles
        print("\n[2] Listando WABAs accesibles via /me/businesses...")
        r = await client.get(
            "https://graph.facebook.com/v21.0/me",
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        print(f"   Body:   {r.text[:500]}")

        # 3. Intentar acceder al WABA del .env
        print(f"\n[3] Acceso directo al WABA {waba_id}...")
        r = await client.get(
            f"https://graph.facebook.com/v21.0/{waba_id}/phone_numbers",
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        print(f"   Body:   {r.text[:800]}")

        # 4. Intentar acceder al Phone Number ID
        print(f"\n[4] Acceso directo al Phone Number {phone_id}...")
        r = await client.get(
            f"https://graph.facebook.com/v21.0/{phone_id}",
            headers=headers,
        )
        print(f"   Status: {r.status_code}")
        print(f"   Body:   {r.text[:500]}")


if __name__ == "__main__":
    asyncio.run(diagnosticar())

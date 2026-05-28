# -*- coding: utf-8 -*-
# agent/whatsapp_helper.py — Helper unificado para Meta WhatsApp Cloud API
# Lapora Marketing Digital

"""
Refactor DRY: extrae la lógica de envío WhatsApp duplicada en:
- agent/clinic_brain.py (per-tenant, credenciales de cada clínica)
- agent/voice_outcomes.py (Lapora business, credenciales globales)
- agent/dashboard.py (admin manual reply)
- agent/clinic.py (clinic-side manual reply)
- agent/clinic_workers.py (recordatorios de cita)

Antes: ~5 implementaciones casi idénticas, ~100 líneas duplicadas.
Después: 1 helper compartido, ~50 líneas total, mejor manejo de errores.

API pública:
- enviar_mensaje_meta(phone_id, token, telefono, mensaje) → dict
- credenciales_lapora() → (phone_id, token) desde env
"""

import os
import logging
from typing import Optional
import httpx

logger = logging.getLogger("agentkit")

META_API_VERSION = "v21.0"
TIMEOUT_SECONDS = 15
MAX_MESSAGE_LENGTH = 4000  # WhatsApp límite ~4096


def credenciales_lapora() -> tuple[Optional[str], Optional[str]]:
    """Devuelve (phone_id, access_token) del Lapora business desde env vars.

    Returns: tuple, None en el slot si la env var no está configurada.
    """
    return (
        os.getenv("META_PHONE_NUMBER_ID") or None,
        os.getenv("META_ACCESS_TOKEN") or None,
    )


def _limpiar_telefono(telefono: str) -> str:
    """Extrae solo dígitos del número (sin + ni separadores)."""
    return "".join(c for c in (telefono or "") if c.isdigit())


async def enviar_mensaje_meta(
    phone_id: str,
    token: str,
    telefono: str,
    mensaje: str,
    contexto_log: str = "",
) -> dict:
    """Envía un mensaje de texto vía Meta WhatsApp Cloud API.

    Args:
        phone_id: META_PHONE_NUMBER_ID (per-tenant o global)
        token: META_ACCESS_TOKEN (per-tenant o global)
        telefono: número destino, con o sin "+"
        mensaje: texto a enviar (se trunca a 4000 chars)
        contexto_log: identificador para logs (ej "clinica=12" o "lapora-outreach")

    Returns:
        {
            "exito": bool,
            "error": str,         # vacío si exito=True
            "message_id": str,    # vacío si error
            "status_code": int,   # HTTP code, 0 si excepción
        }
    """
    if not phone_id or not token:
        return {
            "exito": False,
            "error": "Credenciales WhatsApp no configuradas (phone_id o token vacío)",
            "message_id": "",
            "status_code": 0,
        }

    tel_limpio = _limpiar_telefono(telefono)
    if not tel_limpio or len(tel_limpio) < 7:
        return {
            "exito": False,
            "error": f"Teléfono inválido: {telefono!r}",
            "message_id": "",
            "status_code": 0,
        }

    if not mensaje or not mensaje.strip():
        return {
            "exito": False,
            "error": "Mensaje vacío",
            "message_id": "",
            "status_code": 0,
        }

    url = f"https://graph.facebook.com/{META_API_VERSION}/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": tel_limpio,
        "type": "text",
        "text": {"body": mensaje[:MAX_MESSAGE_LENGTH]},
    }

    log_prefix = f"[wa{('|' + contexto_log) if contexto_log else ''}]"

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            r = await client.post(url, json=payload, headers=headers)

        if r.status_code == 200:
            data = r.json()
            message_id = ""
            try:
                message_id = data.get("messages", [{}])[0].get("id", "")
            except (IndexError, KeyError, AttributeError):
                pass
            logger.info(f"{log_prefix} enviado a {tel_limpio} ({len(mensaje)} chars)")
            return {
                "exito": True,
                "error": "",
                "message_id": message_id,
                "status_code": 200,
            }
        else:
            err_text = r.text[:300]
            logger.error(f"{log_prefix} {r.status_code}: {err_text}")
            return {
                "exito": False,
                "error": f"Meta API {r.status_code}: {err_text}",
                "message_id": "",
                "status_code": r.status_code,
            }
    except httpx.TimeoutException:
        logger.error(f"{log_prefix} timeout tras {TIMEOUT_SECONDS}s")
        return {
            "exito": False,
            "error": f"Timeout tras {TIMEOUT_SECONDS}s",
            "message_id": "",
            "status_code": 0,
        }
    except Exception as e:
        logger.error(f"{log_prefix} excepción: {e}", exc_info=True)
        return {
            "exito": False,
            "error": str(e)[:300],
            "message_id": "",
            "status_code": 0,
        }


async def enviar_mensaje_lapora(telefono: str, mensaje: str, contexto_log: str = "lapora") -> dict:
    """Atajo: envía mensaje usando credenciales globales de Lapora business.

    Útil para notificaciones a Michael y follow-ups de outreach.
    """
    phone_id, token = credenciales_lapora()
    return await enviar_mensaje_meta(phone_id, token, telefono, mensaje, contexto_log)

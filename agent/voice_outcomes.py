# -*- coding: utf-8 -*-
# agent/voice_outcomes.py — Post-call analysis + WhatsApp follow-up
# Lapora Marketing Digital

"""
Day 6 del Voice Bot.

Cuando una llamada termina (Twilio status callback con status=completed),
este módulo:

1. Carga el transcript completo de la llamada
2. Pide a Claude que clasifique el outcome final + genere resumen ejecutivo
3. Si outcome='interested' o 'callback':
   - Envía WhatsApp al prospecto con info + link Lapora
   - Envía notificación WhatsApp a Michael (+57 320 998 9552)
4. Si outcome='opt_out':
   - Registra el teléfono en VoiceOptOut (lista negra permanente)
5. Actualiza VoiceCall.outcome, resumen_ia, sentimiento
6. Actualiza CRM (estados_prospectos.csv) si es prospect

Diseño: análisis post-call es un async task disparado por el callback Twilio.
NO bloquea el ACK al webhook.
"""

import os
import json
import logging
from datetime import datetime
from typing import Optional
import httpx
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from sqlalchemy import select
from agent.memory import async_session
from agent.voice_models import (
    VoiceCall, VoiceTranscript, registrar_optout,
)
from agent.clinic_models import Clinica

load_dotenv(override=True)
logger = logging.getLogger("agentkit")

# Teléfono personal de Michael para notificaciones (de la memoria del proyecto)
MICHAEL_NOTIF_TEL = os.getenv("LAPORA_OWNER_NOTIF_TEL", "+573209989552")

# Credenciales Meta de Lapora (mismo Phone Number ID que usa SofIA)
LAPORA_PHONE_ID = os.getenv("META_PHONE_NUMBER_ID", "")
LAPORA_ACCESS_TOKEN = os.getenv("META_ACCESS_TOKEN", "")
LAPORA_WA_NUMBER = "+573228783019"  # Número público Lapora

_client: Optional[AsyncAnthropic] = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY no configurada")
        _client = AsyncAnthropic(api_key=api_key)
    return _client


# ════════════════════════════════════════════════════════════
# ENVÍO DE WHATSAPP (Lapora business OR per-tenant clinic)
# ════════════════════════════════════════════════════════════

async def enviar_whatsapp_lapora(telefono: str, mensaje: str) -> dict:
    """Atajo: envía con credenciales globales de Lapora business."""
    from agent.whatsapp_helper import enviar_mensaje_lapora
    return await enviar_mensaje_lapora(telefono, mensaje, contexto_log="voice-outcomes")


async def enviar_whatsapp_target(call: VoiceCall, mensaje: str) -> dict:
    """Envía WhatsApp al target usando credenciales correctas (per-tenant o Lapora).

    - call.clinica_id set → credenciales de esa clínica
    - call.clinica_id None → Lapora business global
    """
    from agent.whatsapp_helper import enviar_mensaje_meta, credenciales_lapora

    if call.clinica_id:
        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.id == call.clinica_id)
            )).scalar_one_or_none()
        if not c:
            return {"exito": False, "error": "Clinica no encontrada"}
        return await enviar_mensaje_meta(
            phone_id=c.whatsapp_phone_id,
            token=c.whatsapp_token,
            telefono=call.telefono,
            mensaje=mensaje,
            contexto_log=f"clinica={c.id}",
        )

    # Lapora outreach
    phone_id, token = credenciales_lapora()
    return await enviar_mensaje_meta(
        phone_id=phone_id, token=token,
        telefono=call.telefono, mensaje=mensaje,
        contexto_log=f"outreach call={call.id}",
    )


# ════════════════════════════════════════════════════════════
# ANÁLISIS POST-CALL CON CLAUDE
# ════════════════════════════════════════════════════════════

SYSTEM_PROMPT_ANALISIS = """Eres un analista de llamadas comerciales para Lapora Marketing Digital.

Recibes el TRANSCRIPT completo de una llamada que SofIA (asistente virtual de Lapora)
hizo a un prospecto o paciente. Tu trabajo es:

1. Clasificar el OUTCOME real de la llamada
2. Detectar el SENTIMIENTO general del interlocutor
3. Generar un RESUMEN ejecutivo de 2-3 frases
4. Sugerir el SIGUIENTE PASO operativo
5. Extraer DATOS CLAVE mencionados (precio, horarios, dudas, etc.)

OUTCOMES POSIBLES (elige UNO):
- "interested": Mostró interés claro. Quiere info, demo o llamada de asesor.
- "not_interested": Rechazó claramente sin agresividad.
- "callback": Pidió que lo llamen en otro momento específico.
- "voicemail": Cayó en buzón, no hubo conversación humana.
- "no_answer": No contestó / cortó antes de conversar.
- "opt_out": Pidió explícitamente NO ser llamado de nuevo.
- "wrong_number": Era número equivocado / no era la persona.
- "failed": Error técnico / corte / inaudible.

SENTIMIENTO (elige UNO): "positivo" | "neutral" | "negativo" | "molesto"

DEBES responder SIEMPRE en este formato JSON exacto:

```json
{
  "outcome": "interested",
  "sentimiento": "positivo",
  "resumen": "El doctor X mostró interés en Lapora Clinic, pidió que un asesor lo llame mañana en la tarde.",
  "siguiente_paso": "Llamar mañana 3pm con propuesta del plan Pro",
  "datos_clave": ["Especialidad: dermatología", "Tamaño consultorio: 200 pacientes/mes", "Objeción: precio"],
  "mensaje_whatsapp_prospecto": "Hola doctor X, fue un gusto hablar con usted hace un momento. Como acordamos, le compartimos info de Lapora Clinic: lapora.studio/clinic/landing. Cualquier duda nos escribe por aquí.",
  "mensaje_whatsapp_michael": "🔥 LEAD: Dr. X (dermatología) interesado en Pro. Pidió que llames mañana 3pm. Resumen: ..."
}
```

REGLAS:
- mensaje_whatsapp_prospecto SOLO si outcome es 'interested' o 'callback'. Si no, vacío.
- mensaje_whatsapp_michael SOLO si outcome es 'interested', 'callback' u 'opt_out'. Si no, vacío.
- Mensajes WhatsApp: máx 300 caracteres, naturales, sin emojis excesivos
- Resumen objetivo, sin marketing
- datos_clave: solo lo MENCIONADO en la conversación
"""


async def analizar_llamada(call_id: int) -> dict:
    """Analiza un transcript con Claude y retorna outcome + resumen + mensajes."""
    async with async_session() as session:
        call = (await session.execute(
            select(VoiceCall).where(VoiceCall.id == call_id)
        )).scalar_one_or_none()
        if not call:
            return {"error": "call no encontrada"}

        # Construir transcript a partir de VoiceTranscript (granular) o usar el agregado
        if call.transcript_completo:
            transcript_txt = call.transcript_completo
        else:
            turnos = (await session.execute(
                select(VoiceTranscript)
                .where(VoiceTranscript.call_id == call.id)
                .order_by(VoiceTranscript.timestamp)
            )).scalars().all()
            lineas = []
            for t in turnos:
                quien = "SofIA" if t.quien_hablo == "bot" else "Persona"
                lineas.append(f"{quien}: {t.contenido}")
            transcript_txt = "\n".join(lineas)

    if not transcript_txt or len(transcript_txt.strip()) < 30:
        return {
            "outcome": "no_answer",
            "sentimiento": "neutral",
            "resumen": "Llamada sin contenido sustantivo.",
            "siguiente_paso": "Reintentar mañana",
            "datos_clave": [],
            "mensaje_whatsapp_prospecto": "",
            "mensaje_whatsapp_michael": "",
        }

    # Contexto del target para el prompt
    contexto_target = f"Target: {call.target_nombre} | Teléfono: {call.telefono} | Tipo: {call.target_type}"
    if call.clinica_id:
        contexto_target += f" | Clínica multi-tenant ID: {call.clinica_id}"
    contexto_target += f" | Script usado: {call.script_id}"

    user_msg = f"""{contexto_target}

TRANSCRIPT COMPLETO DE LA LLAMADA:
\"\"\"
{transcript_txt[:6000]}
\"\"\"

Analiza esta llamada y responde en formato JSON."""

    try:
        client = _get_client()
        response = await client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            temperature=0.2,
            system=SYSTEM_PROMPT_ANALISIS,
            messages=[{"role": "user", "content": user_msg}],
        )

        texto = ""
        for bloque in response.content:
            if bloque.type == "text":
                texto += bloque.text

        return _parsear_json(texto)

    except Exception as e:
        logger.error(f"[voice_outcomes] error análisis call={call_id}: {e}", exc_info=True)
        return {
            "outcome": "failed",
            "sentimiento": "neutral",
            "resumen": f"Error técnico analizando llamada: {str(e)[:100]}",
            "siguiente_paso": "Revisar manualmente",
            "datos_clave": [],
            "mensaje_whatsapp_prospecto": "",
            "mensaje_whatsapp_michael": "",
        }


def _parsear_json(texto: str) -> dict:
    """Parsea JSON de Claude tolerando ```json fences."""
    import re
    if not texto:
        return {}
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if m:
        texto = m.group(1)
    else:
        start = texto.find("{")
        end = texto.rfind("}")
        if start >= 0 and end > start:
            texto = texto[start:end + 1]
    try:
        return json.loads(texto)
    except json.JSONDecodeError:
        return {}


# ════════════════════════════════════════════════════════════
# PROCESAR LLAMADA TERMINADA — pipeline completo
# ════════════════════════════════════════════════════════════

async def procesar_post_call(call_id: int) -> dict:
    """Pipeline completo tras una llamada:
    1. Analizar transcript con Claude
    2. Actualizar VoiceCall (outcome, resumen, sentimiento)
    3. Si interested/callback: enviar WhatsApp al prospecto
    4. Si interested/callback/opt_out: notificar a Michael
    5. Si opt_out: registrar en blacklist
    6. Actualizar VoiceQueue para reagendar (si aplica)

    Llamado desde /voice/twilio/status cuando CallStatus=completed.
    """
    analisis = await analizar_llamada(call_id)
    if "error" in analisis:
        return analisis

    outcome = analisis.get("outcome", "failed")
    sentimiento = analisis.get("sentimiento", "neutral")
    resumen = analisis.get("resumen", "")
    msg_prospecto = analisis.get("mensaje_whatsapp_prospecto", "")
    msg_michael = analisis.get("mensaje_whatsapp_michael", "")

    # 1. Actualizar VoiceCall
    async with async_session() as session:
        call = (await session.execute(
            select(VoiceCall).where(VoiceCall.id == call_id)
        )).scalar_one_or_none()
        if not call:
            return {"error": "call no encontrada"}

        call.outcome = outcome
        call.sentimiento = sentimiento
        call.resumen_ia = resumen[:5000]
        await session.commit()

    # 2. Registrar opt-out si aplica (CRÍTICO)
    if outcome == "opt_out":
        async with async_session() as session:
            call = (await session.execute(
                select(VoiceCall).where(VoiceCall.id == call_id)
            )).scalar_one_or_none()
            await registrar_optout(call.telefono, motivo="Pedido en llamada", origen="voice")
            logger.info(f"[voice_outcomes] opt-out registrado: {call.telefono}")

    # 3. Enviar WhatsApp al prospecto si aplica
    wa_prospecto_ok = False
    if outcome in ("interested", "callback") and msg_prospecto:
        async with async_session() as session:
            call = (await session.execute(
                select(VoiceCall).where(VoiceCall.id == call_id)
            )).scalar_one_or_none()
        envio = await enviar_whatsapp_target(call, msg_prospecto)
        wa_prospecto_ok = envio.get("exito", False)
        if wa_prospecto_ok:
            async with async_session() as session:
                c = (await session.execute(
                    select(VoiceCall).where(VoiceCall.id == call_id)
                )).scalar_one_or_none()
                if c:
                    c.whatsapp_enviado = True
                    await session.commit()

    # 4. Notificar a Michael si aplica
    notif_ok = False
    if outcome in ("interested", "callback", "opt_out") and msg_michael:
        envio_michael = await enviar_whatsapp_lapora(MICHAEL_NOTIF_TEL, msg_michael)
        notif_ok = envio_michael.get("exito", False)
        if notif_ok:
            async with async_session() as session:
                c = (await session.execute(
                    select(VoiceCall).where(VoiceCall.id == call_id)
                )).scalar_one_or_none()
                if c:
                    c.notif_enviada = True
                    await session.commit()

    # 5. Reagendar en cola si aplica
    try:
        from agent.voice_workers import reagendar_segun_outcome
        await reagendar_segun_outcome(call_id)
    except Exception as e:
        logger.warning(f"[voice_outcomes] reagendar falló: {e}")

    return {
        "outcome": outcome,
        "sentimiento": sentimiento,
        "resumen": resumen[:200],
        "whatsapp_prospecto_enviado": wa_prospecto_ok,
        "notif_michael_enviada": notif_ok,
        "datos_clave": analisis.get("datos_clave", []),
    }

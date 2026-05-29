# -*- coding: utf-8 -*-
# agent/voice_mock.py — Simulador de conversaciones para QA sin Twilio
# Lapora Marketing Digital

"""
Mock Mode del Voice Bot.

Cuando VoiceConfig.mock_mode = True (o env var VOICE_MOCK_MODE=1):
- _iniciar_twilio_call() NO llama a Twilio real
- En su lugar invoca simular_conversacion_completa()
- Esta simula una conversación FULL usando 2 instancias de Claude:
  * Bot SofIA (con voice_brain.generar_turno)
  * Prospecto simulado (un actor IA con personalidad random)
- Genera transcript completo
- Marca VoiceCall.estado='completed' + duration estimada
- Dispara procesar_post_call() REAL → WhatsApp follow-up + análisis real

Esto permite probar el sistema end-to-end ANTES de pagar Twilio.
Los WhatsApp follow-ups SÍ se envían (porque ya tenemos Meta credentials).
El único costo: ~$0.02 de Claude por simulación.
"""

import os
import random
import logging
from datetime import datetime, timedelta
from typing import Optional
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from sqlalchemy import select
from agent.memory import async_session
from agent.voice_models import VoiceCall, VoiceTranscript

load_dotenv(override=True)
logger = logging.getLogger("agentkit")

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
# PERSONALIDADES DEL PROSPECTO SIMULADO
# ════════════════════════════════════════════════════════════
# Cada llamada se asigna una personalidad random para probar
# distintos outcomes esperados.

PERSONALIDADES = [
    {
        "id": "interesado_curioso",
        "peso": 25,
        "perfil": "Médico curioso, abierto a innovar. Hace preguntas, pide info por WhatsApp si le explican bien.",
        "outcome_esperado": "interested o callback",
    },
    {
        "id": "ocupado_pero_interesado",
        "peso": 20,
        "perfil": "Dice 'estoy ocupado' al inicio pero acepta que le manden info por WhatsApp.",
        "outcome_esperado": "interested",
    },
    {
        "id": "ya_tiene_proveedor",
        "peso": 15,
        "perfil": "Ya tiene agencia de marketing. Rechaza educadamente pero acepta info comparativa.",
        "outcome_esperado": "callback o interested",
    },
    {
        "id": "no_interesado_directo",
        "peso": 15,
        "perfil": "No le interesa, lo dice claro pero sin agresividad. No pide info.",
        "outcome_esperado": "not_interested",
    },
    {
        "id": "molesto_pide_no_llamen",
        "peso": 10,
        "perfil": "Se molesta con la llamada. Pide explícitamente no ser llamado más. Tono firme.",
        "outcome_esperado": "opt_out",
    },
    {
        "id": "voicemail",
        "peso": 10,
        "perfil": "Es buzón de voz. Solo dice 'deja tu mensaje después del tono'. Nada más.",
        "outcome_esperado": "voicemail",
    },
    {
        "id": "pregunta_precio_decide_despues",
        "peso": 5,
        "perfil": "Pregunta el precio, piensa, dice 'lo voy a pensar y le respondo'. Quiere info por WhatsApp.",
        "outcome_esperado": "callback",
    },
]


def elegir_personalidad() -> dict:
    """Elige una personalidad random ponderada para el prospecto simulado."""
    total = sum(p["peso"] for p in PERSONALIDADES)
    r = random.uniform(0, total)
    acc = 0
    for p in PERSONALIDADES:
        acc += p["peso"]
        if r <= acc:
            return p
    return PERSONALIDADES[0]


# ════════════════════════════════════════════════════════════
# BRAIN DEL PROSPECTO SIMULADO
# ════════════════════════════════════════════════════════════

async def generar_respuesta_prospecto(
    personalidad: dict,
    nombre_doctor: str,
    historial: list[dict],
) -> str:
    """Genera la siguiente respuesta del prospecto simulado.

    Args:
        personalidad: dict de PERSONALIDADES
        nombre_doctor: nombre que SofIA usó para saludar
        historial: lista de turnos [{role, content}]
                   El último mensaje del bot debe estar al final.

    Returns:
        Texto que el prospecto diría
    """
    # Si la personalidad es voicemail, responder con mensaje grabado de buzón
    if personalidad["id"] == "voicemail":
        return "Hola, no puedo atender en este momento. Por favor deja tu mensaje después del tono. Gracias."

    system = f"""Estás simulando una llamada telefónica. Tú eres el DR. {nombre_doctor} (o quien sea que conteste).

PERSONALIDAD QUE DEBES ACTUAR:
{personalidad['perfil']}

REGLAS:
- Habla en español colombiano coloquial
- Respuestas BREVES (máx 1-2 frases) — es una llamada telefónica
- Sé natural, NO actúes como bot
- Puedes interrumpir, pedir aclaraciones, hacer preguntas
- NO menciones que estás simulando
- Si la personalidad es "molesto", sé directo pero no grosero
- Si pides info por WhatsApp, dilo claramente: "mándame por WhatsApp"
- Si no quieres, di "no me interesa" o "no gracias"
- Si quieres terminar, di "bueno, hasta luego" o similar

Acabas de contestar el teléfono y SofIA (asistente virtual de Lapora) te está llamando.
"""

    client = _get_client()
    response = await client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=120,
        temperature=0.85,
        system=system,
        messages=historial,
    )
    texto = ""
    for bloque in response.content:
        if bloque.type == "text":
            texto += bloque.text
    return texto.strip()[:300]


# ════════════════════════════════════════════════════════════
# LOOP COMPLETO DE CONVERSACIÓN SIMULADA
# ════════════════════════════════════════════════════════════

MAX_TURNOS_MOCK = 8  # 8 turnos = ~ 90 seg de llamada real


async def simular_conversacion_completa(call: VoiceCall) -> dict:
    """Simula una conversación completa para esta call.

    Pasos:
    1. Elige personalidad aleatoria
    2. Genera apertura del bot (turno 1)
    3. Genera respuesta del prospecto
    4. Itera hasta que el bot diga end_call=true o se alcance MAX_TURNOS
    5. Guarda transcripts (VoiceTranscript) por cada turno
    6. Actualiza VoiceCall (transcript_completo, duracion_seg, estado=completed)
    7. NO dispara post_call — eso lo hace voice_bot._post_call_background

    Returns: dict con resumen de la simulación
    """
    from agent.voice_brain import generar_turno

    personalidad = elegir_personalidad()
    logger.info(
        f"[voice_mock] simulando call_id={call.id} target={call.target_nombre[:30]} "
        f"personalidad={personalidad['id']}"
    )

    # Variables para el script
    nombre = call.target_nombre or "doctor"
    # Extraer solo el primer nombre/título para naturalidad
    nombre_corto = nombre.replace("Dr. ", "").replace("Dra. ", "").split()[0] if nombre else "doctor"
    variables = {
        "nombre_doctor": nombre,
        "nombre_negocio": nombre,
        "telefono": call.telefono,
        "especialidad": "",
        "ciudad": "Ibagué",
        "nombre_paciente": nombre,
        "nombre_clinica": "su clínica",
        "fecha_cita": "mañana",
        "hora_cita": "10am",
        "motivo": "control",
    }

    transcripts: list[dict] = []  # Para guardar luego como VoiceTranscript
    historial_bot: list[dict] = []
    historial_prospecto: list[dict] = []  # Para el prospecto, perspectiva inversa
    duracion_seg_estimada = 0

    inicio = datetime.utcnow()

    # === Turno 1: apertura del bot ===
    # Pasamos teléfono y clinica_id para que el brain cargue contexto cross-canal
    turno_bot = await generar_turno(
        script_id=call.script_id or "outreach_medicos",
        variables=variables,
        historial=[],
        primer_turno=True,
        telefono_target=call.telefono,
        clinica_id=call.clinica_id,
    )
    transcripts.append({
        "quien": "bot",
        "contenido": turno_bot.respuesta,
        "internal": turno_bot.internal_note,
    })
    historial_bot.append({"role": "assistant", "content": turno_bot.respuesta})
    # Para el prospecto: lo que escucha es lo que dijo el bot
    historial_prospecto.append({"role": "user", "content": f"[SofIA dice]: {turno_bot.respuesta}"})
    duracion_seg_estimada += max(3, len(turno_bot.respuesta.split()) // 3)

    end_call = turno_bot.end_call
    outcome_final = turno_bot.outcome
    send_wa = turno_bot.send_whatsapp_summary
    optout_flag = turno_bot.optout
    transfer = turno_bot.transfer_to_human

    # === Loop: prospecto responde → bot responde → repite ===
    for turno_idx in range(MAX_TURNOS_MOCK):
        if end_call:
            break

        # Respuesta del prospecto simulado
        resp_prospecto = await generar_respuesta_prospecto(
            personalidad=personalidad,
            nombre_doctor=nombre_corto,
            historial=historial_prospecto,
        )
        transcripts.append({"quien": "persona", "contenido": resp_prospecto, "internal": ""})
        historial_bot.append({"role": "user", "content": resp_prospecto})
        historial_prospecto.append({"role": "assistant", "content": resp_prospecto})
        duracion_seg_estimada += max(3, len(resp_prospecto.split()) // 3)

        # Turno del bot respondiendo
        turno_bot = await generar_turno(
            script_id=call.script_id or "outreach_medicos",
            variables=variables,
            historial=historial_bot,
            transcript_usuario=resp_prospecto,
            primer_turno=False,
            telefono_target=call.telefono,
            clinica_id=call.clinica_id,
        )
        transcripts.append({
            "quien": "bot",
            "contenido": turno_bot.respuesta,
            "internal": turno_bot.internal_note,
        })
        historial_bot.append({"role": "assistant", "content": turno_bot.respuesta})
        historial_prospecto.append({"role": "user", "content": f"[SofIA dice]: {turno_bot.respuesta}"})
        duracion_seg_estimada += max(3, len(turno_bot.respuesta.split()) // 3)

        end_call = turno_bot.end_call
        if turno_bot.outcome:
            outcome_final = turno_bot.outcome
        send_wa = send_wa or turno_bot.send_whatsapp_summary
        optout_flag = optout_flag or turno_bot.optout
        transfer = transfer or turno_bot.transfer_to_human

    # Si llegamos al max turnos sin cerrar, asignar outcome 'failed'
    if not end_call and not outcome_final:
        outcome_final = "failed"

    fin = datetime.utcnow()

    # Armar transcript_completo
    lineas = []
    for t in transcripts:
        prefix = "SofIA" if t["quien"] == "bot" else "Persona"
        lineas.append(f"{prefix}: {t['contenido']}")
    transcript_txt = "\n".join(lineas)

    # Persistir en BD: VoiceCall + VoiceTranscript
    async with async_session() as session:
        c = (await session.execute(
            select(VoiceCall).where(VoiceCall.id == call.id)
        )).scalar_one_or_none()
        if c:
            c.estado = "completed"
            c.outcome = outcome_final
            c.transcript_completo = transcript_txt
            c.duracion_seg = duracion_seg_estimada
            c.inicio = inicio
            c.fin = fin
            # Mock cost: solo Claude (~$0.02 por simulación con 8 turnos)
            c.costo_usd = round(0.02 * (len(transcripts) / 16), 4)
            c.twilio_call_sid = f"MOCK_{call.id}_{int(inicio.timestamp())}"
            c.error_msg = f"[MOCK MODE] personalidad={personalidad['id']}"

        # Guardar cada turno como VoiceTranscript
        ts_acumulado = inicio
        for t in transcripts:
            session.add(VoiceTranscript(
                call_id=call.id,
                quien_hablo=t["quien"],
                contenido=t["contenido"],
                script_nodo=t.get("internal", "")[:80],
                timestamp=ts_acumulado,
            ))
            ts_acumulado += timedelta(seconds=10)
        await session.commit()

    logger.info(
        f"[voice_mock] call_id={call.id} terminada — outcome={outcome_final} "
        f"turnos={len(transcripts)} duracion={duracion_seg_estimada}s personalidad={personalidad['id']}"
    )

    return {
        "exito": True,
        "outcome": outcome_final,
        "turnos": len(transcripts),
        "duracion_seg": duracion_seg_estimada,
        "personalidad": personalidad["id"],
    }


# ════════════════════════════════════════════════════════════
# ENTRY POINT — se llama desde voice_workers._iniciar_twilio_call
# ════════════════════════════════════════════════════════════

async def iniciar_call_mock(call: VoiceCall) -> bool:
    """Equivalente mock de _iniciar_twilio_call.

    Simula la conversación completa de forma síncrona y dispara post-call
    analysis al final (igual que haría el callback de Twilio).
    """
    try:
        resultado = await simular_conversacion_completa(call)
    except Exception as e:
        logger.error(f"[voice_mock] error simulando call={call.id}: {e}", exc_info=True)
        # Marcar como failed
        async with async_session() as session:
            c = (await session.execute(
                select(VoiceCall).where(VoiceCall.id == call.id)
            )).scalar_one_or_none()
            if c:
                c.estado = "failed"
                c.outcome = "failed"
                c.error_msg = f"[MOCK error] {str(e)[:300]}"
                c.fin = datetime.utcnow()
                await session.commit()
        return False

    # Disparar post-call analysis (igual que Twilio callback)
    try:
        from agent.voice_outcomes import procesar_post_call
        await procesar_post_call(call.id)
    except Exception as e:
        logger.error(f"[voice_mock] post-call error call={call.id}: {e}", exc_info=True)

    return True

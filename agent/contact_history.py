# -*- coding: utf-8 -*-
# agent/contact_history.py — Historia unificada cross-canal por contacto
# Lapora Marketing Digital

"""
Memoria unificada de SofIA. Junta en orden cronológico:
- Mensajes de chat (WhatsApp/Instagram/Email) — del CRM Lapora o de una clínica
- Llamadas de voz (con outcome, resumen, transcript comprimido)

Usado por:
- brain.py — cuando responde un chat, ve si hubo llamadas previas
- voice_brain.py — cuando llama, ve si hubo chats previos
- clinic_brain.py — versión multi-tenant per-clínica

Garantías:
- Aislamiento multi-tenant: si clinica_id está set, SOLO ve eventos de esa clínica
- Sin clinica_id (Lapora): SOLO ve Mensaje (CRM SofIA) + VoiceCall(clinica_id=None)
- Orden cronológico estricto (más viejo → más nuevo)
- Trunca contenidos largos para no inflar el prompt
"""

import logging
from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, desc, or_, and_

from agent.memory import async_session, Mensaje
from agent.voice_models import VoiceCall

logger = logging.getLogger("agentkit")

# Límites para mantener el contexto manejable
MAX_EVENTOS_RETORNAR = 30
MAX_CHARS_CONTENIDO_CHAT = 400
MAX_CHARS_RESUMEN_CALL = 500
MAX_CHARS_TRANSCRIPT_PREVIEW = 800


def _normalizar_tel(telefono: str) -> str:
    """Normaliza un teléfono a solo dígitos para matching robusto."""
    return "".join(c for c in (telefono or "") if c.isdigit())


async def obtener_historial_unificado(
    telefono: str,
    clinica_id: Optional[int] = None,
    dias_atras: int = 90,
    limite: int = MAX_EVENTOS_RETORNAR,
) -> list[dict]:
    """Devuelve eventos cronológicos cross-canal para un teléfono.

    Args:
        telefono: Número (con o sin +, con o sin espacios)
        clinica_id: None=Lapora CRM. Set=clínica específica multi-tenant.
        dias_atras: Cuántos días hacia atrás mirar (default 90)
        limite: Máximo de eventos a retornar (default 30)

    Returns:
        Lista de dicts ordenados por timestamp ASC (más viejo primero):
        Chat: {tipo: "chat", direccion: "in/out", fecha, contenido, canal}
        Call: {tipo: "call", direccion: "out", fecha, outcome, resumen,
               duracion_seg, transcript_preview}
    """
    tel_limpio = _normalizar_tel(telefono)
    if not tel_limpio:
        return []

    desde = datetime.utcnow() - timedelta(days=dias_atras)
    eventos: list[dict] = []

    # Chats y llamadas son queries independientes — paralelas
    import asyncio
    if clinica_id is None:
        # === Lapora CRM ===
        await asyncio.gather(
            _cargar_chats_lapora(eventos, tel_limpio, desde),
            _cargar_llamadas(eventos, tel_limpio, clinica_id=None, desde=desde),
        )
    else:
        # === Clínica multi-tenant ===
        await asyncio.gather(
            _cargar_chats_clinica(eventos, tel_limpio, clinica_id, desde),
            _cargar_llamadas(eventos, tel_limpio, clinica_id=clinica_id, desde=desde),
        )

    # Orden cronológico ASC
    eventos.sort(key=lambda e: e.get("fecha") or datetime.min)

    # Si excede el límite, quedarse con los MÁS RECIENTES (cola)
    if len(eventos) > limite:
        eventos = eventos[-limite:]

    return eventos


async def _cargar_chats_lapora(eventos: list, tel_limpio: str, desde: datetime):
    """Carga mensajes del CRM principal SofIA (tabla mensajes)."""
    async with async_session() as session:
        # Match flexible: el telefono puede estar con o sin +
        result = await session.execute(
            select(Mensaje)
            .where(or_(
                Mensaje.telefono == tel_limpio,
                Mensaje.telefono == f"+{tel_limpio}",
                Mensaje.telefono.contains(tel_limpio[-10:]),
            ))
            .where(Mensaje.timestamp >= desde)
            .order_by(Mensaje.timestamp)
            .limit(100)
        )
        for m in result.scalars().all():
            direccion = "in" if m.role == "user" else "out"
            contenido = (m.content or "").strip()
            if not contenido:
                continue
            eventos.append({
                "tipo": "chat",
                "direccion": direccion,
                "fecha": m.timestamp,
                "contenido": contenido[:MAX_CHARS_CONTENIDO_CHAT],
                "canal": "whatsapp",
                "source_id": m.id,
            })


async def _cargar_chats_clinica(
    eventos: list, tel_limpio: str, clinica_id: int, desde: datetime
):
    """Carga MensajeUnificado de una clínica específica."""
    # Importar acá para evitar circular si alguien importa este módulo desde memory
    from agent.clinic_models import MensajeUnificado, Paciente

    async with async_session() as session:
        # Encontrar el paciente por teléfono
        paciente = (await session.execute(
            select(Paciente)
            .where(Paciente.clinica_id == clinica_id)
            .where(or_(
                Paciente.telefono == tel_limpio,
                Paciente.telefono == f"+{tel_limpio}",
                Paciente.telefono.contains(tel_limpio[-10:]),
            ))
            .limit(1)
        )).scalar_one_or_none()

        if not paciente:
            return

        result = await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.clinica_id == clinica_id)
            .where(MensajeUnificado.paciente_id == paciente.id)
            .where(MensajeUnificado.timestamp >= desde)
            .order_by(MensajeUnificado.timestamp)
            .limit(100)
        )
        for m in result.scalars().all():
            contenido = (m.contenido or "").strip()
            if not contenido:
                continue
            eventos.append({
                "tipo": "chat",
                "direccion": "in" if m.direccion == "entrada" else "out",
                "fecha": m.timestamp,
                "contenido": contenido[:MAX_CHARS_CONTENIDO_CHAT],
                "canal": m.canal or "whatsapp",
                "source_id": m.id,
                "respondido_por": m.respondido_por or "",
            })


async def _cargar_llamadas(
    eventos: list,
    tel_limpio: str,
    clinica_id: Optional[int],
    desde: datetime,
):
    """Carga VoiceCall filtrando por tenant correcto."""
    async with async_session() as session:
        query = (
            select(VoiceCall)
            .where(or_(
                VoiceCall.telefono == tel_limpio,
                VoiceCall.telefono == f"+{tel_limpio}",
                VoiceCall.telefono.contains(tel_limpio[-10:]),
            ))
            .where(VoiceCall.creada_en >= desde)
            .order_by(VoiceCall.creada_en)
            .limit(20)
        )
        # Aislamiento multi-tenant CRÍTICO
        if clinica_id is None:
            query = query.where(VoiceCall.clinica_id.is_(None))
        else:
            query = query.where(VoiceCall.clinica_id == clinica_id)

        result = await session.execute(query)
        for c in result.scalars().all():
            # Solo eventos con contenido significativo
            if not c.outcome and not c.resumen_ia and not c.transcript_completo:
                continue
            transcript_preview = ""
            if c.transcript_completo:
                # Tomar las primeras N líneas para preview
                lineas = c.transcript_completo.split("\n")[:6]
                transcript_preview = "\n".join(lineas)[:MAX_CHARS_TRANSCRIPT_PREVIEW]

            eventos.append({
                "tipo": "call",
                "direccion": "out",  # Siempre outbound (Lapora llama)
                "fecha": c.creada_en or c.inicio,
                "outcome": c.outcome or "",
                "sentimiento": c.sentimiento or "",
                "resumen": (c.resumen_ia or "")[:MAX_CHARS_RESUMEN_CALL],
                "duracion_seg": int(c.duracion_seg or 0),
                "transcript_preview": transcript_preview,
                "source_id": c.id,
            })


# ════════════════════════════════════════════════════════════
# FORMATEO PARA SYSTEM PROMPT — Compresión inteligente
# ════════════════════════════════════════════════════════════

def formatear_historial_para_prompt(
    eventos: list[dict],
    incluir_transcripts: bool = False,
    titulo_seccion: str = "HISTORIAL PREVIO DE INTERACCIONES",
) -> str:
    """Convierte eventos en texto compacto para incluir en system prompt.

    Args:
        eventos: salida de obtener_historial_unificado()
        incluir_transcripts: True si queremos preview del transcript de llamadas
                            (False = solo resumen IA, ahorra tokens)
        titulo_seccion: nombre del bloque en el prompt

    Returns:
        Texto formateado, vacío si no hay eventos.
    """
    if not eventos:
        return ""

    # Stats rápidas
    n_chats = sum(1 for e in eventos if e["tipo"] == "chat")
    n_calls = sum(1 for e in eventos if e["tipo"] == "call")
    desde_str = eventos[0]["fecha"].strftime("%d/%m/%Y") if eventos else ""
    hasta_str = eventos[-1]["fecha"].strftime("%d/%m/%Y") if eventos else ""

    lineas = [
        f"# {titulo_seccion}",
        f"Has tenido {n_chats} mensajes y {n_calls} llamada(s) con esta persona entre {desde_str} y {hasta_str}.",
        "Resumen cronológico (más viejo arriba):",
        "",
    ]

    for e in eventos:
        fecha_str = e["fecha"].strftime("%d/%m %H:%M") if e.get("fecha") else "?"
        if e["tipo"] == "chat":
            quien = "PACIENTE/DOCTOR" if e["direccion"] == "in" else "SofIA"
            canal = e.get("canal", "wa").upper()[:2]
            lineas.append(f"[{fecha_str}] [{canal}] {quien}: {e['contenido']}")
        elif e["tipo"] == "call":
            outcome = (e.get("outcome") or "?").upper()
            dur = e.get("duracion_seg", 0)
            resumen = e.get("resumen") or ""
            sentim = f" sentimiento={e['sentimiento']}" if e.get("sentimiento") else ""
            lineas.append(f"[{fecha_str}] [LLAMADA {outcome} {dur}s{sentim}]")
            if resumen:
                lineas.append(f"  Resumen IA: {resumen}")
            if incluir_transcripts and e.get("transcript_preview"):
                preview = e["transcript_preview"].replace("\n", " | ")[:300]
                lineas.append(f"  Inicio transcript: {preview}")

    lineas.append("")
    lineas.append(
        "Usa este contexto para mantener continuidad. NO repitas información que "
        "ya conocés. Si en una llamada el doctor dijo X, no le preguntés lo mismo."
    )

    return "\n".join(lineas)


# ════════════════════════════════════════════════════════════
# HELPERS DE ALTO NIVEL — Para usar directo desde los brains
# ════════════════════════════════════════════════════════════

async def contexto_para_brain_chat(
    telefono: str,
    clinica_id: Optional[int] = None,
) -> str:
    """Genera bloque de contexto para inyectar al system prompt del brain de CHAT.

    Solo incluye LLAMADAS previas (los chats van naturalmente en `messages=`).
    Si no hay llamadas, retorna string vacío (no contamina el prompt).
    """
    eventos = await obtener_historial_unificado(telefono, clinica_id=clinica_id)
    # Filtrar solo calls para chat brain (chats van como messages array)
    calls = [e for e in eventos if e["tipo"] == "call"]
    if not calls:
        return ""
    return formatear_historial_para_prompt(
        calls,
        incluir_transcripts=False,
        titulo_seccion="LLAMADAS PREVIAS CON ESTE CONTACTO",
    )


async def contexto_para_brain_voz(
    telefono: str,
    clinica_id: Optional[int] = None,
) -> str:
    """Genera bloque de contexto para inyectar al system prompt del brain de VOZ.

    Incluye CHATS previos (cuando llamamos a alguien que ya nos escribió).
    Incluye LLAMADAS previas (si ya lo llamamos antes).
    """
    eventos = await obtener_historial_unificado(telefono, clinica_id=clinica_id)
    if not eventos:
        return ""
    return formatear_historial_para_prompt(
        eventos,
        incluir_transcripts=False,
        titulo_seccion="CONTEXTO PREVIO CON ESTE CONTACTO",
    )

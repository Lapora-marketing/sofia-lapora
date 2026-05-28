# -*- coding: utf-8 -*-
# agent/voice_models.py — Modelos para Lapora Voice Bot
# Lapora Marketing Digital

"""
Modelos SQLAlchemy para el calling bot de Lapora.

Arquitectura:
- VoiceCall: cada llamada física (con Twilio call SID, transcript, outcome)
- VoiceQueue: cola de llamadas pendientes (un prospecto puede tener múltiples retries)
- VoiceTranscript: turnos individuales de la conversación (para auditar y entrenar)

Outcomes posibles:
- pending: en cola, sin llamar aún
- in_progress: marcando o conversando ahora mismo
- interested: prospecto interesado → triggerea WhatsApp follow-up
- not_interested: prospecto rechazó
- callback: pidió que lo llamemos después
- voicemail: cayó en buzón → reagendar
- no_answer: no contestó → retry
- opt_out: pidió no ser llamado nuevamente (NUNCA reintentar)
- failed: error técnico
"""

import secrets
from datetime import datetime
from typing import Optional
from sqlalchemy import (
    String, Text, DateTime, Integer, Boolean, ForeignKey, Float, select, desc, func
)
from sqlalchemy.orm import Mapped, mapped_column

# Reusamos Base y session del archivo memory.py existente
from agent.memory import Base, async_session


# ════════════════════════════════════════════════════════════
# VOICE CALL — Una llamada física (con metadata Twilio)
# ════════════════════════════════════════════════════════════

class VoiceCall(Base):
    """Una llamada física hecha (o intentada) a un prospecto / paciente.

    Multi-tenant: si clinica_id es None → es llamada de Lapora a prospectos del CSV.
                  si clinica_id está set → es llamada de una clínica a su paciente.
    """
    __tablename__ = "voice_calls"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    # Multi-tenant: None = Lapora outreach. Set = llamada de clínica X.
    clinica_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clinic_clinicas.id"), nullable=True, index=True
    )

    # Target — A quién llamamos
    # target_type: "prospect" (de outreach CSV) | "paciente" (Lapora Clinic) | "contacto"
    target_type: Mapped[str] = mapped_column(String(20), index=True)
    target_id:   Mapped[str] = mapped_column(String(100), index=True)  # ID en su tabla
    target_nombre: Mapped[str] = mapped_column(String(200), default="")
    telefono: Mapped[str] = mapped_column(String(50), index=True)

    # Twilio
    twilio_call_sid: Mapped[str] = mapped_column(String(60), default="", index=True)
    twilio_from:     Mapped[str] = mapped_column(String(50), default="")  # nuestro número

    # Script usado (referencia a voice_scripts.yaml)
    script_id: Mapped[str] = mapped_column(String(50), default="outreach_medicos")

    # Estado
    # pending | in_progress | completed | failed
    estado: Mapped[str] = mapped_column(String(30), default="pending", index=True)
    # interested | not_interested | callback | voicemail | no_answer | opt_out | failed
    outcome: Mapped[str] = mapped_column(String(30), default="", index=True)

    # Transcripts y análisis
    transcript_completo: Mapped[str] = mapped_column(Text, default="")
    resumen_ia: Mapped[str] = mapped_column(Text, default="")  # Claude summary post-call
    sentimiento: Mapped[str] = mapped_column(String(30), default="")  # positivo|neutral|negativo

    # Metadata operativa
    intentos:        Mapped[int] = mapped_column(Integer, default=0)
    duracion_seg:    Mapped[int] = mapped_column(Integer, default=0)
    costo_usd:       Mapped[float] = mapped_column(Float, default=0.0)
    error_msg:       Mapped[str] = mapped_column(String(500), default="")

    # Follow-up
    whatsapp_enviado: Mapped[bool] = mapped_column(Boolean, default=False)
    notif_enviada:    Mapped[bool] = mapped_column(Boolean, default=False)

    # Timestamps
    programada_para: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True, index=True)
    inicio:          Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    fin:             Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    creada_en:       Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ════════════════════════════════════════════════════════════
# VOICE QUEUE — Cola de pendientes (con priorización)
# ════════════════════════════════════════════════════════════

class VoiceQueue(Base):
    """Cola con prospectos/pacientes que esperan ser llamados.

    Una entry en la cola produce una o más VoiceCall (si hay retries).
    Cuando un VoiceQueue.intentos_restantes llega a 0 → estado=agotado.
    """
    __tablename__ = "voice_queue"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)

    clinica_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("clinic_clinicas.id"), nullable=True, index=True
    )

    target_type:    Mapped[str] = mapped_column(String(20), index=True)
    target_id:      Mapped[str] = mapped_column(String(100), index=True)
    target_nombre:  Mapped[str] = mapped_column(String(200), default="")
    telefono:       Mapped[str] = mapped_column(String(50), index=True)
    script_id:      Mapped[str] = mapped_column(String(50), default="outreach_medicos")

    # Prioridad y agendado
    prioridad:       Mapped[int] = mapped_column(Integer, default=50, index=True)  # 0-100, mayor=más urgente
    programada_para: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)

    # Estado: queued | locked | done | optout | agotado
    estado: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    intentos_realizados:  Mapped[int] = mapped_column(Integer, default=0)
    intentos_restantes:   Mapped[int] = mapped_column(Integer, default=3)
    ultima_call_id:       Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Lock para evitar doble dispatch desde múltiples workers
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    locked_by:    Mapped[str] = mapped_column(String(50), default="")

    creada_en: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


# ════════════════════════════════════════════════════════════
# VOICE TRANSCRIPT — Turnos individuales (auditoría fina)
# ════════════════════════════════════════════════════════════

class VoiceTranscript(Base):
    """Cada turno (frase) de la conversación, con timing exacto.

    Útil para:
    - Debugging: dónde se cortó la conversación
    - Análisis: qué objeción se repite más
    - Mejora de scripts: qué frases del bot funcionan mejor
    """
    __tablename__ = "voice_transcripts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    call_id: Mapped[int] = mapped_column(ForeignKey("voice_calls.id"), index=True)

    # quien_hablo: bot | persona
    quien_hablo: Mapped[str] = mapped_column(String(10))
    contenido:   Mapped[str] = mapped_column(Text)
    duracion_ms: Mapped[int] = mapped_column(Integer, default=0)

    # Si fue el bot: qué nodo del script generó esto
    script_nodo: Mapped[str] = mapped_column(String(80), default="")
    # Si fue persona: confianza STT (0-100)
    confianza_stt: Mapped[int] = mapped_column(Integer, default=0)

    timestamp: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)


# ════════════════════════════════════════════════════════════
# VOICE CONFIG — Estado global del scheduler (pause/resume)
# ════════════════════════════════════════════════════════════

class VoiceConfig(Base):
    """Singleton: estado global del Voice Bot scheduler.

    Solo hay UNA fila (id=1). Si no existe, se crea automáticamente con
    defaults (no pausado). Permite pausar/reanudar el scheduler sin
    redespliegue.
    """
    __tablename__ = "voice_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)  # siempre 1
    scheduler_pausado: Mapped[bool] = mapped_column(Boolean, default=False)
    motivo_pausa:      Mapped[str] = mapped_column(String(300), default="")
    pausado_por:       Mapped[str] = mapped_column(String(100), default="")
    pausado_en:        Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


async def obtener_config_voice() -> VoiceConfig:
    """Devuelve la fila singleton. La crea si no existe."""
    async with async_session() as session:
        cfg = (await session.execute(
            select(VoiceConfig).where(VoiceConfig.id == 1)
        )).scalar_one_or_none()
        if not cfg:
            cfg = VoiceConfig(id=1, scheduler_pausado=False)
            session.add(cfg)
            await session.commit()
            await session.refresh(cfg)
    return cfg


async def esta_pausado() -> bool:
    """True si el scheduler está pausado globalmente."""
    cfg = await obtener_config_voice()
    return bool(cfg.scheduler_pausado)


async def pausar_scheduler(motivo: str = "", por: str = "admin") -> bool:
    """Pausa el scheduler. Idempotente."""
    async with async_session() as session:
        cfg = (await session.execute(
            select(VoiceConfig).where(VoiceConfig.id == 1)
        )).scalar_one_or_none()
        if not cfg:
            cfg = VoiceConfig(id=1)
            session.add(cfg)
            await session.flush()
        cfg.scheduler_pausado = True
        cfg.motivo_pausa = (motivo or "")[:300]
        cfg.pausado_por = (por or "admin")[:100]
        cfg.pausado_en = datetime.utcnow()
        await session.commit()
    return True


async def reanudar_scheduler() -> bool:
    """Reanuda el scheduler."""
    async with async_session() as session:
        cfg = (await session.execute(
            select(VoiceConfig).where(VoiceConfig.id == 1)
        )).scalar_one_or_none()
        if not cfg:
            cfg = VoiceConfig(id=1, scheduler_pausado=False)
            session.add(cfg)
            await session.commit()
            return True
        cfg.scheduler_pausado = False
        cfg.motivo_pausa = ""
        cfg.pausado_por = ""
        cfg.pausado_en = None
        await session.commit()
    return True


# ════════════════════════════════════════════════════════════
# OPT-OUT LIST — Números que pidieron no ser llamados (CRÍTICO)
# ════════════════════════════════════════════════════════════

class VoiceOptOut(Base):
    """Lista negra de números que pidieron NO ser llamados.

    Antes de hacer cualquier llamada, voice_workers.py debe consultar esta
    tabla. Si el teléfono está aquí → NUNCA llamar. Cumplimiento legal CO.
    """
    __tablename__ = "voice_optouts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telefono: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    motivo:   Mapped[str] = mapped_column(String(300), default="")
    fecha:    Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    origen:   Mapped[str] = mapped_column(String(30), default="voice")  # voice|email|whatsapp|manual


# ════════════════════════════════════════════════════════════
# HELPERS — Queries comunes
# ════════════════════════════════════════════════════════════

async def telefono_en_optout(telefono: str) -> bool:
    """True si el número está en la lista negra. CRÍTICO consultar antes de cada llamada."""
    if not telefono:
        return True  # Sin número → no llamar
    tel_limpio = "".join(c for c in telefono if c.isdigit() or c == "+")
    async with async_session() as session:
        existe = (await session.execute(
            select(VoiceOptOut.id).where(VoiceOptOut.telefono == tel_limpio).limit(1)
        )).scalar_one_or_none()
    return existe is not None


async def registrar_optout(telefono: str, motivo: str = "", origen: str = "voice") -> bool:
    """Agrega un número a la lista negra. Idempotente."""
    tel_limpio = "".join(c for c in (telefono or "") if c.isdigit() or c == "+")
    if not tel_limpio:
        return False
    async with async_session() as session:
        existe = (await session.execute(
            select(VoiceOptOut).where(VoiceOptOut.telefono == tel_limpio)
        )).scalar_one_or_none()
        if existe:
            return True  # ya está
        session.add(VoiceOptOut(
            telefono=tel_limpio,
            motivo=motivo[:300],
            origen=origen,
        ))
        await session.commit()
    return True


async def proxima_llamada_en_cola() -> Optional[VoiceQueue]:
    """Devuelve la siguiente llamada lista para procesar.

    Filtros:
    - estado = queued
    - programada_para <= ahora
    - intentos_restantes > 0
    - NO está locked (locked_until > ahora)
    - Ordena por prioridad DESC, luego programada_para ASC
    """
    ahora = datetime.utcnow()
    async with async_session() as session:
        result = await session.execute(
            select(VoiceQueue)
            .where(VoiceQueue.estado == "queued")
            .where(VoiceQueue.programada_para <= ahora)
            .where(VoiceQueue.intentos_restantes > 0)
            .where((VoiceQueue.locked_until.is_(None)) | (VoiceQueue.locked_until < ahora))
            .order_by(desc(VoiceQueue.prioridad), VoiceQueue.programada_para)
            .limit(1)
        )
        return result.scalar_one_or_none()


async def encolar_prospecto(
    target_type: str,
    target_id: str,
    target_nombre: str,
    telefono: str,
    script_id: str = "outreach_medicos",
    prioridad: int = 50,
    clinica_id: Optional[int] = None,
    programada_para: Optional[datetime] = None,
    intentos_max: int = 3,
) -> Optional[VoiceQueue]:
    """Agrega un prospecto a la cola. Verifica opt-out. Idempotente por (target_type, target_id)."""

    # CRÍTICO: nunca encolar si está en opt-out
    if await telefono_en_optout(telefono):
        return None

    async with async_session() as session:
        # No duplicar si ya hay uno queued o en progreso
        existe = (await session.execute(
            select(VoiceQueue)
            .where(VoiceQueue.target_type == target_type)
            .where(VoiceQueue.target_id == str(target_id))
            .where(VoiceQueue.estado.in_(["queued", "locked"]))
        )).scalar_one_or_none()
        if existe:
            return existe

        entry = VoiceQueue(
            clinica_id=clinica_id,
            target_type=target_type,
            target_id=str(target_id),
            target_nombre=target_nombre[:200],
            telefono=telefono,
            script_id=script_id,
            prioridad=int(max(0, min(100, prioridad))),
            programada_para=programada_para or datetime.utcnow(),
            intentos_restantes=int(intentos_max),
        )
        session.add(entry)
        await session.commit()
        await session.refresh(entry)
    return entry


async def metricas_voice(clinica_id: Optional[int] = None) -> dict:
    """Resumen agregado: cuántas en cola, llamadas hoy, outcomes."""
    from datetime import timedelta
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    async with async_session() as session:
        # Cola pendiente
        q_cola = select(func.count(VoiceQueue.id)).where(VoiceQueue.estado == "queued")
        if clinica_id is not None:
            q_cola = q_cola.where(VoiceQueue.clinica_id == clinica_id)
        en_cola = (await session.execute(q_cola)).scalar() or 0

        # Llamadas hoy
        q_hoy = select(func.count(VoiceCall.id)).where(VoiceCall.creada_en >= hoy_inicio)
        if clinica_id is not None:
            q_hoy = q_hoy.where(VoiceCall.clinica_id == clinica_id)
        hoy = (await session.execute(q_hoy)).scalar() or 0

        # Outcomes de los últimos 7 días
        hace_7d = datetime.utcnow() - timedelta(days=7)
        q_out = (
            select(VoiceCall.outcome, func.count(VoiceCall.id))
            .where(VoiceCall.creada_en >= hace_7d)
            .where(VoiceCall.outcome != "")
            .group_by(VoiceCall.outcome)
        )
        if clinica_id is not None:
            q_out = q_out.where(VoiceCall.clinica_id == clinica_id)
        outcomes = {row[0]: row[1] for row in (await session.execute(q_out)).all()}

        # Costo total mes
        mes_inicio = hoy_inicio.replace(day=1)
        q_cost = select(func.sum(VoiceCall.costo_usd)).where(VoiceCall.creada_en >= mes_inicio)
        if clinica_id is not None:
            q_cost = q_cost.where(VoiceCall.clinica_id == clinica_id)
        costo_mes = float((await session.execute(q_cost)).scalar() or 0)

    return {
        "en_cola": int(en_cola),
        "llamadas_hoy": int(hoy),
        "outcomes_7d": outcomes,
        "costo_mes_usd": round(costo_mes, 2),
    }


# ════════════════════════════════════════════════════════════
# MIGRACIONES — Tablas nuevas se crean con create_all() automáticamente
# ════════════════════════════════════════════════════════════
# No necesitamos ALTER TABLE porque son tablas completamente nuevas.
# Se crean al arrancar el servidor en inicializar_db().

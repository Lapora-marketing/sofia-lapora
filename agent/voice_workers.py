# -*- coding: utf-8 -*-
# agent/voice_workers.py — Cola y scheduler del Voice Bot
# Lapora Marketing Digital

"""
Workers async del Voice Bot.

Día 4: Scheduler que dispara llamadas respetando:
1. Horario hábil Colombia: Lun-Vie 9-12am + 2-5pm (UTC-5)
2. Throttle: 1 llamada nueva cada 15 min (~16/día max)
3. Locks: evita doble dispatch concurrente
4. Reintentos: no-answer → reagenda +1 día, voicemail → +2 días
5. Respeta opt-out: nunca llama a un número en blacklist

Cómo se integra:
- main.py lifespan llama iniciar_voice_workers() al arrancar
- El loop corre cada 5 min, decide si hay que llamar a alguien
- Si sí: marca el VoiceQueue como locked + dispara la llamada Twilio
- Si no (fuera de horario / throttle): espera
"""

import asyncio
import logging
import os
from datetime import datetime, timedelta, time as dtime
from typing import Optional
try:
    from zoneinfo import ZoneInfo  # Python 3.9+ (Linux/Mac)
    TZ_CO = ZoneInfo("America/Bogota")
except Exception:
    import pytz  # Fallback Windows
    TZ_CO = pytz.timezone("America/Bogota")
from sqlalchemy import select, desc, func

from agent.memory import async_session
from agent.voice_models import (
    VoiceQueue, VoiceCall, VoiceOptOut,
    proxima_llamada_en_cola, telefono_en_optout, esta_pausado,
)

logger = logging.getLogger("agentkit")

# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN DEL SCHEDULER
# ════════════════════════════════════════════════════════════

# TZ_CO ya está definido arriba (zoneinfo o pytz)

# Horario hábil (hora local Colombia)
VENTANAS_HABILES = [
    (dtime(9, 0),  dtime(12, 0)),    # Mañana 9-12
    (dtime(14, 0), dtime(17, 0)),    # Tarde 2-5
]
DIAS_HABILES = {0, 1, 2, 3, 4}        # Lun-Vie (Mon=0)

# Throttle: cada cuánto disparar UNA llamada
THROTTLE_MIN_ENTRE_CALLS = 15  # 15 min entre nuevas llamadas

# Loop check cadence
INTERVALO_CHECK_SEG = 60  # Revisamos cada minuto si toca llamar

# Reintentos
REINTENTO_NO_ANSWER_HORAS = 24
REINTENTO_VOICEMAIL_HORAS = 48
REINTENTO_BUSY_HORAS = 4

# Lock timeout (si una llamada se queda colgada en "locked", liberar después de 30 min)
LOCK_TIMEOUT_MIN = 30


# ════════════════════════════════════════════════════════════
# HELPERS DE HORARIO
# ════════════════════════════════════════════════════════════

def hora_actual_co() -> datetime:
    """Hora actual en Colombia (UTC-5)."""
    return datetime.now(TZ_CO)


def _to_utc_naive(dt: datetime) -> datetime:
    """Convierte un datetime aware (cualquier TZ) a UTC naive para guardar en BD."""
    if dt.tzinfo is None:
        return dt
    # Convert to UTC, then strip tz
    try:
        import pytz
        utc = pytz.UTC
    except ImportError:
        from zoneinfo import ZoneInfo as _ZI
        utc = _ZI("UTC")
    return dt.astimezone(utc).replace(tzinfo=None)


def esta_en_horario_habil(dt: Optional[datetime] = None) -> bool:
    """True si es Lun-Vie dentro de 9-12 o 14-17 hora Colombia."""
    if dt is None:
        dt = hora_actual_co()
    if dt.weekday() not in DIAS_HABILES:
        return False
    ahora_t = dt.time()
    for inicio, fin in VENTANAS_HABILES:
        if inicio <= ahora_t < fin:
            return True
    return False


def proximo_horario_habil(dt: Optional[datetime] = None) -> datetime:
    """Calcula el próximo momento dentro de horario hábil.

    Útil para reagendar reintentos al día siguiente sin que caigan en
    sábado/domingo/madrugada.
    """
    if dt is None:
        dt = hora_actual_co()

    # Si ya estamos en horario hábil, devolver ahora
    if esta_en_horario_habil(dt):
        return dt

    # Buscar hasta 7 días adelante
    candidato = dt
    for _ in range(7 * 24 * 2):  # Hasta 7 días en pasos de 30 min
        candidato += timedelta(minutes=30)
        # Snap al inicio de la próxima ventana hábil si es muy temprano
        if candidato.weekday() in DIAS_HABILES:
            for inicio, fin in VENTANAS_HABILES:
                if candidato.time() < inicio:
                    return candidato.replace(hour=inicio.hour, minute=inicio.minute, second=0, microsecond=0)
                if inicio <= candidato.time() < fin:
                    return candidato
    # Fallback: mañana 9am
    manana = dt + timedelta(days=1)
    return manana.replace(hour=9, minute=0, second=0, microsecond=0)


async def tiempo_desde_ultima_call() -> Optional[timedelta]:
    """Cuánto pasó desde la última llamada que disparamos. None si nunca."""
    async with async_session() as session:
        ultima = (await session.execute(
            select(VoiceCall.creada_en)
            .where(VoiceCall.clinica_id.is_(None))   # solo outbound de Lapora (no de clínicas)
            .order_by(desc(VoiceCall.creada_en))
            .limit(1)
        )).scalar_one_or_none()
    if ultima is None:
        return None
    # ultima es naive UTC; ahora también UTC naive
    return datetime.utcnow() - ultima


async def puede_disparar_ahora() -> tuple[bool, str]:
    """¿Es momento legal y operativo de disparar una nueva llamada?

    Returns: (puede, motivo_si_no)
    """
    # Pausa global: respeta el flag de admin
    if await esta_pausado():
        return False, "scheduler pausado por admin"

    ahora = hora_actual_co()
    if not esta_en_horario_habil(ahora):
        return False, f"fuera de horario habil ({ahora.strftime('%a %H:%M')} CO)"

    delta = await tiempo_desde_ultima_call()
    if delta is not None and delta < timedelta(minutes=THROTTLE_MIN_ENTRE_CALLS):
        restante = THROTTLE_MIN_ENTRE_CALLS - int(delta.total_seconds() / 60)
        return False, f"throttle: faltan ~{restante} min para la proxima"

    return True, "ok"


# ════════════════════════════════════════════════════════════
# DISPATCH DE UNA LLAMADA
# ════════════════════════════════════════════════════════════

async def disparar_llamada(entry: VoiceQueue, worker_id: str = "default") -> Optional[VoiceCall]:
    """Dispara UNA llamada Twilio para esta entry de la cola.

    Pasos:
    1. Valida opt-out de nuevo (defensivo)
    2. Crea VoiceCall con estado=in_progress
    3. Marca VoiceQueue.estado=locked
    4. Llama a Twilio.calls.create() (stub Día 4, real Día 2 endpoint listo)
    5. Si Twilio falla: revertir estado, log error

    Día 4 (HOY): no llama Twilio real. Solo crea el VoiceCall registrado
                 con estado='pending' y deja el flow listo para Día 2.
    """
    # Doble check opt-out
    if await telefono_en_optout(entry.telefono):
        async with async_session() as session:
            q = (await session.execute(
                select(VoiceQueue).where(VoiceQueue.id == entry.id)
            )).scalar_one_or_none()
            if q:
                q.estado = "optout"
                await session.commit()
        logger.warning(f"[voice_workers] entry {entry.id} canceled: opt-out")
        return None

    # Lock + crear VoiceCall
    inicio = datetime.utcnow()
    async with async_session() as session:
        q = (await session.execute(
            select(VoiceQueue).where(VoiceQueue.id == entry.id)
        )).scalar_one_or_none()
        if not q:
            return None
        if q.estado != "queued":
            logger.info(f"[voice_workers] entry {entry.id} ya no está queued ({q.estado}), skip")
            return None

        # Marcar locked
        q.estado = "locked"
        q.locked_until = inicio + timedelta(minutes=LOCK_TIMEOUT_MIN)
        q.locked_by = worker_id
        q.intentos_realizados += 1

        call = VoiceCall(
            clinica_id=q.clinica_id,
            target_type=q.target_type,
            target_id=q.target_id,
            target_nombre=q.target_nombre,
            telefono=q.telefono,
            script_id=q.script_id,
            estado="pending",
            twilio_from=os.getenv("TWILIO_VOICE_NUMBER", ""),
            programada_para=q.programada_para,
            creada_en=inicio,
        )
        session.add(call)
        await session.flush()

        q.ultima_call_id = call.id
        await session.commit()
        await session.refresh(call)

    # Día 4: ya tenemos el VoiceCall registrado.
    # Día 2 (próximo): aquí se invoca al Twilio REST API para iniciar la llamada
    # con TwiML apuntando a /voice/twilio/answer.
    iniciada_twilio = await _iniciar_twilio_call(call)
    if not iniciada_twilio:
        async with async_session() as session:
            c = (await session.execute(
                select(VoiceCall).where(VoiceCall.id == call.id)
            )).scalar_one_or_none()
            if c:
                c.estado = "failed"
                c.error_msg = "Twilio call API no disponible (Día 4: stub)"
            q = (await session.execute(
                select(VoiceQueue).where(VoiceQueue.id == entry.id)
            )).scalar_one_or_none()
            if q:
                # Volver a queued para reintentar más tarde
                q.estado = "queued"
                q.locked_until = None
                q.locked_by = ""
                q.programada_para = datetime.utcnow() + timedelta(hours=1)
            await session.commit()
        logger.info(f"[voice_workers] call {call.id} marcado pending Twilio (Día 4 stub)")

    return call


async def _iniciar_twilio_call(call: VoiceCall) -> bool:
    """Inicia la llamada — real (Twilio) o simulada (mock mode).

    Si VoiceConfig.mock_mode = True (o env VOICE_MOCK_MODE=1):
    - Llama a voice_mock.iniciar_call_mock() que simula la conversación
      completa con Claude actuando como prospecto
    - El procesamiento es síncrono pero usa un task en background para
      no bloquear al scheduler

    Si NO está en mock mode:
    - Día 4: stub que solo verifica si las credenciales existen
    - Día 2 (próximo): integración real con twilio-python
    """
    # ¿Estamos en modo mock?
    from agent.voice_models import esta_en_mock_mode
    if await esta_en_mock_mode():
        from agent.voice_mock import iniciar_call_mock
        # Disparar en background — no bloqueamos al scheduler
        asyncio.create_task(_mock_call_background(call))
        logger.info(f"[voice_workers] call={call.id} MOCK MODE — simulación en background")
        return True

    sid = os.getenv("TWILIO_ACCOUNT_SID")
    token = os.getenv("TWILIO_AUTH_TOKEN")
    from_num = os.getenv("TWILIO_VOICE_NUMBER")

    if not (sid and token and from_num):
        return False

    # Día 2: aquí va el código real:
    # from twilio.rest import Client
    # client = Client(sid, token)
    # base_url = os.getenv("PUBLIC_BASE_URL", "https://sofia-lapora-production.up.railway.app")
    # twilio_call = client.calls.create(
    #     to=call.telefono, from_=from_num,
    #     url=f"{base_url}/voice/twilio/answer?call_id={call.id}",
    #     status_callback=f"{base_url}/voice/twilio/status",
    #     status_callback_event=['initiated','ringing','answered','completed'],
    #     timeout=20, machine_detection='Enable',
    # )
    # call.twilio_call_sid = twilio_call.sid

    logger.info(f"[voice_workers] Twilio creds OK, faltan endpoints reales (Día 2)")
    return False


async def _mock_call_background(call: VoiceCall):
    """Wrapper que ejecuta la simulación mock en background."""
    try:
        from agent.voice_mock import iniciar_call_mock
        # Liberar el lock primero porque procesar_post_call necesita ver
        # la entry actualizada. Marcar call como in_progress.
        async with async_session() as session:
            c = (await session.execute(
                select(VoiceCall).where(VoiceCall.id == call.id)
            )).scalar_one_or_none()
            if c:
                c.estado = "in_progress"
                c.inicio = datetime.utcnow()
                await session.commit()

        await iniciar_call_mock(call)
    except Exception as e:
        logger.error(f"[voice_workers] mock background error call={call.id}: {e}", exc_info=True)


# ════════════════════════════════════════════════════════════
# DESBLOQUEO Y REINTENTOS
# ════════════════════════════════════════════════════════════

async def liberar_locks_vencidos():
    """Libera entries que se quedaron locked más del timeout (worker murió, etc.)."""
    ahora = datetime.utcnow()
    async with async_session() as session:
        vencidos = (await session.execute(
            select(VoiceQueue)
            .where(VoiceQueue.estado == "locked")
            .where(VoiceQueue.locked_until < ahora)
        )).scalars().all()
        for q in vencidos:
            q.estado = "queued"
            q.locked_until = None
            q.locked_by = ""
        if vencidos:
            logger.info(f"[voice_workers] liberados {len(vencidos)} locks vencidos")
            await session.commit()


async def reagendar_segun_outcome(call_id: int):
    """Tras un outcome de Twilio, decide si reagendar la entry o marcarla done."""
    async with async_session() as session:
        call = (await session.execute(
            select(VoiceCall).where(VoiceCall.id == call_id)
        )).scalar_one_or_none()
        if not call:
            return
        # Buscar VoiceQueue asociado
        q = (await session.execute(
            select(VoiceQueue)
            .where(VoiceQueue.target_type == call.target_type)
            .where(VoiceQueue.target_id == call.target_id)
            .where(VoiceQueue.estado == "locked")
            .order_by(desc(VoiceQueue.id))
            .limit(1)
        )).scalar_one_or_none()
        if not q:
            return

        outcome = call.outcome or ""
        ahora_co = hora_actual_co()

        if outcome in ("interested", "not_interested", "opt_out", "callback"):
            # Resultados terminales → done
            q.estado = "done"
        elif outcome == "voicemail":
            # Reagendar +48h en horario hábil
            target = proximo_horario_habil(ahora_co + timedelta(hours=REINTENTO_VOICEMAIL_HORAS))
            q.estado = "queued" if q.intentos_restantes > 1 else "agotado"
            q.intentos_restantes = max(0, q.intentos_restantes - 1)
            q.programada_para = _to_utc_naive(target)
            q.locked_until = None; q.locked_by = ""
        elif outcome in ("no_answer", "failed"):
            target = proximo_horario_habil(ahora_co + timedelta(hours=REINTENTO_NO_ANSWER_HORAS))
            q.estado = "queued" if q.intentos_restantes > 1 else "agotado"
            q.intentos_restantes = max(0, q.intentos_restantes - 1)
            q.programada_para = _to_utc_naive(target)
            q.locked_until = None; q.locked_by = ""
        else:
            # Outcome desconocido → liberar lock y dejar como queued
            q.estado = "queued"
            q.locked_until = None; q.locked_by = ""

        await session.commit()


# ════════════════════════════════════════════════════════════
# LOOP PRINCIPAL DEL SCHEDULER
# ════════════════════════════════════════════════════════════

async def loop_scheduler(stop_event: asyncio.Event):
    """Loop principal: cada minuto revisa si toca disparar una llamada."""
    logger.info(
        f"[voice_workers] scheduler arrancado — check c/{INTERVALO_CHECK_SEG}s, "
        f"throttle {THROTTLE_MIN_ENTRE_CALLS}min, horario Lun-Vie 9-12+14-17 CO"
    )

    # Delay inicial 30s para no chocar con startup
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=30)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            # Limpieza housekeeping
            await liberar_locks_vencidos()

            # ¿Estamos en ventana operativa?
            puede, motivo = await puede_disparar_ahora()
            if puede:
                proxima = await proxima_llamada_en_cola()
                if proxima:
                    logger.info(
                        f"[voice_workers] disparando call: target={proxima.target_nombre} "
                        f"tel={proxima.telefono} script={proxima.script_id} prio={proxima.prioridad}"
                    )
                    await disparar_llamada(proxima, worker_id="loop_main")
                # else: cola vacía, no hacemos nada
        except Exception as e:
            logger.error(f"[voice_workers] error en loop: {e}", exc_info=True)

        # Esperar próximo ciclo (interrumpible)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=INTERVALO_CHECK_SEG)
        except asyncio.TimeoutError:
            continue

    logger.info("[voice_workers] scheduler detenido limpiamente")


# ════════════════════════════════════════════════════════════
# REGISTRO — Inicio/parada
# ════════════════════════════════════════════════════════════

# ════════════════════════════════════════════════════════════
# DAY 5 — WORKER MULTI-TENANT: encola confirmaciones de citas por clinic
# ════════════════════════════════════════════════════════════

INTERVALO_SCAN_CITAS_SEG = 600  # 10 minutos — encolar nuevas confirmaciones


async def encolar_confirmaciones_citas():
    """Para cada clínica con voz_confirmar_citas_activa=True, busca citas
    que estén entre 24h y 26h en el futuro y aún no se encolaron para
    confirmación por voz. Las encola con script 'confirmar_cita_clinica'.

    Idempotente: usa CitaClinic.voz_confirmacion_encolada para no duplicar.
    """
    from agent.clinic_models import Clinica, CitaClinic, Paciente
    from agent.voice_models import encolar_prospecto

    ahora = datetime.utcnow()
    ventana_inicio = ahora + timedelta(hours=24)
    ventana_fin = ahora + timedelta(hours=26)

    async with async_session() as session:
        # Citas elegibles: estado=agendada/confirmada, en ventana 24-26h,
        # NO ya encoladas para voz, clínica con voz_confirmar_citas_activa=True
        result = await session.execute(
            select(CitaClinic, Clinica, Paciente)
            .join(Clinica, CitaClinic.clinica_id == Clinica.id)
            .join(Paciente, CitaClinic.paciente_id == Paciente.id)
            .where(CitaClinic.estado.in_(["agendada", "confirmada"]))
            .where(CitaClinic.fecha_hora >= ventana_inicio)
            .where(CitaClinic.fecha_hora <= ventana_fin)
            .where(CitaClinic.voz_confirmacion_encolada == False)  # noqa: E712
            .where(Clinica.voz_confirmar_citas_activa == True)     # noqa: E712
            .where(Clinica.activo == True)                         # noqa: E712
            .where(Clinica.congelada == False)                     # noqa: E712
        )

        encoladas = 0
        for cita, clinica, paciente in result.all():
            if not paciente.telefono or len(paciente.telefono.replace("+", "")) < 8:
                # Marcar como "procesado" igual para no reintentar
                cita.voz_confirmacion_encolada = True
                continue

            # Construir nombre legible de fecha/hora
            fecha_str = cita.fecha_hora.strftime("%A %d de %B")
            hora_str = cita.fecha_hora.strftime("%I:%M %p").lstrip("0").lower()

            entry = await encolar_prospecto(
                target_type="paciente",
                target_id=str(paciente.id),
                target_nombre=paciente.nombre or "paciente",
                telefono=paciente.telefono,
                script_id="confirmar_cita_clinica",
                prioridad=70,  # alta — operativo, no esperar
                clinica_id=clinica.id,
                programada_para=ahora,  # tan pronto el scheduler pueda
                intentos_max=2,  # citas son operativas, max 2 retries
            )
            if entry is not None:
                cita.voz_confirmacion_encolada = True
                encoladas += 1

        if encoladas:
            await session.commit()
            logger.info(f"[voice_workers] encoladas {encoladas} confirmaciones de cita")


async def loop_scan_citas_clinic(stop_event: asyncio.Event):
    """Loop cada 10 min: escanea citas próximas de todas las clínicas opt-in."""
    logger.info(f"[voice_workers] scan citas clinic arrancado — cada {INTERVALO_SCAN_CITAS_SEG}s")

    # Delay inicial
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=45)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            await encolar_confirmaciones_citas()
        except Exception as e:
            logger.error(f"[voice_workers] error scan citas: {e}", exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=INTERVALO_SCAN_CITAS_SEG)
        except asyncio.TimeoutError:
            continue

    logger.info("[voice_workers] scan citas clinic detenido")


# ════════════════════════════════════════════════════════════
# REGISTRO — Inicio/parada
# ════════════════════════════════════════════════════════════

_voice_tasks: list[asyncio.Task] = []
_voice_stop_event: Optional[asyncio.Event] = None


async def iniciar_voice_workers():
    """Inicia los workers async. Idempotente."""
    global _voice_stop_event, _voice_tasks
    if _voice_tasks:
        return
    _voice_stop_event = asyncio.Event()
    _voice_tasks = [
        asyncio.create_task(loop_scheduler(_voice_stop_event)),
        asyncio.create_task(loop_scan_citas_clinic(_voice_stop_event)),
    ]
    logger.info(f"[voice_workers] iniciados ({len(_voice_tasks)} tasks)")


async def detener_voice_workers():
    """Detiene el scheduler limpiamente."""
    global _voice_stop_event, _voice_tasks
    if not _voice_tasks:
        return
    if _voice_stop_event:
        _voice_stop_event.set()
    try:
        await asyncio.wait_for(
            asyncio.gather(*_voice_tasks, return_exceptions=True), timeout=10,
        )
    except asyncio.TimeoutError:
        for t in _voice_tasks:
            t.cancel()
    _voice_tasks = []
    _voice_stop_event = None
    logger.info("[voice_workers] detenidos")

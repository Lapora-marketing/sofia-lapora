# -*- coding: utf-8 -*-
# agent/clinic_workers.py — Workers async de fondo para Lapora Clinic
# Lapora Marketing Digital

"""
Workers de fondo que corren mientras el servidor está vivo:

1. worker_recordatorios_citas: cada 5 min revisa CitaClinic con estado=agendada
   y envía recordatorios WhatsApp 24h antes y 2h antes de la cita.

2. (futuro) worker_sync_sheets: sync bidireccional con Google Sheets.

Diseño:
- Se inician en main.py durante el lifespan startup.
- Cada worker es un task asyncio que se cancela en shutdown.
- Los errores se loguean pero NUNCA tumban al worker (try/except en cada loop).
- Idempotente: usa flags en BD (recordatorio_24h_enviado, recordatorio_2h_enviado)
  para no enviar duplicados, aunque el worker se reinicie.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from sqlalchemy import select

from agent.memory import async_session
from agent.clinic_models import Clinica, Paciente, CitaClinic

logger = logging.getLogger("agentkit")

# Cadencia del loop principal (segundos)
INTERVALO_CHECK_SEG = 300  # 5 minutos

# Ventanas de detección (en minutos) para evitar perder citas
# Si el worker corre cada 5min, una ventana de +/- 10min cubre cualquier drift
VENTANA_24H_MIN = 15
VENTANA_2H_MIN = 10

# Cadencia del sync de Sheets (segundos) — más relajado, no es crítico
INTERVALO_SYNC_SHEETS_SEG = 900  # 15 minutos


# ════════════════════════════════════════════════════════════
# PLANTILLAS DE MENSAJE
# ════════════════════════════════════════════════════════════

def _fmt_fecha_es(dt: datetime) -> str:
    """Formato amigable en español: 'mañana viernes a las 10:00 AM'."""
    dias = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
    meses = ["enero", "febrero", "marzo", "abril", "mayo", "junio",
             "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]
    dia_sem = dias[dt.weekday()]
    hora_str = dt.strftime("%I:%M %p").lstrip("0").lower()
    return f"{dia_sem} {dt.day} de {meses[dt.month - 1]} a las {hora_str}"


def mensaje_recordatorio_24h(nombre_paciente: str, fecha_hora: datetime,
                              nombre_clinica: str, motivo: str = "") -> str:
    saludo_nombre = nombre_paciente.split()[0] if nombre_paciente else "Hola"
    motivo_txt = f" ({motivo})" if motivo and len(motivo) < 60 else ""
    return (
        f"¡Hola {saludo_nombre}! 👋\n\n"
        f"Te recordamos tu cita en *{nombre_clinica}* mañana {_fmt_fecha_es(fecha_hora)}{motivo_txt}.\n\n"
        f"¿Confirmas tu asistencia? Responde:\n"
        f"✅ SI — para confirmar\n"
        f"❌ NO — si necesitas reprogramar"
    )


def mensaje_recordatorio_2h(nombre_paciente: str, fecha_hora: datetime,
                             nombre_clinica: str) -> str:
    saludo_nombre = nombre_paciente.split()[0] if nombre_paciente else "Hola"
    hora_str = fecha_hora.strftime("%I:%M %p").lstrip("0").lower()
    return (
        f"⏰ {saludo_nombre}, tu cita en *{nombre_clinica}* es en 2 horas (hoy a las {hora_str}).\n\n"
        f"Te esperamos. Si tienes algún inconveniente, escríbenos por aquí."
    )


# ════════════════════════════════════════════════════════════
# LÓGICA DE DETECCIÓN DE CITAS QUE NECESITAN RECORDATORIO
# ════════════════════════════════════════════════════════════

async def buscar_citas_para_recordar() -> list[dict]:
    """Encuentra citas elegibles para recordatorio 24h o 2h.

    Retorna lista de dicts con: cita, paciente, clinica, tipo ('24h' o '2h').
    """
    ahora = datetime.utcnow()
    pendientes = []

    async with async_session() as session:
        # Ventana global: solo nos interesan citas en las próximas 25 horas
        limite_superior = ahora + timedelta(hours=25)

        result = await session.execute(
            select(CitaClinic, Paciente, Clinica)
            .join(Paciente, CitaClinic.paciente_id == Paciente.id)
            .join(Clinica, CitaClinic.clinica_id == Clinica.id)
            .where(CitaClinic.estado.in_(["agendada", "confirmada"]))
            .where(CitaClinic.fecha_hora >= ahora)
            .where(CitaClinic.fecha_hora <= limite_superior)
            .where(Clinica.activo == True)  # noqa: E712
            .where(Clinica.congelada == False)  # noqa: E712
        )

        for cita, paciente, clinica in result.all():
            # Filtros básicos: clínica con WhatsApp, paciente con teléfono
            if not clinica.whatsapp_phone_id or not clinica.whatsapp_token:
                continue
            if not paciente.telefono or len(paciente.telefono.replace("+", "")) < 8:
                continue

            minutos_hasta_cita = (cita.fecha_hora - ahora).total_seconds() / 60

            # Ventana 24h: cita en ~24h ± 15min, y aún no se envió
            if (
                not cita.recordatorio_24h_enviado
                and (24 * 60 - VENTANA_24H_MIN) <= minutos_hasta_cita <= (24 * 60 + VENTANA_24H_MIN)
            ):
                pendientes.append({
                    "cita_id": cita.id,
                    "paciente_id": paciente.id,
                    "clinica_id": clinica.id,
                    "tipo": "24h",
                    "fecha_hora": cita.fecha_hora,
                    "nombre_paciente": paciente.nombre or "",
                    "telefono": paciente.telefono,
                    "nombre_clinica": clinica.nombre or "la clínica",
                    "motivo": cita.motivo or "",
                })
                continue

            # Ventana 2h: cita en ~2h ± 10min, y aún no se envió
            if (
                not cita.recordatorio_2h_enviado
                and (2 * 60 - VENTANA_2H_MIN) <= minutos_hasta_cita <= (2 * 60 + VENTANA_2H_MIN)
            ):
                pendientes.append({
                    "cita_id": cita.id,
                    "paciente_id": paciente.id,
                    "clinica_id": clinica.id,
                    "tipo": "2h",
                    "fecha_hora": cita.fecha_hora,
                    "nombre_paciente": paciente.nombre or "",
                    "telefono": paciente.telefono,
                    "nombre_clinica": clinica.nombre or "la clínica",
                    "motivo": cita.motivo or "",
                })

    return pendientes


# ════════════════════════════════════════════════════════════
# ENVÍO DE UN RECORDATORIO (con persistencia + idempotencia)
# ════════════════════════════════════════════════════════════

async def enviar_recordatorio(item: dict) -> bool:
    """Envía un recordatorio y marca la cita como enviada.

    Retorna True si se envió correctamente. False si falló.
    """
    from agent.clinic_brain import enviar_whatsapp_clinica
    from agent.clinic_models import MensajeUnificado

    tipo = item["tipo"]
    nombre = item["nombre_paciente"]
    fecha_hora = item["fecha_hora"]
    nombre_clinica = item["nombre_clinica"]
    motivo = item["motivo"]

    # Construir mensaje
    if tipo == "24h":
        texto = mensaje_recordatorio_24h(nombre, fecha_hora, nombre_clinica, motivo)
    else:
        texto = mensaje_recordatorio_2h(nombre, fecha_hora, nombre_clinica)

    # Cargar la clínica completa para tener credenciales
    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.id == item["clinica_id"])
        )).scalar_one_or_none()
        if not clinica:
            return False

        # Enviar WhatsApp
        envio = await enviar_whatsapp_clinica(clinica, item["telefono"], texto)

        if not envio["exito"]:
            logger.warning(
                f"[recordatorio {tipo}] cita={item['cita_id']} clinica={clinica.id} "
                f"falló: {envio['error']}"
            )
            return False

        # Marcar flag en la cita + guardar mensaje en inbox
        cita = (await session.execute(
            select(CitaClinic).where(CitaClinic.id == item["cita_id"])
        )).scalar_one_or_none()
        if cita:
            if tipo == "24h":
                cita.recordatorio_24h_enviado = True
            else:
                cita.recordatorio_2h_enviado = True

        # Guardar mensaje de salida en inbox para auditoría
        session.add(MensajeUnificado(
            clinica_id=clinica.id,
            paciente_id=item["paciente_id"],
            canal="whatsapp",
            direccion="salida",
            contenido=texto,
            canal_msg_id=envio.get("message_id", ""),
            leido=True,
            respondido_por="recordatorio",
            timestamp=datetime.utcnow(),
        ))

        await session.commit()

    logger.info(
        f"[recordatorio {tipo}] enviado cita={item['cita_id']} "
        f"paciente={item['nombre_paciente'][:30]} clinica={item['nombre_clinica'][:30]}"
    )
    return True


# ════════════════════════════════════════════════════════════
# LOOP PRINCIPAL DEL WORKER
# ════════════════════════════════════════════════════════════

async def worker_recordatorios_citas(stop_event: asyncio.Event):
    """Loop que corre cada INTERVALO_CHECK_SEG, indefinidamente.

    Args:
        stop_event: asyncio.Event que se setea en shutdown para terminar.
    """
    logger.info(
        f"[worker_recordatorios] arrancado — intervalo {INTERVALO_CHECK_SEG}s, "
        f"ventana 24h ±{VENTANA_24H_MIN}min, ventana 2h ±{VENTANA_2H_MIN}min"
    )

    # Pequeño delay inicial para no chocar con el startup
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=20)
        logger.info("[worker_recordatorios] detenido durante delay inicial")
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            pendientes = await buscar_citas_para_recordar()
            if pendientes:
                logger.info(f"[worker_recordatorios] {len(pendientes)} recordatorios pendientes")
                for item in pendientes:
                    try:
                        await enviar_recordatorio(item)
                        # Pequeña pausa entre envíos para no triggerear rate limits
                        await asyncio.sleep(1.5)
                    except Exception as e:
                        logger.error(
                            f"[worker_recordatorios] error enviando recordatorio: {e}",
                            exc_info=True,
                        )
        except Exception as e:
            logger.error(f"[worker_recordatorios] error en loop: {e}", exc_info=True)

        # Esperar próximo ciclo (interrumpible por stop_event)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=INTERVALO_CHECK_SEG)
        except asyncio.TimeoutError:
            continue

    logger.info("[worker_recordatorios] detenido limpiamente")


# ════════════════════════════════════════════════════════════
# SYNC GOOGLE SHEETS — Worker periódico per-tenant
# ════════════════════════════════════════════════════════════

async def sincronizar_sheet_clinica(clinica: Clinica) -> dict:
    """Sincroniza pacientes desde Google Sheets de UNA clínica.

    La hoja debe ser pública (acceso "cualquiera con el enlace").
    Columnas esperadas (case-insensitive, con o sin acentos):
      nombre, telefono, email, tratamiento, notas

    Returns: {"exito": bool, "creados": int, "actualizados": int, "error": str}
    """
    import re as _re_sh
    import csv as _csv_sh
    from io import StringIO as _StringIO_sh
    import httpx as _httpx_sh

    if not clinica.google_sheet_id:
        return {"exito": False, "creados": 0, "actualizados": 0, "error": "Sin sheet_id configurado"}

    sheet_input = (clinica.google_sheet_id or "").strip()
    m = _re_sh.search(r"/d/([a-zA-Z0-9_-]+)", sheet_input)
    sheet_id = m.group(1) if m else sheet_input
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

    # Descargar CSV
    try:
        async with _httpx_sh.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(csv_url)
        if resp.status_code != 200:
            return {
                "exito": False, "creados": 0, "actualizados": 0,
                "error": f"HTTP {resp.status_code} — hoja debe ser pública",
            }
        contenido_csv = resp.text
    except Exception as e:
        return {"exito": False, "creados": 0, "actualizados": 0, "error": str(e)[:200]}

    # Parsear CSV
    reader = _csv_sh.DictReader(_StringIO_sh(contenido_csv))
    if reader.fieldnames:
        reader.fieldnames = [
            (h or "").lower().strip()
            .replace("é", "e").replace("ó", "o").replace("í", "i")
            .replace("á", "a").replace("ú", "u").replace("ñ", "n")
            for h in reader.fieldnames
        ]

    creados = actualizados = 0
    ahora = datetime.utcnow()

    async with async_session() as session:
        for row in reader:
            nombre = (row.get("nombre") or row.get("name") or "").strip()
            if not nombre:
                continue
            telefono = (row.get("telefono") or row.get("teléfono") or row.get("phone") or "").strip()
            email = (row.get("email") or row.get("correo") or "").strip().lower()
            tratamiento = (row.get("tratamiento") or row.get("tratamiento_actual") or "").strip()
            notas = (row.get("notas") or row.get("notes") or "").strip()

            # Upsert por telefono o email
            existing = None
            if telefono:
                existing = (await session.execute(
                    select(Paciente)
                    .where(Paciente.clinica_id == clinica.id)
                    .where(Paciente.telefono == telefono)
                )).scalar_one_or_none()
            if not existing and email:
                existing = (await session.execute(
                    select(Paciente)
                    .where(Paciente.clinica_id == clinica.id)
                    .where(Paciente.email == email)
                )).scalar_one_or_none()

            if existing:
                existing.nombre = nombre
                if telefono:
                    existing.telefono = telefono
                if email:
                    existing.email = email
                if tratamiento:
                    existing.tratamiento_actual = tratamiento
                if notas:
                    existing.notas_basicas = notas
                existing.ultimo_contacto = ahora
                actualizados += 1
            else:
                session.add(Paciente(
                    clinica_id=clinica.id,
                    nombre=nombre,
                    telefono=telefono,
                    email=email,
                    tratamiento_actual=tratamiento,
                    notas_basicas=notas,
                    fuente="sheets",
                    estado="nuevo",
                    primer_contacto=ahora,
                    ultimo_contacto=ahora,
                ))
                creados += 1

        await session.commit()

    return {"exito": True, "creados": creados, "actualizados": actualizados, "error": ""}


async def worker_sync_sheets(stop_event: asyncio.Event):
    """Loop que cada 15 min sincroniza Sheets de TODAS las clínicas configuradas."""
    logger.info(f"[worker_sync_sheets] arrancado — cada {INTERVALO_SYNC_SHEETS_SEG}s")

    # Delay inicial
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=60)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            # Buscar todas las clínicas con sheet_id configurado, activas y no congeladas
            async with async_session() as session:
                clinicas = (await session.execute(
                    select(Clinica)
                    .where(Clinica.google_sheet_id != "")
                    .where(Clinica.activo == True)  # noqa: E712
                    .where(Clinica.congelada == False)  # noqa: E712
                )).scalars().all()

            if clinicas:
                logger.info(f"[worker_sync_sheets] sincronizando {len(clinicas)} clínicas")
                for clinica in clinicas:
                    try:
                        resultado = await sincronizar_sheet_clinica(clinica)
                        if resultado["exito"]:
                            if resultado["creados"] or resultado["actualizados"]:
                                logger.info(
                                    f"[worker_sync_sheets] clinica={clinica.id} "
                                    f"creados={resultado['creados']} "
                                    f"actualizados={resultado['actualizados']}"
                                )
                        else:
                            logger.warning(
                                f"[worker_sync_sheets] clinica={clinica.id} "
                                f"falló: {resultado['error']}"
                            )
                        await asyncio.sleep(2)  # Throttle entre clínicas
                    except Exception as e:
                        logger.error(
                            f"[worker_sync_sheets] error clinica={clinica.id}: {e}",
                            exc_info=True,
                        )
        except Exception as e:
            logger.error(f"[worker_sync_sheets] error en loop: {e}", exc_info=True)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=INTERVALO_SYNC_SHEETS_SEG)
        except asyncio.TimeoutError:
            continue

    logger.info("[worker_sync_sheets] detenido limpiamente")


# ════════════════════════════════════════════════════════════
# REGISTRO DE WORKERS (llamado desde main.py lifespan)
# ════════════════════════════════════════════════════════════

# Estado global: tasks + stop event
_workers_tasks: list[asyncio.Task] = []
_workers_stop_event: asyncio.Event = None


async def worker_auto_freeze_billing(stop_event: asyncio.Event):
    """Cada 1 hora: congela trials expirados sin suscripción."""
    INTERVALO = 3600
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=120)
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        try:
            from agent.clinic_billing import auto_freeze_trials_expirados
            n = await auto_freeze_trials_expirados()
            if n:
                logger.info(f"[billing worker] {n} clínicas congeladas (trial expirado)")
        except Exception as e:
            logger.error(f"[billing worker] error: {e}", exc_info=True)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=INTERVALO)
        except asyncio.TimeoutError:
            continue


async def iniciar_workers():
    """Inicia todos los workers de fondo. Idempotente."""
    global _workers_stop_event, _workers_tasks

    if _workers_tasks:
        logger.warning("[workers] ya están iniciados, skip")
        return

    _workers_stop_event = asyncio.Event()
    _workers_tasks = [
        asyncio.create_task(worker_recordatorios_citas(_workers_stop_event)),
        asyncio.create_task(worker_sync_sheets(_workers_stop_event)),
        asyncio.create_task(worker_auto_freeze_billing(_workers_stop_event)),
    ]
    logger.info(f"[workers] {len(_workers_tasks)} workers iniciados (recordatorios + sync_sheets + billing)")


async def detener_workers():
    """Detiene todos los workers limpiamente."""
    global _workers_stop_event, _workers_tasks

    if not _workers_tasks:
        return

    if _workers_stop_event:
        _workers_stop_event.set()

    # Esperar hasta 10s a que terminen
    try:
        await asyncio.wait_for(
            asyncio.gather(*_workers_tasks, return_exceptions=True),
            timeout=10,
        )
    except asyncio.TimeoutError:
        logger.warning("[workers] timeout esperando shutdown, cancelando")
        for t in _workers_tasks:
            t.cancel()

    _workers_tasks = []
    _workers_stop_event = None
    logger.info("[workers] todos detenidos")

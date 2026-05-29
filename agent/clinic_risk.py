# -*- coding: utf-8 -*-
# agent/clinic_risk.py — Detección de pacientes en riesgo de fuga
# Lapora Marketing Digital — feature flagship Studio plan

"""
Detecta pacientes con probabilidad alta de NO regresar al consultorio.

Algoritmo de scoring 0-100 basado en señales conductuales:

Señal                                    | Puntos riesgo
-----------------------------------------|---------------
Sin contacto >60 días, era activo        | +35
Sin contacto >30 días, era nuevo         | +20
Cita pasada NO completada (no_show)      | +25
Cita futura cancelada sin reagendar      | +30
Tratamiento "activo" sin cita en 45 días | +25
Múltiples mensajes sin respuesta         | +15
Sentimiento negativo en última conv.     | +20
Pidió hablar con humano y nadie le habló | +20

Score >= 70: ALTO riesgo, acción urgente
Score 40-69: MEDIO riesgo, hacer follow-up esta semana
Score < 40:  BAJO riesgo, está sano
"""

from datetime import datetime, timedelta
from typing import Optional
from sqlalchemy import select, desc, func, and_, or_

from agent.memory import async_session
from agent.clinic_models import Paciente, CitaClinic, MensajeUnificado, Clinica


# Pesos de cada señal — calibrados conservadoramente
PESOS = {
    "sin_contacto_60d_activo": 35,
    "sin_contacto_30d_nuevo": 20,
    "no_show_cita_pasada":    25,
    "cita_cancelada_sin_reagenda": 30,
    "tratamiento_sin_cita_45d": 25,
    "mensajes_sin_respuesta":  15,
    "sentimiento_negativo":    20,
    "escalado_sin_responder":  20,
}


async def calcular_riesgo_paciente(
    paciente: Paciente,
    clinica_id: int,
    ahora: Optional[datetime] = None,
) -> dict:
    """Calcula score 0-100 + razones para UN paciente.

    Returns:
        {
            "score": int,            # 0-100
            "nivel": str,            # "alto" | "medio" | "bajo"
            "razones": list[str],    # Razones humanas-legibles
            "accion_sugerida": str,  # Qué hacer YA
        }
    """
    ahora = ahora or datetime.utcnow()
    score = 0
    razones: list[str] = []

    # Estados terminales: nunca en riesgo
    if paciente.estado == "dado_de_alta":
        return {
            "score": 0,
            "nivel": "bajo",
            "razones": ["Paciente dado de alta"],
            "accion_sugerida": "Ninguna",
        }

    async with async_session() as session:
        # === Señal 1: Sin contacto reciente ===
        dias_sin_contacto = (ahora - paciente.ultimo_contacto).days if paciente.ultimo_contacto else 999

        if dias_sin_contacto >= 60 and paciente.estado == "activo":
            score += PESOS["sin_contacto_60d_activo"]
            razones.append(f"{dias_sin_contacto} días sin contacto siendo paciente activo")
        elif dias_sin_contacto >= 30 and paciente.estado == "nuevo":
            score += PESOS["sin_contacto_30d_nuevo"]
            razones.append(f"{dias_sin_contacto} días sin contacto siendo paciente nuevo")

        # === Señal 2: Citas no completadas ===
        no_shows = (await session.execute(
            select(func.count(CitaClinic.id))
            .where(CitaClinic.paciente_id == paciente.id)
            .where(CitaClinic.estado == "no_show")
            .where(CitaClinic.fecha_hora >= ahora - timedelta(days=90))
        )).scalar() or 0

        if no_shows > 0:
            score += PESOS["no_show_cita_pasada"]
            razones.append(f"{no_shows} cita(s) marcada(s) como no_show en últimos 90 días")

        # === Señal 3: Cita cancelada sin reagendar ===
        canceladas = (await session.execute(
            select(CitaClinic)
            .where(CitaClinic.paciente_id == paciente.id)
            .where(CitaClinic.estado == "cancelada")
            .order_by(desc(CitaClinic.creado_en))
            .limit(1)
        )).scalar_one_or_none()

        if canceladas:
            # ¿Tiene cita futura después de la cancelada?
            cita_futura = (await session.execute(
                select(CitaClinic)
                .where(CitaClinic.paciente_id == paciente.id)
                .where(CitaClinic.estado.in_(["agendada", "confirmada"]))
                .where(CitaClinic.fecha_hora > ahora)
                .limit(1)
            )).scalar_one_or_none()
            if not cita_futura:
                score += PESOS["cita_cancelada_sin_reagenda"]
                razones.append("Canceló su última cita y NO reagendó")

        # === Señal 4: Tratamiento activo sin cita en 45 días ===
        if paciente.tratamiento_actual and paciente.estado == "activo":
            ultima_cita = (await session.execute(
                select(CitaClinic)
                .where(CitaClinic.paciente_id == paciente.id)
                .where(CitaClinic.fecha_hora <= ahora)
                .order_by(desc(CitaClinic.fecha_hora))
                .limit(1)
            )).scalar_one_or_none()

            if ultima_cita:
                dias_desde_ult_cita = (ahora - ultima_cita.fecha_hora).days
                if dias_desde_ult_cita >= 45:
                    score += PESOS["tratamiento_sin_cita_45d"]
                    razones.append(
                        f"Tratamiento '{paciente.tratamiento_actual[:40]}' "
                        f"sin cita en {dias_desde_ult_cita} días"
                    )

        # === Señal 5: Mensajes entrantes sin respuesta de la clínica ===
        mensajes_in_recientes = (await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.paciente_id == paciente.id)
            .where(MensajeUnificado.direccion == "entrada")
            .where(MensajeUnificado.timestamp >= ahora - timedelta(days=14))
            .order_by(desc(MensajeUnificado.timestamp))
        )).scalars().all()

        if mensajes_in_recientes:
            ultimo_in = mensajes_in_recientes[0]
            # ¿Hay mensaje de salida DESPUÉS del último de entrada?
            tiene_respuesta = (await session.execute(
                select(func.count(MensajeUnificado.id))
                .where(MensajeUnificado.paciente_id == paciente.id)
                .where(MensajeUnificado.direccion == "salida")
                .where(MensajeUnificado.timestamp > ultimo_in.timestamp)
            )).scalar() or 0

            if not tiene_respuesta and len(mensajes_in_recientes) >= 2:
                score += PESOS["mensajes_sin_respuesta"]
                razones.append(
                    f"{len(mensajes_in_recientes)} mensajes en últimos 14d sin respuesta del consultorio"
                )

        # === Señal 6: Tag de escalado sin atender ===
        if paciente.tags and "escalado" in paciente.tags:
            # Si fue escalado y nadie le respondió en últimos 3 días
            mensaje_salida_reciente = (await session.execute(
                select(func.count(MensajeUnificado.id))
                .where(MensajeUnificado.paciente_id == paciente.id)
                .where(MensajeUnificado.direccion == "salida")
                .where(MensajeUnificado.timestamp >= ahora - timedelta(days=3))
                .where(MensajeUnificado.respondido_por != "ia")
            )).scalar() or 0

            if mensaje_salida_reciente == 0:
                score += PESOS["escalado_sin_responder"]
                razones.append("Pidió hablar con humano y nadie le respondió en 3+ días")

    # Cap el score a 100
    score = min(100, score)

    # Nivel + acción
    if score >= 70:
        nivel = "alto"
        if "cancelada" in str(razones):
            accion = "Llamar HOY para reagendar y recuperar al paciente"
        elif "sin contacto" in str(razones):
            accion = "WhatsApp personalizado HOY ofreciendo control gratuito o descuento"
        elif "escalado" in str(razones):
            accion = "El doctor debe responder personalmente AHORA"
        else:
            accion = "Contactar HOY — paciente a punto de perderse"
    elif score >= 40:
        nivel = "medio"
        accion = "Follow-up esta semana — mandar WhatsApp con saludo + propuesta"
    else:
        nivel = "bajo"
        accion = "OK — paciente sano, mantener cadencia normal"

    return {
        "score": score,
        "nivel": nivel,
        "razones": razones,
        "accion_sugerida": accion,
    }


async def listar_pacientes_en_riesgo(
    clinica_id: int,
    score_minimo: int = 40,
    limite: int = 50,
) -> list[dict]:
    """Escanea todos los pacientes de la clínica y retorna los de riesgo >= score_minimo.

    Returns: lista de dicts:
        {paciente, score, nivel, razones, accion_sugerida}
        Ordenada por score DESC (más riesgo primero)
    """
    ahora = datetime.utcnow()

    async with async_session() as session:
        pacientes = list((await session.execute(
            select(Paciente)
            .where(Paciente.clinica_id == clinica_id)
            .where(Paciente.estado.in_(["nuevo", "activo", "inactivo"]))
            .order_by(Paciente.ultimo_contacto)
            .limit(500)  # límite de seguridad
        )).scalars().all())

    resultados = []
    for p in pacientes:
        try:
            riesgo = await calcular_riesgo_paciente(p, clinica_id, ahora=ahora)
            if riesgo["score"] >= score_minimo:
                resultados.append({
                    "paciente": p,
                    "score": riesgo["score"],
                    "nivel": riesgo["nivel"],
                    "razones": riesgo["razones"],
                    "accion_sugerida": riesgo["accion_sugerida"],
                })
        except Exception:
            continue

    # Ordenar por score DESC
    resultados.sort(key=lambda r: r["score"], reverse=True)
    return resultados[:limite]


async def metricas_riesgo(clinica_id: int) -> dict:
    """Estadísticas rápidas: cuántos en cada nivel + valor estimado en riesgo."""
    todos_riesgo = await listar_pacientes_en_riesgo(clinica_id, score_minimo=40, limite=500)

    alto = sum(1 for r in todos_riesgo if r["nivel"] == "alto")
    medio = sum(1 for r in todos_riesgo if r["nivel"] == "medio")

    # Valor en riesgo: sumar valor_total de los pacientes en riesgo alto
    valor_en_riesgo = sum(
        r["paciente"].valor_total or 0
        for r in todos_riesgo
        if r["nivel"] == "alto"
    )

    return {
        "total_riesgo": alto + medio,
        "alto_riesgo": alto,
        "medio_riesgo": medio,
        "valor_en_riesgo_cop": valor_en_riesgo,
    }

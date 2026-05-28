# -*- coding: utf-8 -*-
# agent/clinic_brain.py — IA SofIA per-tenant para Lapora Clinic
# Lapora Marketing Digital

"""
Cerebro de IA por clínica. Genera respuestas con Claude usando el contexto
específico de cada tenant (nombre, especialidad, horario, plantillas, etc.).

Cada clínica configura su propia IA en /clinic/app/configuracion:
- ia_activa: ON/OFF master switch
- ia_saludo: Primera frase que usa SofIA
- ia_servicios: Lista de servicios que ofrece
- ia_horario: Horario de atención
- ia_precios_basicos: Precios públicos (NO inventa fuera de aquí)
- ia_instrucciones_extra: Reglas custom de la clínica

Funciones principales:
- generar_respuesta_clinica(clinica, paciente, mensaje, historial) → dict
- enviar_whatsapp_clinica(clinica, telefono, mensaje) → bool
- detectar_escalacion(texto) → bool (handoff a humano)
"""

import os
import logging
from typing import Optional
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from agent.clinic_models import Clinica, Paciente, MensajeUnificado, PlantillaRespuesta
from agent.memory import async_session
from sqlalchemy import select, desc

load_dotenv(override=True)
logger = logging.getLogger("agentkit")

# Cliente Anthropic (compartido para todos los tenants — la separación es por system prompt)
_client: Optional[AsyncAnthropic] = None


def _get_client() -> AsyncAnthropic:
    """Inicialización perezosa del cliente Anthropic."""
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY no configurado en .env")
        _client = AsyncAnthropic(api_key=api_key)
    return _client


MODELO = "claude-sonnet-4-6"
MAX_TOKENS = 600  # Mensajes WhatsApp deben ser cortos
HISTORIAL_LIMITE = 12  # Últimos 12 mensajes por paciente


# ════════════════════════════════════════════════════════════
# ESCALACIÓN A HUMANO — Keywords que activan handoff
# ════════════════════════════════════════════════════════════

ESCALACION_KEYWORDS = [
    "humano", "persona real", "persona de verdad", "agente real",
    "no quiero hablar con ia", "no quiero bot", "no eres real",
    "asesor", "vendedor humano", "alguien del equipo",
    "urgente urgente", "emergencia",
]

URGENCIA_MEDICA_KEYWORDS = [
    "sangrado", "no puedo respirar", "dolor fuerte fuerte",
    "alergia grave", "desmayo", "convulsion", "presion alta",
    "infarto", "accidente", "intoxicacion",
]


def detectar_escalacion(texto: str) -> bool:
    """True si el paciente pide hablar con humano o reporta urgencia médica."""
    if not texto:
        return False
    t = texto.lower()
    return any(k in t for k in ESCALACION_KEYWORDS + URGENCIA_MEDICA_KEYWORDS)


# ════════════════════════════════════════════════════════════
# CONSTRUCCIÓN DEL SYSTEM PROMPT PER-TENANT
# ════════════════════════════════════════════════════════════

def construir_system_prompt(
    clinica: Clinica,
    plantillas: list[PlantillaRespuesta] = None,
    paciente: Paciente = None,
) -> str:
    """Construye el system prompt usando datos de la clínica.

    Args:
        clinica: La clínica tenant
        plantillas: Plantillas de respuesta de la clínica (opcionales)
        paciente: El paciente actual (para personalización)

    Returns:
        System prompt completo
    """
    nombre_clinica = clinica.nombre or "la clínica"
    especialidad = clinica.especialidad or "salud"
    ciudad = clinica.ciudad or ""
    saludo = clinica.ia_saludo or f"¡Hola! Soy SofIA, asistente virtual de {nombre_clinica}. ¿En qué te puedo ayudar?"
    servicios = clinica.ia_servicios or "Consulta general"
    horario = clinica.ia_horario or "Lunes a viernes de 8am a 6pm"
    precios = clinica.ia_precios_basicos or ""
    extra = clinica.ia_instrucciones_extra or ""

    # Plantillas formateadas
    plantillas_txt = ""
    if plantillas:
        plantillas_txt = "\n".join(
            f"- {p.titulo}: {p.contenido}" for p in plantillas[:10]
        )

    # Contexto del paciente si existe
    contexto_paciente = ""
    if paciente:
        if paciente.nombre and not paciente.nombre.startswith("WhatsApp +"):
            contexto_paciente += f"\n- Nombre del paciente: {paciente.nombre}"
        if paciente.tratamiento_actual:
            contexto_paciente += f"\n- Tratamiento actual: {paciente.tratamiento_actual}"
        if paciente.estado:
            contexto_paciente += f"\n- Estado: {paciente.estado}"
        if paciente.notas_basicas:
            contexto_paciente += f"\n- Notas: {paciente.notas_basicas[:200]}"

    prompt = f"""Eres SofIA, asistente virtual por WhatsApp de {nombre_clinica}, una clínica de {especialidad}{' en ' + ciudad if ciudad else ''}.

## TU IDENTIDAD
- Eres SofIA (mujer, voz amable y profesional)
- Representas EXCLUSIVAMENTE a {nombre_clinica} — nunca menciones otras clínicas
- Hablas SIEMPRE en español colombiano (usa "tú" o "usted" según el tono del paciente)
- Tu objetivo: ayudar al paciente y facilitar que agende cita o resuelva su duda

## INFORMACIÓN DE LA CLÍNICA
- Nombre: {nombre_clinica}
- Especialidad: {especialidad}
{'- Ciudad: ' + ciudad if ciudad else ''}
- Horario de atención: {horario}

## SERVICIOS QUE OFRECE LA CLÍNICA
{servicios}

## PRECIOS PÚBLICOS (úsalos cuando el paciente pregunte — NO inventes precios fuera de esta lista)
{precios if precios else 'No hay precios públicos configurados. Si el paciente pregunta precios, di: "Para darle el precio exacto, déjeme conectarle con un asesor del equipo. ¿Me deja su nombre y le contactan hoy?"'}

## SALUDO INICIAL (úsalo solo en el primer mensaje a un paciente nuevo)
{saludo}

## PLANTILLAS DE RESPUESTA DE LA CLÍNICA (úsalas como referencia)
{plantillas_txt if plantillas_txt else '(sin plantillas configuradas)'}

## CONTEXTO DEL PACIENTE ACTUAL{contexto_paciente if contexto_paciente else ' (paciente nuevo, sin historial)'}

## REGLAS CRÍTICAS DE COMPORTAMIENTO

1. **BREVEDAD**: Respuestas máximo 2-3 frases. WhatsApp = mensajes cortos. NO hagas listas largas ni respondas con párrafos.

2. **NUNCA INVENTES INFORMACIÓN**:
   - Precios fuera de la lista de "PRECIOS PÚBLICOS" → di que un asesor le contactará
   - Disponibilidad de horarios → propón 2-3 opciones genéricas, confirma con el equipo
   - Diagnósticos médicos → NUNCA des diagnósticos. Di "eso lo debe revisar el doctor en consulta"

3. **AGENDAR CITAS**: Cuando el paciente quiera cita, pide en ESTE orden (1 dato por mensaje):
   - Nombre completo
   - Motivo de consulta
   - Día/hora preferida
   Luego di: "Listo, paso tu solicitud al equipo. Te confirman la cita en máximo 1 hora."

4. **URGENCIAS MÉDICAS**: Si el paciente menciona dolor fuerte, sangrado, dificultad respirar, alergia grave, etc:
   - Responde: "Si es una urgencia médica, por favor llame inmediatamente al consultorio o vaya a urgencias. Aquí no podemos atender emergencias por chat."

5. **PEDIDO DE HUMANO**: Si el paciente dice "quiero hablar con un humano", "persona real", "asesor", etc:
   - Responde: "Por supuesto. Le paso tu mensaje al equipo y te contactan pronto."
   - NO sigas la conversación después de esto.

6. **PRIVACIDAD**: NUNCA pidas datos sensibles como documento, número de tarjeta, contraseñas. Solo nombre, teléfono y motivo de consulta.

7. **FUERA DE HORARIO**: Si el paciente escribe fuera del horario ({horario}), responde igual pero al final agrega: "Nuestro horario es {horario}, te respondemos apenas estemos disponibles."

## INSTRUCCIONES ADICIONALES DE LA CLÍNICA
{extra if extra else '(ninguna)'}

---
RECUERDA: Eres SofIA de {nombre_clinica}. Breve. Cálida. Profesional. NO inventes. Cuando dudes, di "te contacta un asesor"."""

    return prompt


# ════════════════════════════════════════════════════════════
# HISTORIAL DE CONVERSACIÓN PER-TENANT
# ════════════════════════════════════════════════════════════

async def obtener_historial_paciente(
    clinica_id: int,
    paciente_id: int,
    limite: int = HISTORIAL_LIMITE,
) -> list[dict]:
    """Recupera últimos N mensajes entre la clínica y el paciente.

    Returns: lista en orden cronológico [{"role": "user/assistant", "content": "..."}]
    """
    async with async_session() as session:
        result = await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.clinica_id == clinica_id)
            .where(MensajeUnificado.paciente_id == paciente_id)
            .order_by(desc(MensajeUnificado.timestamp))
            .limit(limite)
        )
        mensajes = list(result.scalars().all())
        mensajes.reverse()  # Cronológico

    return [
        {
            "role": "user" if m.direccion == "entrada" else "assistant",
            "content": m.contenido or "",
        }
        for m in mensajes
        if m.contenido and m.contenido.strip()
    ]


# ════════════════════════════════════════════════════════════
# GENERACIÓN DE RESPUESTA
# ════════════════════════════════════════════════════════════

async def generar_respuesta_clinica(
    clinica: Clinica,
    paciente: Paciente,
    mensaje: str,
) -> dict:
    """Genera respuesta de SofIA para un mensaje entrante de paciente.

    Args:
        clinica: La clínica tenant (debe tener ia_activa=True para llegar aquí)
        paciente: El paciente que escribió
        mensaje: Texto del mensaje entrante

    Returns:
        {
            "respuesta": str,           # Texto a enviar (vacío si no se debe responder)
            "escalar_humano": bool,     # True si se detectó pedido de humano/urgencia
            "exito": bool,
            "error": str,               # Mensaje de error si exito=False
        }
    """
    # Detección rápida de escalación (sin gastar tokens de Claude)
    if detectar_escalacion(mensaje):
        return {
            "respuesta": (
                "Por supuesto, le paso tu mensaje al equipo de "
                f"{clinica.nombre or 'la clínica'} y te contactan pronto. "
                "Si es una emergencia médica, por favor llame al consultorio o vaya a urgencias."
            ),
            "escalar_humano": True,
            "exito": True,
            "error": "",
        }

    # Validar mensaje
    if not mensaje or len(mensaje.strip()) < 2:
        return {
            "respuesta": "",
            "escalar_humano": False,
            "exito": False,
            "error": "Mensaje vacío o muy corto",
        }

    try:
        # Cargar plantillas de la clínica
        async with async_session() as session:
            plantillas_result = await session.execute(
                select(PlantillaRespuesta)
                .where(PlantillaRespuesta.clinica_id == clinica.id)
                .limit(10)
            )
            plantillas = list(plantillas_result.scalars().all())

        # Construir system prompt + historial
        system_prompt = construir_system_prompt(clinica, plantillas, paciente)
        historial = await obtener_historial_paciente(clinica.id, paciente.id)

        # Armar mensajes (historial NO incluye el mensaje actual)
        mensajes = list(historial)
        mensajes.append({"role": "user", "content": mensaje})

        # Llamar Claude
        client = _get_client()
        response = await client.messages.create(
            model=MODELO,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=mensajes,
        )

        # Extraer texto
        texto_partes = []
        for bloque in response.content:
            if bloque.type == "text":
                texto_partes.append(bloque.text)
        respuesta = "\n".join(texto_partes).strip()

        if not respuesta:
            respuesta = (
                f"Hola, soy SofIA de {clinica.nombre or 'la clínica'}. "
                "¿En qué te puedo ayudar?"
            )

        logger.info(
            f"[IA clinica={clinica.id}] in={response.usage.input_tokens} "
            f"out={response.usage.output_tokens} respuesta_len={len(respuesta)}"
        )

        return {
            "respuesta": respuesta,
            "escalar_humano": False,
            "exito": True,
            "error": "",
        }

    except Exception as e:
        logger.error(f"[IA clinica={clinica.id}] Error generando respuesta: {e}", exc_info=True)
        return {
            "respuesta": "",
            "escalar_humano": False,
            "exito": False,
            "error": str(e)[:200],
        }


# ════════════════════════════════════════════════════════════
# ENVÍO DE WHATSAPP USANDO CREDENCIALES PROPIAS DE LA CLÍNICA
# ════════════════════════════════════════════════════════════

async def enviar_whatsapp_clinica(
    clinica: Clinica,
    telefono: str,
    mensaje: str,
) -> dict:
    """Envía mensaje WhatsApp usando las credenciales Meta de la clínica.

    Cada clínica tiene su propio whatsapp_phone_id y whatsapp_token configurados
    en /clinic/app/configuracion. Refactor: delega a whatsapp_helper.

    Returns: {"exito": bool, "error": str, "message_id": str}
    """
    from agent.whatsapp_helper import enviar_mensaje_meta
    return await enviar_mensaje_meta(
        phone_id=clinica.whatsapp_phone_id,
        token=clinica.whatsapp_token,
        telefono=telefono,
        mensaje=mensaje,
        contexto_log=f"clinica={clinica.id}",
    )


# ════════════════════════════════════════════════════════════
# FLUJO COMPLETO — Procesa mensaje entrante y responde
# ════════════════════════════════════════════════════════════

async def procesar_mensaje_entrante(
    clinica: Clinica,
    paciente: Paciente,
    mensaje_texto: str,
) -> dict:
    """Pipeline completo: detecta escalación, genera respuesta, envía WhatsApp,
    guarda mensaje de salida en MensajeUnificado.

    Llamada desde el webhook /clinic/webhook/whatsapp/{slug} DESPUÉS de
    guardar el mensaje entrante en la BD.

    Returns: dict con estado del procesamiento (para logging).
    """
    from datetime import datetime

    if not clinica.ia_activa:
        return {"accion": "ia_desactivada", "respuesta_enviada": False}

    if clinica.congelada:
        return {"accion": "clinica_congelada", "respuesta_enviada": False}

    # Generar respuesta con Claude
    resultado = await generar_respuesta_clinica(clinica, paciente, mensaje_texto)

    if not resultado["exito"] or not resultado["respuesta"]:
        return {
            "accion": "error_generacion",
            "respuesta_enviada": False,
            "error": resultado.get("error", ""),
        }

    respuesta = resultado["respuesta"]
    escalado = resultado["escalar_humano"]

    # Enviar por WhatsApp
    envio = await enviar_whatsapp_clinica(clinica, paciente.telefono, respuesta)

    # Guardar mensaje de salida en MensajeUnificado
    async with async_session() as session:
        msg_salida = MensajeUnificado(
            clinica_id=clinica.id,
            paciente_id=paciente.id,
            canal="whatsapp",
            direccion="salida",
            contenido=respuesta,
            canal_msg_id=envio.get("message_id", ""),
            leido=True,  # Salidas se marcan leídas automáticamente
            respondido_por="ia",
            timestamp=datetime.utcnow(),
        )
        session.add(msg_salida)

        # Si fue escalación, marcar el paciente con tag
        if escalado:
            from sqlalchemy import select as _select
            p = (await session.execute(
                _select(Paciente).where(Paciente.id == paciente.id)
            )).scalar_one_or_none()
            if p:
                tags = p.tags or ""
                if "escalado" not in tags:
                    p.tags = (tags + ",escalado").strip(",")

        await session.commit()

    return {
        "accion": "respondido_por_ia",
        "respuesta_enviada": envio["exito"],
        "escalado": escalado,
        "error_envio": envio.get("error", "") if not envio["exito"] else "",
        "respuesta": respuesta[:100],
    }

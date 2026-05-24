# agent/brain.py — Cerebro de SofIA: conexion con Claude API + Tool Use
# Generado por AgentKit

"""
Logica de IA de SofIA con Tool Use (function calling).

SofIA puede usar estas herramientas:
- verificar_disponibilidad: Saber si una fecha/hora esta libre
- agendar_cita: Crear evento en Google Calendar
- listar_citas_proximas: Ver citas agendadas
"""

import os
import yaml
import logging
from pathlib import Path
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

from datetime import datetime
from agent.calendar_service import (
    verificar_disponibilidad,
    agendar_cita,
    listar_citas_proximas,
)
from agent.reminders import programar_recordatorio
from agent.memory import incrementar_citas_agendadas, actualizar_contacto

load_dotenv(override=True)
logger = logging.getLogger("agentkit")

# Cliente de Anthropic
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Modelo de Claude
MODELO_CLAUDE = "claude-sonnet-4-6"
MAX_TOKENS = 1500


# ════════════════════════════════════════════════════════════
# DEFINICION DE TOOLS QUE SOFIA PUEDE USAR
# ════════════════════════════════════════════════════════════

TOOLS = [
    {
        "name": "verificar_disponibilidad",
        "description": (
            "Verifica si una fecha y hora especifica esta disponible en el calendario de Lapora "
            "para agendar un diagnostico/llamada con un doctor. "
            "USA ESTO ANTES de confirmar cualquier cita."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {
                    "type": "string",
                    "description": (
                        "Fecha en formato 'manana', 'pasado manana', 'hoy', "
                        "'YYYY-MM-DD' (ej: 2026-05-25) o 'DD/MM/YYYY' (ej: 25/05/2026)."
                    ),
                },
                "hora": {
                    "type": "string",
                    "description": (
                        "Hora en formato 'HH:MM' (24h), '3pm', '10am', '3:30pm', etc. "
                        "Horario de atencion: 7am-8pm."
                    ),
                },
            },
            "required": ["fecha", "hora"],
        },
    },
    {
        "name": "agendar_cita",
        "description": (
            "Crea una cita de diagnostico/llamada en el calendario de Lapora. "
            "Envia invitacion al doctor con enlace de Google Meet. "
            "USA ESTO SOLO cuando ya verificaste la disponibilidad Y el doctor confirmo. "
            "Si no tienes el email del doctor, primero preguntale por su correo."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "fecha": {"type": "string", "description": "Misma fecha verificada como disponible."},
                "hora": {"type": "string", "description": "Misma hora verificada como disponible."},
                "nombre_doctor": {"type": "string", "description": "Nombre completo del doctor."},
                "email_doctor": {
                    "type": "string",
                    "description": "Email del doctor para enviar invitacion. OPCIONAL pero recomendado.",
                },
                "telefono": {"type": "string", "description": "WhatsApp del doctor (numero)."},
                "especialidad": {"type": "string", "description": "Especialidad medica."},
                "ciudad": {"type": "string", "description": "Ciudad del consultorio."},
                "notas": {"type": "string", "description": "Contexto adicional relevante."},
            },
            "required": ["fecha", "hora", "nombre_doctor"],
        },
    },
    {
        "name": "listar_citas_proximas",
        "description": (
            "Lista las citas agendadas en los proximos dias. "
            "Util si el doctor pregunta sobre disponibilidad general o cuando proponer horarios."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "dias": {
                    "type": "integer",
                    "description": "Cuantos dias hacia adelante mirar (default: 7).",
                    "default": 7,
                }
            },
            "required": [],
        },
    },
]


# ════════════════════════════════════════════════════════════
# CARGA DE CONFIGURACION
# ════════════════════════════════════════════════════════════

def cargar_config_prompts() -> dict:
    """Lee toda la configuracion desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_knowledge() -> str:
    """Carga todos los archivos de /knowledge."""
    contenido = []
    knowledge_dir = Path("knowledge")
    if not knowledge_dir.exists():
        return ""
    for archivo in sorted(knowledge_dir.iterdir()):
        if archivo.name.startswith(".") or not archivo.is_file():
            continue
        try:
            texto = archivo.read_text(encoding="utf-8")
            contenido.append(f"=== {archivo.name} ===\n{texto}\n")
        except (UnicodeDecodeError, IOError):
            continue
    return "\n".join(contenido)


def cargar_system_prompt() -> str:
    """Lee el system prompt + knowledge."""
    config = cargar_config_prompts()
    prompt_base = config.get(
        "system_prompt",
        "Eres SofIA, asistente virtual de Lapora. Responde en español."
    )
    knowledge = cargar_knowledge()
    if knowledge:
        prompt_base += f"\n\n## 📚 Información detallada del negocio\n\n{knowledge}"
    return prompt_base


def obtener_mensaje_error() -> str:
    config = cargar_config_prompts()
    return config.get(
        "error_message",
        "Uy, doctor, estoy teniendo un problema técnico chiquito. ¿Me da 2 minutos y le respondo?"
    )


def obtener_mensaje_fallback() -> str:
    config = cargar_config_prompts()
    return config.get(
        "fallback_message",
        "Disculpe, doctor, no logré entender. ¿Me lo puede contar con otras palabras?"
    )


# ════════════════════════════════════════════════════════════
# EJECUCION DE TOOLS
# ════════════════════════════════════════════════════════════

async def ejecutar_tool(nombre: str, input_data: dict, telefono_usuario: str) -> str:
    """
    Ejecuta una tool y retorna el resultado como string.
    """
    logger.info(f"Ejecutando tool: {nombre} con input: {input_data}")

    try:
        if nombre == "verificar_disponibilidad":
            resultado = verificar_disponibilidad(
                fecha=input_data["fecha"],
                hora=input_data["hora"],
            )
            return str(resultado)

        elif nombre == "agendar_cita":
            # Si no llega el telefono, usar el del usuario actual
            input_data.setdefault("telefono", telefono_usuario)
            resultado = agendar_cita(**input_data)

            # Si la cita se agendo correctamente, programar recordatorio + CRM
            if resultado.get("exito") and resultado.get("fecha_iso"):
                try:
                    fecha_cita = datetime.fromisoformat(resultado["fecha_iso"])
                    telefono_cliente = input_data.get("telefono", telefono_usuario)
                    nombre_doctor = input_data.get("nombre_doctor", "Doctor")

                    # Programar recordatorio 1h antes
                    await programar_recordatorio(
                        telefono=telefono_cliente,
                        nombre_doctor=nombre_doctor,
                        evento_id=resultado.get("evento_id", ""),
                        fecha_cita=fecha_cita,
                    )

                    # CRM: actualizar contacto con datos del doctor + estado
                    datos_contacto = {
                        "nombre": nombre_doctor,
                        "email": input_data.get("email_doctor", ""),
                        "especialidad": input_data.get("especialidad", ""),
                        "ciudad": input_data.get("ciudad", ""),
                    }
                    # Limpiar campos vacios
                    datos_contacto = {k: v for k, v in datos_contacto.items() if v}
                    if datos_contacto:
                        await actualizar_contacto(telefono_cliente, datos_contacto)

                    # Incrementar contador de citas y cambiar estado
                    await incrementar_citas_agendadas(telefono_cliente)

                    logger.info(
                        f"Recordatorio programado + CRM actualizado para {telefono_cliente}"
                    )
                except Exception as e:
                    # No fallar si el recordatorio falla
                    logger.error(f"Error programando recordatorio/CRM: {e}", exc_info=True)

            return str(resultado)

        elif nombre == "listar_citas_proximas":
            dias = input_data.get("dias", 7)
            resultado = listar_citas_proximas(dias=dias)
            return str(resultado)

        else:
            return f"Error: tool '{nombre}' no reconocida."

    except Exception as e:
        logger.error(f"Error ejecutando tool {nombre}: {e}", exc_info=True)
        return f"Error tecnico al ejecutar {nombre}: {e}"


# ════════════════════════════════════════════════════════════
# GENERACION DE RESPUESTA CON TOOL USE
# ════════════════════════════════════════════════════════════

async def generar_respuesta(
    mensaje: str,
    historial: list[dict],
    telefono_usuario: str = "",
) -> str:
    """
    Genera una respuesta usando Claude API con Tool Use.

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Lista de mensajes anteriores
        telefono_usuario: WhatsApp del doctor (para tools que lo necesiten)

    Returns:
        La respuesta generada por Claude
    """
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system_prompt = cargar_system_prompt()

    # Construir mensajes
    mensajes = []
    for msg in historial:
        mensajes.append({"role": msg["role"], "content": msg["content"]})
    mensajes.append({"role": "user", "content": mensaje})

    try:
        # Loop de Tool Use: maximo 5 iteraciones para evitar loops infinitos
        for iteracion in range(5):
            response = await client.messages.create(
                model=MODELO_CLAUDE,
                max_tokens=MAX_TOKENS,
                system=system_prompt,
                tools=TOOLS,
                messages=mensajes,
            )

            logger.info(
                f"Iteracion {iteracion+1}: stop_reason={response.stop_reason} | "
                f"tokens in={response.usage.input_tokens}, out={response.usage.output_tokens}"
            )

            # Si Claude no quiere usar tools, retornar el texto
            if response.stop_reason != "tool_use":
                # Extraer el texto de la respuesta
                texto_partes = []
                for bloque in response.content:
                    if bloque.type == "text":
                        texto_partes.append(bloque.text)
                respuesta_final = "\n".join(texto_partes).strip()
                if not respuesta_final:
                    respuesta_final = obtener_mensaje_fallback()
                return respuesta_final

            # Claude quiere usar una o mas tools
            # Agregamos la respuesta del asistente al historial
            mensajes.append({
                "role": "assistant",
                "content": response.content,
            })

            # Ejecutamos cada tool y agregamos resultados
            tool_results = []
            for bloque in response.content:
                if bloque.type == "tool_use":
                    resultado = await ejecutar_tool(
                        nombre=bloque.name,
                        input_data=bloque.input,
                        telefono_usuario=telefono_usuario,
                    )
                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": bloque.id,
                        "content": resultado,
                    })

            # Agregamos los resultados como un mensaje del usuario
            mensajes.append({
                "role": "user",
                "content": tool_results,
            })

        # Si llegamos aqui, hubo demasiadas iteraciones
        logger.warning("Loop de Tool Use excedio iteraciones maximas")
        return (
            "Disculpe doctor, estoy teniendo un poco de dificultad procesando su solicitud. "
            "¿Me lo puede repetir de otra forma?"
        )

    except Exception as e:
        logger.error(f"Error Claude API: {e}", exc_info=True)
        return obtener_mensaje_error()

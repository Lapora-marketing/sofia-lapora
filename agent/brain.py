# agent/brain.py — Cerebro de SofIA: conexion con Claude API
# Generado por AgentKit

"""
Logica de IA de SofIA.
Lee el system prompt de prompts.yaml e incorpora el contenido de /knowledge
para que SofIA conozca a fondo a Lapora.
"""

import os
import yaml
import logging
from pathlib import Path
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("agentkit")

# Cliente de Anthropic
client = AsyncAnthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

# Modelo de Claude
MODELO_CLAUDE = "claude-sonnet-4-6"

# Tamano maximo de respuesta
MAX_TOKENS = 1024


def cargar_config_prompts() -> dict:
    """Lee toda la configuracion desde config/prompts.yaml."""
    try:
        with open("config/prompts.yaml", "r", encoding="utf-8") as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.error("config/prompts.yaml no encontrado")
        return {}


def cargar_knowledge() -> str:
    """
    Carga todos los archivos de /knowledge y los concatena.
    SofIA tendra este contenido como contexto adicional.
    """
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
            logger.warning(f"No se pudo leer: {archivo.name}")
            continue

    return "\n".join(contenido)


def cargar_system_prompt() -> str:
    """Lee el system prompt desde config/prompts.yaml + knowledge."""
    config = cargar_config_prompts()
    prompt_base = config.get(
        "system_prompt",
        "Eres SofIA, asistente virtual de Lapora. Responde en español."
    )

    # Incorporar knowledge
    knowledge = cargar_knowledge()
    if knowledge:
        prompt_base += f"\n\n## 📚 Información detallada del negocio\n\n{knowledge}"

    return prompt_base


def obtener_mensaje_error() -> str:
    """Retorna el mensaje de error configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get(
        "error_message",
        "Uy, doctor, estoy teniendo un problema técnico chiquito. ¿Me da 2 minutos y le respondo?"
    )


def obtener_mensaje_fallback() -> str:
    """Retorna el mensaje de fallback configurado en prompts.yaml."""
    config = cargar_config_prompts()
    return config.get(
        "fallback_message",
        "Disculpe, doctor, no logré entender. ¿Me lo puede contar con otras palabras?"
    )


async def generar_respuesta(mensaje: str, historial: list[dict]) -> str:
    """
    Genera una respuesta usando Claude API.

    Args:
        mensaje: El mensaje nuevo del usuario
        historial: Lista de mensajes anteriores [{"role": "user/assistant", "content": "..."}]

    Returns:
        La respuesta generada por Claude
    """
    # Si el mensaje es muy corto o vacio, usar fallback
    if not mensaje or len(mensaje.strip()) < 2:
        return obtener_mensaje_fallback()

    system_prompt = cargar_system_prompt()

    # Construir mensajes para la API
    mensajes = []
    for msg in historial:
        mensajes.append({
            "role": msg["role"],
            "content": msg["content"]
        })

    # Agregar el mensaje actual
    mensajes.append({
        "role": "user",
        "content": mensaje
    })

    try:
        response = await client.messages.create(
            model=MODELO_CLAUDE,
            max_tokens=MAX_TOKENS,
            system=system_prompt,
            messages=mensajes,
        )

        respuesta = response.content[0].text
        logger.info(
            f"SofIA respondio ({response.usage.input_tokens} in / "
            f"{response.usage.output_tokens} out tokens)"
        )
        return respuesta

    except Exception as e:
        logger.error(f"Error Claude API: {e}", exc_info=True)
        return obtener_mensaje_error()

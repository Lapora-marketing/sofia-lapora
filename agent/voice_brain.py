# -*- coding: utf-8 -*-
# agent/voice_brain.py — Brain conversacional del Voice Bot
# Lapora Marketing Digital

"""
El brain del Voice Bot. Carga voice_scripts.yaml, construye system prompt
para Claude, decide qué decir en cada turno.

Diseño: NO es una máquina de estados rígida. Claude conduce la conversación
naturalmente usando el script como guía (apertura, objetivos, objeciones,
cierres).

Flow:
1. Cargo script (ej: 'outreach_medicos')
2. Inyecto variables del target ({nombre_doctor}, {especialidad}, etc.)
3. Construyo system prompt enorme con TODO el contexto
4. En cada turno:
   - Recibo transcript del usuario
   - Mando a Claude el system + histórico + nuevo
   - Claude devuelve: respuesta + flags ('end_call', 'send_whatsapp', 'optout')
5. El runtime decide: hablar la respuesta o ejecutar acción
"""

import os
import re
import json
import logging
from pathlib import Path
from typing import Optional
import yaml
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("agentkit")

_client: Optional[AsyncAnthropic] = None

CONFIG_PATH = Path(__file__).parent.parent / "config" / "voice_scripts.yaml"
_config_cache: Optional[dict] = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY no configurada")
        _client = AsyncAnthropic(api_key=api_key)
    return _client


def cargar_config() -> dict:
    """Carga voice_scripts.yaml. Cachea para no leer el disco en cada turno."""
    global _config_cache
    if _config_cache is None:
        if not CONFIG_PATH.exists():
            raise FileNotFoundError(f"voice_scripts.yaml no encontrado en {CONFIG_PATH}")
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            _config_cache = yaml.safe_load(f) or {}
    return _config_cache


def recargar_config():
    """Fuerza recarga del YAML. Útil tras editar el script en producción."""
    global _config_cache
    _config_cache = None
    return cargar_config()


def obtener_script(script_id: str) -> dict:
    """Devuelve el script seleccionado, resolviendo referencias 'reusar_*_de'."""
    config = cargar_config()
    scripts = config.get("scripts", {})
    if script_id not in scripts:
        raise ValueError(f"Script '{script_id}' no existe en voice_scripts.yaml")
    s = dict(scripts[script_id])  # copia

    # Resolver herencia (reusar_objeciones_de, reusar_cierres_de)
    if "reusar_objeciones_de" in s:
        padre = scripts.get(s["reusar_objeciones_de"], {})
        s["objeciones"] = s.get("objeciones") or padre.get("objeciones", [])
    if "reusar_cierres_de" in s:
        padre = scripts.get(s["reusar_cierres_de"], {})
        s["cierres"] = s.get("cierres") or padre.get("cierres", {})
    return s


def inyectar_variables(texto: str, variables: dict) -> str:
    """Reemplaza {variable} con su valor. Si la var no existe, deja literal."""
    if not texto:
        return ""
    def repl(m):
        key = m.group(1)
        return str(variables.get(key, m.group(0)))
    return re.sub(r"\{(\w+)\}", repl, texto)


# ════════════════════════════════════════════════════════════
# SYSTEM PROMPT BUILDER
# ════════════════════════════════════════════════════════════

def construir_system_prompt(script_id: str, variables: dict) -> str:
    """Convierte el script YAML + variables del target en system prompt para Claude.

    El prompt le da a Claude:
    - Su identidad (SofIA)
    - El contexto del negocio
    - Los objetivos de esta llamada
    - Las reglas de comportamiento
    - Las objeciones esperadas con respuestas modelo
    - Los cierres posibles
    - Formato de respuesta esperado (JSON con respuesta + flags)
    """
    config = cargar_config()
    script = obtener_script(script_id)
    global_cfg = config.get("config_global", {})

    # Variables canónicas con defaults
    vars_safe = {
        "nombre_doctor":    variables.get("nombre_doctor", "doctor"),
        "nombre_negocio":   variables.get("nombre_negocio", "su consultorio"),
        "especialidad":     variables.get("especialidad", ""),
        "ciudad":           variables.get("ciudad", "Ibagué"),
        "telefono":         variables.get("telefono", ""),
        "nombre_paciente":  variables.get("nombre_paciente", ""),
        "nombre_clinica":   variables.get("nombre_clinica", ""),
        "fecha_cita":       variables.get("fecha_cita", ""),
        "hora_cita":        variables.get("hora_cita", ""),
        "motivo":           variables.get("motivo", ""),
    }

    apertura = inyectar_variables(script.get("apertura", ""), vars_safe).strip()
    contexto = inyectar_variables(script.get("contexto_negocio", ""), vars_safe).strip()
    objetivos = "\n".join(f"- {o}" for o in script.get("objetivos_del_call", []))
    reglas = "\n".join(f"- {r}" for r in script.get("reglas_comportamiento", []))

    # Objeciones formateadas
    objeciones_txt = ""
    for o in script.get("objeciones", []):
        patrones = ", ".join(f'"{p}"' for p in o.get("patron", []))
        respuesta = inyectar_variables(o.get("respuesta_modelo", ""), vars_safe).strip()
        accion = o.get("siguiente_accion", "")
        objeciones_txt += f"\nSi el doctor dice algo como: {patrones}\n"
        objeciones_txt += f"  Responde modelo: \"{respuesta}\"\n"
        objeciones_txt += f"  Acción interna: {accion}\n"

    # Cierres
    cierres_txt = ""
    for nombre, c in (script.get("cierres") or {}).items():
        despedida = inyectar_variables(c.get("despedida", ""), vars_safe).strip()
        accion = c.get("accion", "")
        cierres_txt += f"\n  - Cierre '{nombre}' (acción: {accion}):\n    \"{despedida}\"\n"

    # Opt-out frases
    optout_frases = "\n".join(f'  - "{f}"' for f in global_cfg.get("opt_out_frases", []))

    # System prompt completo
    prompt = f"""Eres SofIA, asistente virtual de Lapora Marketing Digital, hablando por TELÉFONO con un médico/paciente.

# CONTEXTO CRÍTICO DE LA LLAMADA

Esta es una conversación HABLADA por teléfono. NO un chat de texto.
- Habla en frases CORTAS (máx 3-4 segundos de audio = ~15 palabras)
- Usa pausas naturales con coma y punto
- NUNCA hables más de 4 segundos seguidos sin dejar pausar a la persona
- Hablas español colombiano, tono cálido y profesional, NO vendedor agresivo

# TU IDENTIDAD
Eres SofIA, una asistente virtual de Lapora Marketing Digital con sede en Ibagué, Tolima.

# APERTURA (úsala SOLO en el primer turno)
"{apertura}"

# CONTEXTO DEL NEGOCIO
{contexto}

# OBJETIVOS DE ESTA LLAMADA
{objetivos}

# REGLAS DE COMPORTAMIENTO (cumplir SIEMPRE)
{reglas}

# OBJECIONES ESPERADAS Y CÓMO RESPONDER
Usa estas respuestas modelo como guía, NO las copies textual. Adáptalas al flujo natural.
{objeciones_txt}

# FRASES QUE DISPARAN OPT-OUT INMEDIATO (terminar llamada)
Si la persona dice cualquiera de estas frases (o algo similar), activa flag opt_out=true:
{optout_frases}

# CIERRES POSIBLES (cuando detectes que es momento de terminar)
{cierres_txt}

# DETECCIÓN DE BUZÓN DE VOZ
Si en el primer turno escuchas frases como "deja tu mensaje", "después del tono", "buzón de voz",
"no se encuentra disponible", es BUZÓN DE VOZ — NO una persona.
Acción: di un mensaje BREVE de 10 segundos máximo y activa flag end_call=true con outcome="voicemail".

# FORMATO DE RESPUESTA — CRÍTICO

DEBES responder SIEMPRE en este formato JSON exacto:

```json
{{
  "respuesta": "Lo que vas a decir en voz alta. CORTO (máx 15 palabras).",
  "end_call": false,
  "outcome": "",
  "send_whatsapp_summary": false,
  "transfer_to_human": false,
  "optout": false,
  "internal_note": "Tu razonamiento interno (no se habla, solo para logs)"
}}
```

Reglas del JSON:
- `respuesta`: lo que SofIA dice. Máx 15 palabras = ~3-4 segundos de audio. Si vas a despedirte, incluí la despedida aquí.
- `end_call`: true SOLO cuando la conversación debe terminar (cierre acordado, opt-out, voicemail, off-topic prolongado)
- `outcome`: si end_call=true, uno de: "interested", "not_interested", "callback", "voicemail", "no_answer", "opt_out", "failed"
- `send_whatsapp_summary`: true si vamos a mandar info por WhatsApp tras colgar (caso típico: el doctor pidió info)
- `transfer_to_human`: true si la persona pide explícitamente hablar con humano y debemos pasar el caso
- `optout`: true si la persona pidió NO ser llamada de nuevo (lista negra permanente)
- `internal_note`: explicación corta de tu razonamiento (para que el equipo pueda auditar después)

# IMPORTANTE
- En el PRIMER turno, usa la APERTURA exacta (puede ser adaptada levemente)
- En turnos siguientes, conversa naturalmente respetando las reglas
- Si la persona te pregunta algo que no sabes responder, di "le paso esa pregunta al equipo, lo llaman hoy" y `transfer_to_human=true`
- Nunca inventes precios diferentes a $100 USD/mes Pro o $250 USD/mes Studio
- Nunca prometas cosas que el sistema no puede hacer
"""
    return prompt


# ════════════════════════════════════════════════════════════
# GENERAR RESPUESTA — Llamar Claude con el historial
# ════════════════════════════════════════════════════════════

class RespuestaBot:
    """Resultado de un turno del brain."""
    def __init__(
        self,
        respuesta: str,
        end_call: bool = False,
        outcome: str = "",
        send_whatsapp_summary: bool = False,
        transfer_to_human: bool = False,
        optout: bool = False,
        internal_note: str = "",
    ):
        self.respuesta = respuesta
        self.end_call = end_call
        self.outcome = outcome
        self.send_whatsapp_summary = send_whatsapp_summary
        self.transfer_to_human = transfer_to_human
        self.optout = optout
        self.internal_note = internal_note

    def to_dict(self):
        return {
            "respuesta": self.respuesta,
            "end_call": self.end_call,
            "outcome": self.outcome,
            "send_whatsapp_summary": self.send_whatsapp_summary,
            "transfer_to_human": self.transfer_to_human,
            "optout": self.optout,
            "internal_note": self.internal_note,
        }


async def generar_turno(
    script_id: str,
    variables: dict,
    historial: list[dict],
    transcript_usuario: str = "",
    primer_turno: bool = False,
) -> RespuestaBot:
    """Genera el siguiente turno del bot.

    Args:
        script_id: 'outreach_medicos', 'confirmar_cita_clinica', etc.
        variables: dict con {nombre_doctor, especialidad, ...}
        historial: [{"role": "assistant/user", "content": "..."}]
        transcript_usuario: lo que acabamos de escuchar de la persona (vacío si primer_turno)
        primer_turno: True si es el saludo inicial

    Returns:
        RespuestaBot con respuesta + flags
    """
    config = cargar_config()
    max_tokens = config.get("config_global", {}).get("llm", {}).get("max_tokens_por_turno", 200)
    temperatura = config.get("config_global", {}).get("llm", {}).get("temperatura", 0.4)
    modelo = config.get("config_global", {}).get("llm", {}).get("modelo", "claude-sonnet-4-6")

    system_prompt = construir_system_prompt(script_id, variables)

    # Construir mensajes
    mensajes = list(historial)
    if primer_turno:
        mensajes.append({
            "role": "user",
            "content": "[LLAMADA INICIADA — el doctor acaba de contestar. Saludalo con la apertura. Responde en formato JSON.]",
        })
    else:
        mensajes.append({
            "role": "user",
            "content": (transcript_usuario or "[silencio]") + "\n\n[Responde en formato JSON.]",
        })

    try:
        client = _get_client()
        resp = await client.messages.create(
            model=modelo,
            max_tokens=max_tokens,
            temperature=temperatura,
            system=system_prompt,
            messages=mensajes,
        )

        texto = ""
        for bloque in resp.content:
            if bloque.type == "text":
                texto += bloque.text

        # Extraer JSON del texto (puede venir con backticks o sin)
        data = _parsear_json_respuesta(texto)

        return RespuestaBot(
            respuesta=data.get("respuesta", "").strip() or "Disculpe, no escuché bien.",
            end_call=bool(data.get("end_call", False)),
            outcome=data.get("outcome", "") or "",
            send_whatsapp_summary=bool(data.get("send_whatsapp_summary", False)),
            transfer_to_human=bool(data.get("transfer_to_human", False)),
            optout=bool(data.get("optout", False)),
            internal_note=(data.get("internal_note", "") or "")[:300],
        )

    except Exception as e:
        logger.error(f"[voice_brain] error generando turno: {e}", exc_info=True)
        # Fallback seguro: terminar llamada
        return RespuestaBot(
            respuesta="Disculpe doctor, estoy teniendo un problema técnico. Lo llamamos en otro momento. Que tenga buen día.",
            end_call=True,
            outcome="failed",
            internal_note=f"error técnico: {str(e)[:100]}",
        )


def _parsear_json_respuesta(texto: str) -> dict:
    """Parsea el JSON de la respuesta de Claude. Tolera markdown ```json ... ```"""
    if not texto:
        return {}
    # Quitar fences markdown
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if m:
        texto = m.group(1)
    else:
        # Buscar primer { hasta último }
        start = texto.find("{")
        end = texto.rfind("}")
        if start >= 0 and end > start:
            texto = texto[start:end + 1]
    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        logger.warning(f"[voice_brain] JSON inválido de Claude: {e}. Texto: {texto[:200]}")
        return {"respuesta": texto.strip()[:200], "end_call": False}


# ════════════════════════════════════════════════════════════
# DETECTOR DE VOICEMAIL — heurística rápida sin gastar tokens
# ════════════════════════════════════════════════════════════

def es_probable_voicemail(transcript: str, duracion_primer_turno_seg: float = 0) -> bool:
    """Detecta si lo que escuchamos al inicio es un buzón de voz.

    Reglas:
    1. El audio dura más de 8 segundos sin pausas (probable mensaje grabado largo)
    2. Contiene frases típicas de buzón
    """
    config = cargar_config()
    patrones = config.get("config_global", {}).get("detección", {}).get("es_voicemail_patron", [])

    if duracion_primer_turno_seg > 8:
        return True

    t = (transcript or "").lower()
    return any(p.lower() in t for p in patrones)


def detectar_opt_out_keyword(transcript: str) -> bool:
    """Heurística rápida para detectar opt-out por keywords (sin Claude)."""
    config = cargar_config()
    frases = config.get("config_global", {}).get("opt_out_frases", [])
    t = (transcript or "").lower()
    return any(f.lower() in t for f in frases)

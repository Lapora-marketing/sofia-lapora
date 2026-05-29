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
    """Fuerza recarga del YAML + invalida cache de prompts."""
    global _config_cache
    _config_cache = None
    _invalidar_cache_prompts()
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
# SYSTEM PROMPT BUILDER — Optimizado con caching + few-shot
# ════════════════════════════════════════════════════════════

# Cache en memoria: script_id → texto base (sin variables del target)
# Esto evita reconstruir el prompt enorme cada turno (8K chars × 8 turnos × 220 llamadas/mes = ahorro real)
_base_prompt_cache: dict[str, str] = {}


def _invalidar_cache_prompts():
    """Llamar tras recargar voice_scripts.yaml para refrescar el cache."""
    _base_prompt_cache.clear()


# Few-shot examples — Claude aprende del estilo deseado mejor con ejemplos que con reglas
FEW_SHOT_EJEMPLOS = """
# EJEMPLOS DE BUENAS RESPUESTAS (estudia el TONO y BREVEDAD)

Ejemplo 1 — Apertura cálida:
✓ "Buenos días doctor Rodríguez, le habla SofIA de Lapora. Solo le quito 30 segundos, ¿tiene un momento?"
✗ "Hola buenas tardes mi nombre es SofIA soy la asistente virtual de Lapora Marketing Digital y estoy llamando porque..."
(la mala es muy larga y suena robótica)

Ejemplo 2 — Doctor ocupado:
Doctor: "Estoy entre pacientes ahora"
✓ Bot: "Por supuesto doctor. ¿Le mando la info por WhatsApp ahora mismo y la revisa cuando pueda?"
✗ Bot: "Entiendo, pero solo serían dos minutos para explicarle..."
(la mala empuja cuando debería ceder)

Ejemplo 3 — Doctor pregunta "¿de qué se trata?":
✓ Bot: "Es un software que automatiza el WhatsApp de su consultorio con IA. ¿Le interesa que le mande detalles?"
✗ Bot: "Es Lapora Clinic, nuestra plataforma multicanal que integra WhatsApp Business, Instagram y email con inteligencia artificial..."
(la mala es jerga marketinera)

Ejemplo 4 — Doctor parece desconfiado:
Doctor: "¿Cómo consiguieron mi número?"
✓ Bot: "Lo encontramos en su sitio público, doctor. Si prefiere no recibir llamadas, lo quito ya de la lista."
✗ Bot: "Su número está en nuestra base de datos verificada..."
(la mala suena evasivo)

Ejemplo 5 — Detecta buzón de voz:
Persona: "Hola, no puedo atender, deja tu mensaje después del tono..."
✓ Bot: "Hola doctor, soy SofIA de Lapora. Lo llamamos en otro momento. Buen día."
   → end_call=true, outcome="voicemail"
✗ Bot: continúa con la apertura normal como si fuera persona
"""


def _construir_base_prompt(script_id: str) -> str:
    """Construye la parte ESTÁTICA del system prompt (sin variables del target).

    Cacheable: solo cambia si edits voice_scripts.yaml + llamas _invalidar_cache_prompts().
    """
    if script_id in _base_prompt_cache:
        return _base_prompt_cache[script_id]

    config = cargar_config()
    script = obtener_script(script_id)
    global_cfg = config.get("config_global", {})

    contexto = script.get("contexto_negocio", "").strip()
    objetivos = "\n".join(f"- {o}" for o in script.get("objetivos_del_call", []))
    reglas = "\n".join(f"- {r}" for r in script.get("reglas_comportamiento", []))

    # Objeciones (sin inyectar variables todavía — usaremos placeholders)
    objeciones_txt = ""
    for o in script.get("objeciones", []):
        patrones = ", ".join(f'"{p}"' for p in o.get("patron", []))
        respuesta = o.get("respuesta_modelo", "").strip()
        accion = o.get("siguiente_accion", "")
        objeciones_txt += f"\nSi la persona dice algo como: {patrones}\n"
        objeciones_txt += f"  Tono de respuesta: \"{respuesta}\"\n"
        objeciones_txt += f"  Acción interna: {accion}\n"

    cierres_txt = ""
    for nombre, c in (script.get("cierres") or {}).items():
        despedida = c.get("despedida", "").strip()
        accion = c.get("accion", "")
        cierres_txt += f"\n  - Cierre '{nombre}' (acción: {accion}):\n    \"{despedida}\"\n"

    optout_frases = "\n".join(f'  - "{f}"' for f in global_cfg.get("opt_out_frases", []))

    base = f"""Eres SofIA, asistente virtual por TELÉFONO de Lapora Marketing Digital (Ibagué, Tolima, Colombia).

# CONTEXTO CRÍTICO

Esta es una llamada HABLADA. NO un chat. Reglas inviolables:
1. BREVEDAD: máx 15 palabras por turno (~3 segundos de audio). NUNCA listas largas.
2. NATURALIDAD: español colombiano, "doctor/doctora", tono cálido y profesional.
3. NUNCA EMPUJES: si la persona dice "ocupado" o "no me interesa", respeta de inmediato.
4. NO inventes precios. Solo: Pro $100 USD/mes, Studio $250 USD/mes.
5. NO repitas tu saludo si ya saludaste — sigue la conversación.
6. NO te disculpes 3 veces. Profesionalismo, no sumisión.

{FEW_SHOT_EJEMPLOS}

# CONTEXTO DEL NEGOCIO
{contexto}

# OBJETIVOS DE ESTA LLAMADA
{objetivos}

# REGLAS DE COMPORTAMIENTO (cumplir SIEMPRE)
{reglas}

# OBJECIONES TÍPICAS Y CÓMO RESPONDER
Usa estas respuestas como GUÍA del tono, NO las copies textual. Adáptalas naturalmente.
{objeciones_txt}

# OPT-OUT (terminar llamada PERMANENTE)
Si la persona dice algo similar a:
{optout_frases}
→ activa optout=true, end_call=true, outcome="opt_out"

# CIERRES POSIBLES
{cierres_txt}

# DETECCIÓN DE BUZÓN DE VOZ
Si en el PRIMER turno escuchas: "deja tu mensaje", "después del tono", "buzón", "no se encuentra disponible"
→ NO continúes la apertura. Di un mensaje breve de 5-10 segundos y activa end_call=true outcome="voicemail".

# FORMATO DE RESPUESTA — OBLIGATORIO

Responde SIEMPRE con un objeto JSON puro (sin prefijo de texto, sin ```fences```):

{{
  "respuesta": "Texto a hablar — MÁX 15 palabras",
  "end_call": false,
  "outcome": "",
  "send_whatsapp_summary": false,
  "transfer_to_human": false,
  "optout": false,
  "internal_note": "razonamiento corto (no se habla)"
}}

Validez del JSON:
- `respuesta`: el texto natural a decir. Si es despedida, ya incluye "que tenga buen día" o similar.
- `end_call`: true cuando termina la conversación (cierre, opt-out, voicemail, off-topic).
- `outcome`: si end_call=true → "interested" | "not_interested" | "callback" | "voicemail" | "no_answer" | "opt_out" | "failed".
- `send_whatsapp_summary`: true si seguirá un WhatsApp con info (interested/callback típicamente).
- `transfer_to_human`: true cuando piden hablar con humano o necesitan ayuda especializada.
- `optout`: true cuando piden explícitamente NO ser llamados de nuevo.
- `internal_note`: 1 frase corta con tu razonamiento, útil para auditoría.

# REGLA FINAL
Si dudas, prefiere terminar amablemente y mandar info por WhatsApp antes que insistir.
"""
    _base_prompt_cache[script_id] = base
    return base


def construir_system_prompt(script_id: str, variables: dict) -> str:
    """System prompt completo = base cacheado + sección variables del target.

    Optimizado: el 95% del prompt (~10K chars) viene de cache.
    Solo la sección VARIABLES + APERTURA cambia entre llamadas.
    """
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

    base = _construir_base_prompt(script_id)

    # Sección dinámica: apertura inyectada + identificación del target
    script = obtener_script(script_id)
    apertura = inyectar_variables(script.get("apertura", ""), vars_safe).strip()

    # Resumen del target en una línea — Claude consume esto rápido
    target_summary_partes = []
    if vars_safe["nombre_doctor"] and vars_safe["nombre_doctor"] != "doctor":
        target_summary_partes.append(f"nombre={vars_safe['nombre_doctor']}")
    if vars_safe["especialidad"]:
        target_summary_partes.append(f"especialidad={vars_safe['especialidad']}")
    if vars_safe["nombre_negocio"] and vars_safe["nombre_negocio"] != "su consultorio":
        target_summary_partes.append(f"consultorio={vars_safe['nombre_negocio']}")
    if vars_safe["ciudad"]:
        target_summary_partes.append(f"ciudad={vars_safe['ciudad']}")
    target_summary = " | ".join(target_summary_partes) or "(sin datos del target)"

    seccion_dinamica = f"""
# DATOS DEL TARGET DE ESTA LLAMADA
{target_summary}

# APERTURA EXACTA (usar SOLO en el primer turno, adaptable levemente)
"{apertura}"
"""
    return base + seccion_dinamica


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
    telefono_target: str = "",
    clinica_id: Optional[int] = None,
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

    # System prompt en bloques para aprovechar Anthropic prompt caching:
    # Bloque 1 (cacheable): base + few-shot — idéntico para todos los targets
    # Bloque 2 (no cacheable): variables del target específico
    # Bloque 3 (no cacheable): contexto cross-canal si lo hay
    base_prompt = _construir_base_prompt(script_id)
    seccion_dinamica = construir_system_prompt(script_id, variables)[len(base_prompt):]

    # Memoria cross-canal: chats/llamadas previas con este teléfono
    contexto_previo = ""
    if telefono_target:
        try:
            from agent.contact_history import contexto_para_brain_voz
            contexto_previo = await contexto_para_brain_voz(
                telefono_target, clinica_id=clinica_id
            )
        except Exception as e:
            logger.warning(f"[voice_brain] no se pudo cargar contexto previo: {e}")

    system_blocks = [
        {
            "type": "text",
            "text": base_prompt,
            "cache_control": {"type": "ephemeral"},  # Caching nativo Anthropic (5 min TTL)
        },
        {"type": "text", "text": seccion_dinamica},
    ]
    if contexto_previo:
        system_blocks.append({"type": "text", "text": "\n\n" + contexto_previo})

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
            system=system_blocks,
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

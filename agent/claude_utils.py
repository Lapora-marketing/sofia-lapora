# -*- coding: utf-8 -*-
# agent/claude_utils.py — Helpers compartidos para parsear respuestas de Claude
# Lapora Marketing Digital

"""
Utilidades para procesar respuestas de Claude API.

Antes vivía duplicada en voice_brain.py + voice_outcomes.py + lapora_bot.py.
"""

import json
import re
import logging
from typing import Optional

logger = logging.getLogger("agentkit")


def parsear_json_claude(texto: str, fallback: Optional[dict] = None) -> dict:
    """Extrae un dict JSON de la respuesta de Claude.

    Tolera:
    - JSON puro
    - JSON dentro de ```json ... ``` fences
    - JSON con texto antes/después (busca primer `{` hasta último `}`)

    Args:
        texto: respuesta cruda de Claude
        fallback: dict a devolver si el parseo falla (default: {})

    Returns:
        dict parseado, o `fallback` si no se pudo
    """
    if not texto:
        return fallback or {}

    # Caso 1: JSON dentro de ```json ... ``` o ``` ... ```
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", texto, re.DOTALL)
    if m:
        candidato = m.group(1)
    else:
        # Caso 2: primer `{` hasta último `}` (tolera texto preliminar)
        start = texto.find("{")
        end = texto.rfind("}")
        if start >= 0 and end > start:
            candidato = texto[start:end + 1]
        else:
            return fallback or {}

    try:
        return json.loads(candidato)
    except json.JSONDecodeError as e:
        logger.warning(f"[claude_utils] JSON inválido: {e}. Texto[:200]: {candidato[:200]}")
        return fallback or {}

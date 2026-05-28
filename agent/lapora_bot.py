# -*- coding: utf-8 -*-
# agent/lapora_bot.py — Lapora Bot: asistente conversacional del sitio web
# Lapora Marketing Digital

"""
Lapora Bot es el chatbot público que vive como widget flotante en TODAS las
webs de Lapora (lapora.studio principal + clinic.lapora.studio).

Su trabajo:
1. Responder dudas de visitantes sobre los servicios de Lapora
2. Recomendar el servicio correcto según el problema del visitante
3. Devolver "chips" de navegación con links sugeridos
4. Capturar leads (nombre + WhatsApp) cuando el visitante está interesado
5. NUNCA inventar precios o features fuera del system prompt

Endpoint: POST /lapora-bot/chat
- CORS habilitado para lapora.studio + clinic.lapora.studio
- Acepta {message: str, history: [{role, content}]}
- Retorna {respuesta: str, chips: [{label, url}], lead_captured: bool}
"""

import os
import json
import logging
from typing import Optional
from datetime import datetime
from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from anthropic import AsyncAnthropic
from dotenv import load_dotenv

load_dotenv(override=True)
logger = logging.getLogger("agentkit")

router = APIRouter(prefix="/lapora-bot", tags=["lapora-bot"])

_client: Optional[AsyncAnthropic] = None


def _get_client() -> AsyncAnthropic:
    global _client
    if _client is None:
        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY no configurada")
        _client = AsyncAnthropic(api_key=api_key)
    return _client


MODELO = "claude-sonnet-4-6"
MAX_TOKENS = 500   # Mensajes cortos, conversacionales
MAX_HISTORIAL = 12  # Últimos 12 turnos


# ════════════════════════════════════════════════════════════
# KNOWLEDGE BASE — Todo lo que el bot sabe sobre Lapora
# ════════════════════════════════════════════════════════════

SYSTEM_PROMPT = """Eres **Lapora Bot**, el asistente virtual oficial de Lapora Marketing Digital.

## TU IDENTIDAD
- Te llamas Lapora Bot
- Trabajas para Lapora Marketing Digital (agencia colombiana con base en Ibagué, Tolima)
- Tu tono: cálido, profesional, breve, colombiano
- Hablas SIEMPRE en español
- Tratas a los visitantes de "tú" por defecto (más cercano)

## QUÉ HACE LAPORA — Servicios y productos

Lapora tiene DOS líneas de negocio:

### 1. AGENCIA DE MARKETING DIGITAL (lapora.studio)
Lapora ayuda a negocios colombianos (sobre todo Ibagué y Tolima) a crecer con:
- **Marketing digital integral**: estrategia + ejecución
- **SEO local**: posicionar negocios en Google de su ciudad
- **Contenido para redes sociales**: Instagram, TikTok, Facebook
- **Diseño web**: sitios profesionales que convierten
- **Branding**: identidad visual completa
- **Producción de video**: comerciales, reels, testimoniales
- **Publicidad paga**: Meta Ads, Google Ads
- **Mentorías 1 a 1**: para creativos y negocios que quieren escalar

**Para quién es la agencia:** Negocios establecidos (mínimo 6 meses operando) que ya facturan pero quieren crecer.

### 2. LAPORA CLINIC — SaaS para consultorios médicos (en /clinic/landing)
Software multicanal que automatiza el WhatsApp + Instagram + agenda de clínicas y consultorios.

**Para quién:** Médicos premium (cirujanos plásticos, odontólogos, dermatólogos, especialistas).

**Planes:**
- **PRO — $100 USD/mes** (~$400.000 COP):
  - Pacientes ilimitados
  - WhatsApp + Instagram + Email unificados
  - IA SofIA responde 24/7 automáticamente
  - 5 usuarios del equipo
  - Recordatorios automáticos 24h y 2h antes de citas
  - Google Calendar + Google Sheets sync
  - Plantillas, agenda, llamadas
  - 14 días de prueba gratis

- **STUDIO — $250 USD/mes** (~$1.000.000 COP):
  - Todo lo de Pro
  - Usuarios ilimitados
  - White-label (tu marca, no la de Lapora)
  - Dominio propio (tuclinica.com)
  - API custom para integrar tus sistemas
  - Analytics avanzado + ROI por canal
  - Detección de pacientes en riesgo de fuga
  - Soporte 24/7 dedicado

## SECCIONES DE LA WEB lapora.studio (ENVÍA CHIPS PARA NAVEGAR)
Cuando recomiendes algo, devuelve un "chip" con el link. Las anclas disponibles:
- `#hero` — inicio
- `#problema` — el problema que resolvemos
- `#servicios` — lista de servicios
- `#porque` — por qué elegir Lapora
- `#paquetes` — paquetes y precios de la agencia
- `#proceso` — cómo trabajamos
- `#casos` — casos de éxito
- `#clinic` — sección Lapora Clinic SaaS
- `#cta` — contactar / contratar

Y rutas reales:
- `/clinic/landing` — landing completa del SaaS Lapora Clinic
- `/clinic/registro` — empezar 14 días gratis del SaaS
- `/clinic/login` — login para clínicas existentes
- `https://wa.me/573228783019` — WhatsApp directo de Lapora

## CONTACTO
- **WhatsApp Lapora:** +57 322 878 3019 (también `wa.me/573228783019`)
- **Email:** hola@lapora.studio
- **Ubicación:** Ibagué, Tolima, Colombia
- **Horario:** Lunes a viernes 8am-6pm

## REGLAS CRÍTICAS

1. **Respuestas BREVES** (máx 2-3 frases por turno). Es un chat, no un artículo.

2. **Recomienda con criterio**:
   - Si pregunta por servicios para CRECER su negocio → recomienda Agencia
   - Si es médico/dentista/clínica → recomienda Lapora Clinic SaaS
   - Si no estás seguro → pregunta una vez antes de recomendar

3. **NUNCA inventes precios o features** que no estén arriba. Si te preguntan precio de un servicio de agencia, di: "Los planes varían según necesidad. ¿Quieres que te conecte con un asesor por WhatsApp?"

4. **Cuando detectes interés real** (frases como "quiero contratar", "cuánto cuesta", "necesito ayuda con X"):
   - Ofrece chip de WhatsApp `https://wa.me/573228783019`
   - O sugiérele dejar nombre + WhatsApp para que un asesor le escriba

5. **AL TERMINAR TU RESPUESTA**, si aplica, agrega chips de navegación al final usando este formato EXACTO:

```
[CHIPS]
{"label": "Ver Lapora Clinic", "url": "/clinic/landing"}
{"label": "Hablar por WhatsApp", "url": "https://wa.me/573228783019"}
[/CHIPS]
```

Solo agrega chips cuando ayuden al visitante. Máximo 3 chips. Si no hay chips útiles, omite el bloque completo.

6. **Lapora Clinic NO está disponible para consultorios fuera de Colombia por ahora.**

7. Si te preguntan algo que no sabes, di: "Buena pregunta, déjame conectarte con un asesor" y ofrece el WhatsApp.

---
RECUERDA: Eres Lapora Bot. Breve. Cálido. Profesional. Recomienda con criterio. Chips solo cuando ayuden."""


# ════════════════════════════════════════════════════════════
# MODELO PYDANTIC PARA REQUEST/RESPONSE
# ════════════════════════════════════════════════════════════

class MensajeChat(BaseModel):
    role: str = Field(..., pattern="^(user|assistant)$")
    content: str = Field(..., max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)
    history: list[MensajeChat] = Field(default_factory=list, max_length=20)


class Chip(BaseModel):
    label: str
    url: str


class ChatResponse(BaseModel):
    respuesta: str
    chips: list[Chip] = Field(default_factory=list)


# ════════════════════════════════════════════════════════════
# PARSER DE CHIPS — Extrae bloques [CHIPS]...[/CHIPS] del texto
# ════════════════════════════════════════════════════════════

def parsear_respuesta_con_chips(texto_crudo: str) -> tuple[str, list[Chip]]:
    """Separa el texto limpio de los chips JSON que Claude devuelve al final."""
    import re

    chips_match = re.search(r"\[CHIPS\](.*?)\[/CHIPS\]", texto_crudo, re.DOTALL)
    if not chips_match:
        return texto_crudo.strip(), []

    bloque_chips = chips_match.group(1).strip()
    texto_limpio = re.sub(r"\[CHIPS\].*?\[/CHIPS\]", "", texto_crudo, flags=re.DOTALL).strip()

    chips: list[Chip] = []
    for linea in bloque_chips.split("\n"):
        linea = linea.strip()
        if not linea or not linea.startswith("{"):
            continue
        try:
            data = json.loads(linea)
            label = (data.get("label") or "").strip()[:60]
            url = (data.get("url") or "").strip()[:300]
            if label and url:
                chips.append(Chip(label=label, url=url))
        except (json.JSONDecodeError, ValueError):
            continue

    return texto_limpio, chips[:3]


# ════════════════════════════════════════════════════════════
# ENDPOINT PRINCIPAL
# ════════════════════════════════════════════════════════════

@router.post("/chat")
async def chat_endpoint(req: ChatRequest, request: Request):
    """Endpoint principal del Lapora Bot.

    Recibe el mensaje del visitante + historial corto.
    Retorna respuesta de Claude + chips de navegación.
    """
    # Validar API key disponible
    try:
        client = _get_client()
    except ValueError as e:
        logger.error(f"[lapora_bot] {e}")
        return JSONResponse(
            status_code=503,
            content={
                "respuesta": "Estoy teniendo un problema técnico. Escríbenos por WhatsApp +57 322 878 3019.",
                "chips": [{"label": "Abrir WhatsApp", "url": "https://wa.me/573228783019"}],
            },
        )

    # Limitar historial al máximo razonable
    historial = req.history[-MAX_HISTORIAL:]

    # Construir mensajes para Claude
    mensajes = [{"role": m.role, "content": m.content} for m in historial]
    mensajes.append({"role": "user", "content": req.message[:1000]})

    # Log básico (sin contenido PII)
    origen = request.headers.get("origin", "unknown")[:80]
    logger.info(f"[lapora_bot] msg de {origen} len={len(req.message)} hist={len(historial)}")

    try:
        response = await client.messages.create(
            model=MODELO,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            messages=mensajes,
        )

        texto_partes = []
        for bloque in response.content:
            if bloque.type == "text":
                texto_partes.append(bloque.text)
        texto_crudo = "\n".join(texto_partes).strip()

        if not texto_crudo:
            texto_crudo = "Disculpa, no logré procesar eso. ¿Puedes reformular tu pregunta?"

        respuesta_limpia, chips = parsear_respuesta_con_chips(texto_crudo)

        logger.info(
            f"[lapora_bot] resp in={response.usage.input_tokens} "
            f"out={response.usage.output_tokens} chips={len(chips)}"
        )

        return ChatResponse(respuesta=respuesta_limpia, chips=chips)

    except Exception as e:
        logger.error(f"[lapora_bot] error Claude: {e}", exc_info=True)
        return ChatResponse(
            respuesta="Estoy teniendo un problema técnico. Por favor escríbenos por WhatsApp.",
            chips=[Chip(label="WhatsApp Lapora", url="https://wa.me/573228783019")],
        )


@router.get("/health")
async def health():
    """Health check del bot."""
    return {"status": "ok", "service": "lapora-bot"}


# ════════════════════════════════════════════════════════════
# WIDGET — JavaScript self-contained que se embebe en cualquier sitio
# ════════════════════════════════════════════════════════════

WIDGET_JS = r"""// Lapora Bot Widget — Self-contained
// Embed: <script src="https://sofia-lapora-production.up.railway.app/lapora-bot/widget.js"></script>
(function() {
  if (window.__laporaBotLoaded) return;
  window.__laporaBotLoaded = true;

  var API_URL = 'https://sofia-lapora-production.up.railway.app/lapora-bot/chat';
  var STORAGE_KEY = 'laporabot_v1';
  var WELCOME_MSG = '¡Hola! Soy Lapora Bot. ¿En qué te puedo ayudar? Pregúntame por servicios, precios o navegación 😊';

  // === Estilos inyectados ===
  var css = `
    .lpbot-bubble {
      position: fixed; bottom: 22px; right: 22px; z-index: 999999;
      width: 60px; height: 60px; border-radius: 50%;
      background: linear-gradient(135deg, #FF3B30, #E8302A);
      color: white; cursor: pointer; border: none;
      box-shadow: 0 8px 24px rgba(255,59,48,0.4), 0 2px 8px rgba(0,0,0,0.15);
      display: flex; align-items: center; justify-content: center;
      transition: transform 0.2s cubic-bezier(0.34, 1.56, 0.64, 1);
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    }
    .lpbot-bubble:hover { transform: scale(1.08); }
    .lpbot-bubble svg { width: 28px; height: 28px; fill: white; }
    .lpbot-bubble .lpbot-dot {
      position: absolute; top: 4px; right: 4px;
      width: 14px; height: 14px; border-radius: 50%;
      background: #10B981; border: 2px solid white;
      animation: lpbot-pulse 2s infinite;
    }
    @keyframes lpbot-pulse {
      0%, 100% { transform: scale(1); opacity: 1; }
      50% { transform: scale(1.15); opacity: 0.8; }
    }
    .lpbot-panel {
      position: fixed; bottom: 96px; right: 22px; z-index: 999998;
      width: 380px; max-width: calc(100vw - 32px);
      height: 560px; max-height: calc(100vh - 130px);
      background: white; border-radius: 18px;
      box-shadow: 0 20px 50px rgba(0,0,0,0.25), 0 4px 16px rgba(0,0,0,0.08);
      display: none; flex-direction: column; overflow: hidden;
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
      transform-origin: bottom right;
      animation: lpbot-pop 0.25s cubic-bezier(0.34, 1.56, 0.64, 1);
    }
    @keyframes lpbot-pop {
      0% { transform: scale(0.7) translateY(20px); opacity: 0; }
      100% { transform: scale(1) translateY(0); opacity: 1; }
    }
    .lpbot-panel.open { display: flex; }
    .lpbot-header {
      background: linear-gradient(135deg, #FF3B30, #C0261F);
      color: white; padding: 16px 18px;
      display: flex; align-items: center; gap: 12px;
    }
    .lpbot-header-avatar {
      width: 38px; height: 38px; border-radius: 50%;
      background: white; color: #FF3B30;
      display: flex; align-items: center; justify-content: center;
      font-weight: 800; font-size: 18px; flex-shrink: 0;
    }
    .lpbot-header-text { flex: 1; min-width: 0; }
    .lpbot-header-title { font-weight: 700; font-size: 15px; margin: 0; }
    .lpbot-header-sub { font-size: 11px; opacity: 0.9; display: flex; align-items: center; gap: 6px; }
    .lpbot-header-sub::before {
      content: ''; width: 8px; height: 8px; border-radius: 50%;
      background: #10B981; display: inline-block;
      box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5);
      animation: lpbot-pulse-dot 2s infinite;
    }
    @keyframes lpbot-pulse-dot {
      0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.5); }
      70% { box-shadow: 0 0 0 8px rgba(16, 185, 129, 0); }
      100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
    }
    .lpbot-close {
      background: rgba(255,255,255,0.15); border: none; color: white;
      width: 30px; height: 30px; border-radius: 50%;
      cursor: pointer; font-size: 16px; line-height: 1;
      display: flex; align-items: center; justify-content: center;
    }
    .lpbot-close:hover { background: rgba(255,255,255,0.25); }
    .lpbot-messages {
      flex: 1; overflow-y: auto; padding: 16px;
      background: #F9FAFB; display: flex; flex-direction: column; gap: 10px;
    }
    .lpbot-msg {
      max-width: 85%; padding: 10px 14px; border-radius: 14px;
      font-size: 14px; line-height: 1.5; word-wrap: break-word;
    }
    .lpbot-msg-bot {
      background: white; color: #111827; border: 1px solid #E5E7EB;
      align-self: flex-start; border-bottom-left-radius: 4px;
    }
    .lpbot-msg-user {
      background: #FF3B30; color: white;
      align-self: flex-end; border-bottom-right-radius: 4px;
    }
    .lpbot-msg strong { font-weight: 700; }
    .lpbot-chips {
      display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px;
      align-self: flex-start; max-width: 90%;
    }
    .lpbot-chip {
      background: white; border: 1px solid #FF3B30;
      color: #FF3B30; padding: 6px 12px; border-radius: 16px;
      font-size: 12px; font-weight: 600; cursor: pointer;
      text-decoration: none; display: inline-flex; align-items: center; gap: 4px;
      transition: all 0.15s ease;
    }
    .lpbot-chip:hover { background: #FF3B30; color: white; }
    .lpbot-typing {
      align-self: flex-start; padding: 12px 16px;
      background: white; border: 1px solid #E5E7EB;
      border-radius: 14px; border-bottom-left-radius: 4px;
    }
    .lpbot-typing span {
      display: inline-block; width: 6px; height: 6px;
      background: #9CA3AF; border-radius: 50%; margin: 0 1px;
      animation: lpbot-typing 1.4s infinite ease-in-out;
    }
    .lpbot-typing span:nth-child(2) { animation-delay: 0.2s; }
    .lpbot-typing span:nth-child(3) { animation-delay: 0.4s; }
    @keyframes lpbot-typing {
      0%, 60%, 100% { opacity: 0.3; transform: translateY(0); }
      30% { opacity: 1; transform: translateY(-3px); }
    }
    .lpbot-input-area {
      border-top: 1px solid #E5E7EB; padding: 12px;
      background: white; display: flex; gap: 8px;
    }
    .lpbot-input {
      flex: 1; border: 1px solid #E5E7EB; border-radius: 22px;
      padding: 10px 14px; font-size: 14px; outline: none;
      font-family: inherit; transition: border-color 0.15s;
    }
    .lpbot-input:focus { border-color: #FF3B30; }
    .lpbot-send {
      background: #FF3B30; color: white; border: none;
      width: 40px; height: 40px; border-radius: 50%;
      cursor: pointer; display: flex; align-items: center; justify-content: center;
      flex-shrink: 0; transition: transform 0.15s;
    }
    .lpbot-send:hover { transform: scale(1.05); }
    .lpbot-send:disabled { opacity: 0.5; cursor: not-allowed; }
    .lpbot-send svg { width: 18px; height: 18px; fill: white; }
    .lpbot-footer {
      text-align: center; font-size: 10px; color: #9CA3AF;
      padding: 6px 0 8px 0; background: white;
    }
    @media (max-width: 480px) {
      .lpbot-panel {
        right: 8px; left: 8px; width: auto; max-width: none;
        bottom: 84px; height: calc(100vh - 100px);
      }
      .lpbot-bubble { right: 14px; bottom: 14px; }
    }
  `;
  var styleEl = document.createElement('style');
  styleEl.textContent = css;
  document.head.appendChild(styleEl);

  // === HTML ===
  var container = document.createElement('div');
  container.innerHTML = `
    <button class="lpbot-bubble" id="lpbot-bubble" aria-label="Abrir chat de Lapora">
      <span class="lpbot-dot"></span>
      <svg viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zM7 9h10v2H7V9zm7 5H7v-2h7v2zm3-6H7V6h10v2z"/></svg>
    </button>
    <div class="lpbot-panel" id="lpbot-panel" role="dialog" aria-label="Chat Lapora Bot">
      <div class="lpbot-header">
        <div class="lpbot-header-avatar">L</div>
        <div class="lpbot-header-text">
          <p class="lpbot-header-title">Lapora Bot</p>
          <p class="lpbot-header-sub">En línea · responde al instante</p>
        </div>
        <button class="lpbot-close" id="lpbot-close" aria-label="Cerrar">✕</button>
      </div>
      <div class="lpbot-messages" id="lpbot-messages"></div>
      <div class="lpbot-input-area">
        <input class="lpbot-input" id="lpbot-input" type="text" placeholder="Escribe tu pregunta..." maxlength="800" autocomplete="off">
        <button class="lpbot-send" id="lpbot-send" aria-label="Enviar">
          <svg viewBox="0 0 24 24"><path d="M2.01 21L23 12 2.01 3 2 10l15 2-15 2z"/></svg>
        </button>
      </div>
      <div class="lpbot-footer">Powered by Lapora · IA</div>
    </div>
  `;
  document.body.appendChild(container);

  // === Estado ===
  var bubble = document.getElementById('lpbot-bubble');
  var panel = document.getElementById('lpbot-panel');
  var closeBtn = document.getElementById('lpbot-close');
  var messagesEl = document.getElementById('lpbot-messages');
  var input = document.getElementById('lpbot-input');
  var sendBtn = document.getElementById('lpbot-send');
  var historial = [];
  var loading = false;

  // Cargar historial de localStorage
  try {
    var saved = localStorage.getItem(STORAGE_KEY);
    if (saved) {
      var data = JSON.parse(saved);
      if (data.historial && Array.isArray(data.historial)) {
        historial = data.historial.slice(-12);
      }
    }
  } catch(e) {}

  // === Render ===
  function escapeHTML(s) {
    return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
  }

  function renderBold(s) {
    // Convertir **texto** en <strong>texto</strong>
    return escapeHTML(s).replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>').replace(/\n/g, '<br>');
  }

  function addMessage(role, text, chips) {
    var div = document.createElement('div');
    div.className = 'lpbot-msg ' + (role === 'user' ? 'lpbot-msg-user' : 'lpbot-msg-bot');
    div.innerHTML = renderBold(text);
    messagesEl.appendChild(div);

    if (chips && chips.length) {
      var chipsWrap = document.createElement('div');
      chipsWrap.className = 'lpbot-chips';
      chips.forEach(function(c) {
        var a = document.createElement('a');
        a.className = 'lpbot-chip';
        a.textContent = c.label;
        a.href = c.url;
        if (c.url.indexOf('http') === 0 || c.url.indexOf('wa.me') !== -1) {
          a.target = '_blank';
          a.rel = 'noopener';
        }
        chipsWrap.appendChild(a);
      });
      messagesEl.appendChild(chipsWrap);
    }
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function showTyping() {
    var div = document.createElement('div');
    div.className = 'lpbot-typing';
    div.id = 'lpbot-typing-indicator';
    div.innerHTML = '<span></span><span></span><span></span>';
    messagesEl.appendChild(div);
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }
  function hideTyping() {
    var t = document.getElementById('lpbot-typing-indicator');
    if (t) t.remove();
  }

  function persist() {
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify({historial: historial.slice(-12)})); } catch(e) {}
  }

  function restoreMessages() {
    messagesEl.innerHTML = '';
    if (historial.length === 0) {
      addMessage('assistant', WELCOME_MSG, [
        {label: '¿Qué hace Lapora?', url: '#'},
        {label: 'Ver Lapora Clinic', url: '/clinic/landing'},
      ]);
    } else {
      historial.forEach(function(m) {
        addMessage(m.role, m.content, m.chips || []);
      });
    }
  }

  // === API call ===
  function send(text) {
    if (!text || loading) return;
    loading = true;
    sendBtn.disabled = true;

    addMessage('user', text);
    historial.push({role: 'user', content: text});
    showTyping();

    // Historial para API (sin chips, solo role+content)
    var apiHist = historial.slice(0, -1).map(function(m) {
      return {role: m.role, content: m.content};
    });

    fetch(API_URL, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message: text, history: apiHist}),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      hideTyping();
      var respuesta = data.respuesta || 'Disculpa, no logré procesar eso.';
      var chips = data.chips || [];
      addMessage('assistant', respuesta, chips);
      historial.push({role: 'assistant', content: respuesta, chips: chips});
      persist();
    })
    .catch(function(e) {
      hideTyping();
      addMessage('assistant', 'Tuve un problema técnico. Por favor escríbenos por WhatsApp.', [
        {label: 'WhatsApp', url: 'https://wa.me/573228783019'},
      ]);
    })
    .finally(function() {
      loading = false;
      sendBtn.disabled = false;
      input.focus();
    });
  }

  // === Eventos ===
  bubble.addEventListener('click', function() {
    panel.classList.toggle('open');
    if (panel.classList.contains('open')) {
      if (messagesEl.children.length === 0) restoreMessages();
      setTimeout(function() { input.focus(); }, 100);
    }
  });
  closeBtn.addEventListener('click', function() { panel.classList.remove('open'); });
  sendBtn.addEventListener('click', function() {
    var t = input.value.trim();
    if (!t) return;
    input.value = '';
    send(t);
  });
  input.addEventListener('keydown', function(e) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendBtn.click();
    }
  });
  // ESC cierra
  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape' && panel.classList.contains('open')) panel.classList.remove('open');
  });
})();
"""


@router.get("/widget.js")
async def widget_js():
    """Sirve el JS del widget. Una sola fuente de verdad para todos los sitios."""
    from fastapi.responses import Response
    return Response(
        content=WIDGET_JS,
        media_type="application/javascript; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=300",  # 5 min cache
            "Access-Control-Allow-Origin": "*",
        },
    )

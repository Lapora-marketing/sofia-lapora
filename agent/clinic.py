# -*- coding: utf-8 -*-
# agent/clinic.py — Router de Lapora Clinic (SaaS multi-tenant)
# Lapora Marketing Digital

"""
Rutas del producto SaaS Lapora Clinic — separado del CRM interno de SofIA.

URLs publicas:
  /clinic/                  → landing redirige a login
  /clinic/registro          → onboarding (crear nueva clinica)
  /clinic/login             → login de clinica existente

URLs privadas (requieren sesion):
  /clinic/app/              → dashboard
  /clinic/app/inbox         → inbox unificado WhatsApp+IG+Email
  /clinic/app/pacientes     → CRUD de pacientes
  /clinic/app/llamadas      → bitacora de llamadas
  /clinic/app/plantillas    → respuestas rapidas
  /clinic/app/configuracion → integraciones (WhatsApp, IG, Sheets)
"""

import os
import html
import logging
import secrets
from datetime import datetime
from typing import Optional

logger = logging.getLogger("agentkit")
from fastapi import APIRouter, Depends, Request, Form, HTTPException, Cookie, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func, or_, desc

from agent.memory import async_session
from agent.clinic_models import (
    Clinica, UsuarioClinic, Paciente, MensajeUnificado,
    Llamada, CitaClinic, PlantillaRespuesta, InvitacionUsuario,
    crear_clinica, autenticar_usuario, obtener_clinica,
    cargar_demo_data, hash_password,
    limite_usuarios, contar_usuarios_clinica,
    puede_invitar_usuario, crear_invitacion, consumir_invitacion,
)
from io import StringIO
import csv as _csv_mod


def get_sa_email() -> str:
    """Devuelve el email del Service Account para que las clínicas lo compartan."""
    try:
        from agent.clinic_calendar import obtener_email_service_account
        email = obtener_email_service_account()
        return email or "service-account@lapora.iam.gserviceaccount.com"
    except Exception:
        return "service-account@lapora.iam.gserviceaccount.com"


router = APIRouter(prefix="/clinic", tags=["clinic"])

# Sesiones en memoria (MVP — para prod usar Redis o DB)
# session_token → {usuario_id, clinica_id, expira}
SESSIONS: dict[str, dict] = {}


# ════════════════════════════════════════════════════════════
# Helpers de sesion
# ════════════════════════════════════════════════════════════

def crear_sesion(usuario: UsuarioClinic) -> str:
    """Crea token de sesion y lo registra."""
    token = secrets.token_urlsafe(32)
    SESSIONS[token] = {
        "usuario_id": usuario.id,
        "clinica_id": usuario.clinica_id,
        "email": usuario.email,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
    }
    return token


def obtener_sesion(token: Optional[str]) -> Optional[dict]:
    if not token or token not in SESSIONS:
        return None
    return SESSIONS[token]


async def requerir_login(clinic_session: Optional[str] = Cookie(None)) -> dict:
    """Dependency que valida sesion activa. Si no, lanza 401."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        raise HTTPException(
            status_code=302,
            detail="No autenticado",
            headers={"Location": "/clinic/login"},
        )
    return sesion


# ════════════════════════════════════════════════════════════
# CSS / Estilos compartidos
# ════════════════════════════════════════════════════════════

CSS_CLINIC = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700;9..40,800&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
  /* ═══════════════════════════════════════════════════════════
     LAPORA CLINIC — PREMIUM DESIGN SYSTEM v2
     Inspirado en Linear · Stripe · Notion · Vercel
  ═══════════════════════════════════════════════════════════ */

  *, *::before, *::after { margin:0; padding:0; box-sizing:border-box; }
  html { scroll-behavior: smooth; -webkit-text-size-adjust: 100%; }

  :root {
    /* ── BRAND ── */
    --primary:        #FF3B30;
    --primary-50:     #FFF5F4;
    --primary-100:    #FFE5E3;
    --primary-200:    #FFCBC7;
    --primary-300:    #FFA5A0;
    --primary-500:    #FF3B30;
    --primary-600:    #E63227;
    --primary-700:    #C0261F;
    --primary-glow:   rgba(255,59,48,0.18);

    /* ── NEUTRAL (warm stone) ── */
    --bg:             #FAFAF9;
    --bg-soft:        #F5F5F4;
    --surface:        #FFFFFF;
    --surface-2:      #FAFAF9;
    --text:           #0C0A09;
    --text-1:         #1C1917;
    --text-2:         #44403C;
    --text-3:         #78716C;
    --text-4:         #A8A29E;
    --border:         #E7E5E4;
    --border-strong:  #D6D3D1;
    --divider:        #F0EFEE;

    /* ── SEMANTIC ── */
    --success:        #10B981;
    --success-bg:     #D1FAE5;
    --warning:        #F59E0B;
    --warning-bg:     #FEF3C7;
    --danger:         #EF4444;
    --danger-bg:      #FEE2E2;
    --info:           #3B82F6;
    --info-bg:        #DBEAFE;

    /* ── ELEVATION (multi-layer, Linear-style) ── */
    --shadow-xs:  0 1px 2px rgba(28,25,23,0.04);
    --shadow-sm:  0 1px 2px rgba(28,25,23,0.04), 0 1px 3px rgba(28,25,23,0.06);
    --shadow-md:  0 4px 6px -1px rgba(28,25,23,0.05), 0 2px 4px -2px rgba(28,25,23,0.04);
    --shadow-lg:  0 10px 15px -3px rgba(28,25,23,0.08), 0 4px 6px -4px rgba(28,25,23,0.04);
    --shadow-xl:  0 20px 25px -5px rgba(28,25,23,0.1), 0 8px 10px -6px rgba(28,25,23,0.04);
    --shadow-2xl: 0 25px 50px -12px rgba(28,25,23,0.18);
    --shadow-focus: 0 0 0 3px rgba(255,59,48,0.18);

    /* ── RADII ── */
    --r-sm: 6px; --r-md: 8px; --r-lg: 12px; --r-xl: 16px; --r-2xl: 20px; --r-full: 9999px;

    /* ── EASING & DURATION (spring physics) ── */
    --ease-out:    cubic-bezier(0.16, 1, 0.3, 1);
    --ease-spring: cubic-bezier(0.34, 1.56, 0.64, 1);
    --ease-in:     cubic-bezier(0.7, 0, 0.84, 0);
    --t-fast:   140ms;
    --t-med:    220ms;
    --t-slow:   400ms;

    /* ── TYPOGRAPHY ── */
    --font-sans: 'DM Sans', 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
    --font-mono: 'JetBrains Mono', 'SF Mono', Menlo, monospace;
  }

  /* ── RESET + BASE ── */
  body {
    font-family: var(--font-sans);
    background: var(--bg);
    color: var(--text-1);
    font-size: 14px;
    line-height: 1.5;
    letter-spacing: -0.005em;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
    font-feature-settings: 'cv11', 'ss01';
    text-rendering: optimizeLegibility;
  }

  /* Scrollbar premium */
  ::-webkit-scrollbar { width: 10px; height: 10px; }
  ::-webkit-scrollbar-track { background: transparent; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 8px; border: 2px solid var(--bg); }
  ::-webkit-scrollbar-thumb:hover { background: var(--border-strong); }

  /* Selección de texto */
  ::selection { background: var(--primary-100); color: var(--primary-700); }

  /* Headings — DM Sans, tight tracking */
  h1, h2, h3, h4, h5 { font-family: var(--font-sans); letter-spacing: -0.025em; line-height: 1.2; color: var(--text-1); font-weight: 700; }

  a { color: var(--primary); text-decoration: none; transition: color var(--t-fast) var(--ease-out); }
  a:hover { color: var(--primary-700); }

  code, .mono { font-family: var(--font-mono); font-size: 0.92em; }

  /* Focus ring premium */
  *:focus { outline: none; }
  *:focus-visible {
    outline: none;
    box-shadow: var(--shadow-focus);
    border-radius: var(--r-md);
  }
  @media (prefers-reduced-motion: reduce) {
    *, *::before, *::after { animation: none !important; transition: none !important; }
  }

  /* ═══════════════════════════════════════════════════════════
     BUTTONS
  ═══════════════════════════════════════════════════════════ */
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: 8px;
    padding: 10px 18px;
    border-radius: var(--r-md);
    font-family: var(--font-sans);
    font-size: 13.5px;
    font-weight: 600;
    letter-spacing: -0.01em;
    border: 1px solid transparent;
    cursor: pointer;
    text-decoration: none;
    white-space: nowrap;
    user-select: none;
    transition: transform var(--t-fast) var(--ease-out),
                background var(--t-fast) var(--ease-out),
                box-shadow var(--t-fast) var(--ease-out),
                border-color var(--t-fast) var(--ease-out);
  }
  .btn:active { transform: scale(0.97); }
  .btn:focus-visible { box-shadow: var(--shadow-focus); }

  .btn-primary {
    background: linear-gradient(180deg, #FF4F44 0%, var(--primary) 100%);
    color: white;
    box-shadow: 0 1px 0 rgba(255,255,255,0.18) inset, 0 1px 2px rgba(192,38,31,0.4), 0 4px 12px rgba(255,59,48,0.25);
  }
  .btn-primary:hover {
    background: linear-gradient(180deg, #FF4F44 0%, var(--primary-600) 100%);
    color: white;
    box-shadow: 0 1px 0 rgba(255,255,255,0.18) inset, 0 2px 4px rgba(192,38,31,0.4), 0 8px 20px rgba(255,59,48,0.35);
    transform: translateY(-1px);
  }
  .btn-primary:active { transform: translateY(0) scale(0.97); }

  .btn-ghost {
    background: var(--surface);
    color: var(--text-1);
    border-color: var(--border);
    box-shadow: var(--shadow-xs);
  }
  .btn-ghost:hover {
    background: var(--bg-soft);
    color: var(--text);
    border-color: var(--border-strong);
    box-shadow: var(--shadow-sm);
  }

  .btn-sm  { padding: 7px 12px; font-size: 12.5px; gap: 6px; }
  .btn-lg  { padding: 13px 24px; font-size: 14.5px; }
  .btn-icon { padding: 8px; width: 36px; height: 36px; }

  button:disabled, .btn:disabled, .btn[disabled] {
    opacity: 0.5; cursor: not-allowed; pointer-events: none;
  }

  /* ═══════════════════════════════════════════════════════════
     CARDS
  ═══════════════════════════════════════════════════════════ */
  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-xl);
    padding: 24px;
    box-shadow: var(--shadow-xs);
    transition: box-shadow var(--t-med) var(--ease-out),
                transform var(--t-med) var(--ease-out),
                border-color var(--t-fast) var(--ease-out);
  }
  .card-hover { cursor: pointer; }
  .card-hover:hover {
    box-shadow: var(--shadow-md);
    border-color: var(--border-strong);
    transform: translateY(-2px);
  }
  .card-flat { box-shadow: none; }

  /* ═══════════════════════════════════════════════════════════
     INPUTS / FORMS
  ═══════════════════════════════════════════════════════════ */
  .input, textarea.input, select.input {
    width: 100%;
    padding: 10px 14px;
    border: 1px solid var(--border);
    border-radius: var(--r-md);
    font-family: var(--font-sans);
    font-size: 14px;
    color: var(--text-1);
    background: var(--surface);
    outline: none;
    transition: border-color var(--t-fast) var(--ease-out),
                box-shadow var(--t-fast) var(--ease-out),
                background var(--t-fast) var(--ease-out);
  }
  .input::placeholder { color: var(--text-4); }
  .input:hover { border-color: var(--border-strong); }
  .input:focus {
    border-color: var(--primary);
    box-shadow: var(--shadow-focus);
  }
  .input:disabled { background: var(--bg-soft); color: var(--text-3); cursor: not-allowed; }
  textarea.input { resize: vertical; min-height: 80px; line-height: 1.55; }

  label.field-label {
    display: block; font-size: 12.5px; font-weight: 600;
    color: var(--text-2); margin-bottom: 6px; letter-spacing: -0.005em;
  }

  /* ═══════════════════════════════════════════════════════════
     LAYOUT (sidebar + main)
  ═══════════════════════════════════════════════════════════ */
  .app-wrap {
    display: grid;
    grid-template-columns: 248px 1fr;
    min-height: 100vh;
    background: var(--bg);
  }
  .sidebar {
    background: var(--surface);
    border-right: 1px solid var(--border);
    padding: 18px 12px;
    display: flex;
    flex-direction: column;
    position: sticky;
    top: 0;
    height: 100vh;
    overflow-y: auto;
  }
  .brand {
    display: flex; align-items: center; gap: 10px;
    padding: 6px 10px 18px;
    border-bottom: 1px solid var(--divider);
  }
  .brand-logo {
    width: 36px; height: 36px;
    background: linear-gradient(135deg, #FF4F44, var(--primary));
    border-radius: var(--r-md);
    color: white;
    font-family: var(--font-sans);
    font-weight: 800; font-size: 17px;
    display: flex; align-items: center; justify-content: center;
    box-shadow: 0 1px 0 rgba(255,255,255,0.2) inset, 0 4px 12px rgba(255,59,48,0.3);
    letter-spacing: -0.04em;
  }
  .brand-name { font-weight: 800; font-size: 14.5px; letter-spacing: -0.02em; color: var(--text-1); }
  .brand-sub  { font-size: 11.5px; color: var(--text-3); margin-top: 1px; }

  .nav-item {
    display: flex; align-items: center; gap: 10px;
    padding: 9px 12px;
    border-radius: var(--r-md);
    color: var(--text-2);
    font-weight: 500;
    font-size: 13.5px;
    margin-bottom: 2px;
    position: relative;
    transition: background var(--t-fast) var(--ease-out),
                color var(--t-fast) var(--ease-out);
  }
  .nav-item:hover {
    background: var(--bg-soft);
    color: var(--text-1);
  }
  .nav-item.active {
    background: var(--primary-50);
    color: var(--primary-700);
    font-weight: 600;
  }
  .nav-item.active::before {
    content: '';
    position: absolute; left: -12px; top: 50%; transform: translateY(-50%);
    width: 3px; height: 18px;
    background: var(--primary);
    border-radius: 0 3px 3px 0;
  }

  .main {
    padding: 28px 36px;
    min-width: 0;
    animation: pageEnter var(--t-slow) var(--ease-out);
  }
  @keyframes pageEnter {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }

  /* ═══════════════════════════════════════════════════════════
     BADGES & TAGS
  ═══════════════════════════════════════════════════════════ */
  .badge {
    display: inline-flex; align-items: center; gap: 4px;
    padding: 3px 9px;
    border-radius: var(--r-full);
    font-size: 11px; font-weight: 600;
    letter-spacing: -0.005em;
    border: 1px solid transparent;
    line-height: 1.4;
  }
  .badge-free   { background: var(--bg-soft);   color: var(--text-3); border-color: var(--border); }
  .badge-pro    { background: var(--success-bg); color: #065F46;       border-color: rgba(16,185,129,0.3); }
  .badge-studio { background: var(--info-bg);    color: #1E40AF;       border-color: rgba(59,130,246,0.3); }
  .badge-warning { background: var(--warning-bg); color: #92400E;      border-color: rgba(245,158,11,0.3); }
  .badge-danger { background: var(--danger-bg);  color: #991B1B;       border-color: rgba(239,68,68,0.3); }

  /* ═══════════════════════════════════════════════════════════
     TABLES
  ═══════════════════════════════════════════════════════════ */
  table.tbl { width: 100%; border-collapse: separate; border-spacing: 0; font-size: 13.5px; }
  table.tbl th {
    text-align: left;
    padding: 12px 14px;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--text-3); font-weight: 600;
    background: var(--bg-soft);
    border-bottom: 1px solid var(--border);
  }
  table.tbl th:first-child { border-top-left-radius: var(--r-lg); }
  table.tbl th:last-child  { border-top-right-radius: var(--r-lg); }
  table.tbl td {
    padding: 13px 14px;
    border-bottom: 1px solid var(--divider);
    color: var(--text-1);
    vertical-align: middle;
  }
  table.tbl tr:last-child td { border-bottom: none; }
  table.tbl tbody tr { transition: background var(--t-fast); }
  table.tbl tbody tr:hover { background: var(--bg-soft); }

  /* ═══════════════════════════════════════════════════════════
     STATS / KPI CARDS
  ═══════════════════════════════════════════════════════════ */
  .stat {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-xl);
    padding: 18px 20px;
    transition: all var(--t-med) var(--ease-out);
  }
  .stat:hover { box-shadow: var(--shadow-sm); transform: translateY(-1px); border-color: var(--border-strong); }
  .stat-label {
    font-size: 11px; font-weight: 600;
    color: var(--text-3); text-transform: uppercase;
    letter-spacing: 0.08em;
  }
  .stat-value {
    font-family: var(--font-sans);
    font-size: 30px; font-weight: 800;
    color: var(--text-1);
    letter-spacing: -0.04em;
    margin-top: 6px;
    line-height: 1.1;
    font-variant-numeric: tabular-nums;
  }
  .stat-sub { font-size: 12px; color: var(--text-3); margin-top: 4px; }

  /* ═══════════════════════════════════════════════════════════
     EMPTY STATES & ANIMATIONS
  ═══════════════════════════════════════════════════════════ */
  .empty {
    text-align: center; padding: 64px 24px;
    color: var(--text-3);
  }
  .empty-icon {
    width: 64px; height: 64px;
    margin: 0 auto 18px;
    border-radius: var(--r-2xl);
    background: linear-gradient(135deg, var(--bg-soft), var(--surface));
    border: 1px solid var(--border);
    display: flex; align-items: center; justify-content: center;
    font-size: 28px;
    box-shadow: var(--shadow-xs);
  }
  .empty h3 { font-size: 16px; font-weight: 700; color: var(--text-1); margin-bottom: 6px; }
  .empty p  { font-size: 13.5px; line-height: 1.55; max-width: 380px; margin: 0 auto 22px; }

  @keyframes fadeInUp {
    from { opacity: 0; transform: translateY(8px); }
    to   { opacity: 1; transform: translateY(0); }
  }
  @keyframes spin { to { transform: rotate(360deg); } }
  @keyframes shimmer { to { background-position: -200% 0; } }

  .skeleton {
    background: linear-gradient(90deg, var(--bg-soft) 0%, var(--border) 50%, var(--bg-soft) 100%);
    background-size: 200% 100%;
    animation: shimmer 1.4s linear infinite;
    border-radius: var(--r-md);
  }

  /* ═══════════════════════════════════════════════════════════
     BANNERS / ALERTS
  ═══════════════════════════════════════════════════════════ */
  .alert {
    display: flex; gap: 12px; align-items: flex-start;
    padding: 14px 16px;
    border-radius: var(--r-lg);
    font-size: 13.5px; line-height: 1.55;
    border: 1px solid;
    animation: fadeInUp var(--t-slow) var(--ease-out);
  }
  .alert-success { background: var(--success-bg); border-color: rgba(16,185,129,0.3); color: #065F46; }
  .alert-warning { background: var(--warning-bg); border-color: rgba(245,158,11,0.3); color: #78350F; }
  .alert-danger  { background: var(--danger-bg);  border-color: rgba(239,68,68,0.3);  color: #7F1D1D; }
  .alert-info    { background: var(--info-bg);    border-color: rgba(59,130,246,0.3);  color: #1E3A8A; }
  .alert strong { font-weight: 700; }

  /* ═══════════════════════════════════════════════════════════
     PAGE HEADER
  ═══════════════════════════════════════════════════════════ */
  .page-header {
    display: flex; justify-content: space-between; align-items: center;
    gap: 16px; flex-wrap: wrap;
    margin-bottom: 24px;
  }
  .page-title {
    font-size: 26px; font-weight: 800;
    letter-spacing: -0.04em;
    color: var(--text-1);
    margin-bottom: 4px;
  }
  .page-subtitle {
    font-size: 14px; color: var(--text-3);
  }

  /* ═══════════════════════════════════════════════════════════
     RESPONSIVE
  ═══════════════════════════════════════════════════════════ */
  @media (max-width: 768px) {
    .app-wrap { grid-template-columns: 1fr; }
    .sidebar { display: none; }
    .main { padding: 20px; }
    .page-title { font-size: 22px; }
  }

  /* ═══════════════════════════════════════════════════════════
     SCROLL ANIMATIONS
  ═══════════════════════════════════════════════════════════ */
  .reveal { animation: fadeInUp var(--t-slow) var(--ease-out) both; }

  /* ═══════════════════════════════════════════════════════════
     TOAST NOTIFICATIONS (Linear-style)
  ═══════════════════════════════════════════════════════════ */
  #toast-container {
    position: fixed; top: 20px; right: 20px;
    display: flex; flex-direction: column; gap: 10px;
    z-index: 9999; pointer-events: none;
    max-width: 380px;
  }
  .toast {
    background: var(--text-1); color: white;
    padding: 12px 18px; border-radius: var(--r-md);
    box-shadow: var(--shadow-xl);
    font-size: 13.5px; font-weight: 500;
    display: flex; align-items: center; gap: 10px;
    pointer-events: auto;
    min-width: 280px;
    animation: toastIn 350ms var(--ease-spring) both;
    transform-origin: top right;
  }
  .toast.toast-success { background: #052e1f; border: 1px solid #10B981; }
  .toast.toast-error   { background: #2f0f0f; border: 1px solid #EF4444; }
  .toast.toast-info    { background: #0c1f3a; border: 1px solid #3B82F6; }
  .toast .toast-icon { font-size: 16px; }
  .toast.fade-out { animation: toastOut 250ms var(--ease-in) forwards; }
  @keyframes toastIn {
    from { opacity: 0; transform: translateX(40px) scale(0.95); }
    to   { opacity: 1; transform: translateX(0) scale(1); }
  }
  @keyframes toastOut {
    to { opacity: 0; transform: translateX(40px) scale(0.95); }
  }

  /* ═══════════════════════════════════════════════════════════
     COMMAND PALETTE (Cmd+K)
  ═══════════════════════════════════════════════════════════ */
  #cmd-palette-overlay {
    position: fixed; inset: 0;
    background: rgba(12,10,9,0.45);
    backdrop-filter: blur(10px) saturate(140%);
    -webkit-backdrop-filter: blur(10px) saturate(140%);
    z-index: 9000;
    display: none;
    align-items: flex-start;
    justify-content: center;
    padding-top: 14vh;
    animation: cmdFade 200ms var(--ease-out);
  }
  #cmd-palette-overlay.open { display: flex; }
  @keyframes cmdFade {
    from { opacity: 0; backdrop-filter: blur(0); }
    to   { opacity: 1; backdrop-filter: blur(10px) saturate(140%); }
  }
  #cmd-palette {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-xl);
    box-shadow: var(--shadow-2xl);
    width: 100%; max-width: 580px;
    overflow: hidden;
    animation: cmdSlide 280ms var(--ease-spring);
  }
  @keyframes cmdSlide {
    from { opacity: 0; transform: translateY(-8px) scale(0.98); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }
  #cmd-palette-input-wrap {
    display: flex; align-items: center; gap: 12px;
    padding: 16px 20px;
    border-bottom: 1px solid var(--divider);
  }
  #cmd-palette-input {
    flex: 1;
    border: none; outline: none;
    font-family: var(--font-sans);
    font-size: 16px;
    color: var(--text-1);
    background: transparent;
  }
  #cmd-palette-input::placeholder { color: var(--text-4); }
  #cmd-palette-kbd {
    font-family: var(--font-mono); font-size: 11px;
    color: var(--text-3); background: var(--bg-soft);
    padding: 3px 7px; border-radius: 4px;
    border: 1px solid var(--border);
  }
  #cmd-palette-results { max-height: 50vh; overflow-y: auto; padding: 8px 0; }
  .cmd-result {
    display: flex; align-items: center; gap: 12px;
    padding: 10px 20px;
    cursor: pointer;
    color: var(--text-2);
    font-size: 13.5px;
    text-decoration: none;
    transition: background var(--t-fast);
  }
  .cmd-result:hover, .cmd-result.selected {
    background: var(--primary-50);
    color: var(--primary-700);
  }
  .cmd-result-icon { font-size: 18px; opacity: 0.7; }
  .cmd-result-category { font-size: 11px; color: var(--text-4); margin-left: auto; }
  .cmd-section-label {
    padding: 10px 20px 6px;
    font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.08em;
    color: var(--text-4); font-weight: 600;
  }

  /* ═══════════════════════════════════════════════════════════
     ONBOARDING CHECKLIST
  ═══════════════════════════════════════════════════════════ */
  .checklist {
    background: linear-gradient(135deg, var(--primary-50) 0%, var(--surface) 60%);
    border: 1px solid var(--primary-200);
    border-radius: var(--r-2xl);
    padding: 24px;
    margin-bottom: 24px;
  }
  .checklist-header {
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 16px;
  }
  .checklist-progress-bar {
    height: 6px; background: var(--bg-soft);
    border-radius: var(--r-full); overflow: hidden;
    margin: 12px 0 18px;
  }
  .checklist-progress-fill {
    height: 100%;
    background: linear-gradient(90deg, var(--primary), #FF6B5E);
    border-radius: var(--r-full);
    transition: width 600ms var(--ease-out);
  }
  .checklist-item {
    display: flex; align-items: center; gap: 14px;
    padding: 12px;
    background: var(--surface); border: 1px solid var(--border);
    border-radius: var(--r-lg);
    margin-bottom: 8px;
    text-decoration: none; color: var(--text-1);
    transition: all var(--t-fast);
  }
  .checklist-item:hover {
    border-color: var(--primary-300);
    transform: translateX(4px);
    box-shadow: var(--shadow-sm);
    color: var(--text-1);
  }
  .checklist-item.done {
    opacity: 0.6;
    background: var(--bg-soft);
  }
  .checklist-item.done .checklist-text { text-decoration: line-through; }
  .checklist-icon {
    width: 28px; height: 28px; border-radius: 50%;
    border: 2px solid var(--border-strong);
    display: flex; align-items: center; justify-content: center;
    color: white; font-size: 14px;
    transition: all var(--t-med) var(--ease-spring);
  }
  .checklist-item.done .checklist-icon {
    background: var(--success); border-color: var(--success);
  }
  .checklist-text { font-size: 13.5px; font-weight: 600; flex: 1; }
  .checklist-arrow { color: var(--text-4); font-size: 16px; }

  /* ═══════════════════════════════════════════════════════════
     SPARKLINES & MINI CHARTS
  ═══════════════════════════════════════════════════════════ */
  .sparkline {
    width: 100%; height: 60px;
  }
  .sparkline path { transition: all var(--t-med); }
  .stat-trend {
    display: inline-flex; align-items: center; gap: 4px;
    font-size: 12px; font-weight: 600;
  }
  .stat-trend.up   { color: var(--success); }
  .stat-trend.down { color: var(--danger); }

  /* ═══════════════════════════════════════════════════════════
     CALENDAR WEEK VIEW
  ═══════════════════════════════════════════════════════════ */
  .calendar-week {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--r-xl);
    overflow: hidden;
  }
  .calendar-week-head {
    display: grid; grid-template-columns: 60px repeat(7, 1fr);
    border-bottom: 1px solid var(--border);
    background: var(--bg-soft);
  }
  .calendar-day-label {
    padding: 12px 8px;
    text-align: center;
    font-size: 11px; text-transform: uppercase; letter-spacing: 0.06em;
    color: var(--text-3); font-weight: 600;
  }
  .calendar-day-label.today {
    color: var(--primary);
    background: var(--primary-50);
  }
  .calendar-day-num {
    display: block;
    font-size: 22px; font-weight: 700;
    color: var(--text-1);
    margin-top: 2px;
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.03em;
  }
  .calendar-day-label.today .calendar-day-num { color: var(--primary); }
  .calendar-body {
    display: grid; grid-template-columns: 60px repeat(7, 1fr);
    min-height: 480px;
  }
  .calendar-hour-col {
    border-right: 1px solid var(--divider);
    padding-top: 8px;
    background: var(--bg-soft);
  }
  .calendar-hour-label {
    height: 60px;
    padding: 2px 8px;
    font-size: 10.5px;
    color: var(--text-4);
    text-align: right;
    border-top: 1px solid var(--divider);
  }
  .calendar-day-col {
    border-right: 1px solid var(--divider);
    position: relative;
  }
  .calendar-day-col:last-child { border-right: none; }
  .calendar-slot {
    height: 60px;
    border-top: 1px solid var(--divider);
    transition: background var(--t-fast);
    cursor: pointer;
  }
  .calendar-slot:hover { background: var(--primary-50); }
  .calendar-event {
    position: absolute;
    left: 4px; right: 4px;
    background: linear-gradient(135deg, var(--primary), #FF6B5E);
    color: white;
    border-radius: var(--r-sm);
    padding: 6px 8px;
    font-size: 11.5px; font-weight: 600;
    cursor: pointer;
    overflow: hidden;
    box-shadow: var(--shadow-sm);
    transition: all var(--t-fast);
  }
  .calendar-event:hover {
    transform: translateX(1px) translateY(-1px);
    box-shadow: var(--shadow-md);
    color: white;
  }
  .calendar-event-time { font-size: 10px; opacity: 0.85; font-weight: 500; }
</style>

<!-- ═══════════════════════════════════════════════════════════
     SCRIPT: TOASTS + COMMAND PALETTE + KEYBOARD SHORTCUTS
═══════════════════════════════════════════════════════════ -->
<script>
(function() {
  // ── TOAST SYSTEM ─────────────────────────────────────────
  window.showToast = function(message, type = 'success', duration = 3500) {
    let container = document.getElementById('toast-container');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toast-container';
      document.body.appendChild(container);
    }
    const toast = document.createElement('div');
    toast.className = 'toast toast-' + type;
    const icons = {success:'✓', error:'✗', info:'i', warning:'⚠'};
    toast.innerHTML = '<span class="toast-icon">' + (icons[type]||'•') + '</span><span>' + message + '</span>';
    container.appendChild(toast);
    setTimeout(() => {
      toast.classList.add('fade-out');
      setTimeout(() => toast.remove(), 250);
    }, duration);
  };

  // Detectar toasts via query params (?creado=1, ?guardado=1, ?error=...)
  document.addEventListener('DOMContentLoaded', function() {
    const params = new URLSearchParams(window.location.search);
    if (params.get('creado')) window.showToast('Guardado correctamente', 'success');
    if (params.get('guardado')) window.showToast('Cambios guardados', 'success');
    if (params.get('demo')) window.showToast('¡Datos demo cargados!', 'success');
    if (params.get('error')) window.showToast(decodeURIComponent(params.get('error')), 'error', 5000);
  });

  // ── COMMAND PALETTE Cmd+K ────────────────────────────────
  const ROUTES = [
    {icon: '⌂', name: 'Dashboard',       url: '/clinic/app/',           cat: 'Páginas'},
    {icon: '✉', name: 'Inbox',            url: '/clinic/app/inbox',      cat: 'Páginas'},
    {icon: '◯', name: 'Pacientes',        url: '/clinic/app/pacientes',  cat: 'Páginas'},
    {icon: '✚', name: 'Nuevo paciente',   url: '/clinic/app/pacientes/nuevo', cat: 'Acciones'},
    {icon: '↑', name: 'Importar pacientes CSV', url: '/clinic/app/pacientes/importar', cat: 'Acciones'},
    {icon: '↓', name: 'Exportar pacientes CSV', url: '/clinic/app/pacientes-export', cat: 'Acciones'},
    {icon: '📅', name: 'Citas',           url: '/clinic/app/citas',      cat: 'Páginas'},
    {icon: '✚', name: 'Nueva cita',       url: '/clinic/app/citas/nueva', cat: 'Acciones'},
    {icon: '☎', name: 'Llamadas',         url: '/clinic/app/llamadas',   cat: 'Páginas'},
    {icon: '✚', name: 'Registrar llamada',url: '/clinic/app/llamadas/nueva', cat: 'Acciones'},
    {icon: '⌨', name: 'Plantillas',       url: '/clinic/app/plantillas', cat: 'Páginas'},
    {icon: '◉', name: 'Usuarios del equipo', url: '/clinic/app/usuarios', cat: 'Páginas'},
    {icon: '⚙', name: 'Configuración',    url: '/clinic/app/configuracion', cat: 'Páginas'},
    {icon: '⎋', name: 'Cerrar sesión',    url: '/clinic/logout',         cat: 'Cuenta'},
  ];

  function buildPalette() {
    if (document.getElementById('cmd-palette-overlay')) return;
    const html = `
      <div id="cmd-palette-overlay">
        <div id="cmd-palette">
          <div id="cmd-palette-input-wrap">
            <span style="color:var(--text-3);">⌕</span>
            <input id="cmd-palette-input" placeholder="Buscar páginas, acciones, atajos..." autocomplete="off">
            <span id="cmd-palette-kbd">ESC</span>
          </div>
          <div id="cmd-palette-results"></div>
        </div>
      </div>`;
    document.body.insertAdjacentHTML('beforeend', html);
  }

  function renderResults(query) {
    const q = (query || '').toLowerCase().trim();
    const filtered = ROUTES.filter(r =>
      !q || r.name.toLowerCase().includes(q) || r.cat.toLowerCase().includes(q)
    );
    const grouped = {};
    filtered.forEach(r => { (grouped[r.cat] = grouped[r.cat] || []).push(r); });
    let html = '';
    Object.entries(grouped).forEach(([cat, items]) => {
      html += `<div class="cmd-section-label">${cat}</div>`;
      items.forEach((r, i) => {
        const selected = i === 0 && cat === Object.keys(grouped)[0] ? ' selected' : '';
        html += `<a href="${r.url}" class="cmd-result${selected}">
          <span class="cmd-result-icon">${r.icon}</span>
          <span>${r.name}</span>
          <span class="cmd-result-category">${r.cat}</span>
        </a>`;
      });
    });
    if (!filtered.length) {
      html = '<div style="padding:30px;text-align:center;color:var(--text-3);font-size:13px;">Sin resultados para "' + query + '"</div>';
    }
    document.getElementById('cmd-palette-results').innerHTML = html;
  }

  function openPalette() {
    buildPalette();
    const overlay = document.getElementById('cmd-palette-overlay');
    const input = document.getElementById('cmd-palette-input');
    overlay.classList.add('open');
    renderResults('');
    setTimeout(() => input.focus(), 50);
    input.value = '';
  }
  function closePalette() {
    const o = document.getElementById('cmd-palette-overlay');
    if (o) o.classList.remove('open');
  }

  document.addEventListener('keydown', function(e) {
    // Cmd+K / Ctrl+K
    if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
      e.preventDefault();
      openPalette();
    }
    // ESC para cerrar
    if (e.key === 'Escape') {
      closePalette();
    }
    // Cmd+/ para abrir también (alternativa)
    if ((e.metaKey || e.ctrlKey) && e.key === '/') {
      e.preventDefault();
      openPalette();
    }
  });

  document.addEventListener('click', function(e) {
    const overlay = document.getElementById('cmd-palette-overlay');
    if (overlay && overlay.classList.contains('open') && e.target === overlay) {
      closePalette();
    }
    // Filtrar mientras escribe
    if (e.target.id === 'cmd-palette-input') {
      // delegado abajo
    }
  });

  document.addEventListener('input', function(e) {
    if (e.target.id === 'cmd-palette-input') {
      renderResults(e.target.value);
    }
  });

  // Atajos extras: G luego H = home, G I = inbox, G P = pacientes
  let gPressed = false;
  document.addEventListener('keydown', function(e) {
    if (e.target.matches('input, textarea, select')) return;
    if (e.key === 'g' && !gPressed) {
      gPressed = true;
      setTimeout(() => { gPressed = false; }, 1000);
      return;
    }
    if (gPressed) {
      const map = {'h':'/clinic/app/', 'i':'/clinic/app/inbox', 'p':'/clinic/app/pacientes',
                   'c':'/clinic/app/citas', 'l':'/clinic/app/llamadas', 't':'/clinic/app/plantillas'};
      if (map[e.key]) {
        e.preventDefault();
        window.location.href = map[e.key];
      }
      gPressed = false;
    }
  });
})();
</script>
"""


def sidebar_clinic(activa: str, sesion: dict, clinica: Clinica) -> str:
    """Sidebar de la app del SaaS."""
    items = [
        ("dashboard", "Dashboard",  "/clinic/app/",            "M3 12h2l2-7 4 14 4-7 2 0"),
        ("inbox",     "Inbox",      "/clinic/app/inbox",       "M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"),
        ("pacientes", "Pacientes",  "/clinic/app/pacientes",   "M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2 M12 7a4 4 0 1 1-8 0 4 4 0 0 1 8 0z"),
        ("citas",     "Citas",      "/clinic/app/citas",       "M3 4h18v2H3z M3 10h18v10H3z"),
        ("llamadas",  "Llamadas",   "/clinic/app/llamadas",    "M22 16.92v3a2 2 0 0 1-2.18 2A19.79 19.79 0 0 1 2 5.18 2 2 0 0 1 4 3h3"),
        ("plantillas","Plantillas", "/clinic/app/plantillas",  "M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"),
        ("usuarios",  "Equipo",     "/clinic/app/usuarios",    "M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2 M22 21v-2a4 4 0 0 0-3-3.87"),
        ("config",    "Configuración","/clinic/app/configuracion","M12 1v6 M12 17v6 M4.22 4.22l4.24 4.24"),
    ]
    links = ""
    for k, label, url, _path in items:
        clase = "nav-item active" if k == activa else "nav-item"
        links += f'<a href="{url}" class="{clase}">{html.escape(label)}</a>'

    plan = clinica.plan if clinica else "free"
    badge_plan = {"free": "badge-free", "pro": "badge-pro", "studio": "badge-studio"}.get(plan, "badge-free")
    nombre = html.escape(clinica.nombre if clinica else "Clinica")

    return f"""
    <aside class="sidebar">
      <div class="brand">
        <div class="brand-logo">L</div>
        <div>
          <div class="brand-name">Lapora Clinic</div>
          <div class="brand-sub">{nombre}</div>
        </div>
      </div>
      <form action="/clinic/app/buscar" method="get" style="margin:14px 0 6px;">
        <input type="text" name="q" placeholder="🔍 Buscar pacientes, mensajes..."
               style="width:100%;padding:9px 12px;border:1.5px solid var(--border);border-radius:9px;font-size:13px;outline:none;background:var(--bg);"
               onfocus="this.style.borderColor='var(--primary)'"
               onblur="this.style.borderColor='var(--border)'">
      </form>
      <nav style="margin-top: 8px; flex: 1;">{links}</nav>
      <div style="border-top: 1px solid var(--border); padding-top: 14px;">
        <div style="font-size: 12px; color: var(--text-soft); margin-bottom: 6px;">
          {html.escape(sesion.get('nombre', ''))}
        </div>
        <span class="badge {badge_plan}">{plan.upper()}</span>
        <a href="/clinic/logout" style="display:block;margin-top:12px;font-size:12px;color:var(--text-soft);">Salir →</a>
      </div>
    </aside>
    """


# ════════════════════════════════════════════════════════════
# 1) LANDING — Redirige a login
# ════════════════════════════════════════════════════════════

@router.get("/", response_class=HTMLResponse)
async def landing(clinic_session: Optional[str] = Cookie(None)):
    if obtener_sesion(clinic_session):
        return RedirectResponse("/clinic/app/", status_code=303)
    return RedirectResponse("/clinic/login", status_code=303)


# ════════════════════════════════════════════════════════════
# 2) REGISTRO — Onboarding nueva clínica
# ════════════════════════════════════════════════════════════

@router.get("/registro", response_class=HTMLResponse)
async def registro_form(error: Optional[str] = None):
    err_html = f'<div style="background:#FEE2E2;color:#7F1D1D;padding:12px;border-radius:10px;margin-bottom:16px;font-size:13px;">{html.escape(error)}</div>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Crear cuenta - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px;">
    <div style="max-width: 460px; width: 100%;">
      <div style="text-align: center; margin-bottom: 28px;">
        <div style="display: inline-flex; align-items: center; gap: 12px;">
          <div class="brand-logo" style="width:44px;height:44px;font-size:20px;">L</div>
          <div>
            <div style="font-weight: 800; font-size: 22px; color: var(--text);">Lapora Clinic</div>
            <div style="font-size: 12px; color: var(--text-soft);">El cerebro digital de tu consultorio</div>
          </div>
        </div>
      </div>
      <div class="card" style="padding: 32px;">
        <h1 style="font-size: 22px; font-weight: 800; margin-bottom: 6px;">Crear cuenta gratis</h1>
        <p style="color: var(--text-soft); margin-bottom: 24px; font-size: 13px;">
          Plan FREE incluye: 100 pacientes · Inbox WhatsApp · 1 usuario. Sin tarjeta.
        </p>
        {err_html}
        <form method="post" action="/clinic/registro" style="display: flex; flex-direction: column; gap: 14px;">
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Nombre del consultorio</label>
            <input type="text" name="nombre_clinica" required placeholder="Ej: Clínica Sonrisa Plena" class="input">
          </div>
          <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px;">
            <div>
              <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Especialidad</label>
              <input type="text" name="especialidad" placeholder="Odontología" class="input">
            </div>
            <div>
              <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Ciudad</label>
              <input type="text" name="ciudad" placeholder="Ibagué" value="Ibagué" class="input">
            </div>
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Tu nombre</label>
            <input type="text" name="nombre_admin" required placeholder="Dr. Juan Pérez" class="input">
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Email</label>
            <input type="email" name="email" required placeholder="doctor@consultorio.com" class="input">
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Contraseña</label>
            <input type="password" name="password" required minlength="6" placeholder="Mínimo 6 caracteres" class="input">
          </div>
          <button type="submit" class="btn btn-primary" style="margin-top: 8px; justify-content: center;">
            Crear mi cuenta gratis
          </button>
        </form>
        <p style="margin-top: 18px; font-size: 13px; color: var(--text-soft); text-align: center;">
          ¿Ya tienes cuenta? <a href="/clinic/login" style="font-weight: 600;">Iniciar sesión</a>
        </p>
      </div>
    </div>
  </div>
</body></html>""")


@router.post("/registro", response_class=HTMLResponse)
async def registro_procesar(
    nombre_clinica: str = Form(...),
    especialidad: str = Form(""),
    ciudad: str = Form("Ibagué"),
    nombre_admin: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
):
    """Crea la clínica + usuario admin + sesión y redirige al dashboard."""
    if len(password) < 6:
        return RedirectResponse(
            f"/clinic/registro?error={html.escape('La contraseña debe tener mínimo 6 caracteres')}",
            status_code=303,
        )

    # Verificar email único
    async with async_session() as session:
        existing = (await session.execute(
            select(UsuarioClinic).where(UsuarioClinic.email == email.lower())
        )).scalar_one_or_none()
        if existing:
            return RedirectResponse(
                f"/clinic/registro?error={html.escape('Ese email ya está registrado. Inicia sesión.')}",
                status_code=303,
            )

    try:
        clinica, usuario = await crear_clinica(
            nombre=nombre_clinica,
            email_admin=email,
            password_admin=password,
            nombre_admin=nombre_admin,
            especialidad=especialidad,
            ciudad=ciudad,
        )
    except Exception as e:
        return RedirectResponse(
            f"/clinic/registro?error={html.escape('Error creando cuenta: ' + str(e)[:80])}",
            status_code=303,
        )

    token = crear_sesion(usuario)
    response = RedirectResponse("/clinic/app/?bienvenida=1", status_code=303)
    response.set_cookie("clinic_session", token, max_age=86400 * 30, httponly=True, samesite="lax")
    return response


# ════════════════════════════════════════════════════════════
# 3) LOGIN
# ════════════════════════════════════════════════════════════

@router.get("/login", response_class=HTMLResponse)
async def login_form(error: Optional[str] = None):
    err_html = f'<div style="background:#FEE2E2;color:#7F1D1D;padding:12px;border-radius:10px;margin-bottom:16px;font-size:13px;">{html.escape(error)}</div>' if error else ""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Iniciar sesión - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div style="min-height: 100vh; display: flex; align-items: center; justify-content: center; padding: 20px;">
    <div style="max-width: 420px; width: 100%;">
      <div style="text-align: center; margin-bottom: 28px;">
        <div style="display: inline-flex; align-items: center; gap: 12px;">
          <div class="brand-logo" style="width:44px;height:44px;font-size:20px;">L</div>
          <div>
            <div style="font-weight: 800; font-size: 22px;">Lapora Clinic</div>
            <div style="font-size: 12px; color: var(--text-soft);">Iniciar sesión</div>
          </div>
        </div>
      </div>
      <div class="card" style="padding: 32px;">
        {err_html}
        <form method="post" action="/clinic/login" style="display: flex; flex-direction: column; gap: 14px;">
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Email</label>
            <input type="email" name="email" required class="input" autofocus>
          </div>
          <div>
            <label style="font-size: 12px; font-weight: 700; display: block; margin-bottom: 5px;">Contraseña</label>
            <input type="password" name="password" required class="input">
          </div>
          <button type="submit" class="btn btn-primary" style="margin-top: 8px; justify-content: center;">
            Entrar
          </button>
        </form>
        <p style="margin-top: 18px; font-size: 13px; color: var(--text-soft); text-align: center;">
          ¿Sin cuenta? <a href="/clinic/registro" style="font-weight: 600;">Crear gratis</a>
        </p>
      </div>
    </div>
  </div>
</body></html>""")


@router.post("/login", response_class=HTMLResponse)
async def login_procesar(email: str = Form(...), password: str = Form(...)):
    usuario = await autenticar_usuario(email, password)
    if not usuario:
        return RedirectResponse(
            f"/clinic/login?error={html.escape('Email o contraseña incorrectos')}",
            status_code=303,
        )
    # Verificar si la clínica está congelada
    clinica = await obtener_clinica(usuario.clinica_id)
    if clinica and clinica.congelada:
        motivo = clinica.motivo_suspension or "Falta de pago"
        return RedirectResponse(
            f"/clinic/suspendida?motivo={html.escape(motivo, quote=True)}",
            status_code=303,
        )
    token = crear_sesion(usuario)
    response = RedirectResponse("/clinic/app/", status_code=303)
    response.set_cookie("clinic_session", token, max_age=86400 * 30, httponly=True, samesite="lax")
    return response


@router.get("/suspendida", response_class=HTMLResponse)
async def cuenta_suspendida(motivo: Optional[str] = None):
    """Página que se muestra cuando una clínica intenta entrar con cuenta congelada."""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Cuenta suspendida</title>{CSS_CLINIC}</head>
<body>
  <div style="min-height:100vh;display:flex;align-items:center;justify-content:center;padding:24px;">
    <div style="max-width:500px;width:100%;text-align:center;">
      <div style="font-size:80px;margin-bottom:18px;">⏸️</div>
      <h1 style="font-size:28px;font-weight:800;margin-bottom:12px;color:#EF4444;">Cuenta suspendida</h1>
      <div class="card" style="text-align:left;">
        <p style="font-size:15px;line-height:1.6;color:var(--text);margin-bottom:14px;">
          Tu acceso a Lapora Clinic está temporalmente <strong>suspendido</strong>. Toda tu información sigue intacta y la podrás recuperar al reactivar.
        </p>
        <div style="background:#FEE2E2;color:#7F1D1D;padding:14px;border-radius:10px;font-size:14px;margin-bottom:14px;">
          <strong>Motivo:</strong> {html.escape(motivo or "Falta de pago")}
        </div>
        <p style="font-size:14px;color:var(--text-soft);">
          Para reactivar tu cuenta, contáctanos:
        </p>
        <div style="display:flex;flex-direction:column;gap:8px;margin-top:14px;">
          <a href="https://wa.me/573228783019?text=Quiero+reactivar+mi+cuenta+Lapora+Clinic" class="btn btn-primary" style="justify-content:center;background:#25D366;box-shadow:0 4px 12px rgba(37,211,102,0.3);">📱 WhatsApp Lapora</a>
          <a href="mailto:laporamarketingdigital@gmail.com" class="btn btn-ghost" style="justify-content:center;">✉️ Enviar email</a>
        </div>
      </div>
    </div>
  </div>
</body></html>""")


@router.get("/logout")
async def logout(clinic_session: Optional[str] = Cookie(None)):
    if clinic_session and clinic_session in SESSIONS:
        del SESSIONS[clinic_session]
    response = RedirectResponse("/clinic/login", status_code=303)
    response.delete_cookie("clinic_session")
    return response


# ════════════════════════════════════════════════════════════
# 4) DASHBOARD — Vista principal post-login
# ════════════════════════════════════════════════════════════

@router.get("/app/", response_class=HTMLResponse)
@router.get("/app", response_class=HTMLResponse)
async def dashboard(
    bienvenida: Optional[str] = None,
    demo: Optional[int] = None,
    impersonate: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    clinica = await obtener_clinica(sesion["clinica_id"])
    if not clinica:
        return RedirectResponse("/clinic/login", status_code=303)

    # Stats reales + vista "HOY"
    from datetime import timedelta
    hoy_inicio = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    hoy_fin = hoy_inicio + timedelta(days=1)
    hace_7_dias = hoy_inicio - timedelta(days=7)
    hace_1_dia = datetime.utcnow() - timedelta(days=1)

    async with async_session() as session:
        total_pacientes = (await session.execute(
            select(func.count(Paciente.id)).where(Paciente.clinica_id == clinica.id)
        )).scalar() or 0
        total_mensajes = (await session.execute(
            select(func.count(MensajeUnificado.id)).where(MensajeUnificado.clinica_id == clinica.id)
        )).scalar() or 0
        mensajes_no_leidos = (await session.execute(
            select(func.count(MensajeUnificado.id))
            .where(MensajeUnificado.clinica_id == clinica.id)
            .where(MensajeUnificado.leido == False)
            .where(MensajeUnificado.direccion == "entrada")
        )).scalar() or 0
        total_citas = (await session.execute(
            select(func.count(CitaClinic.id)).where(CitaClinic.clinica_id == clinica.id)
        )).scalar() or 0

        # === Tareas de HOY ===
        # Pacientes nuevos esta semana
        nuevos_semana = list((await session.execute(
            select(Paciente).where(Paciente.clinica_id == clinica.id)
            .where(Paciente.primer_contacto >= hace_7_dias)
            .order_by(desc(Paciente.primer_contacto)).limit(10)
        )).scalars().all())
        # Citas de hoy
        citas_hoy = list((await session.execute(
            select(CitaClinic).where(CitaClinic.clinica_id == clinica.id)
            .where(CitaClinic.fecha_hora >= hoy_inicio)
            .where(CitaClinic.fecha_hora < hoy_fin)
            .order_by(CitaClinic.fecha_hora)
        )).scalars().all())
        # Mensajes sin responder de hace > 1 día
        mensajes_pendientes = list((await session.execute(
            select(MensajeUnificado).where(MensajeUnificado.clinica_id == clinica.id)
            .where(MensajeUnificado.direccion == "entrada")
            .where(MensajeUnificado.leido == False)
            .where(MensajeUnificado.timestamp < hace_1_dia)
            .order_by(MensajeUnificado.timestamp).limit(5)
        )).scalars().all())
        # Llamadas marcadas como "volver_a_llamar"
        volver_llamar = list((await session.execute(
            select(Llamada).where(Llamada.clinica_id == clinica.id)
            .where(Llamada.resultado == "volver_a_llamar")
            .order_by(desc(Llamada.timestamp)).limit(5)
        )).scalars().all())

    bienvenida_html = ""
    sesion_impersonate = sesion.get("impersonado_por") if sesion else None
    if sesion_impersonate:
        bienvenida_html = f'<div class="alert alert-warning" style="margin-bottom:16px;"><strong>👁️ SUPER ADMIN</strong> — Estás accediendo como esta clínica ({html.escape(sesion_impersonate)}). <a href="/clinic/superadmin" style="color:inherit;text-decoration:underline;font-weight:700;">Volver al panel</a></div>'

    # === ONBOARDING CHECKLIST ===
    # Detecta progreso: WA conectado, pacientes, plantillas, calendar, IA SofIA
    pasos_setup = [
        ("Conectar WhatsApp Business",       bool(clinica.whatsapp_phone_id), "/clinic/app/configuracion#whatsapp"),
        ("Importar o crear primer paciente", total_pacientes > 0,             "/clinic/app/pacientes/nuevo"),
        ("Conectar Google Calendar",         bool(clinica.google_calendar_id), "/clinic/app/configuracion#calendar"),
        ("Crear plantillas de respuesta",    False,                            "/clinic/app/plantillas/nueva"),
        ("Activar IA SofIA (responde 24/7)", bool(clinica.ia_activa),         "/clinic/app/configuracion#ia-config"),
    ]
    # Verificar plantillas
    async with async_session() as session:
        n_plantillas = (await session.execute(
            select(func.count(PlantillaRespuesta.id)).where(PlantillaRespuesta.clinica_id == clinica.id)
        )).scalar() or 0
        pasos_setup[3] = ("Crear plantillas de respuesta", n_plantillas > 0, "/clinic/app/plantillas/nueva")

    completados = sum(1 for _, done, _ in pasos_setup if done)
    pct = int(completados / len(pasos_setup) * 100)

    checklist_html = ""
    if pct < 100:
        items_html = ""
        for label, done, url in pasos_setup:
            cls = "checklist-item done" if done else "checklist-item"
            icon = "✓" if done else ""
            items_html += f'''
            <a href="{url}" class="{cls}">
              <span class="checklist-icon">{icon}</span>
              <span class="checklist-text">{label}</span>
              <span class="checklist-arrow">→</span>
            </a>'''
        checklist_html = f"""
        <div class="checklist reveal">
          <div class="checklist-header">
            <div>
              <h2 style="font-size:17px;font-weight:800;color:var(--text-1);margin-bottom:2px;">Termina tu configuración</h2>
              <p style="font-size:13px;color:var(--text-3);">{completados} de {len(pasos_setup)} pasos completados</p>
            </div>
            <div style="font-family:var(--font-mono);font-size:22px;font-weight:800;color:var(--primary);">{pct}%</div>
          </div>
          <div class="checklist-progress-bar">
            <div class="checklist-progress-fill" style="width:{pct}%;"></div>
          </div>
          {items_html}
        </div>"""

    bienvenida_html += checklist_html

    # Render bloque "Hoy"
    def render_lista(items, fn_render, vacio_msg):
        if not items:
            return f'<p style="color:var(--text-soft);font-size:13px;padding:14px;text-align:center;">{vacio_msg}</p>'
        return "".join(fn_render(i) for i in items)

    citas_html = render_lista(
        citas_hoy,
        lambda c: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><strong>{c.fecha_hora.strftime("%H:%M")}</strong> · <a href="/clinic/app/pacientes/{c.paciente_id}">paciente</a> · {html.escape(c.motivo or "")}</div>',
        "Sin citas hoy 🎉",
    )
    pendientes_html = render_lista(
        mensajes_pendientes,
        lambda m: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><a href="/clinic/app/inbox?paciente_id={m.paciente_id}">{html.escape((m.contenido or "")[:60])}...</a></div>',
        "Todo respondido ✓",
    )
    volver_html = render_lista(
        volver_llamar,
        lambda l: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><a href="/clinic/app/pacientes/{l.paciente_id}">{html.escape((l.notas or "Pendiente")[:60])}</a></div>',
        "Sin llamadas pendientes 📞",
    )
    nuevos_html = render_lista(
        nuevos_semana,
        lambda p: f'<div style="padding:10px 14px;border-bottom:1px solid var(--border);font-size:13px;"><a href="/clinic/app/pacientes/{p.id}">{html.escape(p.nombre)}</a> · {html.escape(p.tratamiento_actual or "")}</div>',
        "Sin pacientes nuevos esta semana",
    )

    # Generar sparkline (últimos 7 días — datos simplificados)
    import random as _r
    _seed = sum(ord(c) for c in clinica.nombre)
    _r.seed(_seed)
    # Datos simulados de últimos 7 días basados en pacientes existentes
    sparkline_pacientes = [_r.randint(2, max(8, total_pacientes // 4)) for _ in range(7)] if total_pacientes else [0]*7
    sparkline_mensajes  = [_r.randint(1, max(10, total_mensajes // 5)) for _ in range(7)] if total_mensajes else [0]*7

    def render_sparkline(data, color="#FF3B30"):
        if not data or max(data) == 0:
            return ''
        w, h = 280, 50
        mx = max(data)
        n = len(data)
        pts = []
        for i, v in enumerate(data):
            x = (i / (n - 1)) * w if n > 1 else w / 2
            y = h - (v / mx) * (h - 8) - 4
            pts.append(f"{x:.1f},{y:.1f}")
        path = "M " + " L ".join(pts)
        return f'''<svg class="sparkline" viewBox="0 0 {w} {h}" preserveAspectRatio="none">
          <defs><linearGradient id="grad-{color[1:]}" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stop-color="{color}" stop-opacity="0.2"/>
            <stop offset="100%" stop-color="{color}" stop-opacity="0"/>
          </linearGradient></defs>
          <path d="{path} L {w},{h} L 0,{h} Z" fill="url(#grad-{color[1:]})"/>
          <path d="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>'''

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Dashboard - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("dashboard", sesion, clinica)}
    <main class="main">
      <div class="page-header">
        <div>
          <h1 class="page-title">Hola, {html.escape(sesion.get('nombre','').split()[0] if sesion.get('nombre') else '')} 👋</h1>
          <p class="page-subtitle">Vista general de <strong>{html.escape(clinica.nombre)}</strong></p>
        </div>
        <div style="display:flex;gap:8px;align-items:center;">
          <kbd style="font-family:var(--font-mono);font-size:11px;color:var(--text-3);background:var(--bg-soft);padding:5px 9px;border-radius:5px;border:1px solid var(--border);">⌘ K</kbd>
          <span style="font-size:11px;color:var(--text-4);">para buscar</span>
        </div>
      </div>
      {bienvenida_html}

      <!-- KPIs CON SPARKLINES -->
      <div style="display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 12px; margin-bottom: 24px;">
        <div class="stat">
          <div class="stat-label">Pacientes</div>
          <div class="stat-value">{total_pacientes}</div>
          <div style="margin-top:8px;">{render_sparkline(sparkline_pacientes, '#FF3B30')}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Sin responder</div>
          <div class="stat-value" style="color:{('var(--primary)' if mensajes_no_leidos > 0 else 'var(--text-1)')};">{mensajes_no_leidos}</div>
          <div class="stat-sub"><a href="/clinic/app/inbox" style="font-size:12px;">Ir al inbox →</a></div>
        </div>
        <div class="stat">
          <div class="stat-label">Mensajes totales</div>
          <div class="stat-value">{total_mensajes}</div>
          <div style="margin-top:8px;">{render_sparkline(sparkline_mensajes, '#3B82F6')}</div>
        </div>
        <div class="stat">
          <div class="stat-label">Citas agendadas</div>
          <div class="stat-value">{total_citas}</div>
          <div class="stat-sub"><a href="/clinic/app/citas" style="font-size:12px;">Ver agenda →</a></div>
        </div>
      </div>

      <!-- VISTA HOY -->
      <h2 style="font-size:18px;font-weight:800;margin:8px 0 12px;">📅 Hoy y esta semana</h2>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:14px;margin-bottom:28px;">
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#3B82F6;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            📅 Citas hoy ({len(citas_hoy)})
          </div>
          {citas_html}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#F59E0B;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            ⚠️ Sin responder ({len(mensajes_pendientes)})
          </div>
          {pendientes_html}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#A855F7;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            📞 Volver a llamar ({len(volver_llamar)})
          </div>
          {volver_html}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#10B981;color:white;font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1px;">
            🆕 Nuevos esta semana ({len(nuevos_semana)})
          </div>
          {nuevos_html}
        </div>
      </div>

      <div class="card" style="padding: 28px;">
        <h2 style="font-size: 18px; font-weight: 700; margin-bottom: 16px;">🚀 Empieza en 3 pasos</h2>
        <ol style="padding-left: 20px; line-height: 1.9; color: var(--text); font-size: 14px;">
          <li><strong>Conectá WhatsApp Business</strong> — recibí los mensajes de tus pacientes en el inbox unificado.
            <a href="/clinic/app/configuracion" style="margin-left: 6px;">Conectar →</a></li>
          <li><strong>Sincronizá Google Sheets</strong> — importá tus pacientes existentes desde Excel/Sheets.
            <a href="/clinic/app/configuracion" style="margin-left: 6px;">Sincronizar →</a></li>
          <li><strong>Creá plantillas de respuesta</strong> — respondé a preguntas frecuentes con un click.
            <a href="/clinic/app/plantillas" style="margin-left: 6px;">Crear →</a></li>
        </ol>
        {('<div style="margin-top:20px;padding-top:16px;border-top:1px solid var(--border);"><form method="post" action="/clinic/app/demo-data"><button type="submit" class="btn btn-ghost">🎁 Cargar datos de ejemplo</button></form><p style="font-size:11px;color:var(--text-soft);margin-top:6px;">Crea 5 pacientes, 7 mensajes, 3 llamadas y 4 plantillas demo para explorar la plataforma.</p></div>' if total_pacientes == 0 else '')}
      </div>
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 5) INBOX — Mockup MVP (se llena con datos reales en Mes 1)
# ════════════════════════════════════════════════════════════

@router.get("/app/inbox", response_class=HTMLResponse)
async def vista_inbox(
    canal: Optional[str] = None,
    paciente_id: Optional[int] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    """Inbox unificado: lista de conversaciones a la izquierda, chat seleccionado a la derecha."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        # Última conversación por paciente (group by paciente, order by último msg)
        # Para simplicidad, traemos todos los mensajes recientes y agrupamos en memoria
        query = select(MensajeUnificado).where(MensajeUnificado.clinica_id == clinica.id)
        if canal and canal != "todos":
            query = query.where(MensajeUnificado.canal == canal)
        query = query.order_by(desc(MensajeUnificado.timestamp)).limit(500)
        todos_mensajes = list((await session.execute(query)).scalars().all())

        # Agrupar por paciente: tomar el último mensaje de cada uno
        conversaciones: dict[int, dict] = {}
        for m in todos_mensajes:
            pid = m.paciente_id or 0
            if pid not in conversaciones:
                conversaciones[pid] = {
                    "paciente_id": pid,
                    "ultimo_mensaje": m,
                    "no_leidos": 0,
                    "total": 0,
                    "canales": set(),
                }
            conversaciones[pid]["total"] += 1
            conversaciones[pid]["canales"].add(m.canal)
            if not m.leido and m.direccion == "entrada":
                conversaciones[pid]["no_leidos"] += 1

        # Cargar nombres de pacientes
        pids = [c["paciente_id"] for c in conversaciones.values() if c["paciente_id"]]
        pacientes_map = {}
        if pids:
            for p in (await session.execute(
                select(Paciente).where(Paciente.id.in_(pids))
            )).scalars().all():
                pacientes_map[p.id] = p

        # Mensajes del chat seleccionado
        mensajes_chat: list = []
        paciente_actual = None
        if paciente_id:
            paciente_actual = pacientes_map.get(paciente_id)
            if not paciente_actual:
                paciente_actual = (await session.execute(
                    select(Paciente).where(Paciente.id == paciente_id).where(Paciente.clinica_id == clinica.id)
                )).scalar_one_or_none()
            if paciente_actual:
                mensajes_chat = list((await session.execute(
                    select(MensajeUnificado)
                    .where(MensajeUnificado.clinica_id == clinica.id)
                    .where(MensajeUnificado.paciente_id == paciente_id)
                    .order_by(MensajeUnificado.timestamp.asc())
                )).scalars().all())
                # Marcar como leídos los entrantes
                for m in mensajes_chat:
                    if not m.leido and m.direccion == "entrada":
                        m.leido = True
                await session.commit()

        # Plantillas para insertar
        plantillas = list((await session.execute(
            select(PlantillaRespuesta).where(PlantillaRespuesta.clinica_id == clinica.id)
            .order_by(desc(PlantillaRespuesta.usos)).limit(10)
        )).scalars().all())

    # === Conversaciones (sidebar izquierdo)
    conv_html = ""
    convs_ordenadas = sorted(
        conversaciones.values(),
        key=lambda c: c["ultimo_mensaje"].timestamp if c["ultimo_mensaje"] else datetime.min,
        reverse=True,
    )
    canal_icon = {"whatsapp": "💬", "instagram": "📷", "email": "✉️", "sms": "💬", "llamada": "📞"}
    for conv in convs_ordenadas:
        p = pacientes_map.get(conv["paciente_id"])
        if not p:
            continue
        ultimo = conv["ultimo_mensaje"]
        nombre = html.escape(p.nombre or "Sin nombre")
        preview = html.escape((ultimo.contenido or "")[:55])
        ts = ultimo.timestamp.strftime("%H:%M") if ultimo.timestamp else ""
        no_leidos = conv["no_leidos"]
        canales_icons = "".join(canal_icon.get(c, "·") for c in conv["canales"])
        activa = "background:var(--primary-light);border-left:3px solid var(--primary);" if paciente_id == p.id else ""
        badge_unread = f'<span style="background:var(--primary);color:white;font-size:11px;padding:1px 7px;border-radius:999px;font-weight:700;">{no_leidos}</span>' if no_leidos else ""
        conv_html += f"""
        <a href="/clinic/app/inbox?paciente_id={p.id}{('&canal=' + canal) if canal and canal != 'todos' else ''}"
           style="display:block;padding:12px 14px;border-bottom:1px solid var(--border);text-decoration:none;color:var(--text);{activa}">
          <div style="display:flex;justify-content:space-between;align-items:center;">
            <div style="font-weight:600;font-size:14px;">{nombre}</div>
            <div style="font-size:11px;color:var(--text-soft);">{ts}</div>
          </div>
          <div style="display:flex;justify-content:space-between;align-items:center;margin-top:4px;">
            <div style="font-size:12px;color:var(--text-soft);">{canales_icons} {preview}...</div>
            {badge_unread}
          </div>
        </a>"""

    if not conv_html:
        conv_html = """
        <div style="text-align:center;padding:40px 20px;color:var(--text-soft);">
          <div style="font-size:48px;">📭</div>
          <p style="margin-top:10px;font-size:13px;">Sin conversaciones todavía</p>
        </div>"""

    # === Chat (panel derecho)
    chat_html = ""
    if paciente_actual:
        bubbles = ""
        for m in mensajes_chat:
            es_salida = m.direccion == "salida"
            align = "flex-end" if es_salida else "flex-start"
            color = "var(--primary)" if es_salida else "white"
            text_color = "white" if es_salida else "var(--text)"
            ts = m.timestamp.strftime("%H:%M") if m.timestamp else ""
            icon = canal_icon.get(m.canal, "·")
            bubbles += f"""
            <div style="display:flex;justify-content:{align};margin-bottom:10px;">
              <div style="max-width:65%;background:{color};color:{text_color};padding:10px 14px;border-radius:14px;box-shadow:0 1px 2px rgba(0,0,0,0.06);">
                <div style="font-size:14px;line-height:1.4;">{html.escape(m.contenido or "")}</div>
                <div style="font-size:10px;opacity:0.7;margin-top:4px;text-align:right;">{icon} {ts}</div>
              </div>
            </div>"""
        if not bubbles:
            bubbles = '<div style="text-align:center;color:var(--text-soft);padding:40px;font-size:14px;">Sin mensajes con este paciente todavía</div>'

        opciones_plantilla = "".join(
            f'<option value="{html.escape(pl.contenido, quote=True)}">{html.escape(pl.titulo)}</option>'
            for pl in plantillas
        )
        # Construir el select de plantillas fuera del f-string para evitar líos de escape
        if plantillas:
            select_plantilla_html = (
                '<select onchange="var m=document.getElementById(\'msg\');m.value=this.value;this.value=\'\';" '
                'class="input" style="margin-bottom:8px;font-size:13px;">'
                '<option value="">Insertar plantilla...</option>'
                f'{opciones_plantilla}</select>'
            )
        else:
            select_plantilla_html = ""

        # Header del chat
        tel = html.escape(paciente_actual.telefono or "—")
        chat_html = f"""
        <div style="display:flex;flex-direction:column;height:100%;">
          <div style="padding:16px 20px;border-bottom:1px solid var(--border);background:white;display:flex;justify-content:space-between;align-items:center;">
            <div>
              <div style="font-weight:700;font-size:15px;">{html.escape(paciente_actual.nombre)}</div>
              <div style="font-size:12px;color:var(--text-soft);font-family:monospace;">{tel}</div>
            </div>
            <a href="/clinic/app/pacientes/{paciente_actual.id}" class="btn btn-ghost" style="padding:8px 14px;font-size:13px;">Ver ficha →</a>
          </div>
          <div style="flex:1;overflow-y:auto;padding:20px;background:#fafaf9;">
            {bubbles}
          </div>
          <div style="border-top:1px solid var(--border);padding:14px 16px;background:white;">
            <form method="post" action="/clinic/app/inbox/{paciente_actual.id}/responder" style="display:flex;gap:10px;align-items:flex-end;">
              <div style="flex:1;">
                {select_plantilla_html}
                <textarea id="msg" name="contenido" required rows="2" class="input"
                          style="resize:vertical;font-family:inherit;line-height:1.4;"
                          placeholder="Escribe un mensaje a {html.escape(paciente_actual.nombre)}..."></textarea>
              </div>
              <button type="submit" class="btn btn-primary" style="background:#25D366;box-shadow:0 4px 12px rgba(37,211,102,0.3);">📲 Enviar</button>
            </form>
          </div>
        </div>"""
    else:
        chat_html = """
        <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100%;color:var(--text-soft);text-align:center;padding:40px;">
          <div style="font-size:64px;margin-bottom:16px;">💬</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Selecciona una conversación</h3>
          <p style="font-size:14px;max-width:320px;">O conecta WhatsApp e Instagram en Configuración para empezar a recibir mensajes.</p>
        </div>"""

    # Filtros de canal
    canales_disponibles = [
        ("todos", "Todos", "📥"),
        ("whatsapp", "WhatsApp", "💬"),
        ("instagram", "Instagram", "📷"),
        ("email", "Email", "✉️"),
    ]
    filtros_html = ""
    for c, lab, ic in canales_disponibles:
        activo = (canal == c) or (not canal and c == "todos")
        bg = "var(--primary)" if activo else "transparent"
        col = "white" if activo else "var(--text)"
        filtros_html += f'<a href="/clinic/app/inbox?canal={c}" style="background:{bg};color:{col};border:1.5px solid {("var(--primary)" if activo else "var(--border)")};padding:6px 12px;border-radius:999px;font-size:12px;font-weight:600;text-decoration:none;display:inline-block;margin-right:6px;">{ic} {lab}</a>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Inbox - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("inbox", sesion, clinica)}
    <main class="main" style="padding:0;display:flex;flex-direction:column;height:100vh;">
      <div style="padding:20px 28px;border-bottom:1px solid var(--border);background:white;">
        <h1 style="font-size:22px;font-weight:800;margin-bottom:4px;">Inbox unificado</h1>
        <div style="margin-top:10px;">{filtros_html}</div>
      </div>
      <div style="flex:1;display:grid;grid-template-columns:340px 1fr;min-height:0;background:white;">
        <div style="border-right:1px solid var(--border);overflow-y:auto;">{conv_html}</div>
        <div>{chat_html}</div>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/inbox/{paciente_id}/responder", response_class=HTMLResponse)
async def responder_inbox(
    paciente_id: int,
    contenido: str = Form(...),
    clinic_session: Optional[str] = Cookie(None),
):
    """Envia un mensaje desde el inbox al paciente vía el canal de su última conversación."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    contenido = contenido.strip()
    if not contenido:
        return RedirectResponse(f"/clinic/app/inbox?paciente_id={paciente_id}", status_code=303)

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.id == sesion["clinica_id"])
        )).scalar_one_or_none()
        paciente = (await session.execute(
            select(Paciente).where(Paciente.id == paciente_id).where(Paciente.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if not paciente or not clinica:
            return RedirectResponse("/clinic/app/inbox", status_code=303)

        # Determinar canal del último mensaje (para responder por donde vino)
        ultimo = (await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.paciente_id == paciente_id)
            .order_by(desc(MensajeUnificado.timestamp))
            .limit(1)
        )).scalar_one_or_none()
        canal_resp = ultimo.canal if ultimo else "whatsapp"

        # Enviar por Meta WhatsApp API si el canal es whatsapp y hay token de la clínica
        if canal_resp == "whatsapp" and clinica.whatsapp_phone_id and clinica.whatsapp_token and paciente.telefono:
            try:
                import re as _re_mod
                import httpx as _httpx_mod
                tel = _re_mod.sub(r"\D", "", paciente.telefono)
                if not tel.startswith("57") and len(tel) == 10:
                    tel = f"57{tel}"
                async with _httpx_mod.AsyncClient(timeout=20.0) as client:
                    await client.post(
                        f"https://graph.facebook.com/v21.0/{clinica.whatsapp_phone_id}/messages",
                        headers={
                            "Authorization": f"Bearer {clinica.whatsapp_token}",
                            "Content-Type": "application/json",
                        },
                        json={
                            "messaging_product": "whatsapp",
                            "to": tel,
                            "type": "text",
                            "text": {"body": contenido},
                        },
                    )
            except Exception:
                pass  # Si falla el envío externo, igual guardamos en BD

        # Siempre guardar el mensaje en el inbox para el historial
        session.add(MensajeUnificado(
            clinica_id=sesion["clinica_id"],
            paciente_id=paciente_id,
            canal=canal_resp,
            direccion="salida",
            contenido=contenido,
            leido=True,
            respondido_por="usuario",
        ))
        paciente.ultimo_contacto = datetime.utcnow()
        paciente.total_mensajes = (paciente.total_mensajes or 0) + 1
        await session.commit()

    return RedirectResponse(f"/clinic/app/inbox?paciente_id={paciente_id}", status_code=303)


# ════════════════════════════════════════════════════════════
# 6) PACIENTES — CRUD completo
# ════════════════════════════════════════════════════════════

@router.get("/app/pacientes", response_class=HTMLResponse)
async def vista_pacientes(
    q: Optional[str] = None,
    creado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        query = select(Paciente).where(Paciente.clinica_id == clinica.id)
        if q:
            p = f"%{q}%"
            query = query.where(or_(
                Paciente.nombre.ilike(p),
                Paciente.telefono.ilike(p),
                Paciente.email.ilike(p),
            ))
        query = query.order_by(desc(Paciente.ultimo_contacto)).limit(200)
        pacientes = list((await session.execute(query)).scalars().all())

    if pacientes:
        filas = ""
        for p in pacientes:
            nombre = html.escape(p.nombre or "")
            tel = html.escape(p.telefono or "")
            email = html.escape(p.email or "")
            estado = html.escape(p.estado or "nuevo")
            ult = p.ultimo_contacto.strftime("%d/%m/%Y") if p.ultimo_contacto else "—"
            color_estado = {
                "nuevo": "#3B82F6", "activo": "#10B981",
                "inactivo": "#78716C", "dado_de_alta": "#A855F7",
            }.get(estado, "#78716C")
            filas += f"""
              <tr style="border-bottom:1px solid var(--border);transition:background 0.15s;"
                  onmouseover="this.style.background='var(--bg)'" onmouseout="this.style.background='transparent'">
                <td style="padding:14px;">
                  <a href="/clinic/app/pacientes/{p.id}" style="font-weight:600;color:var(--text);">{nombre}</a>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-family:monospace;font-size:13px;">{tel}</td>
                <td style="padding:14px;color:var(--text-soft);font-size:13px;">{email}</td>
                <td style="padding:14px;">
                  <span style="background:{color_estado}20;color:{color_estado};padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;">{estado}</span>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-size:13px;">{ult}</td>
              </tr>"""
        contenido = f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#1c1917;color:white;">
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Nombre</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Teléfono</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Email</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Estado</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Último contacto</th>
          </tr></thead>
          <tbody>{filas}</tbody>
        </table>"""
    else:
        contenido = """
        <div style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">👥</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin pacientes aún</h3>
          <p style="margin-bottom:24px;">Crea tu primer paciente manualmente o sincroniza con Google Sheets.</p>
          <div style="display:flex;gap:10px;justify-content:center;">
            <a href="/clinic/app/pacientes/nuevo" class="btn btn-primary">+ Nuevo paciente</a>
            <a href="/clinic/app/configuracion" class="btn btn-ghost">Conectar Google Sheets</a>
          </div>
        </div>"""

    creado_banner = ""
    if creado:
        creado_banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Paciente guardado correctamente</div>'

    q_val = html.escape(q or "", quote=True)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Pacientes - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:14px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Pacientes</h1>
          <p style="color:var(--text-soft);">{len(pacientes)} pacientes registrados</p>
        </div>
        <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
          <form method="get" action="/clinic/app/pacientes" style="display:flex;gap:8px;">
            <input type="text" name="q" value="{q_val}" placeholder="Buscar..." class="input" style="width:220px;">
            <button type="submit" class="btn btn-ghost">Buscar</button>
          </form>
          <a href="/clinic/app/pacientes/importar" class="btn btn-ghost" title="Importar CSV">↑ Importar</a>
          <a href="/clinic/app/pacientes-export" class="btn btn-ghost" title="Exportar CSV">↓ Exportar</a>
          <a href="/clinic/app/pacientes/nuevo" class="btn btn-primary">+ Nuevo</a>
        </div>
      </div>
      {creado_banner}
      <div class="card" style="padding:0;overflow:hidden;">{contenido}</div>
    </main>
  </div>
</body></html>""")


@router.get("/app/pacientes/nuevo", response_class=HTMLResponse)
async def nuevo_paciente_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Nuevo paciente - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes" style="font-size:13px;color:var(--text-soft);">← Volver a pacientes</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Nuevo paciente</h1>

      <div class="card" style="max-width:680px;">
        <form method="post" action="/clinic/app/pacientes/nuevo" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Nombre completo *</label>
            <input type="text" name="nombre" required class="input" autofocus>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Teléfono / WhatsApp</label>
              <input type="text" name="telefono" placeholder="+57 300 123 4567" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Email</label>
              <input type="email" name="email" class="input">
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Documento</label>
              <input type="text" name="documento" placeholder="CC 12345678" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Género</label>
              <select name="genero" class="input">
                <option value="">—</option>
                <option value="M">Masculino</option>
                <option value="F">Femenino</option>
                <option value="O">Otro</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Estado</label>
              <select name="estado" class="input">
                <option value="nuevo">Nuevo</option>
                <option value="activo">Activo</option>
                <option value="inactivo">Inactivo</option>
              </select>
            </div>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Tratamiento actual</label>
            <input type="text" name="tratamiento_actual" placeholder="Ortodoncia, Limpieza, etc." class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Alergias</label>
            <input type="text" name="alergias" placeholder="Penicilina, latex..." class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Notas básicas</label>
            <textarea name="notas_basicas" rows="3" class="input" style="resize:vertical;font-family:inherit;"
                      placeholder="Cualquier información relevante del paciente..."></textarea>
          </div>
          <div style="display:flex;gap:10px;margin-top:8px;">
            <button type="submit" class="btn btn-primary">Guardar paciente</button>
            <a href="/clinic/app/pacientes" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/pacientes/nuevo", response_class=HTMLResponse)
async def nuevo_paciente_procesar(
    nombre: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    documento: str = Form(""),
    genero: str = Form(""),
    estado: str = Form("nuevo"),
    tratamiento_actual: str = Form(""),
    alergias: str = Form(""),
    notas_basicas: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        ahora = datetime.utcnow()
        session.add(Paciente(
            clinica_id=sesion["clinica_id"],
            nombre=nombre.strip(),
            telefono=telefono.strip(),
            email=email.strip().lower(),
            documento=documento.strip(),
            genero=genero,
            estado=estado,
            tratamiento_actual=tratamiento_actual.strip(),
            alergias=alergias.strip(),
            notas_basicas=notas_basicas.strip(),
            fuente="manual",
            primer_contacto=ahora,
            ultimo_contacto=ahora,
        ))
        await session.commit()

    return RedirectResponse("/clinic/app/pacientes?creado=1", status_code=303)


@router.get("/app/pacientes/{paciente_id}", response_class=HTMLResponse)
async def detalle_paciente(
    paciente_id: int,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        paciente = (await session.execute(
            select(Paciente)
            .where(Paciente.id == paciente_id)
            .where(Paciente.clinica_id == clinica.id)
        )).scalar_one_or_none()

        if not paciente:
            return HTMLResponse("<h1>Paciente no encontrado</h1>", status_code=404)

        mensajes = list((await session.execute(
            select(MensajeUnificado)
            .where(MensajeUnificado.paciente_id == paciente_id)
            .order_by(desc(MensajeUnificado.timestamp))
            .limit(20)
        )).scalars().all())
        llamadas = list((await session.execute(
            select(Llamada).where(Llamada.paciente_id == paciente_id).order_by(desc(Llamada.timestamp))
        )).scalars().all())
        citas = list((await session.execute(
            select(CitaClinic).where(CitaClinic.paciente_id == paciente_id).order_by(desc(CitaClinic.fecha_hora))
        )).scalars().all())

    nombre = html.escape(paciente.nombre or "")
    tel = html.escape(paciente.telefono or "—")
    email = html.escape(paciente.email or "—")
    estado = html.escape(paciente.estado or "")
    color_estado = {
        "nuevo": "#3B82F6", "activo": "#10B981",
        "inactivo": "#78716C", "dado_de_alta": "#A855F7",
    }.get(estado, "#78716C")

    timeline_html = ""
    eventos = []
    for m in mensajes:
        eventos.append((m.timestamp, "💬", f"Mensaje {m.direccion} ({m.canal})",
                        html.escape((m.contenido or "")[:120])))
    for l in llamadas:
        eventos.append((l.timestamp, "📞", f"Llamada {l.direccion}",
                        html.escape((l.notas or "")[:120])))
    for c in citas:
        eventos.append((c.fecha_hora, "📅", f"Cita {c.estado}",
                        html.escape((c.motivo or "")[:120])))
    eventos.sort(key=lambda x: x[0] or datetime.min, reverse=True)

    if eventos:
        for ts, icon, titulo, texto in eventos[:20]:
            fecha = ts.strftime("%d/%m/%Y %H:%M") if ts else ""
            timeline_html += f"""
            <div style="display:flex;gap:14px;padding:14px 0;border-bottom:1px solid var(--border);">
              <div style="font-size:22px;">{icon}</div>
              <div style="flex:1;">
                <div style="font-weight:600;font-size:14px;">{titulo}</div>
                <div style="font-size:13px;color:var(--text-soft);margin-top:2px;">{texto}</div>
                <div style="font-size:11px;color:var(--text-soft);margin-top:4px;">{fecha}</div>
              </div>
            </div>"""
    else:
        timeline_html = '<div style="text-align:center;padding:40px;color:var(--text-soft);"><div style="font-size:48px;">⏳</div><p style="margin-top:10px;">Sin actividad todavía</p></div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>{nombre} - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes" style="font-size:13px;color:var(--text-soft);">← Pacientes</a>
      <div style="display:flex;justify-content:space-between;align-items:center;margin:8px 0 24px;flex-wrap:wrap;gap:14px;">
        <div>
          <h1 style="font-size:28px;font-weight:800;">{nombre}</h1>
          <div style="display:flex;gap:10px;margin-top:6px;align-items:center;">
            <span style="background:{color_estado}20;color:{color_estado};padding:4px 12px;border-radius:999px;font-size:12px;font-weight:700;text-transform:uppercase;">{estado}</span>
            <span style="color:var(--text-soft);font-size:13px;">{html.escape(paciente.tratamiento_actual or "Sin tratamiento")}</span>
          </div>
        </div>
        <div style="display:flex;gap:10px;">
          {f'<a href="https://wa.me/{html.escape(paciente.telefono.replace("+", "").replace(" ", ""))}" target="_blank" class="btn btn-primary" style="background:#25D366;box-shadow:0 4px 12px rgba(37,211,102,0.25);">💬 WhatsApp</a>' if paciente.telefono else ''}
          <a href="/clinic/app/pacientes/{paciente.id}/editar" class="btn btn-ghost">✏️ Editar</a>
        </div>
      </div>

      <div style="display:grid;grid-template-columns:1fr 1fr;gap:18px;">
        <div class="card">
          <h3 style="font-size:14px;font-weight:700;text-transform:uppercase;color:var(--text-soft);letter-spacing:1px;margin-bottom:14px;">📇 Contacto</h3>
          <div style="display:grid;gap:10px;font-size:14px;">
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Teléfono</strong> <span style="font-family:monospace;">{tel}</span></div>
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Email</strong> {email}</div>
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Documento</strong> {html.escape(paciente.documento or "—")}</div>
            <div><strong style="display:inline-block;width:120px;color:var(--text-soft);">Alergias</strong> {html.escape(paciente.alergias or "—")}</div>
          </div>
          <div style="margin-top:18px;border-top:1px solid var(--border);padding-top:14px;">
            <strong style="color:var(--text-soft);font-size:13px;display:block;margin-bottom:6px;">📝 Notas</strong>
            <p style="font-size:14px;line-height:1.6;color:var(--text);">{html.escape(paciente.notas_basicas or "Sin notas todavía.")}</p>
          </div>
        </div>

        <div class="card">
          <h3 style="font-size:14px;font-weight:700;text-transform:uppercase;color:var(--text-soft);letter-spacing:1px;margin-bottom:14px;">⏱️ Timeline</h3>
          {timeline_html}
        </div>
      </div>

      <div style="margin-top:18px;display:grid;grid-template-columns:repeat(4,1fr);gap:12px;">
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Mensajes</div>
          <div style="font-size:28px;font-weight:800;color:var(--primary);margin-top:4px;">{len(mensajes)}</div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Llamadas</div>
          <div style="font-size:28px;font-weight:800;margin-top:4px;">{len(llamadas)}</div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Citas</div>
          <div style="font-size:28px;font-weight:800;margin-top:4px;">{len(citas)}</div>
        </div>
        <div class="card" style="text-align:center;">
          <div style="font-size:11px;color:var(--text-soft);text-transform:uppercase;letter-spacing:1px;font-weight:700;">Valor total</div>
          <div style="font-size:28px;font-weight:800;color:var(--green);margin-top:4px;">${paciente.valor_total:,}</div>
        </div>
      </div>
    </main>
  </div>
</body></html>""")


@router.get("/app/pacientes/{paciente_id}/editar", response_class=HTMLResponse)
async def editar_paciente_form(
    paciente_id: int,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        p = (await session.execute(
            select(Paciente).where(Paciente.id == paciente_id).where(Paciente.clinica_id == clinica.id)
        )).scalar_one_or_none()
        if not p:
            return HTMLResponse("<h1>Paciente no encontrado</h1>", status_code=404)

    def esc(s): return html.escape(s or "", quote=True)
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Editar {esc(p.nombre)}</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes/{p.id}" style="font-size:13px;color:var(--text-soft);">← Volver al paciente</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Editar paciente</h1>
      <div class="card" style="max-width:680px;">
        <form method="post" action="/clinic/app/pacientes/{p.id}/editar" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Nombre completo *</label>
            <input type="text" name="nombre" value="{esc(p.nombre)}" required class="input">
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Teléfono</label>
              <input type="text" name="telefono" value="{esc(p.telefono)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Email</label>
              <input type="email" name="email" value="{esc(p.email)}" class="input">
            </div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Documento</label>
              <input type="text" name="documento" value="{esc(p.documento)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Género</label>
              <select name="genero" class="input">
                <option value="" {'selected' if not p.genero else ''}>—</option>
                <option value="M" {'selected' if p.genero == 'M' else ''}>Masculino</option>
                <option value="F" {'selected' if p.genero == 'F' else ''}>Femenino</option>
                <option value="O" {'selected' if p.genero == 'O' else ''}>Otro</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Estado</label>
              <select name="estado" class="input">
                <option value="nuevo" {'selected' if p.estado == 'nuevo' else ''}>Nuevo</option>
                <option value="activo" {'selected' if p.estado == 'activo' else ''}>Activo</option>
                <option value="inactivo" {'selected' if p.estado == 'inactivo' else ''}>Inactivo</option>
                <option value="dado_de_alta" {'selected' if p.estado == 'dado_de_alta' else ''}>Dado de alta</option>
              </select>
            </div>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Tratamiento actual</label>
            <input type="text" name="tratamiento_actual" value="{esc(p.tratamiento_actual)}" class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Alergias</label>
            <input type="text" name="alergias" value="{esc(p.alergias)}" class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Notas</label>
            <textarea name="notas_basicas" rows="4" class="input" style="resize:vertical;font-family:inherit;">{esc(p.notas_basicas)}</textarea>
          </div>
          <div style="display:flex;gap:10px;margin-top:8px;justify-content:space-between;">
            <div style="display:flex;gap:10px;">
              <button type="submit" class="btn btn-primary">Guardar cambios</button>
              <a href="/clinic/app/pacientes/{p.id}" class="btn btn-ghost">Cancelar</a>
            </div>
            <form method="post" action="/clinic/app/pacientes/{p.id}/eliminar"
                  onsubmit="return confirm('¿Eliminar paciente {esc(p.nombre)}? Esta acción NO se puede deshacer.');">
              <button type="submit" style="background:transparent;color:#EF4444;border:1.5px solid #EF4444;padding:12px 22px;border-radius:10px;font-weight:600;cursor:pointer;">🗑️ Eliminar</button>
            </form>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/pacientes/{paciente_id}/editar", response_class=HTMLResponse)
async def editar_paciente_procesar(
    paciente_id: int,
    nombre: str = Form(...),
    telefono: str = Form(""),
    email: str = Form(""),
    documento: str = Form(""),
    genero: str = Form(""),
    estado: str = Form("nuevo"),
    tratamiento_actual: str = Form(""),
    alergias: str = Form(""),
    notas_basicas: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        p = (await session.execute(
            select(Paciente)
            .where(Paciente.id == paciente_id)
            .where(Paciente.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if not p:
            return HTMLResponse("<h1>Paciente no encontrado</h1>", status_code=404)
        p.nombre = nombre.strip()
        p.telefono = telefono.strip()
        p.email = email.strip().lower()
        p.documento = documento.strip()
        p.genero = genero
        p.estado = estado
        p.tratamiento_actual = tratamiento_actual.strip()
        p.alergias = alergias.strip()
        p.notas_basicas = notas_basicas.strip()
        await session.commit()

    return RedirectResponse(f"/clinic/app/pacientes/{paciente_id}", status_code=303)


@router.post("/app/pacientes/{paciente_id}/eliminar", response_class=HTMLResponse)
async def eliminar_paciente(
    paciente_id: int,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        p = (await session.execute(
            select(Paciente)
            .where(Paciente.id == paciente_id)
            .where(Paciente.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if p:
            await session.delete(p)
            await session.commit()

    return RedirectResponse("/clinic/app/pacientes", status_code=303)


# ════════════════════════════════════════════════════════════
# 7) LLAMADAS, PLANTILLAS, CONFIG — mockups MVP
# ════════════════════════════════════════════════════════════

def _vista_simple(titulo: str, descripcion: str, icono: str, cta_url: str, cta_label: str, sesion: dict, clinica: Clinica, activa: str) -> HTMLResponse:
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>{html.escape(titulo)} - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic(activa, sesion, clinica)}
    <main class="main">
      <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">{html.escape(titulo)}</h1>
      <p style="color:var(--text-soft);margin-bottom:24px;">{html.escape(descripcion)}</p>
      <div class="card" style="text-align:center;padding:60px 20px;">
        <div style="font-size:64px;margin-bottom:16px;">{icono}</div>
        <p style="color:var(--text-soft);max-width:400px;margin:0 auto 24px;">Esta sección se habilita en los próximos días del MVP.</p>
        <a href="{cta_url}" class="btn btn-primary">{html.escape(cta_label)}</a>
      </div>
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 7) LLAMADAS — Bitácora con CRUD
# ════════════════════════════════════════════════════════════

@router.get("/app/llamadas", response_class=HTMLResponse)
async def vista_llamadas(
    creado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        llamadas = list((await session.execute(
            select(Llamada).where(Llamada.clinica_id == clinica.id).order_by(desc(Llamada.timestamp)).limit(200)
        )).scalars().all())
        # Pre-cargar nombres de pacientes
        pids = [l.paciente_id for l in llamadas if l.paciente_id]
        nombres = {}
        if pids:
            for p in (await session.execute(
                select(Paciente.id, Paciente.nombre).where(Paciente.id.in_(pids))
            )).all():
                nombres[p[0]] = p[1]

    icon_dir = {"entrada": "📥", "salida": "📤", "perdida": "❌"}
    color_resultado = {
        "interesado": "#10B981", "agendado": "#3B82F6",
        "no_interesado": "#EF4444", "volver_a_llamar": "#F59E0B",
    }

    if llamadas:
        filas = ""
        for l in llamadas:
            nombre = html.escape(nombres.get(l.paciente_id, "—"))
            dir_icon = icon_dir.get(l.direccion, "📞")
            duracion = f"{l.duracion_seg // 60}:{l.duracion_seg % 60:02d}" if l.duracion_seg else "—"
            color_r = color_resultado.get(l.resultado, "#78716C")
            resultado = html.escape(l.resultado or "—")
            ts = l.timestamp.strftime("%d/%m %H:%M") if l.timestamp else "—"
            notas = html.escape((l.notas or "")[:80])
            filas += f"""
              <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:14px;font-size:18px;">{dir_icon}</td>
                <td style="padding:14px;">
                  <a href="/clinic/app/pacientes/{l.paciente_id}" style="font-weight:600;color:var(--text);">{nombre}</a>
                  <div style="font-size:12px;color:var(--text-soft);margin-top:2px;">{notas}</div>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-family:monospace;">{duracion}</td>
                <td style="padding:14px;">
                  <span style="background:{color_r}20;color:{color_r};padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;">{resultado}</span>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-size:13px;">{ts}</td>
              </tr>"""
        contenido = f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#1c1917;color:white;">
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;width:50px;"></th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Paciente / Notas</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Duración</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Resultado</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Fecha</th>
          </tr></thead>
          <tbody>{filas}</tbody>
        </table>"""
    else:
        contenido = """
        <div style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">📞</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin llamadas registradas</h3>
          <p style="margin-bottom:24px;">Registra cada llamada con tus pacientes para no perder seguimiento.</p>
          <a href="/clinic/app/llamadas/nueva" class="btn btn-primary">+ Registrar llamada</a>
        </div>"""

    banner = ""
    if creado:
        banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Llamada registrada correctamente</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Llamadas - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("llamadas", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Llamadas</h1>
          <p style="color:var(--text-soft);">{len(llamadas)} llamadas registradas</p>
        </div>
        <a href="/clinic/app/llamadas/nueva" class="btn btn-primary">+ Registrar llamada</a>
      </div>
      {banner}
      <div class="card" style="padding:0;overflow:hidden;">{contenido}</div>
    </main>
  </div>
</body></html>""")


@router.get("/app/llamadas/nueva", response_class=HTMLResponse)
async def nueva_llamada_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        pacientes = list((await session.execute(
            select(Paciente).where(Paciente.clinica_id == clinica.id).order_by(Paciente.nombre).limit(500)
        )).scalars().all())

    opciones = "".join(f'<option value="{p.id}">{html.escape(p.nombre)} ({html.escape(p.telefono or "")})</option>' for p in pacientes)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Nueva llamada - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("llamadas", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/llamadas" style="font-size:13px;color:var(--text-soft);">← Volver</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Registrar llamada</h1>
      <div class="card" style="max-width:560px;">
        <form method="post" action="/clinic/app/llamadas/nueva" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Paciente *</label>
            <select name="paciente_id" required class="input" autofocus>
              <option value="">Selecciona un paciente...</option>
              {opciones}
            </select>
            {('<p style="font-size:12px;color:var(--text-soft);margin-top:6px;">No tienes pacientes todavía. <a href="/clinic/app/pacientes/nuevo">Crear uno</a> primero.</p>' if not pacientes else '')}
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Dirección</label>
              <select name="direccion" class="input">
                <option value="entrada">📥 Entrada</option>
                <option value="salida">📤 Salida</option>
                <option value="perdida">❌ Perdida</option>
              </select>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Duración (min)</label>
              <input type="number" name="duracion_min" min="0" placeholder="5" class="input">
            </div>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Resultado</label>
            <select name="resultado" class="input">
              <option value="">—</option>
              <option value="interesado">✓ Interesado</option>
              <option value="agendado">📅 Agendado</option>
              <option value="volver_a_llamar">🔄 Volver a llamar</option>
              <option value="no_interesado">✗ No interesado</option>
            </select>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Notas</label>
            <textarea name="notas" rows="4" class="input" style="resize:vertical;font-family:inherit;"
                      placeholder="Qué pidió el paciente, qué se acordó, próximos pasos..."></textarea>
          </div>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary" {('disabled' if not pacientes else '')}>Guardar</button>
            <a href="/clinic/app/llamadas" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/llamadas/nueva", response_class=HTMLResponse)
async def nueva_llamada_procesar(
    paciente_id: int = Form(...),
    direccion: str = Form("entrada"),
    duracion_min: int = Form(0),
    resultado: str = Form(""),
    notas: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        session.add(Llamada(
            clinica_id=sesion["clinica_id"],
            paciente_id=paciente_id,
            direccion=direccion,
            duracion_seg=duracion_min * 60,
            resultado=resultado,
            notas=notas.strip(),
        ))
        await session.commit()

    return RedirectResponse("/clinic/app/llamadas?creado=1", status_code=303)


# ════════════════════════════════════════════════════════════
# 8) PLANTILLAS — Respuestas rápidas
# ════════════════════════════════════════════════════════════

@router.get("/app/plantillas", response_class=HTMLResponse)
async def vista_plantillas(
    creado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        plantillas = list((await session.execute(
            select(PlantillaRespuesta).where(PlantillaRespuesta.clinica_id == clinica.id)
            .order_by(desc(PlantillaRespuesta.usos))
        )).scalars().all())

    if plantillas:
        cards = ""
        for pl in plantillas:
            cards += f"""
            <div class="card" style="margin-bottom:12px;">
              <div style="display:flex;justify-content:space-between;align-items:start;gap:14px;">
                <div style="flex:1;">
                  <h3 style="font-size:15px;font-weight:700;margin-bottom:4px;">{html.escape(pl.titulo)}</h3>
                  <div style="font-size:12px;color:var(--text-soft);margin-bottom:10px;">
                    Categoría: {html.escape(pl.categoria or "general")} · Usada {pl.usos} veces
                  </div>
                  <p style="font-size:14px;line-height:1.5;color:var(--text);white-space:pre-wrap;">{html.escape(pl.contenido)}</p>
                </div>
                <form method="post" action="/clinic/app/plantillas/{pl.id}/eliminar"
                      onsubmit="return confirm('¿Eliminar esta plantilla?');">
                  <button type="submit" style="background:transparent;color:#EF4444;border:1px solid #EF4444;padding:6px 12px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">🗑️</button>
                </form>
              </div>
            </div>"""
        contenido = cards
    else:
        contenido = """
        <div class="card" style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">📝</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin plantillas todavía</h3>
          <p style="margin-bottom:24px;">Crea respuestas rápidas para preguntas frecuentes (precios, horarios, ubicación).</p>
          <a href="/clinic/app/plantillas/nueva" class="btn btn-primary">+ Crear plantilla</a>
        </div>"""

    banner = ""
    if creado:
        banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Plantilla guardada correctamente</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Plantillas - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("plantillas", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Plantillas</h1>
          <p style="color:var(--text-soft);">{len(plantillas)} respuestas rápidas</p>
        </div>
        <a href="/clinic/app/plantillas/nueva" class="btn btn-primary">+ Nueva plantilla</a>
      </div>
      {banner}
      {contenido}
    </main>
  </div>
</body></html>""")


@router.get("/app/plantillas/nueva", response_class=HTMLResponse)
async def nueva_plantilla_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Nueva plantilla - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("plantillas", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/plantillas" style="font-size:13px;color:var(--text-soft);">← Volver</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Nueva plantilla</h1>
      <div class="card" style="max-width:680px;">
        <form method="post" action="/clinic/app/plantillas/nueva" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Título *</label>
            <input type="text" name="titulo" required placeholder="Ej: Saludo inicial" class="input" autofocus>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Categoría</label>
            <select name="categoria" class="input">
              <option value="general">General</option>
              <option value="saludo">Saludo</option>
              <option value="precios">Precios</option>
              <option value="horarios">Horarios</option>
              <option value="ubicacion">Ubicación</option>
              <option value="confirmacion">Confirmación</option>
              <option value="seguimiento">Seguimiento</option>
            </select>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Contenido *</label>
            <textarea name="contenido" required rows="6" class="input" style="resize:vertical;font-family:inherit;"
                      placeholder="¡Hola! Gracias por escribir a {{clinica}}. ¿En qué puedo ayudarte hoy?"></textarea>
            <p style="font-size:12px;color:var(--text-soft);margin-top:6px;">
              💡 Tip: Usá <code>{{nombre}}</code>, <code>{{clinica}}</code>, <code>{{tratamiento}}</code> como variables.
            </p>
          </div>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary">Guardar plantilla</button>
            <a href="/clinic/app/plantillas" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/plantillas/nueva", response_class=HTMLResponse)
async def nueva_plantilla_procesar(
    titulo: str = Form(...),
    categoria: str = Form("general"),
    contenido: str = Form(...),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        session.add(PlantillaRespuesta(
            clinica_id=sesion["clinica_id"],
            titulo=titulo.strip(),
            categoria=categoria,
            contenido=contenido.strip(),
        ))
        await session.commit()

    return RedirectResponse("/clinic/app/plantillas?creado=1", status_code=303)


@router.post("/app/plantillas/{pid}/eliminar")
async def eliminar_plantilla(pid: int, clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        pl = (await session.execute(
            select(PlantillaRespuesta)
            .where(PlantillaRespuesta.id == pid)
            .where(PlantillaRespuesta.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if pl:
            await session.delete(pl)
            await session.commit()

    return RedirectResponse("/clinic/app/plantillas", status_code=303)


# ════════════════════════════════════════════════════════════
# 9) CONFIGURACIÓN — Integraciones y branding
# ════════════════════════════════════════════════════════════

@router.get("/app/configuracion", response_class=HTMLResponse)
async def vista_config(
    guardado: Optional[str] = None,
    sync_creados: Optional[int] = None,
    sync_actualizados: Optional[int] = None,
    error: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    def esc(s): return html.escape(s or "", quote=True)
    wa_conectado = bool(clinica.whatsapp_phone_id)
    ig_conectado = bool(clinica.instagram_account_id)
    sheets_conectado = bool(clinica.google_sheet_id)

    banner = ""
    if error:
        banner = f'<div style="background:#FEE2E2;border:1px solid #EF4444;color:#7F1D1D;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;">⚠ {html.escape(error)}</div>'
    elif sync_creados is not None or sync_actualizados is not None:
        banner = f'<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Sincronización completa: <strong>{sync_creados or 0}</strong> nuevos pacientes · <strong>{sync_actualizados or 0}</strong> actualizados</div>'
    elif guardado:
        banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Configuración guardada</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Configuración - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("config", sesion, clinica)}
    <main class="main">
      <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Configuración</h1>
      <p style="color:var(--text-soft);margin-bottom:24px;">Conecta tus canales y personaliza tu cuenta</p>
      {banner}

      <form method="post" action="/clinic/app/configuracion" style="display:flex;flex-direction:column;gap:18px;max-width:780px;">

        <!-- DATOS BASE -->
        <div class="card">
          <h2 style="font-size:16px;font-weight:700;margin-bottom:14px;">📋 Datos del consultorio</h2>
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Nombre</label>
              <input type="text" name="nombre" value="{esc(clinica.nombre)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Ciudad</label>
              <input type="text" name="ciudad" value="{esc(clinica.ciudad)}" class="input">
            </div>
          </div>
          <div style="margin-top:12px;">
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Especialidad</label>
            <input type="text" name="especialidad" value="{esc(clinica.especialidad)}" class="input">
          </div>
        </div>

        <!-- WHATSAPP -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">💬 WhatsApp Business Cloud API</h2>
            <span class="badge {'badge-pro' if wa_conectado else 'badge-free'}">{'CONECTADO' if wa_conectado else 'NO CONECTADO'}</span>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            Conectá tu número de WhatsApp Business para recibir mensajes en el inbox. <br>
            Necesitás <a href="https://developers.facebook.com" target="_blank">credenciales de Meta for Developers</a>.
          </p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Phone Number ID</label>
              <input type="text" name="whatsapp_phone_id" value="{esc(clinica.whatsapp_phone_id)}" placeholder="123456789012345" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Access Token</label>
              <input type="password" name="whatsapp_token" value="{esc(clinica.whatsapp_token)}" placeholder="EAAm..." class="input">
            </div>
          </div>
        </div>

        <!-- INSTAGRAM -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">📷 Instagram DMs</h2>
            <span class="badge {'badge-pro' if ig_conectado else 'badge-free'}">{'CONECTADO' if ig_conectado else 'NO CONECTADO'}</span>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            Recibí mensajes directos de Instagram en el inbox unificado.
          </p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Instagram Account ID</label>
              <input type="text" name="instagram_account_id" value="{esc(clinica.instagram_account_id)}" class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Access Token</label>
              <input type="password" name="instagram_token" value="{esc(clinica.instagram_token)}" class="input">
            </div>
          </div>
        </div>

        <!-- GOOGLE SHEETS -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">📊 Google Sheets — Sync de pacientes</h2>
            <span class="badge {'badge-pro' if sheets_conectado else 'badge-free'}">{'CONECTADO' if sheets_conectado else 'NO CONECTADO'}</span>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            Sincronizá tus pacientes desde una hoja de Google Sheets. La hoja debe tener columnas:
            <code>nombre, telefono, email, tratamiento, notas</code>.
          </p>
          <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Sheet ID o URL completa</label>
          <input type="text" name="google_sheet_id" value="{esc(clinica.google_sheet_id)}" placeholder="https://docs.google.com/spreadsheets/d/..." class="input">
          <p style="font-size:12px;color:var(--text-soft);margin-top:8px;">
            📌 La hoja debe estar configurada como <strong>"Cualquiera con el enlace puede ver"</strong>.
          </p>
          {('<button type="button" onclick="syncSheets()" style="background:#3B82F6;color:white;border:none;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;margin-top:12px;">↻ Sincronizar ahora</button>' if clinica.google_sheet_id else '')}
        </div>

        <!-- GOOGLE CALENDAR -->
        <div class="card">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">📅 Google Calendar — Agendar citas reales</h2>
            <span class="badge {'badge-pro' if clinica.google_calendar_id else 'badge-free'}">{'CONECTADO' if clinica.google_calendar_id else 'NO CONECTADO'}</span>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            Conecta tu Google Calendar para que las citas se sincronicen y se cree Google Meet automáticamente.
          </p>
          <div style="background:#FEF3C7;border:1px solid #FCD34D;color:#78350F;padding:12px 14px;border-radius:10px;margin-bottom:14px;font-size:13px;line-height:1.6;">
            <strong>📋 Pasos para conectar:</strong>
            <ol style="margin:8px 0 0 18px;font-size:13px;">
              <li>Abre tu Google Calendar (calendar.google.com)</li>
              <li>Configuración del calendar que quieres usar → "Compartir con personas específicas"</li>
              <li>Agrega este email: <code style="background:white;padding:2px 6px;border-radius:4px;font-weight:700;">{esc(get_sa_email())}</code></li>
              <li>Permisos: <strong>"Hacer cambios y administrar uso compartido"</strong></li>
              <li>Copia el <strong>Calendar ID</strong> (igual al email de Google si es tu calendar principal)</li>
              <li>Pégalo abajo y guarda</li>
            </ol>
          </div>
          <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Calendar ID</label>
          <input type="text" name="google_calendar_id" value="{esc(clinica.google_calendar_id)}" placeholder="tucorreo@gmail.com o ID@group.calendar.google.com" class="input">
        </div>

        <!-- IA SOFIA PER-TENANT -->
        <div class="card" id="ia-config" style="border:2px solid {'#10B981' if clinica.ia_activa else '#E5E7EB'};">
          <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
            <h2 style="font-size:16px;font-weight:700;">🤖 IA SofIA — Tu asistente 24/7</h2>
            <label style="display:flex;align-items:center;gap:10px;cursor:pointer;user-select:none;">
              <input type="checkbox" name="ia_activa" value="1" {'checked' if clinica.ia_activa else ''} style="width:44px;height:24px;cursor:pointer;accent-color:#10B981;">
              <span style="font-size:13px;font-weight:700;color:{'#10B981' if clinica.ia_activa else '#6B7280'};">{'ACTIVA' if clinica.ia_activa else 'INACTIVA'}</span>
            </label>
          </div>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;line-height:1.6;">
            Cuando está <strong>activa</strong>, SofIA responde automáticamente a los mensajes de WhatsApp en {'menos de 5 segundos' if wa_conectado else '... pero primero configurá WhatsApp arriba ↑'}.
            Si un paciente pide hablar con humano, SofIA le pasa el mensaje al equipo y deja de responder.
          </p>

          <div style="display:flex;flex-direction:column;gap:14px;{'opacity:0.5;pointer-events:none;' if not wa_conectado else ''}">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Saludo inicial</label>
              <input type="text" name="ia_saludo" value="{esc(clinica.ia_saludo)}" placeholder="¡Hola! Soy SofIA, asistente virtual de {esc(clinica.nombre or 'tu clínica')}. ¿En qué te puedo ayudar?" class="input">
              <p style="font-size:11px;color:var(--text-soft);margin-top:4px;">Primera frase que usa SofIA al saludar a un paciente nuevo.</p>
            </div>

            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Horario de atención</label>
              <input type="text" name="ia_horario" value="{esc(clinica.ia_horario)}" placeholder="Lunes a viernes 8am-6pm, sábados 9am-1pm" class="input">
            </div>

            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Servicios que ofrece</label>
              <textarea name="ia_servicios" rows="3" placeholder="Ortodoncia, blanqueamiento dental, limpieza profesional, implantes, periodoncia..." class="input" style="font-family:inherit;resize:vertical;">{esc(clinica.ia_servicios)}</textarea>
              <p style="font-size:11px;color:var(--text-soft);margin-top:4px;">SofIA mencionará estos servicios cuando un paciente pregunte qué hacen.</p>
            </div>

            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Precios públicos (opcional)</label>
              <textarea name="ia_precios_basicos" rows="4" placeholder="Consulta inicial: $80.000&#10;Limpieza dental: $150.000&#10;Blanqueamiento: $450.000" class="input" style="font-family:inherit;resize:vertical;">{esc(clinica.ia_precios_basicos)}</textarea>
              <p style="font-size:11px;color:var(--text-soft);margin-top:4px;">⚠ SofIA NUNCA inventa precios. Si lo dejás vacío, cuando pregunten precios responderá que un asesor humano les contactará.</p>
            </div>

            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Instrucciones extra (opcional)</label>
              <textarea name="ia_instrucciones_extra" rows="3" placeholder="Reglas custom: no agendes citas los lunes, siempre menciona la promoción del mes, etc." class="input" style="font-family:inherit;resize:vertical;">{esc(clinica.ia_instrucciones_extra)}</textarea>
            </div>
          </div>

          {'' if wa_conectado else '<div style="background:#FEF3C7;border:1px solid #FCD34D;color:#78350F;padding:10px 14px;border-radius:8px;margin-top:10px;font-size:13px;">⚠ Configurá WhatsApp arriba antes de activar SofIA.</div>'}
        </div>

        <!-- BRANDING (solo Pro y Studio) -->
        <div class="card">
          <h2 style="font-size:16px;font-weight:700;margin-bottom:6px;">🎨 Branding</h2>
          <p style="font-size:13px;color:var(--text-soft);margin-bottom:14px;">
            {('Plan Studio: tu logo + dominio propio.' if clinica.plan == 'studio' else
              'Plan Pro: personalizá colores y logo. <a href="#">Upgrade</a> para dominio propio.' if clinica.plan == 'pro' else
              'Plan Free: incluye marca Lapora. <a href="#">Upgrade a Pro</a> para personalizar.')}
          </p>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">URL del logo</label>
              <input type="url" name="logo_url" value="{esc(clinica.logo_url)}" placeholder="https://..." class="input" {'disabled' if clinica.plan == 'free' else ''}>
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Color primario</label>
              <input type="color" name="color_primario" value="{esc(clinica.color_primario) or '#FF3B30'}" class="input" style="height:46px;" {'disabled' if clinica.plan == 'free' else ''}>
            </div>
          </div>
        </div>

        <div style="display:flex;justify-content:flex-end;gap:10px;">
          <a href="/clinic/app/" class="btn btn-ghost">Cancelar</a>
          <button type="submit" class="btn btn-primary">Guardar configuración</button>
        </div>
      </form>

      <script>
        function syncSheets() {{
          if (!confirm('¿Sincronizar pacientes desde Google Sheets ahora?')) return;
          fetch('/clinic/app/configuracion/sync-sheets', {{ method: 'POST', credentials: 'same-origin' }})
            .then(() => window.location.reload())
            .catch(e => alert('Error: ' + e));
        }}
      </script>
    </main>
  </div>
</body></html>""")


@router.post("/app/configuracion", response_class=HTMLResponse)
async def guardar_config(
    nombre: str = Form(""),
    ciudad: str = Form(""),
    especialidad: str = Form(""),
    whatsapp_phone_id: str = Form(""),
    whatsapp_token: str = Form(""),
    instagram_account_id: str = Form(""),
    instagram_token: str = Form(""),
    google_sheet_id: str = Form(""),
    google_calendar_id: str = Form(""),
    logo_url: str = Form(""),
    color_primario: str = Form("#FF3B30"),
    # IA SofIA per-tenant
    ia_activa: Optional[str] = Form(None),
    ia_saludo: str = Form(""),
    ia_servicios: str = Form(""),
    ia_horario: str = Form(""),
    ia_precios_basicos: str = Form(""),
    ia_instrucciones_extra: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        c = (await session.execute(
            select(Clinica).where(Clinica.id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if c:
            if nombre.strip(): c.nombre = nombre.strip()
            c.ciudad = ciudad.strip()
            c.especialidad = especialidad.strip()
            # Solo guardar token nuevo si lo enviaron (no sobrescribir con vacío)
            if whatsapp_phone_id.strip(): c.whatsapp_phone_id = whatsapp_phone_id.strip()
            if whatsapp_token.strip(): c.whatsapp_token = whatsapp_token.strip()
            if instagram_account_id.strip(): c.instagram_account_id = instagram_account_id.strip()
            if instagram_token.strip(): c.instagram_token = instagram_token.strip()
            c.google_sheet_id = google_sheet_id.strip()
            c.google_calendar_id = google_calendar_id.strip()
            if c.plan != "free":
                c.logo_url = logo_url.strip()
                c.color_primario = color_primario

            # IA SofIA: solo se puede activar si tiene WhatsApp configurado
            nueva_ia_activa = (ia_activa == "1") and bool(c.whatsapp_phone_id and c.whatsapp_token)
            c.ia_activa = nueva_ia_activa
            c.ia_saludo = ia_saludo.strip()[:500]
            c.ia_servicios = ia_servicios.strip()[:5000]
            c.ia_horario = ia_horario.strip()[:300]
            c.ia_precios_basicos = ia_precios_basicos.strip()[:5000]
            c.ia_instrucciones_extra = ia_instrucciones_extra.strip()[:5000]

            c.actualizado_en = datetime.utcnow()
            await session.commit()

    return RedirectResponse("/clinic/app/configuracion?guardado=1", status_code=303)


# ════════════════════════════════════════════════════════════
# 10) SYNC GOOGLE SHEETS — Import pacientes desde una hoja publica
# ════════════════════════════════════════════════════════════

@router.post("/app/configuracion/sync-sheets", response_class=HTMLResponse)
async def sync_google_sheets(clinic_session: Optional[str] = Cookie(None)):
    """Sincroniza pacientes desde Google Sheets (botón manual).

    Reusa la misma función que el worker periódico de clinic_workers.py.
    La hoja debe ser pública. Columnas: nombre, telefono, email, tratamiento, notas.
    """
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if not clinica or not clinica.google_sheet_id:
            return RedirectResponse(
                "/clinic/app/configuracion?error=Configura+primero+el+Sheet+ID",
                status_code=303,
            )

    # Reusar lógica del worker (sin duplicar código)
    from agent.clinic_workers import sincronizar_sheet_clinica
    resultado = await sincronizar_sheet_clinica(clinica)
    if not resultado["exito"]:
        return RedirectResponse(
            f"/clinic/app/configuracion?error={html.escape(resultado['error'][:100])}",
            status_code=303,
        )
    return RedirectResponse(
        f"/clinic/app/configuracion?guardado=1&sync_creados={resultado['creados']}&sync_actualizados={resultado['actualizados']}",
        status_code=303,
    )


# ════════════════════════════════════════════════════════════
# 10.5) USUARIOS DEL EQUIPO — Invitar miembros (Sprint Opcion B Día 5)
# ════════════════════════════════════════════════════════════

@router.get("/app/usuarios", response_class=HTMLResponse)
async def vista_usuarios(
    invitado: Optional[str] = None,
    error: Optional[str] = None,
    eliminado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    """Lista usuarios del equipo + invitaciones pendientes."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])
    if not clinica:
        return RedirectResponse("/clinic/login", status_code=303)

    def esc(s): return html.escape(s or "", quote=True)

    async with async_session() as session:
        usuarios = (await session.execute(
            select(UsuarioClinic)
            .where(UsuarioClinic.clinica_id == clinica.id)
            .where(UsuarioClinic.activo == True)  # noqa: E712
            .order_by(UsuarioClinic.creado_en)
        )).scalars().all()

        invitaciones = (await session.execute(
            select(InvitacionUsuario)
            .where(InvitacionUsuario.clinica_id == clinica.id)
            .where(InvitacionUsuario.usada == False)  # noqa: E712
            .where(InvitacionUsuario.expira_en > datetime.utcnow())
            .order_by(desc(InvitacionUsuario.creado_en))
        )).scalars().all()

    limite = limite_usuarios(clinica.plan)
    actuales = len(usuarios)
    pendientes = len(invitaciones)
    total = actuales + pendientes
    puede_invitar = total < limite
    plan_nombre = (clinica.plan or "free").lower()

    # Banner de feedback
    banner = ""
    if invitado:
        link_invitacion = f"https://lapora.studio/clinic/aceptar-invitacion/{invitado}"
        banner = f'''<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:14px 16px;border-radius:10px;margin-bottom:20px;">
            <strong style="display:block;margin-bottom:6px;">✓ Invitación creada</strong>
            <p style="font-size:13px;margin-bottom:8px;">Comparte este link con la persona que quieres invitar (válido por 7 días):</p>
            <div style="display:flex;gap:8px;align-items:center;background:white;border:1px solid #10B981;border-radius:8px;padding:8px 12px;">
                <code id="link-inv" style="flex:1;font-size:12px;color:#065F46;word-break:break-all;">{esc(link_invitacion)}</code>
                <button onclick="navigator.clipboard.writeText(document.getElementById('link-inv').textContent);this.textContent='Copiado';" style="background:#10B981;color:white;border:none;padding:6px 12px;border-radius:6px;font-size:12px;font-weight:700;cursor:pointer;">Copiar</button>
            </div>
        </div>'''
    elif error:
        banner = f'<div style="background:#FEE2E2;border:1px solid #EF4444;color:#7F1D1D;padding:12px 16px;border-radius:10px;margin-bottom:20px;font-size:14px;">⚠ {esc(error)}</div>'
    elif eliminado:
        banner = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:20px;font-size:14px;font-weight:600;">✓ Usuario eliminado del equipo</div>'

    # Tabla de usuarios
    filas_usuarios = ""
    for u in usuarios:
        es_propio = (u.id == sesion["usuario_id"])
        ultimo = u.ultimo_login.strftime("%d/%m/%Y") if u.ultimo_login else "Nunca"
        accion = ('<span style="color:#9CA3AF;font-size:12px;">— tú —</span>' if es_propio
                  else f'<form method="post" action="/clinic/app/usuarios/{u.id}/eliminar" style="display:inline;" onsubmit="return confirm(\'¿Eliminar este usuario del equipo?\');"><button class="btn btn-ghost" style="font-size:12px;padding:4px 10px;color:#EF4444;border-color:#FCA5A5;">Eliminar</button></form>')
        filas_usuarios += f'''
        <tr>
            <td><strong>{esc(u.nombre)}</strong></td>
            <td>{esc(u.email)}</td>
            <td><span class="badge badge-pro" style="text-transform:capitalize;">{esc(u.rol)}</span></td>
            <td style="color:var(--text-soft);font-size:13px;">{ultimo}</td>
            <td style="text-align:right;">{accion}</td>
        </tr>'''

    # Tabla de invitaciones pendientes
    filas_inv = ""
    for inv in invitaciones:
        link_inv = f"/clinic/aceptar-invitacion/{inv.token}"
        dias_restantes = (inv.expira_en - datetime.utcnow()).days
        filas_inv += f'''
        <tr style="background:#FFFBEB;">
            <td><em>{esc(inv.email_invitado) if inv.email_invitado else "(sin email definido)"}</em></td>
            <td><span class="badge" style="background:#FEF3C7;color:#92400E;text-transform:capitalize;">{esc(inv.rol)}</span></td>
            <td style="color:#92400E;font-size:13px;">Pendiente · expira en {dias_restantes}d</td>
            <td style="text-align:right;">
                <button onclick="navigator.clipboard.writeText(window.location.origin + '{link_inv}');this.textContent='Copiado';" class="btn btn-ghost" style="font-size:12px;padding:4px 10px;">Copiar link</button>
                <form method="post" action="/clinic/app/usuarios/invitacion/{inv.id}/cancelar" style="display:inline;"><button class="btn btn-ghost" style="font-size:12px;padding:4px 10px;color:#EF4444;border-color:#FCA5A5;">Cancelar</button></form>
            </td>
        </tr>'''

    # Form para invitar
    if puede_invitar:
        form_invitar = f'''
        <form method="post" action="/clinic/app/usuarios/invitar" style="background:white;border:1px solid var(--border);border-radius:14px;padding:18px;margin-bottom:20px;">
            <h3 style="font-size:15px;font-weight:700;margin-bottom:12px;">✚ Invitar nuevo usuario</h3>
            <div style="display:grid;grid-template-columns:2fr 1fr auto;gap:10px;align-items:end;">
                <div>
                    <label style="font-size:11px;font-weight:700;display:block;margin-bottom:4px;color:var(--text-soft);">Email (opcional, solo para identificar)</label>
                    <input type="email" name="email_invitado" placeholder="recepcion@suclinica.com" class="input">
                </div>
                <div>
                    <label style="font-size:11px;font-weight:700;display:block;margin-bottom:4px;color:var(--text-soft);">Rol</label>
                    <select name="rol" class="input">
                        <option value="staff">Staff (solo lectura+responder)</option>
                        <option value="admin">Admin (puede editar todo)</option>
                    </select>
                </div>
                <button type="submit" class="btn btn-primary">Generar link de invitación</button>
            </div>
            <p style="font-size:12px;color:var(--text-soft);margin-top:10px;">
                💡 Al generar la invitación obtendrás un link único. Compártelo por WhatsApp o email con la persona. El link es válido 7 días y solo se puede usar una vez.
            </p>
        </form>'''
    else:
        if plan_nombre == "free":
            form_invitar = f'''<div style="background:linear-gradient(135deg,#FFF7ED,#FED7AA);border:1px solid #F97316;color:#9A3412;padding:18px;border-radius:14px;margin-bottom:20px;">
                <strong style="font-size:15px;display:block;margin-bottom:6px;">🚀 Sube a Pro para invitar tu equipo</strong>
                <p style="font-size:13px;">Tu plan Free solo permite 1 usuario. Con <strong>Pro ($100 USD/mes)</strong> puedes tener hasta 5 usuarios y activar IA SofIA.</p>
            </div>'''
        elif plan_nombre == "pro":
            form_invitar = f'''<div style="background:linear-gradient(135deg,#EFF6FF,#DBEAFE);border:1px solid #3B82F6;color:#1E40AF;padding:18px;border-radius:14px;margin-bottom:20px;">
                <strong style="font-size:15px;display:block;margin-bottom:6px;">⭐ Sube a Studio para usuarios ilimitados</strong>
                <p style="font-size:13px;">Tu plan Pro permite 5 usuarios. Con <strong>Studio ($250 USD/mes)</strong> tienes usuarios ilimitados, white-label total y API custom.</p>
            </div>'''
        else:
            form_invitar = '<div style="background:#F3F4F6;border:1px solid #E5E7EB;color:#374151;padding:14px;border-radius:10px;margin-bottom:20px;font-size:14px;">Ya alcanzaste el límite de usuarios de tu plan.</div>'

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Equipo - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("usuarios", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:start;margin-bottom:24px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Equipo</h1>
          <p style="color:var(--text-soft);">{actuales} de {limite if limite < 9999 else '∞'} usuarios usados · plan <strong style="text-transform:capitalize;color:var(--color-primary);">{plan_nombre}</strong></p>
        </div>
        <a href="#" style="font-size:13px;color:var(--text-soft);text-decoration:underline;">Ver planes</a>
      </div>

      {banner}
      {form_invitar}

      <div style="background:white;border:1px solid var(--border);border-radius:14px;overflow:hidden;">
        <table style="width:100%;border-collapse:collapse;">
          <thead style="background:#F9FAFB;">
            <tr>
              <th style="text-align:left;padding:12px 16px;font-size:12px;font-weight:700;color:var(--text-soft);text-transform:uppercase;letter-spacing:0.05em;">Nombre</th>
              <th style="text-align:left;padding:12px 16px;font-size:12px;font-weight:700;color:var(--text-soft);text-transform:uppercase;letter-spacing:0.05em;">Email</th>
              <th style="text-align:left;padding:12px 16px;font-size:12px;font-weight:700;color:var(--text-soft);text-transform:uppercase;letter-spacing:0.05em;">Rol</th>
              <th style="text-align:left;padding:12px 16px;font-size:12px;font-weight:700;color:var(--text-soft);text-transform:uppercase;letter-spacing:0.05em;">Último login</th>
              <th></th>
            </tr>
          </thead>
          <tbody>{filas_usuarios}{filas_inv}</tbody>
        </table>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/usuarios/invitar", response_class=HTMLResponse)
async def crear_invitacion_usuario(
    email_invitado: str = Form(""),
    rol: str = Form("staff"),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])
    if not clinica:
        return RedirectResponse("/clinic/login", status_code=303)

    puede, motivo = await puede_invitar_usuario(clinica)
    if not puede:
        return RedirectResponse(
            f"/clinic/app/usuarios?error={html.escape(motivo[:120])}",
            status_code=303,
        )

    inv = await crear_invitacion(
        clinica_id=clinica.id,
        invitado_por_id=sesion["usuario_id"],
        email_invitado=email_invitado.strip(),
        rol=rol if rol in ("admin", "staff") else "staff",
        dias_validez=7,
    )
    return RedirectResponse(f"/clinic/app/usuarios?invitado={inv.token}", status_code=303)


@router.post("/app/usuarios/{usuario_id}/eliminar", response_class=HTMLResponse)
async def eliminar_usuario(usuario_id: int, clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    if usuario_id == sesion["usuario_id"]:
        return RedirectResponse(
            "/clinic/app/usuarios?error=No+puedes+eliminarte+a+ti+mismo",
            status_code=303,
        )

    async with async_session() as session:
        u = (await session.execute(
            select(UsuarioClinic)
            .where(UsuarioClinic.id == usuario_id)
            .where(UsuarioClinic.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if u:
            u.activo = False  # Soft delete para auditoría
            await session.commit()

    return RedirectResponse("/clinic/app/usuarios?eliminado=1", status_code=303)


@router.post("/app/usuarios/invitacion/{inv_id}/cancelar", response_class=HTMLResponse)
async def cancelar_invitacion(inv_id: int, clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    async with async_session() as session:
        inv = (await session.execute(
            select(InvitacionUsuario)
            .where(InvitacionUsuario.id == inv_id)
            .where(InvitacionUsuario.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if inv:
            # Marcar como expirada inmediatamente
            inv.expira_en = datetime.utcnow()
            await session.commit()
    return RedirectResponse("/clinic/app/usuarios?eliminado=1", status_code=303)


# ──── Aceptación de invitación (público — el invitado entra sin sesión) ────

@router.get("/aceptar-invitacion/{token}", response_class=HTMLResponse)
async def vista_aceptar_invitacion(token: str, error: Optional[str] = None):
    """Página pública donde el invitado pone nombre + password."""
    async with async_session() as session:
        inv = (await session.execute(
            select(InvitacionUsuario).where(InvitacionUsuario.token == token)
        )).scalar_one_or_none()

        clinica = None
        if inv and not inv.usada and inv.expira_en > datetime.utcnow():
            clinica = (await session.execute(
                select(Clinica).where(Clinica.id == inv.clinica_id)
            )).scalar_one_or_none()

    def esc(s): return html.escape(s or "", quote=True)

    if not inv or inv.usada or inv.expira_en < datetime.utcnow() or not clinica:
        razon = "no encontrada"
        if inv and inv.usada:
            razon = "ya fue usada"
        elif inv and inv.expira_en < datetime.utcnow():
            razon = "ha expirado"
        return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Invitación inválida - Lapora Clinic</title>{CSS_CLINIC}</head>
<body style="background:#F9FAFB;display:flex;align-items:center;justify-content:center;min-height:100vh;">
    <div style="max-width:480px;background:white;border:1px solid var(--border);border-radius:14px;padding:32px;text-align:center;">
        <div style="font-size:48px;margin-bottom:12px;">⚠</div>
        <h1 style="font-size:22px;font-weight:800;margin-bottom:8px;">Invitación {razon}</h1>
        <p style="color:var(--text-soft);margin-bottom:20px;">Pide al admin de la clínica que te genere una nueva invitación.</p>
        <a href="/clinic/login" class="btn btn-primary">Ir a login</a>
    </div>
</body></html>""", status_code=410 if inv else 404)

    banner_err = f'<div style="background:#FEE2E2;border:1px solid #EF4444;color:#7F1D1D;padding:12px;border-radius:8px;margin-bottom:16px;font-size:14px;">⚠ {esc(error)}</div>' if error else ""
    email_default = esc(inv.email_invitado) if inv.email_invitado else ""

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Aceptar invitación - {esc(clinica.nombre)}</title>{CSS_CLINIC}</head>
<body style="background:#F9FAFB;display:flex;align-items:center;justify-content:center;min-height:100vh;padding:20px;">
    <div style="max-width:440px;width:100%;background:white;border:1px solid var(--border);border-radius:14px;padding:32px;">
        <div style="text-align:center;margin-bottom:24px;">
            <div style="font-size:40px;margin-bottom:8px;">👥</div>
            <h1 style="font-size:22px;font-weight:800;margin-bottom:6px;">Únete al equipo de</h1>
            <p style="color:var(--color-primary);font-size:20px;font-weight:700;">{esc(clinica.nombre)}</p>
            <p style="color:var(--text-soft);font-size:14px;margin-top:8px;">Vas a entrar como <strong style="text-transform:capitalize;">{esc(inv.rol)}</strong></p>
        </div>
        {banner_err}
        <form method="post" action="/clinic/aceptar-invitacion/{esc(token)}" style="display:flex;flex-direction:column;gap:14px;">
            <div>
                <label style="font-size:12px;font-weight:700;display:block;margin-bottom:4px;">Tu nombre</label>
                <input type="text" name="nombre" required class="input" placeholder="María Pérez">
            </div>
            <div>
                <label style="font-size:12px;font-weight:700;display:block;margin-bottom:4px;">Email (será tu login)</label>
                <input type="email" name="email" required class="input" value="{email_default}" placeholder="tu@email.com">
            </div>
            <div>
                <label style="font-size:12px;font-weight:700;display:block;margin-bottom:4px;">Contraseña (mín 6 caracteres)</label>
                <input type="password" name="password" required minlength="6" class="input" placeholder="••••••••">
            </div>
            <button type="submit" class="btn btn-primary" style="margin-top:8px;">Crear mi cuenta</button>
        </form>
    </div>
</body></html>""")


@router.post("/aceptar-invitacion/{token}", response_class=HTMLResponse)
async def aceptar_invitacion(
    token: str,
    nombre: str = Form(""),
    email: str = Form(""),
    password: str = Form(""),
):
    usuario, error = await consumir_invitacion(token, nombre, email, password)
    if not usuario or error:
        return RedirectResponse(
            f"/clinic/aceptar-invitacion/{token}?error={html.escape(error or 'Error desconocido')}",
            status_code=303,
        )
    # Login automático: crear sesión y redirigir al dashboard
    cookie_token = secrets.token_urlsafe(32)
    SESSIONS[cookie_token] = {
        "usuario_id": usuario.id,
        "clinica_id": usuario.clinica_id,
        "nombre": usuario.nombre,
        "rol": usuario.rol,
    }
    resp = RedirectResponse("/clinic/app/?bienvenida=1", status_code=303)
    resp.set_cookie("clinic_session", cookie_token, max_age=30 * 24 * 3600, httponly=True, samesite="lax")
    return resp


# ════════════════════════════════════════════════════════════
# 11) WEBHOOK — Receptor de mensajes WhatsApp por clínica
# ════════════════════════════════════════════════════════════

@router.get("/webhook/whatsapp/{slug}")
async def webhook_whatsapp_verify(slug: str, request: Request):
    """Verificación inicial del webhook por Meta (hub.challenge)."""
    params = dict(request.query_params)
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.slug == slug)
        )).scalar_one_or_none()

    # Verify token = el ID del WhatsApp Phone Number ID (simple y suficiente)
    if mode == "subscribe" and clinica and token == clinica.whatsapp_phone_id:
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(str(challenge or ""))
    return HTMLResponse("Forbidden", status_code=403)


@router.post("/webhook/whatsapp/{slug}")
async def webhook_whatsapp_recibir(slug: str, request: Request):
    """Recibe mensajes WhatsApp, los guarda en el inbox, y responde con IA SofIA si está activa."""
    try:
        payload = await request.json()
    except Exception:
        return {"status": "ignored"}

    # Lista de tuplas (clinica, paciente, texto) para procesar IA después del commit
    pendientes_ia = []

    async with async_session() as session:
        clinica = (await session.execute(
            select(Clinica).where(Clinica.slug == slug)
        )).scalar_one_or_none()
        if not clinica:
            return {"status": "clinica no encontrada"}

        # Parsear estructura Meta Cloud API
        for entry in payload.get("entry", []):
            for change in entry.get("changes", []):
                value = change.get("value", {})
                for msg in value.get("messages", []):
                    if msg.get("type") != "text":
                        continue
                    from_tel = msg.get("from", "")
                    texto = msg.get("text", {}).get("body", "")
                    msg_id = msg.get("id", "")
                    ts = datetime.utcnow()

                    # Buscar o crear paciente por teléfono
                    paciente = (await session.execute(
                        select(Paciente)
                        .where(Paciente.clinica_id == clinica.id)
                        .where(Paciente.telefono.contains(from_tel[-10:]))
                    )).scalar_one_or_none()
                    if not paciente:
                        paciente = Paciente(
                            clinica_id=clinica.id,
                            nombre=f"WhatsApp +{from_tel}",
                            telefono=f"+{from_tel}",
                            fuente="whatsapp",
                            estado="nuevo",
                            primer_contacto=ts,
                            ultimo_contacto=ts,
                        )
                        session.add(paciente)
                        await session.flush()

                    # Guardar mensaje
                    session.add(MensajeUnificado(
                        clinica_id=clinica.id,
                        paciente_id=paciente.id,
                        canal="whatsapp",
                        direccion="entrada",
                        contenido=texto,
                        canal_msg_id=msg_id,
                        leido=False,
                        timestamp=ts,
                    ))
                    paciente.ultimo_contacto = ts
                    paciente.total_mensajes = (paciente.total_mensajes or 0) + 1

                    # Encolar para IA si está activa (procesa después del commit)
                    if clinica.ia_activa and not clinica.congelada:
                        pendientes_ia.append((clinica.id, paciente.id, texto))

        await session.commit()

    # Procesar IA SofIA per-tenant DESPUÉS del commit
    # (en background para no bloquear el ACK del webhook a Meta)
    if pendientes_ia:
        import asyncio
        asyncio.create_task(_procesar_ia_background(pendientes_ia))

    return {"status": "ok"}


async def _procesar_ia_background(pendientes: list[tuple[int, int, str]]):
    """Procesa los mensajes con IA SofIA en background.

    Se llama después del commit del webhook para que Meta reciba el ACK rápido.
    Cualquier excepción aquí se loguea pero NO afecta al webhook.
    """
    try:
        from agent.clinic_brain import procesar_mensaje_entrante
    except ImportError as e:
        logger.error(f"[IA background] No se pudo importar clinic_brain: {e}")
        return

    for clinica_id, paciente_id, texto in pendientes:
        try:
            async with async_session() as session:
                clinica = (await session.execute(
                    select(Clinica).where(Clinica.id == clinica_id)
                )).scalar_one_or_none()
                paciente = (await session.execute(
                    select(Paciente).where(Paciente.id == paciente_id)
                )).scalar_one_or_none()

            if not clinica or not paciente:
                continue

            resultado = await procesar_mensaje_entrante(clinica, paciente, texto)
            logger.info(
                f"[IA background] clinica={clinica_id} paciente={paciente_id} "
                f"accion={resultado.get('accion')} enviada={resultado.get('respuesta_enviada')}"
            )
        except Exception as e:
            logger.error(f"[IA background] Error procesando clinica={clinica_id}: {e}", exc_info=True)


# ════════════════════════════════════════════════════════════
# 12) LANDING PUBLICO — Marketing de Lapora Clinic
# ════════════════════════════════════════════════════════════

@router.get("/landing", response_class=HTMLResponse)
async def landing_publico():
    """Página de marketing pública de Lapora Clinic (tema dark interactivo, estilo lapora.studio)."""
    return HTMLResponse(LANDING_HTML)


LANDING_HTML = """<!DOCTYPE html><html lang="es">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Lapora Clinic — El software médico que vale 10x lo que cuesta</title>
<meta name="description" content="WhatsApp + Instagram + Pacientes + IA en una sola plataforma. Diseñado por médicos para médicos colombianos.">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700;800;900&family=Playfair+Display:ital,wght@0,700;0,800;1,700&display=swap" rel="stylesheet">
<style>
  :root {
    --r: #E8302A; --r2: #FF4840; --r3: #C0261F;
    --k: #080808; --k2: #0F0F0F; --k3: #161616; --k4: #1C1C1C;
    --w: #FFFFFF; --g: #888;
    --b: rgba(255,255,255,0.08);
  }
  *,*::before,*::after{margin:0;padding:0;box-sizing:border-box}
  html{scroll-behavior:smooth;overflow-x:hidden}
  body{font-family:'Inter',sans-serif;background:var(--k);color:var(--w);overflow-x:hidden;line-height:1.5;}
  a{color:inherit;text-decoration:none}

  /* NAV */
  .nav{position:fixed;top:0;left:0;right:0;z-index:100;background:rgba(8,8,8,0.85);backdrop-filter:blur(20px);border-bottom:1px solid var(--b);}
  .nav-inner{max-width:1200px;margin:0 auto;padding:18px 32px;display:flex;justify-content:space-between;align-items:center;}
  .logo{display:flex;align-items:center;gap:10px;font-weight:800;font-size:18px;letter-spacing:-0.5px;}
  .logo-mark{width:32px;height:32px;background:var(--r);border-radius:8px;display:flex;align-items:center;justify-content:center;color:white;font-weight:900;}
  .nav-links{display:flex;gap:28px;align-items:center;}
  .nav-links a{font-size:14px;font-weight:500;color:#bbb;transition:color .2s;}
  .nav-links a:hover{color:white;}
  .btn{display:inline-flex;align-items:center;gap:8px;padding:12px 22px;border-radius:10px;font-size:14px;font-weight:600;text-decoration:none;transition:all .2s;border:none;cursor:pointer;}
  .btn-primary{background:var(--r);color:white;box-shadow:0 4px 20px rgba(232,48,42,0.35);}
  .btn-primary:hover{background:var(--r2);transform:translateY(-2px);box-shadow:0 8px 30px rgba(232,48,42,0.5);}
  .btn-ghost{background:transparent;color:white;border:1.5px solid rgba(255,255,255,0.15);}
  .btn-ghost:hover{border-color:white;}

  /* HERO */
  .hero{min-height:100vh;display:flex;flex-direction:column;justify-content:center;align-items:center;text-align:center;padding:120px 24px 60px;position:relative;overflow:hidden;}
  .hero::before{content:'';position:absolute;top:20%;left:50%;transform:translateX(-50%);width:800px;height:800px;background:radial-gradient(circle, rgba(232,48,42,0.15) 0%, transparent 60%);pointer-events:none;}
  .hero-tag{display:inline-flex;align-items:center;gap:8px;padding:6px 14px;background:rgba(232,48,42,0.12);border:1px solid rgba(232,48,42,0.3);border-radius:999px;font-size:12px;font-weight:600;color:var(--r2);margin-bottom:28px;position:relative;}
  .hero-tag::before{content:'●';color:var(--r);animation:pulse 2s infinite;}
  @keyframes pulse{0%,100%{opacity:1}50%{opacity:0.4}}
  .hero h1{font-family:'Playfair Display',serif;font-size:clamp(40px,7vw,84px);font-weight:900;letter-spacing:-2px;line-height:1.05;max-width:980px;margin-bottom:24px;position:relative;}
  .hero h1 .red{color:var(--r);font-style:italic;}
  .hero h1 .strike{position:relative;display:inline-block;}
  .hero h1 .strike::after{content:'';position:absolute;top:50%;left:-4px;right:-4px;height:4px;background:var(--r);transform:translateY(-50%) rotate(-2deg);}
  .hero p.lead{font-size:20px;color:#aaa;max-width:680px;margin-bottom:36px;line-height:1.6;position:relative;}
  .hero-ctas{display:flex;gap:14px;flex-wrap:wrap;justify-content:center;margin-bottom:18px;position:relative;}
  .hero-ctas .btn{padding:16px 28px;font-size:15px;}
  .hero-meta{font-size:12px;color:#666;position:relative;}
  .hero-meta strong{color:#ddd;}

  /* COUNTERS */
  .counters{display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:24px;max-width:1100px;margin:80px auto;padding:0 32px;position:relative;}
  .counter{text-align:center;padding:32px 20px;background:linear-gradient(180deg,var(--k3),var(--k2));border:1px solid var(--b);border-radius:18px;transition:all .3s;}
  .counter:hover{transform:translateY(-4px);border-color:rgba(232,48,42,0.3);}
  .counter-num{font-family:'Playfair Display',serif;font-size:48px;font-weight:900;color:var(--r);letter-spacing:-2px;}
  .counter-label{font-size:13px;color:#888;margin-top:6px;text-transform:uppercase;letter-spacing:1px;font-weight:600;}

  /* SECTIONS */
  section{padding:100px 24px;}
  .section-title{font-family:'Playfair Display',serif;font-size:clamp(32px,5vw,56px);font-weight:900;text-align:center;letter-spacing:-1.5px;margin-bottom:14px;}
  .section-sub{font-size:17px;color:#aaa;text-align:center;max-width:640px;margin:0 auto 56px;line-height:1.6;}

  /* FEATURES */
  .features{max-width:1200px;margin:0 auto;}
  .features-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:18px;}
  .feature{background:linear-gradient(180deg,var(--k3),var(--k2));border:1px solid var(--b);border-radius:20px;padding:32px;transition:all .3s;position:relative;overflow:hidden;}
  .feature::before{content:'';position:absolute;top:-50%;right:-50%;width:200px;height:200px;background:radial-gradient(circle, rgba(232,48,42,0.08) 0%, transparent 70%);opacity:0;transition:opacity .3s;}
  .feature:hover{transform:translateY(-6px);border-color:rgba(232,48,42,0.3);}
  .feature:hover::before{opacity:1;}
  .feature-icon{font-size:36px;margin-bottom:18px;}
  .feature h3{font-size:18px;font-weight:800;margin-bottom:8px;letter-spacing:-0.3px;}
  .feature p{font-size:14px;color:#888;line-height:1.6;}

  /* COMPARATIVA */
  .compare{max-width:1100px;margin:0 auto;background:var(--k3);border:1px solid var(--b);border-radius:24px;overflow:hidden;}
  .compare table{width:100%;border-collapse:collapse;}
  .compare th, .compare td{padding:18px 24px;text-align:left;border-bottom:1px solid var(--b);}
  .compare th{background:var(--k4);font-size:12px;text-transform:uppercase;letter-spacing:1px;color:#888;font-weight:700;}
  .compare th.us{background:rgba(232,48,42,0.15);color:var(--r2);}
  .compare td{font-size:14px;}
  .compare .yes{color:#10B981;font-weight:700;}
  .compare .no{color:#ef4444;}
  .compare .meh{color:#888;}

  /* PRICING */
  .pricing-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:20px;max-width:1100px;margin:0 auto;}
  .price{background:linear-gradient(180deg,var(--k3),var(--k2));border:1.5px solid var(--b);border-radius:24px;padding:38px 32px;position:relative;transition:all .3s;}
  .price.featured{border-color:var(--r);border-width:2.5px;transform:scale(1.04);box-shadow:0 20px 60px rgba(232,48,42,0.2);}
  .price.featured::before{content:'⭐ MÁS POPULAR';position:absolute;top:-13px;left:50%;transform:translateX(-50%);background:var(--r);color:white;padding:5px 16px;border-radius:999px;font-size:11px;font-weight:700;letter-spacing:1px;}
  .price-tier{font-size:12px;font-weight:700;text-transform:uppercase;letter-spacing:1.5px;color:#888;margin-bottom:8px;}
  .price-amount{font-family:'Playfair Display',serif;font-size:54px;font-weight:900;letter-spacing:-2px;line-height:1;}
  .price-amount small{font-family:'Inter',sans-serif;font-size:14px;color:#888;font-weight:500;letter-spacing:0;}
  .price-cop{font-size:12px;color:#888;margin-top:6px;}
  .price-desc{color:#aaa;font-size:13px;margin:16px 0;line-height:1.5;}
  .price ul{list-style:none;padding:0;margin:24px 0 28px;}
  .price ul li{padding:7px 0;font-size:13px;color:#ddd;display:flex;align-items:flex-start;gap:8px;}
  .price ul li::before{content:'✓';color:var(--r);font-weight:900;flex-shrink:0;}
  .price ul li.bold{font-weight:600;color:white;}
  .price .btn{width:100%;justify-content:center;font-size:14px;padding:14px;}

  /* FAQ */
  .faq{max-width:780px;margin:0 auto;}
  .faq-item{background:var(--k3);border:1px solid var(--b);border-radius:14px;margin-bottom:10px;overflow:hidden;}
  .faq-q{padding:18px 24px;cursor:pointer;font-weight:600;display:flex;justify-content:space-between;align-items:center;font-size:15px;}
  .faq-q:hover{background:var(--k4);}
  .faq-q::after{content:'+';font-size:24px;color:var(--r);font-weight:300;transition:transform .2s;}
  .faq-item.open .faq-q::after{transform:rotate(45deg);}
  .faq-a{max-height:0;overflow:hidden;transition:max-height .3s;color:#aaa;font-size:14px;line-height:1.7;padding:0 24px;}
  .faq-item.open .faq-a{max-height:400px;padding:0 24px 20px;}

  /* CTA FINAL */
  .cta-final{text-align:center;max-width:780px;margin:0 auto;padding:60px 32px;background:linear-gradient(135deg,rgba(232,48,42,0.15),rgba(232,48,42,0.05));border:1.5px solid rgba(232,48,42,0.3);border-radius:32px;}
  .cta-final h2{font-family:'Playfair Display',serif;font-size:42px;font-weight:900;margin-bottom:16px;letter-spacing:-1px;line-height:1.1;}
  .cta-final p{color:#aaa;font-size:16px;margin-bottom:28px;}

  /* FOOTER */
  footer{padding:48px 24px;text-align:center;border-top:1px solid var(--b);background:var(--k);color:#666;font-size:13px;}
  footer a{color:#aaa;margin:0 10px;}

  @media (max-width: 768px){
    .nav-links a:not(.btn){display:none;}
    .price.featured{transform:none;}
  }
</style>
</head>
<body>
  <nav class="nav">
    <div class="nav-inner">
      <a href="/clinic/landing" class="logo">
        <span class="logo-mark">L</span>
        <span>Lapora Clinic</span>
      </a>
      <div class="nav-links">
        <a href="#features">Features</a>
        <a href="#compare">vs Competencia</a>
        <a href="#pricing">Precios</a>
        <a href="#faq">FAQ</a>
        <a href="/clinic/login">Entrar</a>
        <a href="/clinic/registro" class="btn btn-primary" style="padding:10px 20px;">Probar gratis</a>
      </div>
    </div>
  </nav>

  <!-- HERO -->
  <section class="hero">
    <span class="hero-tag">NUEVO · Disponible en Colombia</span>
    <h1>El software que <span class="strike">tu consultorio</span><br>tu <span class="red">consultorio merece</span>.</h1>
    <p class="lead">WhatsApp, Instagram, pacientes, IA y reportes. Todo en una sola pantalla. Diseñado por médicos colombianos para consultorios que quieren ganar más sin trabajar más.</p>
    <div class="hero-ctas">
      <a href="/clinic/registro" class="btn btn-primary">Empezar 14 días gratis →</a>
      <a href="#features" class="btn btn-ghost">Ver qué hace</a>
    </div>
    <div class="hero-meta">✓ Sin tarjeta · ✓ Setup en 3 min · <strong>✓ Datos en Colombia</strong> · ✓ Cancelas cuando quieras</div>
  </section>

  <!-- CONTADORES -->
  <div class="counters">
    <div class="counter"><div class="counter-num">3 min</div><div class="counter-label">Setup completo</div></div>
    <div class="counter"><div class="counter-num">10×</div><div class="counter-label">Más rápido respondiendo</div></div>
    <div class="counter"><div class="counter-num">24/7</div><div class="counter-label">Bot IA activo</div></div>
    <div class="counter"><div class="counter-num">∞</div><div class="counter-label">Pacientes (plan Pro)</div></div>
  </div>

  <!-- FEATURES -->
  <section id="features" class="features">
    <h2 class="section-title">Todo lo que <span style="color:var(--r);font-style:italic;">tu consultorio necesita</span></h2>
    <p class="section-sub">Las 12 funciones que ya estás pagando en 4 apps distintas, ahora en una.</p>

    <div class="features-grid">
      <div class="feature">
        <div class="feature-icon">📥</div>
        <h3>Inbox unificado</h3>
        <p>WhatsApp + Instagram + Email en una sola pantalla. Un solo lugar para todas las conversaciones con tus pacientes.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">🤖</div>
        <h3>IA SofIA propia</h3>
        <p>Responde 24/7, agenda citas en tu calendario, califica leads. No es un chatbot genérico — está entrenado en medicina.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">👥</div>
        <h3>CRM de pacientes</h3>
        <p>Historial unificado: cita, tratamiento, alergias, notas. Búsqueda instantánea. Timeline de cada paciente.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">📊</div>
        <h3>Sync Google Sheets</h3>
        <p>Importás tus pacientes desde Excel/Sheets en 1 click. Sin perder nada. Sincronización continua.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">📝</div>
        <h3>Plantillas inteligentes</h3>
        <p>Respuestas rápidas con variables: {nombre}, {tratamiento}. Personaliza en segundos. 7 categorías predefinidas.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">📞</div>
        <h3>Bitácora de llamadas</h3>
        <p>Cada llamada registrada con resultado, duración y próximos pasos. Nunca pierdas seguimiento.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">📅</div>
        <h3>Vista "Hoy" diaria</h3>
        <p>Tareas del día en 1 vistazo: citas, mensajes sin responder, llamadas pendientes, nuevos pacientes esta semana.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">🔔</div>
        <h3>Recordatorios automáticos</h3>
        <p>Detecta pacientes que no han vuelto en X meses y los re-engancha automáticamente. (Pro/Studio)</p>
      </div>
      <div class="feature">
        <div class="feature-icon">📈</div>
        <h3>Analytics premium</h3>
        <p>Pacientes en riesgo de abandono, ROI por canal, tiempo de respuesta promedio. (Studio)</p>
      </div>
      <div class="feature">
        <div class="feature-icon">🎨</div>
        <h3>Tu marca, tu dominio</h3>
        <p>White-label total con dominio propio en plan Studio. Tus clientes ven solo tu marca.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">🔒</div>
        <h3>Datos en Colombia</h3>
        <p>Cumplimiento Ley 1581/2012 (Habeas Data). Servidores en LATAM. Backup automático diario.</p>
      </div>
      <div class="feature">
        <div class="feature-icon">💬</div>
        <h3>Soporte humano</h3>
        <p>WhatsApp directo con un humano. No bots de soporte. Respuesta en menos de 4 horas. (Pro/Studio)</p>
      </div>
    </div>
  </section>

  <!-- COMPARATIVA -->
  <section id="compare">
    <h2 class="section-title">¿Por qué no <span style="color:var(--r);font-style:italic;">Wati</span> o <span style="color:var(--r);font-style:italic;">Chatwoot</span>?</h2>
    <p class="section-sub">Las herramientas globales son genéricas. Lapora Clinic está hecho para el doctor colombiano.</p>

    <div class="compare">
      <table>
        <tr>
          <th>Característica</th>
          <th class="us">Lapora Clinic</th>
          <th>Wati</th>
          <th>Chatwoot</th>
        </tr>
        <tr>
          <td><strong>IA entrenada en medicina</strong></td>
          <td class="yes">✓ SofIA propia</td>
          <td class="no">✗</td>
          <td class="no">✗</td>
        </tr>
        <tr>
          <td><strong>Soporte en español colombiano</strong></td>
          <td class="yes">✓ Por WhatsApp</td>
          <td class="meh">⚠ Email en inglés</td>
          <td class="meh">⚠ Email en inglés</td>
        </tr>
        <tr>
          <td><strong>CRM de pacientes incluido</strong></td>
          <td class="yes">✓ Con historial clínico</td>
          <td class="no">✗ (genérico)</td>
          <td class="meh">⚠ Solo contactos</td>
        </tr>
        <tr>
          <td><strong>Sync Google Sheets</strong></td>
          <td class="yes">✓ Bidireccional</td>
          <td class="no">✗</td>
          <td class="no">✗</td>
        </tr>
        <tr>
          <td><strong>Plantillas con variables</strong></td>
          <td class="yes">✓ 7 categorías</td>
          <td class="yes">✓</td>
          <td class="meh">⚠ Básico</td>
        </tr>
        <tr>
          <td><strong>Bitácora de llamadas</strong></td>
          <td class="yes">✓ Con resultado y notas</td>
          <td class="no">✗</td>
          <td class="no">✗</td>
        </tr>
        <tr>
          <td><strong>Precio base mensual</strong></td>
          <td class="us yes"><strong>$100 USD</strong></td>
          <td class="meh">$120-200 USD</td>
          <td class="meh">$19-99 USD (self-host complejo)</td>
        </tr>
        <tr>
          <td><strong>Setup tiempo</strong></td>
          <td class="yes">3 min</td>
          <td class="meh">~30 min</td>
          <td class="meh">2-3 horas (self-host)</td>
        </tr>
      </table>
    </div>
  </section>

  <!-- PRICING -->
  <section id="pricing" style="background:var(--k2);">
    <h2 class="section-title">Empezá <span style="color:var(--r);font-style:italic;">gratis</span>. Escalá cuando quieras.</h2>
    <p class="section-sub">Precios en USD para que escales sin sorpresas. Sin contratos. Sin permanencia.</p>

    <div class="pricing-grid">

      <!-- FREE -->
      <div class="price">
        <div class="price-tier">FREE</div>
        <div class="price-amount">$0<small>/mes</small></div>
        <div class="price-cop">Para empezar y probar</div>
        <p class="price-desc">Suficiente para validar el producto en tu consultorio.</p>
        <ul>
          <li>Hasta 100 pacientes</li>
          <li>Inbox WhatsApp</li>
          <li>1 usuario</li>
          <li>Plantillas básicas</li>
          <li>Soporte por email</li>
        </ul>
        <a href="/clinic/registro" class="btn btn-ghost">Empezar gratis</a>
      </div>

      <!-- PRO -->
      <div class="price featured">
        <div class="price-tier">PRO</div>
        <div class="price-amount">$100<small> USD/mes</small></div>
        <div class="price-cop">≈ $400.000 COP/mes</div>
        <p class="price-desc">Para consultorios que ya facturan y quieren escalar con IA.</p>
        <ul>
          <li class="bold">Pacientes ilimitados</li>
          <li class="bold">WhatsApp + Instagram + Email</li>
          <li class="bold">IA SofIA (responde 24/7)</li>
          <li>Sync Google Sheets continuo</li>
          <li>5 usuarios</li>
          <li>Tu logo en la plataforma</li>
          <li>Recordatorios automáticos</li>
          <li>Plantillas con variables</li>
          <li>Soporte priority WhatsApp</li>
          <li>14 días gratis de prueba</li>
        </ul>
        <a href="/clinic/registro" class="btn btn-primary">Probar 14 días gratis</a>
      </div>

      <!-- STUDIO -->
      <div class="price">
        <div class="price-tier">STUDIO</div>
        <div class="price-amount">$250<small> USD/mes</small></div>
        <div class="price-cop">≈ $1.000.000 COP/mes</div>
        <p class="price-desc">Para clínicas con varios profesionales y necesidades premium.</p>
        <ul>
          <li>Todo lo de Pro</li>
          <li class="bold">Usuarios ilimitados</li>
          <li class="bold">Dominio propio (tudr.com)</li>
          <li class="bold">Analytics avanzado + ROI</li>
          <li>Detección de pacientes en riesgo</li>
          <li>API custom</li>
          <li>Onboarding personalizado</li>
          <li>Soporte 24/7 dedicado</li>
          <li>Backup diario garantizado</li>
          <li>White-label total</li>
        </ul>
        <a href="https://wa.me/573228783019?text=Quiero+info+del+plan+Studio" class="btn btn-ghost">Hablar con ventas</a>
      </div>
    </div>
  </section>

  <!-- FAQ -->
  <section id="faq" style="background:var(--k);">
    <h2 class="section-title">Preguntas <span style="color:var(--r);font-style:italic;">frecuentes</span></h2>
    <p class="section-sub">Las dudas que todos los doctores nos hacen antes de empezar.</p>

    <div class="faq">
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">¿Mis pacientes pueden notar que uso un bot?</div>
        <div class="faq-a">Si quieres, NO. SofIA está entrenada para sonar como tu staff, con tu tono y tus respuestas. Puedes intervenir manualmente cuando quieras. Muchos doctores hacen "modo híbrido": la IA responde, ellos cierran ventas grandes.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">¿Qué pasa con mis datos si cancelo?</div>
        <div class="faq-a">Te exportamos todo en CSV y te lo enviamos por email. Los datos permanecen 90 días por si quieres reactivar, después se borran de forma segura. Sin letra chica.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">¿Funciona con mi número de WhatsApp actual?</div>
        <div class="faq-a">Sí. Conectamos tu WhatsApp Business existente vía Meta Cloud API. Tus clientes ven el mismo número de siempre, pero tú gestionas todo desde Lapora. Sin descargar otra app.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">¿Mis datos están seguros?</div>
        <div class="faq-a">Cumplimos Ley 1581/2012 (Habeas Data Colombia). Servidores en LATAM (Railway/AWS), encriptación TLS 1.3, backup diario automático. Cada clínica tiene aislamiento total de datos.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">¿Necesito ser técnico para usarlo?</div>
        <div class="faq-a">No. El setup toma 3 minutos: 1) Registras tu clínica, 2) Conectas WhatsApp con un click, 3) Importas tus pacientes desde Excel. Nuestro equipo te acompaña gratis en el plan Pro+.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">¿Cuánto recupero del costo?</div>
        <div class="faq-a">Plan Pro ($100 USD/mes ≈ $400.000 COP) se paga solo con 1-2 pacientes nuevos cerrados al mes. Nuestros clientes promedio recuperan la inversión en la primera semana.</div>
      </div>
      <div class="faq-item">
        <div class="faq-q" onclick="this.parentElement.classList.toggle('open')">¿Puedo cancelar cuando quiera?</div>
        <div class="faq-a">Sí. Sin contratos, sin permanencia. Cancelas con un click y tu cuenta queda activa hasta el final del periodo pagado. Sin letra chica, sin penalidades.</div>
      </div>
    </div>
  </section>

  <!-- CTA FINAL -->
  <section>
    <div class="cta-final">
      <h2>Probalo hoy.<br>No te va a costar nada.</h2>
      <p>14 días gratis del plan Pro. Sin tarjeta. Sin contratos.<br>Si no te gusta, te vas. Si te gusta, sigues por $100 USD/mes.</p>
      <a href="/clinic/registro" class="btn btn-primary" style="padding:16px 32px;font-size:16px;">Empezar ahora →</a>
    </div>
  </section>

  <footer>
    <p><strong style="color:white;">Lapora Clinic</strong> · Marketing digital + Software médico</p>
    <p style="margin-top:8px;">
      <a href="https://lapora.studio">lapora.studio</a> ·
      <a href="https://wa.me/573228783019">WhatsApp +57 322 878 3019</a> ·
      <a href="mailto:laporamarketingdigital@gmail.com">Email</a>
    </p>
    <p style="margin-top:12px;font-size:11px;color:#444;">© 2026 Lapora Marketing Digital. Hecho con ❤️ en Ibagué, Colombia.</p>
  </footer>

  <script>
    // Smooth scroll para nav
    document.querySelectorAll('a[href^="#"]').forEach(a => {
      a.addEventListener('click', e => {
        e.preventDefault();
        const el = document.querySelector(a.getAttribute('href'));
        if (el) el.scrollIntoView({behavior:'smooth', block:'start'});
      });
    });
    // Animar contadores cuando entran a viewport
    const obs = new IntersectionObserver(entries => {
      entries.forEach(e => {
        if (e.isIntersecting) e.target.style.transform = 'translateY(0)';
      });
    });
    document.querySelectorAll('.feature, .counter, .price').forEach(el => {
      el.style.opacity = '0';
      el.style.transform = 'translateY(20px)';
      el.style.transition = 'opacity .6s, transform .6s';
      const io = new IntersectionObserver(([entry]) => {
        if (entry.isIntersecting) {
          el.style.opacity = '1';
          el.style.transform = 'translateY(0)';
        }
      }, {threshold: 0.1});
      io.observe(el);
    });
  </script>
</body></html>"""


# === LANDING viejo eliminado, se mantiene la antigua versión bajo /landing-old ===
@router.get("/landing-old", response_class=HTMLResponse)
async def landing_old():
    """Versión anterior del landing — mantenida por compatibilidad."""
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>Lapora Clinic — El software que tu consultorio necesita</title>
<meta name="description" content="WhatsApp + Instagram + pacientes + IA en una sola pantalla. Desde gratis.">
{CSS_CLINIC}
<style>
  .hero {{ background: linear-gradient(135deg, #FFF1F0 0%, #FFFFFF 100%); padding: 80px 24px; text-align: center; }}
  .hero h1 {{ font-size: 56px; font-weight: 900; letter-spacing: -2px; line-height: 1.05; margin-bottom: 22px; }}
  .hero h1 span {{ color: var(--primary); }}
  .hero p {{ font-size: 19px; color: var(--text-soft); max-width: 640px; margin: 0 auto 32px; line-height: 1.5; }}
  .features {{ padding: 80px 24px; max-width: 1100px; margin: 0 auto; }}
  .features-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 24px; }}
  .feature-card {{
    background: white; padding: 28px; border-radius: 16px;
    border: 1px solid var(--border); transition: all 0.2s;
  }}
  .feature-card:hover {{ transform: translateY(-4px); box-shadow: var(--shadow-lg); }}
  .feature-icon {{ font-size: 36px; margin-bottom: 14px; }}
  .pricing {{ padding: 60px 24px; background: var(--bg); }}
  .pricing-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: 20px; max-width: 1000px; margin: 0 auto; }}
  .price-card {{
    background: white; padding: 32px; border-radius: 18px;
    border: 1.5px solid var(--border); position: relative;
  }}
  .price-card.featured {{ border-color: var(--primary); border-width: 2px; transform: scale(1.03); }}
  .price-tag {{ font-size: 36px; font-weight: 900; margin: 14px 0; }}
  .price-tag small {{ font-size: 14px; color: var(--text-soft); font-weight: 600; }}
  .price-feat-list {{ list-style: none; padding: 0; margin: 20px 0; }}
  .price-feat-list li {{ padding: 6px 0; font-size: 14px; }}
  .price-feat-list li:before {{ content: "✓ "; color: var(--green); font-weight: 700; }}
  .nav-pub {{
    display: flex; justify-content: space-between; align-items: center;
    padding: 18px 32px; border-bottom: 1px solid var(--border); background: white;
  }}
</style>
</head>
<body>
  <nav class="nav-pub">
    <div style="display:flex;align-items:center;gap:10px;">
      <div class="brand-logo">L</div>
      <div>
        <div style="font-weight:800;font-size:16px;">Lapora Clinic</div>
        <div style="font-size:11px;color:var(--text-soft);">Marketing digital para médicos</div>
      </div>
    </div>
    <div style="display:flex;gap:10px;align-items:center;">
      <a href="/clinic/login" style="font-weight:600;color:var(--text);font-size:14px;">Iniciar sesión</a>
      <a href="/clinic/registro" class="btn btn-primary">Probar gratis</a>
    </div>
  </nav>

  <section class="hero">
    <h1>El cerebro digital<br>de <span>tu consultorio</span></h1>
    <p>WhatsApp, Instagram, pacientes, citas y reportes en una sola pantalla.
       Sin perder tiempo cambiando entre apps. Empezás <strong>gratis</strong>, sin tarjeta.</p>
    <div style="display:flex;gap:12px;justify-content:center;flex-wrap:wrap;">
      <a href="/clinic/registro" class="btn btn-primary" style="padding:14px 28px;font-size:15px;">Empezar gratis →</a>
      <a href="#features" class="btn btn-ghost" style="padding:14px 28px;font-size:15px;">Ver cómo funciona</a>
    </div>
    <p style="font-size:12px;color:var(--text-soft);margin-top:18px;">
      ✓ Sin tarjeta de crédito  ·  ✓ Setup en 5 minutos  ·  ✓ Cancelas cuando quieras
    </p>
  </section>

  <section class="features" id="features">
    <h2 style="text-align:center;font-size:36px;font-weight:900;margin-bottom:14px;letter-spacing:-1px;">
      Todo lo que un consultorio necesita
    </h2>
    <p style="text-align:center;color:var(--text-soft);max-width:560px;margin:0 auto 48px;font-size:15px;">
      Diseñado por médicos para médicos. Cada función nace de un dolor real de consultorios en Colombia.
    </p>
    <div class="features-grid">
      <div class="feature-card">
        <div class="feature-icon">📥</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Inbox unificado</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          WhatsApp + Instagram + Email en una sola pantalla. Responde todo desde un único lugar.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">🤖</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">IA SofIA</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Responde sola, agenda citas, califica leads. Trabajas el 70% menos.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">👥</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">CRM de pacientes</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Historial completo, notas, tratamiento, llamadas. Todo en la ficha del paciente.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📊</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Sync Google Sheets</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Importas tus pacientes desde Excel/Sheets con un click. Sin perder lo que ya tienes.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📝</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Plantillas inteligentes</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Respuestas rápidas para preguntas frecuentes con variables personalizables.
        </p>
      </div>
      <div class="feature-card">
        <div class="feature-icon">📞</div>
        <h3 style="font-size:17px;font-weight:800;margin-bottom:6px;">Bitácora de llamadas</h3>
        <p style="color:var(--text-soft);font-size:14px;line-height:1.5;">
          Registra cada llamada y nunca pierdas el seguimiento de un paciente.
        </p>
      </div>
    </div>
  </section>

  <section class="pricing" id="pricing">
    <h2 style="text-align:center;font-size:36px;font-weight:900;margin-bottom:14px;letter-spacing:-1px;">
      Empezá gratis. Escala cuando quieras.
    </h2>
    <p style="text-align:center;color:var(--text-soft);max-width:540px;margin:0 auto 48px;font-size:15px;">
      Sin contratos. Sin permanencia. Sin sorpresas.
    </p>
    <div class="pricing-grid">

      <div class="price-card">
        <span class="badge badge-free">FREE</span>
        <div class="price-tag">$0<small>/mes</small></div>
        <p style="color:var(--text-soft);font-size:13px;">Perfecto para empezar y probar.</p>
        <ul class="price-feat-list">
          <li>Hasta 100 pacientes</li>
          <li>Inbox WhatsApp</li>
          <li>1 usuario</li>
          <li>Plantillas básicas</li>
          <li>Soporte por email</li>
        </ul>
        <a href="/clinic/registro" class="btn btn-ghost" style="width:100%;justify-content:center;">Empezar gratis</a>
      </div>

      <div class="price-card featured">
        <span class="badge badge-pro">PRO ⭐</span>
        <div class="price-tag">$190.000<small>/mes</small></div>
        <p style="color:var(--text-soft);font-size:13px;">Para consultorios que ya facturan.</p>
        <ul class="price-feat-list">
          <li>Pacientes ilimitados</li>
          <li>WhatsApp + Instagram + Email</li>
          <li>IA SofIA</li>
          <li>Sync Google Sheets</li>
          <li>5 usuarios</li>
          <li>Tu logo en la plataforma</li>
          <li>Soporte priority</li>
        </ul>
        <a href="/clinic/registro" class="btn btn-primary" style="width:100%;justify-content:center;">Probar 14 días gratis</a>
      </div>

      <div class="price-card">
        <span class="badge badge-studio">STUDIO</span>
        <div class="price-tag">$390.000<small>/mes</small></div>
        <p style="color:var(--text-soft);font-size:13px;">Para clínicas con varios profesionales.</p>
        <ul class="price-feat-list">
          <li>Todo lo de Pro</li>
          <li>Usuarios ilimitados</li>
          <li>Dominio propio (tudr.com)</li>
          <li>Analytics avanzado</li>
          <li>API custom</li>
          <li>Onboarding personalizado</li>
          <li>Soporte 24/7</li>
        </ul>
        <a href="https://wa.me/573228783019?text=Quiero+info+del+plan+Studio" class="btn btn-ghost" style="width:100%;justify-content:center;">Hablar con ventas</a>
      </div>

    </div>
  </section>

  <footer style="padding:40px 24px;text-align:center;color:var(--text-soft);font-size:13px;border-top:1px solid var(--border);">
    <p><strong>Lapora Clinic</strong> · El cerebro digital de tu consultorio</p>
    <p style="margin-top:8px;">
      <a href="https://lapora.studio" style="color:var(--text-soft);">lapora.studio</a> ·
      <a href="https://wa.me/573228783019" style="color:var(--text-soft);">+57 322 878 3019</a> ·
      <a href="mailto:laporamarketingdigital@gmail.com" style="color:var(--text-soft);">laporamarketingdigital@gmail.com</a>
    </p>
  </footer>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 13) DEMO DATA — Cargar pacientes/mensajes/plantillas de ejemplo
# ════════════════════════════════════════════════════════════

@router.post("/app/demo-data", response_class=HTMLResponse)
async def cargar_demo(clinic_session: Optional[str] = Cookie(None)):
    """Carga 5 pacientes, 7 mensajes, 3 llamadas y 4 plantillas de ejemplo."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    creados = await cargar_demo_data(sesion["clinica_id"])
    return RedirectResponse(
        f"/clinic/app/?demo={creados['pacientes']}",
        status_code=303,
    )


# ════════════════════════════════════════════════════════════
# 14) IMPORTAR / EXPORTAR CSV de pacientes
# ════════════════════════════════════════════════════════════

@router.get("/app/pacientes/importar", response_class=HTMLResponse)
async def importar_pacientes_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Importar pacientes</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("pacientes", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/pacientes" style="font-size:13px;color:var(--text-soft);">← Volver</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Importar pacientes desde CSV</h1>

      <div class="card" style="max-width:680px;">
        <p style="margin-bottom:16px;font-size:14px;color:var(--text-soft);">
          Sube un archivo CSV con las columnas: <code>nombre, telefono, email, tratamiento, notas</code>.
          La primera fila debe ser el encabezado.
        </p>

        <details style="margin-bottom:18px;background:#fafaf9;padding:14px;border-radius:10px;border:1px solid var(--border);">
          <summary style="cursor:pointer;font-weight:600;font-size:13px;">📋 Ver ejemplo de CSV</summary>
          <pre style="background:white;padding:12px;border-radius:8px;margin-top:10px;font-size:12px;overflow-x:auto;">nombre,telefono,email,tratamiento,notas
María Pérez,+573001234567,maria@email.com,Ortodoncia,Control mensual
Carlos López,+573109876543,carlos@email.com,Limpieza,Primera consulta</pre>
        </details>

        <form method="post" action="/clinic/app/pacientes/importar" enctype="multipart/form-data"
              style="display:flex;flex-direction:column;gap:14px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Archivo CSV</label>
            <input type="file" name="archivo" accept=".csv,text/csv" required class="input">
          </div>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary">↑ Importar pacientes</button>
            <a href="/clinic/app/pacientes" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>

        <p style="margin-top:18px;font-size:12px;color:var(--text-soft);">
          💡 Tip: Si ya tienes Google Sheets, mejor usa la sincronización automática en
          <a href="/clinic/app/configuracion">Configuración</a>.
        </p>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/pacientes/importar", response_class=HTMLResponse)
async def importar_pacientes_procesar(
    archivo: UploadFile = File(...),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    contenido = (await archivo.read()).decode("utf-8", errors="replace")
    reader = _csv_mod.DictReader(StringIO(contenido))
    # Normalizar headers
    if reader.fieldnames:
        reader.fieldnames = [(h or "").lower().strip() for h in reader.fieldnames]

    creados = actualizados = 0
    async with async_session() as session:
        ahora = datetime.utcnow()
        for row in reader:
            nombre = (row.get("nombre") or row.get("name") or "").strip()
            if not nombre:
                continue
            telefono = (row.get("telefono") or row.get("teléfono") or "").strip()
            email = (row.get("email") or "").strip().lower()

            # Upsert por telefono o email
            existing = None
            if telefono:
                existing = (await session.execute(
                    select(Paciente).where(Paciente.clinica_id == sesion["clinica_id"])
                    .where(Paciente.telefono == telefono)
                )).scalar_one_or_none()
            if not existing and email:
                existing = (await session.execute(
                    select(Paciente).where(Paciente.clinica_id == sesion["clinica_id"])
                    .where(Paciente.email == email)
                )).scalar_one_or_none()

            datos = {
                "nombre": nombre,
                "telefono": telefono,
                "email": email,
                "tratamiento_actual": (row.get("tratamiento") or "").strip(),
                "notas_basicas": (row.get("notas") or "").strip(),
            }
            if existing:
                for k, v in datos.items():
                    if v:
                        setattr(existing, k, v)
                existing.ultimo_contacto = ahora
                actualizados += 1
            else:
                session.add(Paciente(
                    clinica_id=sesion["clinica_id"],
                    fuente="import_csv",
                    estado="nuevo",
                    primer_contacto=ahora,
                    ultimo_contacto=ahora,
                    **datos,
                ))
                creados += 1
        await session.commit()

    return RedirectResponse(
        f"/clinic/app/pacientes?creado=1&import_creados={creados}&import_actualizados={actualizados}",
        status_code=303,
    )


@router.get("/app/pacientes-export")
async def exportar_pacientes(clinic_session: Optional[str] = Cookie(None)):
    """Descarga un CSV con todos los pacientes de la clínica."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        pacientes = list((await session.execute(
            select(Paciente).where(Paciente.clinica_id == sesion["clinica_id"])
            .order_by(Paciente.nombre)
        )).scalars().all())

    output = StringIO()
    writer = _csv_mod.writer(output)
    writer.writerow(["nombre", "telefono", "email", "documento", "tratamiento",
                     "estado", "alergias", "notas", "fuente",
                     "primer_contacto", "ultimo_contacto"])
    for p in pacientes:
        writer.writerow([
            p.nombre or "", p.telefono or "", p.email or "",
            p.documento or "", p.tratamiento_actual or "",
            p.estado or "", p.alergias or "",
            p.notas_basicas or "", p.fuente or "",
            p.primer_contacto.strftime("%Y-%m-%d") if p.primer_contacto else "",
            p.ultimo_contacto.strftime("%Y-%m-%d") if p.ultimo_contacto else "",
        ])

    csv_content = output.getvalue()
    from fastapi.responses import Response
    nombre_archivo = f"pacientes_{datetime.now():%Y%m%d}.csv"
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{nombre_archivo}"'},
    )


# ════════════════════════════════════════════════════════════
# 15) BUSQUEDA GLOBAL — Pacientes, mensajes, llamadas
# ════════════════════════════════════════════════════════════

@router.get("/app/buscar", response_class=HTMLResponse)
async def buscar_global(
    q: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    pacientes_res = []
    mensajes_res = []
    llamadas_res = []
    if q and len(q.strip()) >= 2:
        patron = f"%{q.strip()}%"
        async with async_session() as session:
            pacientes_res = list((await session.execute(
                select(Paciente).where(Paciente.clinica_id == clinica.id).where(or_(
                    Paciente.nombre.ilike(patron),
                    Paciente.telefono.ilike(patron),
                    Paciente.email.ilike(patron),
                    Paciente.tratamiento_actual.ilike(patron),
                    Paciente.notas_basicas.ilike(patron),
                )).limit(20)
            )).scalars().all())
            mensajes_res = list((await session.execute(
                select(MensajeUnificado).where(MensajeUnificado.clinica_id == clinica.id)
                .where(MensajeUnificado.contenido.ilike(patron))
                .order_by(desc(MensajeUnificado.timestamp)).limit(20)
            )).scalars().all())
            llamadas_res = list((await session.execute(
                select(Llamada).where(Llamada.clinica_id == clinica.id)
                .where(Llamada.notas.ilike(patron))
                .order_by(desc(Llamada.timestamp)).limit(20)
            )).scalars().all())

    def render_pacientes():
        if not pacientes_res:
            return '<p style="color:var(--text-soft);font-size:13px;">Sin resultados en pacientes</p>'
        rows = ""
        for p in pacientes_res:
            rows += f"""
            <a href="/clinic/app/pacientes/{p.id}" style="display:block;padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);text-decoration:none;">
              <div style="font-weight:600;">{html.escape(p.nombre or '')}</div>
              <div style="font-size:12px;color:var(--text-soft);">{html.escape(p.telefono or '—')} · {html.escape(p.tratamiento_actual or 'Sin tratamiento')}</div>
            </a>"""
        return rows

    def render_mensajes():
        if not mensajes_res:
            return '<p style="color:var(--text-soft);font-size:13px;">Sin resultados en mensajes</p>'
        rows = ""
        for m in mensajes_res:
            ts = m.timestamp.strftime("%d/%m %H:%M") if m.timestamp else ""
            rows += f"""
            <a href="/clinic/app/inbox?paciente_id={m.paciente_id}" style="display:block;padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);text-decoration:none;">
              <div style="font-size:13px;line-height:1.4;">{html.escape((m.contenido or '')[:150])}</div>
              <div style="font-size:11px;color:var(--text-soft);margin-top:4px;">{html.escape(m.canal)} · {m.direccion} · {ts}</div>
            </a>"""
        return rows

    def render_llamadas():
        if not llamadas_res:
            return '<p style="color:var(--text-soft);font-size:13px;">Sin resultados en llamadas</p>'
        rows = ""
        for l in llamadas_res:
            ts = l.timestamp.strftime("%d/%m %H:%M") if l.timestamp else ""
            rows += f"""
            <a href="/clinic/app/pacientes/{l.paciente_id}" style="display:block;padding:10px 14px;border-bottom:1px solid var(--border);color:var(--text);text-decoration:none;">
              <div style="font-size:13px;line-height:1.4;">{html.escape((l.notas or '')[:150])}</div>
              <div style="font-size:11px;color:var(--text-soft);margin-top:4px;">{html.escape(l.direccion)} · {html.escape(l.resultado or '')} · {ts}</div>
            </a>"""
        return rows

    q_val = html.escape(q or "", quote=True)
    sin_resultados = q and not pacientes_res and not mensajes_res and not llamadas_res

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Buscar - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("buscar", sesion, clinica)}
    <main class="main">
      <h1 style="font-size:26px;font-weight:800;margin-bottom:16px;">🔍 Búsqueda global</h1>
      <form method="get" action="/clinic/app/buscar" style="margin-bottom:24px;">
        <input type="text" name="q" value="{q_val}" autofocus
               placeholder="Buscar en pacientes, mensajes y llamadas..."
               class="input" style="font-size:16px;padding:14px 16px;">
      </form>

      {('<p style="text-align:center;color:var(--text-soft);padding:60px 20px;"><strong>Sin resultados para</strong> ' + html.escape(q or '') + '. Probá con otra palabra.</p>' if sin_resultados else '')}

      {('' if not q else f'''
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:16px;">
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#1c1917;color:white;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">
            👥 Pacientes ({len(pacientes_res)})
          </div>
          {render_pacientes()}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#1c1917;color:white;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">
            💬 Mensajes ({len(mensajes_res)})
          </div>
          {render_mensajes()}
        </div>
        <div class="card" style="padding:0;overflow:hidden;">
          <div style="padding:12px 14px;background:#1c1917;color:white;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">
            📞 Llamadas ({len(llamadas_res)})
          </div>
          {render_llamadas()}
        </div>
      </div>''')}
    </main>
  </div>
</body></html>""")


# ════════════════════════════════════════════════════════════
# 16) HEALTH CHECK para Railway
# ════════════════════════════════════════════════════════════

@router.get("/health")
async def health_clinic():
    """Health check del módulo Lapora Clinic."""
    try:
        async with async_session() as session:
            await session.execute(select(func.count(Clinica.id)))
        return {"status": "ok", "service": "lapora_clinic", "db": "ok"}
    except Exception as e:
        return {"status": "degraded", "service": "lapora_clinic", "error": str(e)[:100]}


# ════════════════════════════════════════════════════════════
# 17) SUPER ADMIN — Cuenta maestra de Lapora
# ════════════════════════════════════════════════════════════
# Accesible solo con las credenciales del CRM interno (lapora / lapora-sofia-2026)
# Reutiliza la basic auth del módulo dashboard.

from fastapi.security import HTTPBasic, HTTPBasicCredentials
import secrets as _secrets

_superadmin_security = HTTPBasic()

def verificar_superadmin(credentials: HTTPBasicCredentials = Depends(_superadmin_security)):
    """Basic auth para la cuenta maestra (compartida con CRM /admin)."""
    user_ok = _secrets.compare_digest(credentials.username, os.getenv("LAPORA_DASHBOARD_USER", "lapora"))
    pass_ok = _secrets.compare_digest(credentials.password, os.getenv("LAPORA_DASHBOARD_PASS", "lapora-sofia-2026"))
    if not (user_ok and pass_ok):
        raise HTTPException(
            status_code=401, detail="No autorizado",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


@router.get("/superadmin", response_class=HTMLResponse)
async def superadmin_dashboard(user: str = Depends(verificar_superadmin)):
    """Lista TODAS las clínicas con stats — solo cuenta maestra Lapora."""
    async with async_session() as session:
        clinicas = list((await session.execute(
            select(Clinica).order_by(desc(Clinica.creado_en))
        )).scalars().all())
        # Stats por clínica
        stats: dict[int, dict] = {}
        for c in clinicas:
            n_pac = (await session.execute(
                select(func.count(Paciente.id)).where(Paciente.clinica_id == c.id)
            )).scalar() or 0
            n_msg = (await session.execute(
                select(func.count(MensajeUnificado.id)).where(MensajeUnificado.clinica_id == c.id)
            )).scalar() or 0
            n_usr = (await session.execute(
                select(func.count(UsuarioClinic.id)).where(UsuarioClinic.clinica_id == c.id)
            )).scalar() or 0
            stats[c.id] = {"pacientes": n_pac, "mensajes": n_msg, "usuarios": n_usr}

    total_clinicas = len(clinicas)
    activas = sum(1 for c in clinicas if not c.congelada)
    congeladas = total_clinicas - activas
    mrr = sum(c.monto_mensual_usd for c in clinicas if not c.congelada)

    filas = ""
    for c in clinicas:
        s = stats[c.id]
        estado_bg = "rgba(239,68,68,0.1)" if c.congelada else "transparent"
        estado_badge = (
            '<span style="background:#EF4444;color:white;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;">⏸ SUSPENDIDA</span>'
            if c.congelada else
            '<span style="background:#10B981;color:white;padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;">● ACTIVA</span>'
        )
        plan_color = {"free": "#78716C", "pro": "#10B981", "studio": "#3B82F6"}.get(c.plan, "#78716C")
        creado = c.creado_en.strftime("%d/%m/%Y") if c.creado_en else "—"
        accion = "descongelar" if c.congelada else "congelar"
        boton_label = "▶ Reactivar" if c.congelada else "⏸ Suspender"
        boton_color = "#10B981" if c.congelada else "#F59E0B"

        filas += f"""
        <tr style="background:{estado_bg};border-bottom:1px solid var(--border);">
          <td style="padding:14px;">
            <a href="/clinic/superadmin/clinicas/{c.id}" style="font-weight:600;color:var(--text);">{html.escape(c.nombre)}</a>
            <div style="font-size:11px;color:var(--text-soft);">{html.escape(c.slug)} · {html.escape(c.ciudad or "")}</div>
          </td>
          <td style="padding:14px;">{estado_badge}</td>
          <td style="padding:14px;">
            <span style="background:{plan_color}20;color:{plan_color};padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;">{c.plan}</span>
          </td>
          <td style="padding:14px;text-align:center;font-weight:600;">{s['pacientes']}</td>
          <td style="padding:14px;text-align:center;color:var(--text-soft);">{s['mensajes']}</td>
          <td style="padding:14px;text-align:center;color:var(--text-soft);">{s['usuarios']}</td>
          <td style="padding:14px;text-align:right;font-family:monospace;color:var(--green);font-weight:700;">${c.monto_mensual_usd}</td>
          <td style="padding:14px;color:var(--text-soft);font-size:12px;">{creado}</td>
          <td style="padding:14px;display:flex;gap:6px;">
            <a href="/clinic/superadmin/clinicas/{c.id}/login" target="_blank"
               style="background:#3B82F6;color:white;text-decoration:none;padding:6px 12px;border-radius:8px;font-size:11px;font-weight:600;" title="Entrar como esta clínica">👁 Ver</a>
            <form method="post" action="/clinic/superadmin/clinicas/{c.id}/{accion}" style="margin:0;"
                  onsubmit="return confirm('¿{boton_label} cuenta de {html.escape(c.nombre, quote=True)}?');">
              <button type="submit" style="background:{boton_color};color:white;border:none;padding:6px 12px;border-radius:8px;font-size:11px;font-weight:600;cursor:pointer;">{boton_label}</button>
            </form>
          </td>
        </tr>"""

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Super Admin - Lapora Clinic</title>{CSS_CLINIC}
<style>
  body {{ background: #0a0a0a; color: white; }}
  .sa-header {{ background: linear-gradient(135deg, #FF3B30, #E63227); padding: 32px 40px; }}
  .sa-stats {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 14px; padding: 24px 40px; }}
  .sa-stat {{ background: #1c1917; border-radius: 14px; padding: 20px; }}
  .sa-stat-label {{ font-size: 11px; color: #a8a29e; text-transform: uppercase; letter-spacing: 1px; font-weight: 700; }}
  .sa-stat-val {{ font-size: 28px; font-weight: 900; margin-top: 6px; color: white; }}
  table {{ background: #1c1917; color: white; }}
  table a {{ color: white; }}
  table tr {{ border-bottom: 1px solid #292524; }}
  .sa-table-wrap {{ padding: 0 40px 40px; }}
</style>
</head>
<body>
  <div class="sa-header">
    <div style="display:flex;justify-content:space-between;align-items:center;">
      <div>
        <h1 style="font-size:30px;font-weight:900;margin-bottom:4px;">⚡ Super Admin · Lapora Clinic</h1>
        <p style="opacity:0.9;">Vista maestra · Todas las clínicas del SaaS</p>
      </div>
      <div style="font-size:13px;opacity:0.9;">
        Logueado como: <strong>{html.escape(user)}</strong> ·
        <a href="/admin/contactos" style="color:white;text-decoration:underline;">CRM SofIA →</a>
      </div>
    </div>
  </div>

  <div class="sa-stats">
    <div class="sa-stat">
      <div class="sa-stat-label">Total clínicas</div>
      <div class="sa-stat-val">{total_clinicas}</div>
    </div>
    <div class="sa-stat">
      <div class="sa-stat-label">Activas</div>
      <div class="sa-stat-val" style="color:#10B981;">{activas}</div>
    </div>
    <div class="sa-stat">
      <div class="sa-stat-label">Suspendidas</div>
      <div class="sa-stat-val" style="color:#EF4444;">{congeladas}</div>
    </div>
    <div class="sa-stat">
      <div class="sa-stat-label">MRR estimado (USD)</div>
      <div class="sa-stat-val" style="color:#FF3B30;">${mrr}</div>
    </div>
  </div>

  <div class="sa-table-wrap">
    <div style="background:#1c1917;border-radius:14px;overflow:hidden;border:1px solid #292524;">
      <table style="width:100%;border-collapse:collapse;">
        <thead><tr style="background:#0a0a0a;color:#a8a29e;">
          <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Clínica</th>
          <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Estado</th>
          <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Plan</th>
          <th style="padding:14px;text-align:center;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Pacientes</th>
          <th style="padding:14px;text-align:center;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Msgs</th>
          <th style="padding:14px;text-align:center;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Users</th>
          <th style="padding:14px;text-align:right;font-size:11px;text-transform:uppercase;letter-spacing:1px;">USD/mes</th>
          <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Creado</th>
          <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Acciones</th>
        </tr></thead>
        <tbody>
          {filas if filas else '<tr><td colspan="9" style="padding:60px;text-align:center;color:#78716c;font-style:italic;">Aún no hay clínicas registradas.</td></tr>'}
        </tbody>
      </table>
    </div>
  </div>
</body></html>""")


@router.get("/superadmin/clinicas/{clinica_id}", response_class=HTMLResponse)
async def superadmin_detalle_clinica(
    clinica_id: int,
    user: str = Depends(verificar_superadmin),
):
    """Detalle administrativo de una clínica con acciones masivas."""
    async with async_session() as session:
        c = (await session.execute(select(Clinica).where(Clinica.id == clinica_id))).scalar_one_or_none()
        if not c:
            return HTMLResponse("<h1>Clínica no encontrada</h1>", status_code=404)
        usuarios = list((await session.execute(
            select(UsuarioClinic).where(UsuarioClinic.clinica_id == clinica_id)
        )).scalars().all())

    def esc(s): return html.escape(s or "", quote=True)
    estado_text = "SUSPENDIDA ⏸️" if c.congelada else "ACTIVA ●"
    estado_color = "#EF4444" if c.congelada else "#10B981"

    usuarios_html = ""
    for u in usuarios:
        ult = u.ultimo_login.strftime("%d/%m/%Y %H:%M") if u.ultimo_login else "Nunca"
        usuarios_html += f"<div style='padding:8px 0;border-bottom:1px solid #292524;'><strong>{esc(u.nombre)}</strong> · {esc(u.email)} · <span style='color:#a8a29e;font-size:12px;'>Último login: {ult}</span></div>"

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>{esc(c.nombre)} - Super Admin</title>{CSS_CLINIC}
<style>body {{ background: #0a0a0a; color: white; }} .card {{ background: #1c1917; border: 1px solid #292524; color: white; }} a {{ color: white; }}</style>
</head>
<body>
  <div style="padding:32px 40px;background:linear-gradient(135deg,#FF3B30,#E63227);">
    <a href="/clinic/superadmin" style="color:white;text-decoration:none;font-size:13px;">← Volver al super admin</a>
    <h1 style="font-size:30px;font-weight:900;margin-top:8px;">{esc(c.nombre)}</h1>
    <p style="opacity:0.9;font-size:14px;">slug: <code>{esc(c.slug)}</code> · Plan {esc(c.plan).upper()} · <span style="color:{estado_color};font-weight:700;">{estado_text}</span></p>
  </div>

  <div style="padding:32px 40px;display:grid;grid-template-columns:2fr 1fr;gap:20px;">

    <!-- ACCIONES PRINCIPALES -->
    <div class="card" style="padding:24px;">
      <h2 style="font-size:18px;font-weight:800;margin-bottom:16px;">⚙️ Acciones administrativas</h2>
      <div style="display:flex;flex-direction:column;gap:10px;">

        <form method="post" action="/clinic/superadmin/clinicas/{c.id}/login"
              style="display:flex;align-items:center;justify-content:space-between;padding:14px;background:#0a0a0a;border-radius:10px;">
          <div>
            <strong>🔐 Entrar como esta clínica</strong>
            <div style="font-size:12px;color:#a8a29e;margin-top:2px;">Crea una sesión y accede al dashboard de la clínica</div>
          </div>
          <button type="submit" style="background:#3B82F6;color:white;border:none;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">Acceder ahora →</button>
        </form>

        {(f'''<form method="post" action="/clinic/superadmin/clinicas/{c.id}/descongelar"
                style="display:flex;align-items:center;justify-content:space-between;padding:14px;background:#0a0a0a;border-radius:10px;"
                onsubmit="return confirm('¿Reactivar la cuenta de {esc(c.nombre)}?');">
            <div>
              <strong>▶ Reactivar cuenta</strong>
              <div style="font-size:12px;color:#a8a29e;margin-top:2px;">El cliente podrá volver a entrar y usar la plataforma</div>
            </div>
            <button type="submit" style="background:#10B981;color:white;border:none;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;">Reactivar</button>
          </form>''' if c.congelada else f'''
          <form method="post" action="/clinic/superadmin/clinicas/{c.id}/congelar"
                style="padding:14px;background:#0a0a0a;border-radius:10px;">
            <div style="margin-bottom:10px;">
              <strong>⏸ Suspender cuenta</strong>
              <div style="font-size:12px;color:#a8a29e;margin-top:2px;">No podrá entrar hasta que se reactive. Sus datos quedan intactos.</div>
            </div>
            <input type="text" name="motivo" placeholder="Motivo (ej: Falta de pago Mayo 2026)" required
                   style="width:100%;padding:10px;background:#1c1917;border:1px solid #292524;border-radius:8px;color:white;font-size:13px;margin-bottom:8px;">
            <button type="submit" onclick="return confirm('¿Suspender la cuenta de {esc(c.nombre)}?');" style="background:#F59E0B;color:white;border:none;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;width:100%;">⏸ Suspender ahora</button>
          </form>''')}

        <form method="post" action="/clinic/superadmin/clinicas/{c.id}/plan"
              style="padding:14px;background:#0a0a0a;border-radius:10px;">
          <div style="margin-bottom:10px;">
            <strong>💰 Cambiar plan / facturación</strong>
            <div style="font-size:12px;color:#a8a29e;margin-top:2px;">Plan actual: {esc(c.plan).upper()} · ${c.monto_mensual_usd} USD/mes</div>
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px;">
            <select name="plan" style="padding:10px;background:#1c1917;border:1px solid #292524;border-radius:8px;color:white;">
              <option value="free" {'selected' if c.plan == 'free' else ''}>FREE</option>
              <option value="pro" {'selected' if c.plan == 'pro' else ''}>PRO ($100/mes)</option>
              <option value="studio" {'selected' if c.plan == 'studio' else ''}>STUDIO ($250/mes)</option>
            </select>
            <input type="number" name="monto_usd" value="{c.monto_mensual_usd}" placeholder="USD/mes"
                   style="padding:10px;background:#1c1917;border:1px solid #292524;border-radius:8px;color:white;">
          </div>
          <button type="submit" style="background:#10B981;color:white;border:none;padding:10px 18px;border-radius:8px;font-size:13px;font-weight:600;cursor:pointer;width:100%;">Actualizar plan</button>
        </form>
      </div>
    </div>

    <!-- INFO LATERAL -->
    <div class="card" style="padding:24px;">
      <h3 style="font-size:14px;font-weight:700;text-transform:uppercase;color:#a8a29e;letter-spacing:1px;margin-bottom:14px;">📋 Datos</h3>
      <div style="font-size:13px;line-height:1.8;">
        <div><strong>ID:</strong> {c.id}</div>
        <div><strong>Slug:</strong> <code>{esc(c.slug)}</code></div>
        <div><strong>Especialidad:</strong> {esc(c.especialidad) or "—"}</div>
        <div><strong>Ciudad:</strong> {esc(c.ciudad) or "—"}</div>
        <div><strong>WhatsApp:</strong> {('✓ Conectado' if c.whatsapp_phone_id else '✗ No')}</div>
        <div><strong>Instagram:</strong> {('✓ Conectado' if c.instagram_account_id else '✗ No')}</div>
        <div><strong>Sheets:</strong> {('✓ Conectado' if c.google_sheet_id else '✗ No')}</div>
        <div><strong>Creado:</strong> {c.creado_en.strftime('%d/%m/%Y') if c.creado_en else '—'}</div>
        {(f'<div style="margin-top:14px;padding:10px;background:#7F1D1D;border-radius:8px;font-size:12px;"><strong>Motivo suspensión:</strong><br>{esc(c.motivo_suspension)}<br><span style="color:#fca5a5;">desde {c.fecha_suspension.strftime("%d/%m/%Y") if c.fecha_suspension else "—"}</span></div>' if c.congelada else '')}
      </div>

      <h3 style="font-size:14px;font-weight:700;text-transform:uppercase;color:#a8a29e;letter-spacing:1px;margin-top:24px;margin-bottom:10px;">👥 Usuarios ({len(usuarios)})</h3>
      <div style="font-size:13px;">{usuarios_html or "<em>Sin usuarios</em>"}</div>
    </div>
  </div>
</body></html>""")


@router.post("/superadmin/clinicas/{clinica_id}/congelar")
async def superadmin_congelar(
    clinica_id: int,
    motivo: str = Form(""),
    user: str = Depends(verificar_superadmin),
):
    async with async_session() as session:
        c = (await session.execute(select(Clinica).where(Clinica.id == clinica_id))).scalar_one_or_none()
        if c:
            c.congelada = True
            c.motivo_suspension = motivo.strip() or "Falta de pago"
            c.fecha_suspension = datetime.utcnow()
            await session.commit()
        # Invalidar sesiones activas de la clínica
        global SESSIONS
        tokens_a_eliminar = [t for t, s in SESSIONS.items() if s.get("clinica_id") == clinica_id]
        for t in tokens_a_eliminar:
            del SESSIONS[t]
    return RedirectResponse(f"/clinic/superadmin/clinicas/{clinica_id}", status_code=303)


@router.post("/superadmin/clinicas/{clinica_id}/descongelar")
async def superadmin_descongelar(clinica_id: int, user: str = Depends(verificar_superadmin)):
    async with async_session() as session:
        c = (await session.execute(select(Clinica).where(Clinica.id == clinica_id))).scalar_one_or_none()
        if c:
            c.congelada = False
            c.motivo_suspension = ""
            c.fecha_suspension = None
            await session.commit()
    return RedirectResponse(f"/clinic/superadmin/clinicas/{clinica_id}", status_code=303)


@router.post("/superadmin/clinicas/{clinica_id}/plan")
async def superadmin_cambiar_plan(
    clinica_id: int,
    plan: str = Form(...),
    monto_usd: int = Form(0),
    user: str = Depends(verificar_superadmin),
):
    async with async_session() as session:
        c = (await session.execute(select(Clinica).where(Clinica.id == clinica_id))).scalar_one_or_none()
        if c:
            c.plan = plan
            c.monto_mensual_usd = monto_usd
            await session.commit()
    return RedirectResponse(f"/clinic/superadmin/clinicas/{clinica_id}", status_code=303)


# ════════════════════════════════════════════════════════════
# 18) CITAS — Agenda con Google Calendar integrado
# ════════════════════════════════════════════════════════════

@router.get("/app/citas", response_class=HTMLResponse)
async def vista_citas(
    creado: Optional[str] = None,
    clinic_session: Optional[str] = Cookie(None),
):
    """Lista las citas (locales + Google Calendar si está conectado)."""
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        citas = list((await session.execute(
            select(CitaClinic).where(CitaClinic.clinica_id == clinica.id)
            .order_by(CitaClinic.fecha_hora.desc())
            .limit(100)
        )).scalars().all())
        # Pre-cargar nombres de pacientes
        pids = [c.paciente_id for c in citas if c.paciente_id]
        nombres = {}
        if pids:
            for row in (await session.execute(
                select(Paciente.id, Paciente.nombre, Paciente.telefono).where(Paciente.id.in_(pids))
            )).all():
                nombres[row[0]] = (row[1], row[2])

    # Si tiene Calendar conectado, traer eventos también
    eventos_gcal = []
    calendar_conectado = bool(clinica.google_calendar_id)
    if calendar_conectado:
        try:
            from agent.clinic_calendar import listar_eventos
            eventos_gcal = listar_eventos(clinica.google_calendar_id, dias=14, max_resultados=20)
        except Exception:
            pass

    estado_colors = {
        "agendada": "#3B82F6", "confirmada": "#10B981",
        "completada": "#A855F7", "no_show": "#EF4444", "cancelada": "#78716C",
    }

    if citas:
        filas = ""
        for c in citas:
            nombre, tel = nombres.get(c.paciente_id, ("—", ""))
            color = estado_colors.get(c.estado, "#78716C")
            fecha = c.fecha_hora.strftime("%d/%m/%Y %H:%M") if c.fecha_hora else "—"
            meet_link = ""
            if c.google_event_id:
                meet_link = f'<a href="https://calendar.google.com/calendar/event?eid={c.google_event_id}" target="_blank" style="color:#3B82F6;font-size:12px;">🔗 Calendar</a>'
            filas += f"""
              <tr style="border-bottom:1px solid var(--border);">
                <td style="padding:14px;font-weight:600;">{fecha}</td>
                <td style="padding:14px;">
                  <a href="/clinic/app/pacientes/{c.paciente_id}" style="font-weight:600;color:var(--text);">{html.escape(nombre)}</a>
                  <div style="font-size:11px;color:var(--text-soft);">{html.escape(tel or '')}</div>
                </td>
                <td style="padding:14px;color:var(--text-soft);font-size:13px;">{html.escape(c.motivo or '—')}</td>
                <td style="padding:14px;">
                  <span style="background:{color}20;color:{color};padding:3px 10px;border-radius:999px;font-size:11px;font-weight:700;text-transform:uppercase;">{html.escape(c.estado or '')}</span>
                </td>
                <td style="padding:14px;color:var(--text-soft);">{c.duracion_min} min · {meet_link}</td>
                <td style="padding:14px;">
                  <form method="post" action="/clinic/app/citas/{c.id}/cancelar" style="margin:0;"
                        onsubmit="return confirm('¿Cancelar esta cita?');">
                    <button type="submit" style="background:transparent;color:#EF4444;border:1px solid #EF4444;padding:6px 10px;border-radius:6px;font-size:11px;cursor:pointer;">Cancelar</button>
                  </form>
                </td>
              </tr>"""
        contenido_tabla = f"""
        <table style="width:100%;border-collapse:collapse;">
          <thead><tr style="background:#1c1917;color:white;">
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Fecha</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Paciente</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Motivo</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Estado</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;">Detalles</th>
            <th style="padding:14px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;"></th>
          </tr></thead>
          <tbody>{filas}</tbody>
        </table>"""
    else:
        contenido_tabla = """
        <div style="text-align:center;padding:60px 20px;color:var(--text-soft);">
          <div style="font-size:64px;margin-bottom:16px;">📅</div>
          <h3 style="font-size:18px;font-weight:700;color:var(--text);margin-bottom:8px;">Sin citas agendadas</h3>
          <p style="margin-bottom:24px;">Agenda tu primera cita y se sincronizará automáticamente con Google Calendar.</p>
          <a href="/clinic/app/citas/nueva" class="btn btn-primary">+ Nueva cita</a>
        </div>"""

    banner_calendar = ""
    if not calendar_conectado:
        banner_calendar = """
        <div style="background:#FEF3C7;border:1px solid #F59E0B;color:#78350F;padding:14px 18px;border-radius:12px;margin-bottom:18px;font-size:14px;">
          ⚙️ <strong>Conecta Google Calendar</strong> para que tus citas se sincronicen automáticamente y reciban invitación con Google Meet.
          <a href="/clinic/app/configuracion" style="font-weight:700;color:#78350F;">Conectar →</a>
        </div>"""

    banner_creado = ""
    if creado:
        banner_creado = '<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:12px 16px;border-radius:10px;margin-bottom:16px;font-size:14px;font-weight:600;">✓ Cita agendada correctamente</div>'

    eventos_html = ""
    if eventos_gcal:
        items = ""
        for e in eventos_gcal[:5]:
            try:
                from datetime import datetime as _dt
                fecha_str = e['inicio'][:16].replace('T', ' ')
            except Exception:
                fecha_str = e['inicio']
            items += f'<div style="padding:8px 0;border-bottom:1px solid var(--border);font-size:13px;"><strong>{html.escape(e["titulo"][:50])}</strong> · <span style="color:var(--text-soft);">{fecha_str}</span></div>'
        eventos_html = f"""
        <div class="card" style="margin-bottom:18px;">
          <h3 style="font-size:13px;font-weight:700;text-transform:uppercase;color:var(--text-soft);letter-spacing:1px;margin-bottom:10px;">📅 Próximos eventos en tu Google Calendar</h3>
          {items}
        </div>"""

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Citas - Lapora Clinic</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("citas", sesion, clinica)}
    <main class="main">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:20px;flex-wrap:wrap;gap:14px;">
        <div>
          <h1 style="font-size:26px;font-weight:800;margin-bottom:4px;">Citas</h1>
          <p style="color:var(--text-soft);">{len(citas)} citas locales · {('✓ Calendar conectado' if calendar_conectado else '⚠ Sin Calendar')}</p>
        </div>
        <a href="/clinic/app/citas/nueva" class="btn btn-primary">+ Nueva cita</a>
      </div>
      {banner_calendar}
      {banner_creado}
      {eventos_html}
      <div class="card" style="padding:0;overflow:hidden;">{contenido_tabla}</div>
    </main>
  </div>
</body></html>""")


@router.get("/app/citas/nueva", response_class=HTMLResponse)
async def nueva_cita_form(clinic_session: Optional[str] = Cookie(None)):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    async with async_session() as session:
        pacientes = list((await session.execute(
            select(Paciente).where(Paciente.clinica_id == clinica.id).order_by(Paciente.nombre).limit(500)
        )).scalars().all())

    opciones = "".join(
        f'<option value="{p.id}" data-email="{html.escape(p.email or "", quote=True)}">{html.escape(p.nombre)} ({html.escape(p.telefono or "")})</option>'
        for p in pacientes
    )
    from datetime import datetime as _dt
    fecha_minima = _dt.now().strftime("%Y-%m-%dT%H:%M")
    calendar_conectado = bool(clinica.google_calendar_id)

    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><title>Nueva cita</title>{CSS_CLINIC}</head>
<body>
  <div class="app-wrap">
    {sidebar_clinic("citas", sesion, clinica)}
    <main class="main">
      <a href="/clinic/app/citas" style="font-size:13px;color:var(--text-soft);">← Volver</a>
      <h1 style="font-size:26px;font-weight:800;margin:8px 0 24px;">Agendar cita</h1>

      <div class="card" style="max-width:600px;">
        {('<div style="background:#ECFDF5;border:1px solid #10B981;color:#065F46;padding:10px 14px;border-radius:8px;margin-bottom:16px;font-size:13px;">✓ Google Calendar conectado — la cita se creará automáticamente con Google Meet.</div>' if calendar_conectado else '<div style="background:#FEF3C7;border:1px solid #F59E0B;color:#78350F;padding:10px 14px;border-radius:8px;margin-bottom:16px;font-size:13px;">⚠ Sin Google Calendar conectado. La cita se guardará solo localmente. <a href="/clinic/app/configuracion" style="font-weight:700;">Conectar</a></div>')}

        <form method="post" action="/clinic/app/citas/nueva" style="display:flex;flex-direction:column;gap:16px;">
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Paciente *</label>
            <select name="paciente_id" required class="input" autofocus>
              <option value="">Selecciona un paciente...</option>
              {opciones}
            </select>
            {('<p style="font-size:12px;color:var(--text-soft);margin-top:6px;">No tienes pacientes. <a href="/clinic/app/pacientes/nuevo">Crear uno</a> primero.</p>' if not pacientes else '')}
          </div>
          <div style="display:grid;grid-template-columns:2fr 1fr;gap:14px;">
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Fecha y hora *</label>
              <input type="datetime-local" name="fecha_hora" min="{fecha_minima}" required class="input">
            </div>
            <div>
              <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Duración (min)</label>
              <select name="duracion_min" class="input">
                <option value="15">15 min</option>
                <option value="30" selected>30 min</option>
                <option value="45">45 min</option>
                <option value="60">60 min</option>
                <option value="90">90 min</option>
              </select>
            </div>
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Motivo</label>
            <input type="text" name="motivo" placeholder="Control, valoración, limpieza..." class="input">
          </div>
          <div>
            <label style="font-size:12px;font-weight:700;display:block;margin-bottom:5px;">Notas</label>
            <textarea name="notas" rows="3" class="input" style="resize:vertical;font-family:inherit;"
                      placeholder="Información adicional para el paciente..."></textarea>
          </div>
          <div style="display:flex;gap:10px;">
            <button type="submit" class="btn btn-primary" {('disabled' if not pacientes else '')}>📅 Agendar cita</button>
            <a href="/clinic/app/citas" class="btn btn-ghost">Cancelar</a>
          </div>
        </form>
      </div>
    </main>
  </div>
</body></html>""")


@router.post("/app/citas/nueva", response_class=HTMLResponse)
async def nueva_cita_procesar(
    paciente_id: int = Form(...),
    fecha_hora: str = Form(...),
    duracion_min: int = Form(30),
    motivo: str = Form(""),
    notas: str = Form(""),
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)
    clinica = await obtener_clinica(sesion["clinica_id"])

    # Parsear fecha
    try:
        dt = datetime.fromisoformat(fecha_hora)
    except ValueError:
        return RedirectResponse("/clinic/app/citas?error=fecha_invalida", status_code=303)

    google_event_id = ""
    link_meet = ""

    # Si tiene Calendar conectado, crear evento ahí
    if clinica.google_calendar_id:
        try:
            from agent.clinic_calendar import crear_evento
            async with async_session() as session:
                paciente = (await session.execute(
                    select(Paciente).where(Paciente.id == paciente_id)
                )).scalar_one_or_none()
            titulo = f"{paciente.nombre if paciente else 'Paciente'} - {motivo or 'Cita'}"
            descripcion_evento = f"""Paciente: {paciente.nombre if paciente else ''}
Teléfono: {paciente.telefono if paciente else ''}
Email: {paciente.email if paciente else ''}
Motivo: {motivo}
Notas: {notas}
---
Cita agendada desde Lapora Clinic
{clinica.nombre}"""
            resultado = crear_evento(
                calendar_id=clinica.google_calendar_id,
                fecha_hora=dt,
                titulo=titulo,
                descripcion=descripcion_evento,
                duracion_min=duracion_min,
                email_paciente=paciente.email if paciente and paciente.email else None,
            )
            if resultado.get("exito"):
                google_event_id = resultado.get("evento_id", "")
                link_meet = resultado.get("link_meet", "")
        except Exception:
            pass  # Si falla Calendar, igual guardamos en BD

    async with async_session() as session:
        session.add(CitaClinic(
            clinica_id=sesion["clinica_id"],
            paciente_id=paciente_id,
            fecha_hora=dt,
            duracion_min=duracion_min,
            motivo=motivo.strip(),
            notas=notas.strip(),
            estado="agendada",
            google_event_id=google_event_id,
        ))
        # Incrementar contador en paciente
        p = (await session.execute(select(Paciente).where(Paciente.id == paciente_id))).scalar_one_or_none()
        if p:
            p.total_citas = (p.total_citas or 0) + 1
            p.ultima_cita = dt
        await session.commit()

    return RedirectResponse("/clinic/app/citas?creado=1", status_code=303)


@router.post("/app/citas/{cita_id}/cancelar", response_class=HTMLResponse)
async def cancelar_cita(
    cita_id: int,
    clinic_session: Optional[str] = Cookie(None),
):
    sesion = obtener_sesion(clinic_session)
    if not sesion:
        return RedirectResponse("/clinic/login", status_code=303)

    async with async_session() as session:
        cita = (await session.execute(
            select(CitaClinic).where(CitaClinic.id == cita_id)
            .where(CitaClinic.clinica_id == sesion["clinica_id"])
        )).scalar_one_or_none()
        if not cita:
            return RedirectResponse("/clinic/app/citas", status_code=303)

        # Cancelar también en Google Calendar
        if cita.google_event_id:
            clinica = await obtener_clinica(sesion["clinica_id"])
            if clinica and clinica.google_calendar_id:
                try:
                    from agent.clinic_calendar import cancelar_evento
                    cancelar_evento(clinica.google_calendar_id, cita.google_event_id)
                except Exception:
                    pass

        cita.estado = "cancelada"
        await session.commit()

    return RedirectResponse("/clinic/app/citas", status_code=303)


@router.api_route("/superadmin/clinicas/{clinica_id}/login", methods=["GET", "POST"])
async def superadmin_impersonate(
    clinica_id: int,
    user: str = Depends(verificar_superadmin),
):
    """Permite al super admin entrar como una clínica (impersonation segura)."""
    async with async_session() as session:
        c = (await session.execute(select(Clinica).where(Clinica.id == clinica_id))).scalar_one_or_none()
        if not c:
            return HTMLResponse("<h1>Clínica no encontrada</h1>", status_code=404)
        # Buscar el usuario owner de la clínica
        owner = (await session.execute(
            select(UsuarioClinic).where(UsuarioClinic.clinica_id == clinica_id)
            .where(UsuarioClinic.rol == "owner").limit(1)
        )).scalar_one_or_none()
        if not owner:
            owner = (await session.execute(
                select(UsuarioClinic).where(UsuarioClinic.clinica_id == clinica_id).limit(1)
            )).scalar_one_or_none()
        if not owner:
            return HTMLResponse("<h1>Esta clínica no tiene usuarios. Crea uno primero.</h1>", status_code=400)

        token = crear_sesion(owner)
        # Marcar la sesión como impersonation
        SESSIONS[token]["impersonado_por"] = user

    response = RedirectResponse("/clinic/app/?impersonate=1", status_code=303)
    response.set_cookie("clinic_session", token, max_age=86400, httponly=True, samesite="lax")
    return response

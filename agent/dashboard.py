# -*- coding: utf-8 -*-
# agent/dashboard.py — Dashboard CRM premium para SofIA - Lapora
# Generado por AgentKit

"""
Dashboard CRM web premium para gestionar contactos, conversaciones y leads.
Diseno inspirado en Linear/Stripe con identidad visual Lapora.

Endpoints:
- GET  /admin/                              -> Redirige a /admin/contactos
- GET  /admin/contactos                     -> Lista de contactos con filtros
- GET  /admin/contactos/{tel}               -> Detalle del contacto + chat
- POST /admin/contactos/{tel}/editar        -> Actualizar contacto
- GET  /admin/conversaciones                -> Lista de conversaciones
- GET  /admin/conversaciones/{tel}          -> Chat estilo WhatsApp
- GET  /admin/api/stats                     -> Stats JSON
"""

import os
import secrets
import hashlib
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy import select, func, or_

from agent.memory import async_session, Mensaje, Contacto

router = APIRouter(prefix="/admin", tags=["admin"])
security = HTTPBasic()

ADMIN_USER = os.getenv("ADMIN_USER", "lapora")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "lapora-sofia-2026")

ESTADOS = ["nuevo", "contactado", "calificado", "agendado", "cliente", "perdido"]
ESTADOS_LABELS = {
    "nuevo": "Nuevo",
    "contactado": "Contactado",
    "calificado": "Calificado",
    "agendado": "Agendado",
    "cliente": "Cliente",
    "perdido": "Perdido",
}
ESTADOS_COLORES = {
    "nuevo":       {"bg": "#F3F4F6", "fg": "#6B7280", "dot": "#9CA3AF"},
    "contactado":  {"bg": "#DBEAFE", "fg": "#1E40AF", "dot": "#3B82F6"},
    "calificado":  {"bg": "#FEF3C7", "fg": "#92400E", "dot": "#F59E0B"},
    "agendado":    {"bg": "#FED7AA", "fg": "#9A3412", "dot": "#FB923C"},
    "cliente":     {"bg": "#D1FAE5", "fg": "#065F46", "dot": "#10B981"},
    "perdido":     {"bg": "#FEE2E2", "fg": "#991B1B", "dot": "#EF4444"},
}


def verificar_credenciales(credentials: HTTPBasicCredentials = Depends(security)):
    """Valida credenciales basicas."""
    usuario_ok = secrets.compare_digest(credentials.username, ADMIN_USER)
    password_ok = secrets.compare_digest(credentials.password, ADMIN_PASSWORD)
    if not (usuario_ok and password_ok):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales incorrectas",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


def iniciales(nombre: str, telefono: str) -> str:
    """Genera iniciales para avatar."""
    if nombre and nombre.strip():
        partes = nombre.strip().split()
        if len(partes) >= 2:
            return (partes[0][0] + partes[1][0]).upper()
        return partes[0][:2].upper()
    return telefono[-2:] if telefono else "?"


def avatar_color(telefono: str) -> str:
    """Genera color consistente para avatar basado en telefono."""
    colores = [
        "#FF3B30",  # Lapora red
        "#FF6B5E",
        "#F97316",
        "#EAB308",
        "#22C55E",
        "#06B6D4",
        "#3B82F6",
        "#8B5CF6",
        "#EC4899",
        "#A855F7",
    ]
    h = int(hashlib.md5(telefono.encode()).hexdigest(), 16)
    return colores[h % len(colores)]


def tiempo_relativo(dt: Optional[datetime]) -> str:
    """Convierte datetime a tiempo relativo (hace 5 min, hace 2h, etc)."""
    if dt is None:
        return "—"
    ahora = datetime.utcnow()
    diff = ahora - dt
    segundos = int(diff.total_seconds())
    if segundos < 60:
        return "ahora"
    if segundos < 3600:
        return f"hace {segundos // 60}m"
    if segundos < 86400:
        return f"hace {segundos // 3600}h"
    if segundos < 604800:
        return f"hace {segundos // 86400}d"
    return dt.strftime("%d/%m/%y")


# ════════════════════════════════════════════════════════════
# CSS PREMIUM
# ════════════════════════════════════════════════════════════

CSS_BASE = """
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<style>
    *, *::before, *::after {
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }
    :root {
        --lapora-red: #FF3B30;
        --lapora-red-dark: #E63227;
        --lapora-red-light: #FF6B5E;
        --lapora-red-50: #FFF1F0;
        --lapora-red-100: #FFE4E1;

        --gray-50: #FAFAF9;
        --gray-100: #F5F5F4;
        --gray-200: #E7E5E4;
        --gray-300: #D6D3D1;
        --gray-400: #A8A29E;
        --gray-500: #78716C;
        --gray-600: #57534E;
        --gray-700: #44403C;
        --gray-800: #292524;
        --gray-900: #1C1917;

        --shadow-sm: 0 1px 2px 0 rgba(0,0,0,0.04);
        --shadow-md: 0 4px 6px -1px rgba(0,0,0,0.05), 0 2px 4px -2px rgba(0,0,0,0.04);
        --shadow-lg: 0 10px 15px -3px rgba(0,0,0,0.05), 0 4px 6px -4px rgba(0,0,0,0.04);
        --shadow-xl: 0 20px 25px -5px rgba(0,0,0,0.07), 0 8px 10px -6px rgba(0,0,0,0.05);

        --radius-sm: 6px;
        --radius-md: 10px;
        --radius-lg: 14px;
        --radius-xl: 20px;

        --transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }
    html, body {
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, sans-serif;
        background: var(--gray-50);
        color: var(--gray-900);
        font-size: 14px;
        line-height: 1.5;
        -webkit-font-smoothing: antialiased;
        -moz-osx-font-smoothing: grayscale;
    }
    a { color: var(--lapora-red); text-decoration: none; }
    a:hover { color: var(--lapora-red-dark); }

    /* Layout principal con sidebar */
    .app {
        display: grid;
        grid-template-columns: 260px 1fr;
        min-height: 100vh;
    }

    /* SIDEBAR */
    .sidebar {
        background: white;
        border-right: 1px solid var(--gray-200);
        padding: 24px 16px;
        position: sticky;
        top: 0;
        height: 100vh;
        overflow-y: auto;
    }
    .brand {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 0 8px 24px;
        border-bottom: 1px solid var(--gray-200);
        margin-bottom: 16px;
    }
    .brand-logo {
        width: 38px;
        height: 38px;
        background: var(--lapora-red);
        border-radius: 12px;
        display: flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 800;
        font-size: 18px;
        letter-spacing: -1px;
        box-shadow: 0 4px 12px rgba(255,59,48,0.25);
    }
    .brand-text { display: flex; flex-direction: column; }
    .brand-name { font-weight: 700; color: var(--gray-900); font-size: 15px; }
    .brand-sub { font-size: 11px; color: var(--gray-500); font-weight: 500; }

    .nav-section {
        margin-bottom: 24px;
    }
    .nav-section-title {
        font-size: 11px;
        font-weight: 600;
        color: var(--gray-400);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        padding: 0 12px 8px;
    }
    .nav-link {
        display: flex;
        align-items: center;
        gap: 12px;
        padding: 9px 12px;
        border-radius: var(--radius-md);
        color: var(--gray-700);
        font-weight: 500;
        font-size: 14px;
        margin-bottom: 2px;
        transition: var(--transition);
        cursor: pointer;
    }
    .nav-link:hover {
        background: var(--gray-100);
        color: var(--gray-900);
    }
    .nav-link.active {
        background: var(--lapora-red-50);
        color: var(--lapora-red);
        font-weight: 600;
    }
    .nav-link svg {
        width: 18px;
        height: 18px;
        flex-shrink: 0;
    }
    .nav-badge {
        margin-left: auto;
        font-size: 11px;
        font-weight: 600;
        padding: 2px 8px;
        border-radius: 999px;
        background: var(--gray-200);
        color: var(--gray-600);
    }
    .nav-link.active .nav-badge {
        background: var(--lapora-red);
        color: white;
    }

    /* CONTENIDO PRINCIPAL */
    .main {
        min-width: 0;
        padding: 32px 40px;
    }
    .page-header {
        margin-bottom: 28px;
        display: flex;
        justify-content: space-between;
        align-items: flex-end;
        gap: 24px;
        flex-wrap: wrap;
    }
    .page-title {
        font-size: 26px;
        font-weight: 700;
        color: var(--gray-900);
        letter-spacing: -0.5px;
        margin-bottom: 4px;
    }
    .page-subtitle {
        color: var(--gray-500);
        font-size: 14px;
    }

    /* STATS PROFESIONAL */
    .stats-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
        gap: 12px;
        margin-bottom: 24px;
    }
    .stat-card {
        background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-lg);
        padding: 18px 20px;
        transition: var(--transition);
        position: relative;
        overflow: hidden;
    }
    .stat-card:hover {
        border-color: var(--gray-300);
        transform: translateY(-1px);
        box-shadow: var(--shadow-md);
    }
    .stat-card-label {
        display: flex;
        align-items: center;
        gap: 8px;
        font-size: 12px;
        font-weight: 500;
        color: var(--gray-500);
        text-transform: uppercase;
        letter-spacing: 0.3px;
        margin-bottom: 8px;
    }
    .stat-dot {
        width: 8px;
        height: 8px;
        border-radius: 999px;
        flex-shrink: 0;
    }
    .stat-card-value {
        font-size: 28px;
        font-weight: 700;
        color: var(--gray-900);
        letter-spacing: -0.5px;
        line-height: 1;
    }
    .stat-card-total {
        background: linear-gradient(135deg, var(--lapora-red) 0%, var(--lapora-red-light) 100%);
        color: white;
        border: none;
    }
    .stat-card-total .stat-card-label { color: rgba(255,255,255,0.85); }
    .stat-card-total .stat-card-value { color: white; }

    /* CARD GENERAL */
    .card {
        background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-lg);
        overflow: hidden;
        margin-bottom: 20px;
    }
    .card-header {
        padding: 18px 24px;
        border-bottom: 1px solid var(--gray-200);
        display: flex;
        justify-content: space-between;
        align-items: center;
        gap: 12px;
    }
    .card-title {
        font-weight: 600;
        font-size: 15px;
        color: var(--gray-900);
    }
    .card-subtitle {
        color: var(--gray-500);
        font-size: 13px;
        font-weight: 400;
        margin-top: 2px;
    }

    /* FILTROS */
    .filters {
        display: flex;
        gap: 10px;
        flex-wrap: wrap;
        padding: 16px 24px;
        background: var(--gray-50);
        border-bottom: 1px solid var(--gray-200);
    }
    .input, .select {
        padding: 9px 14px;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-md);
        font-size: 13px;
        font-family: inherit;
        color: var(--gray-900);
        background: white;
        transition: var(--transition);
        outline: none;
    }
    .input:focus, .select:focus {
        border-color: var(--lapora-red);
        box-shadow: 0 0 0 3px rgba(255,59,48,0.1);
    }
    .input-search {
        flex: 1;
        min-width: 240px;
        padding-left: 38px;
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='16' height='16' viewBox='0 0 24 24' fill='none' stroke='%23A8A29E' stroke-width='2'><circle cx='11' cy='11' r='8'/><line x1='21' y1='21' x2='16.65' y2='16.65'/></svg>");
        background-repeat: no-repeat;
        background-position: 14px center;
    }
    .select {
        cursor: pointer;
        padding-right: 32px;
        background-image: url("data:image/svg+xml;utf8,<svg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%2378716C' stroke-width='2'><polyline points='6 9 12 15 18 9'/></svg>");
        background-repeat: no-repeat;
        background-position: right 10px center;
        -webkit-appearance: none;
        -moz-appearance: none;
        appearance: none;
    }

    /* BOTONES */
    .btn {
        display: inline-flex;
        align-items: center;
        justify-content: center;
        gap: 6px;
        padding: 9px 16px;
        border-radius: var(--radius-md);
        font-size: 13px;
        font-weight: 600;
        font-family: inherit;
        cursor: pointer;
        border: none;
        transition: var(--transition);
        white-space: nowrap;
    }
    .btn-primary {
        background: var(--lapora-red);
        color: white;
        box-shadow: 0 1px 2px rgba(255,59,48,0.15);
    }
    .btn-primary:hover {
        background: var(--lapora-red-dark);
        box-shadow: 0 4px 12px rgba(255,59,48,0.25);
        transform: translateY(-1px);
    }
    .btn-secondary {
        background: white;
        color: var(--gray-700);
        border: 1px solid var(--gray-200);
    }
    .btn-secondary:hover {
        background: var(--gray-50);
        border-color: var(--gray-300);
        color: var(--gray-900);
    }
    .btn-ghost {
        background: transparent;
        color: var(--gray-600);
    }
    .btn-ghost:hover { background: var(--gray-100); color: var(--gray-900); }

    /* TABLA */
    .table-wrap { overflow-x: auto; }
    table {
        width: 100%;
        border-collapse: collapse;
    }
    th {
        background: var(--gray-50);
        padding: 11px 24px;
        text-align: left;
        font-size: 11px;
        font-weight: 600;
        color: var(--gray-500);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border-bottom: 1px solid var(--gray-200);
    }
    td {
        padding: 14px 24px;
        border-bottom: 1px solid var(--gray-100);
        font-size: 13px;
        color: var(--gray-700);
        vertical-align: middle;
    }
    tr:last-child td { border-bottom: none; }
    tr.row-link {
        cursor: pointer;
        transition: var(--transition);
    }
    tr.row-link:hover {
        background: var(--lapora-red-50);
    }
    tr.row-link:hover td { color: var(--gray-900); }

    /* AVATAR */
    .avatar {
        width: 36px;
        height: 36px;
        border-radius: 50%;
        display: inline-flex;
        align-items: center;
        justify-content: center;
        color: white;
        font-weight: 600;
        font-size: 13px;
        flex-shrink: 0;
        box-shadow: 0 2px 4px rgba(0,0,0,0.08);
    }
    .avatar-lg {
        width: 56px;
        height: 56px;
        font-size: 20px;
        border-radius: 16px;
    }
    .contact-cell {
        display: flex;
        align-items: center;
        gap: 12px;
    }
    .contact-info { min-width: 0; }
    .contact-name {
        font-weight: 600;
        color: var(--gray-900);
        font-size: 13.5px;
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .contact-phone {
        font-size: 12px;
        color: var(--gray-500);
        font-variant-numeric: tabular-nums;
    }

    /* BADGES ESTADO */
    .badge {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 4px 10px;
        border-radius: 999px;
        font-size: 12px;
        font-weight: 600;
        white-space: nowrap;
    }
    .badge-dot {
        width: 6px;
        height: 6px;
        border-radius: 50%;
    }

    /* METRICAS EN TABLA */
    .metric-pill {
        display: inline-flex;
        align-items: center;
        gap: 4px;
        padding: 3px 8px;
        background: var(--gray-100);
        border-radius: 6px;
        font-size: 12px;
        font-weight: 600;
        color: var(--gray-700);
        font-variant-numeric: tabular-nums;
    }
    .metric-pill.has-citas {
        background: var(--lapora-red-50);
        color: var(--lapora-red);
    }

    /* EMPTY STATE */
    .empty {
        text-align: center;
        padding: 80px 40px;
    }
    .empty-icon {
        width: 64px;
        height: 64px;
        margin: 0 auto 16px;
        background: var(--gray-100);
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        color: var(--gray-400);
    }
    .empty h3 {
        color: var(--gray-900);
        font-size: 18px;
        font-weight: 600;
        margin-bottom: 6px;
    }
    .empty p { color: var(--gray-500); font-size: 14px; }

    /* DETALLE CONTACTO */
    .detail-grid {
        display: grid;
        grid-template-columns: 2fr 1fr;
        gap: 20px;
    }
    @media (max-width: 1024px) {
        .detail-grid { grid-template-columns: 1fr; }
    }
    .form-grid {
        display: grid;
        grid-template-columns: 1fr 1fr;
        gap: 16px;
        padding: 24px;
    }
    @media (max-width: 640px) {
        .form-grid { grid-template-columns: 1fr; }
    }
    .form-grid.full { grid-template-columns: 1fr; }
    .field { display: flex; flex-direction: column; }
    .field label {
        font-size: 11px;
        font-weight: 600;
        color: var(--gray-500);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        margin-bottom: 6px;
    }
    .field .input, .field .select, .field textarea {
        width: 100%;
    }
    .field textarea {
        padding: 10px 14px;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-md);
        font-size: 13px;
        font-family: inherit;
        color: var(--gray-900);
        background: white;
        resize: vertical;
        min-height: 80px;
        outline: none;
        transition: var(--transition);
    }
    .field textarea:focus {
        border-color: var(--lapora-red);
        box-shadow: 0 0 0 3px rgba(255,59,48,0.1);
    }
    .form-footer {
        padding: 16px 24px;
        background: var(--gray-50);
        border-top: 1px solid var(--gray-200);
        display: flex;
        justify-content: flex-end;
        gap: 8px;
    }

    /* INFO CARD */
    .info-list {
        padding: 18px 24px;
    }
    .info-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 10px 0;
        border-bottom: 1px solid var(--gray-100);
        font-size: 13px;
    }
    .info-row:last-child { border-bottom: none; }
    .info-label { color: var(--gray-500); font-weight: 500; }
    .info-value { color: var(--gray-900); font-weight: 600; }

    /* CHAT PREVIEW */
    .chat-preview {
        max-height: 380px;
        overflow-y: auto;
        padding: 16px 20px;
    }
    .chat-bubble {
        margin-bottom: 12px;
        padding: 10px 14px;
        border-radius: var(--radius-md);
        font-size: 13px;
        line-height: 1.5;
    }
    .chat-bubble.user {
        background: var(--gray-100);
        color: var(--gray-800);
        margin-right: 24px;
    }
    .chat-bubble.bot {
        background: var(--lapora-red-50);
        color: var(--gray-800);
        margin-left: 24px;
    }
    .chat-meta {
        font-size: 11px;
        color: var(--gray-500);
        font-weight: 500;
        margin-bottom: 4px;
        display: flex;
        align-items: center;
        gap: 6px;
    }

    /* BREADCRUMB */
    .breadcrumb {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 13px;
        color: var(--gray-500);
        margin-bottom: 16px;
    }
    .breadcrumb a { color: var(--gray-500); font-weight: 500; }
    .breadcrumb a:hover { color: var(--gray-900); }
    .breadcrumb-sep { color: var(--gray-300); }

    /* RESPONSIVE */
    @media (max-width: 900px) {
        .app { grid-template-columns: 1fr; }
        .sidebar {
            position: fixed;
            top: 0;
            left: -100%;
            z-index: 100;
            transition: left 0.3s;
            width: 260px;
        }
        .sidebar.open { left: 0; }
        .main { padding: 20px; }
        .mobile-menu { display: block; }
    }
    .mobile-menu { display: none; }

    /* Scroll personalizado */
    ::-webkit-scrollbar { width: 8px; height: 8px; }
    ::-webkit-scrollbar-track { background: transparent; }
    ::-webkit-scrollbar-thumb { background: var(--gray-200); border-radius: 4px; }
    ::-webkit-scrollbar-thumb:hover { background: var(--gray-300); }
</style>
"""


def sidebar_html(activa: str, stats: dict | None = None) -> str:
    """Genera la sidebar con navegacion."""
    total_contactos = stats.get("total_contactos", 0) if stats else 0
    total_convs = stats.get("total_conversaciones", 0) if stats else 0

    nav = [
        ("contactos", "Contactos", "/admin/contactos", total_contactos,
         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>'),
        ("conversaciones", "Conversaciones", "/admin/conversaciones", total_convs,
         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>'),
    ]

    links_html = ""
    for key, label, url, count, icon in nav:
        clase = "nav-link active" if key == activa else "nav-link"
        badge = f'<span class="nav-badge">{count}</span>' if count > 0 else ""
        links_html += f'<a href="{url}" class="{clase}">{icon}<span>{label}</span>{badge}</a>'

    return f"""
    <aside class="sidebar">
        <div class="brand">
            <div class="brand-logo">L</div>
            <div class="brand-text">
                <span class="brand-name">Lapora CRM</span>
                <span class="brand-sub">SofIA Dashboard</span>
            </div>
        </div>
        <div class="nav-section">
            <div class="nav-section-title">Workspace</div>
            {links_html}
        </div>
        <div class="nav-section" style="margin-top:auto">
            <div class="nav-section-title">Acciones</div>
            <a href="https://calendar.google.com" target="_blank" class="nav-link">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="4" width="18" height="18" rx="2" ry="2"/><line x1="16" y1="2" x2="16" y2="6"/><line x1="8" y1="2" x2="8" y2="6"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
                <span>Google Calendar</span>
            </a>
            <a href="https://lapora.studio" target="_blank" class="nav-link">
                <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                <span>lapora.studio</span>
            </a>
        </div>
    </aside>
    """


def badge_estado_html(estado: str) -> str:
    """Genera badge HTML para un estado."""
    c = ESTADOS_COLORES.get(estado, ESTADOS_COLORES["nuevo"])
    label = ESTADOS_LABELS.get(estado, estado.title())
    return (
        f'<span class="badge" style="background:{c["bg"]};color:{c["fg"]}">'
        f'<span class="badge-dot" style="background:{c["dot"]}"></span>'
        f'{label}</span>'
    )


# ════════════════════════════════════════════════════════════
# ENDPOINTS
# ════════════════════════════════════════════════════════════


@router.get("/")
async def admin_index(user: str = Depends(verificar_credenciales)):
    """Redirige al CRM de contactos."""
    return RedirectResponse(url="/admin/contactos")


async def _obtener_stats() -> dict:
    """Obtiene estadisticas para sidebar y vistas."""
    async with async_session() as session:
        total_msgs = (await session.execute(select(func.count(Mensaje.id)))).scalar() or 0
        total_convs = (await session.execute(
            select(func.count(func.distinct(Mensaje.telefono)))
        )).scalar() or 0
        total_contactos = (await session.execute(select(func.count(Contacto.telefono)))).scalar() or 0

        stats_estado = {}
        for est in ESTADOS:
            count = (await session.execute(
                select(func.count(Contacto.telefono)).where(Contacto.estado == est)
            )).scalar() or 0
            stats_estado[est] = count

        return {
            "total_mensajes": total_msgs,
            "total_conversaciones": total_convs,
            "total_contactos": total_contactos,
            "por_estado": stats_estado,
        }


@router.get("/api/stats")
async def stats_json(user: str = Depends(verificar_credenciales)):
    """Stats JSON."""
    return await _obtener_stats()


@router.get("/contactos", response_class=HTMLResponse)
async def listar_contactos(
    user: str = Depends(verificar_credenciales),
    q: Optional[str] = None,
    estado: Optional[str] = None,
    ciudad: Optional[str] = None,
    especialidad: Optional[str] = None,
    orden: Optional[str] = "ultimo_contacto",
):
    """Lista de contactos con filtros."""
    async with async_session() as session:
        query = select(Contacto)

        if q:
            qp = f"%{q}%"
            query = query.where(
                or_(
                    Contacto.telefono.ilike(qp),
                    Contacto.nombre.ilike(qp),
                    Contacto.email.ilike(qp),
                )
            )
        if estado and estado != "todos":
            query = query.where(Contacto.estado == estado)
        if ciudad and ciudad != "todas":
            query = query.where(Contacto.ciudad == ciudad)
        if especialidad and especialidad != "todas":
            query = query.where(Contacto.especialidad == especialidad)

        if orden == "primer_contacto":
            query = query.order_by(Contacto.primer_contacto.desc())
        elif orden == "nombre":
            query = query.order_by(Contacto.nombre.asc())
        elif orden == "total_mensajes":
            query = query.order_by(Contacto.total_mensajes.desc())
        else:
            query = query.order_by(Contacto.ultimo_contacto.desc())

        contactos = (await session.execute(query)).scalars().all()

        # Opciones de filtros
        ciudades = sorted([c for c in (await session.execute(
            select(Contacto.ciudad).distinct().where(Contacto.ciudad != "").where(Contacto.ciudad != None)
        )).scalars().all() if c])

        especialidades = sorted([e for e in (await session.execute(
            select(Contacto.especialidad).distinct().where(Contacto.especialidad != "").where(Contacto.especialidad != None)
        )).scalars().all() if e])

    stats = await _obtener_stats()

    # Stats Grid
    stats_html = '<div class="stats-grid">'
    stats_html += f'<div class="stat-card stat-card-total"><div class="stat-card-label">Total contactos</div><div class="stat-card-value">{stats["total_contactos"]}</div></div>'
    for est in ESTADOS:
        count = stats["por_estado"].get(est, 0)
        c = ESTADOS_COLORES[est]
        label = ESTADOS_LABELS[est]
        stats_html += f"""
        <div class="stat-card">
            <div class="stat-card-label">
                <span class="stat-dot" style="background:{c["dot"]}"></span>
                {label}
            </div>
            <div class="stat-card-value">{count}</div>
        </div>"""
    stats_html += '</div>'

    # Filtros
    opt_estado = '<option value="todos">Estado: Todos</option>'
    for e in ESTADOS:
        sel = " selected" if e == estado else ""
        opt_estado += f'<option value="{e}"{sel}>{ESTADOS_LABELS[e]}</option>'

    opt_ciudad = '<option value="todas">Ciudad: Todas</option>'
    for c in ciudades:
        sel = " selected" if c == ciudad else ""
        opt_ciudad += f'<option value="{c}"{sel}>{c}</option>'

    opt_esp = '<option value="todas">Especialidad: Todas</option>'
    for e in especialidades:
        sel = " selected" if e == especialidad else ""
        opt_esp += f'<option value="{e}"{sel}>{e}</option>'

    ordenes = [
        ("ultimo_contacto", "Mas recientes"),
        ("primer_contacto", "Mas antiguos"),
        ("nombre", "Nombre A-Z"),
        ("total_mensajes", "Mas mensajes"),
    ]
    opt_orden = ""
    for val, lab in ordenes:
        sel = " selected" if val == orden else ""
        opt_orden += f'<option value="{val}"{sel}>{lab}</option>'

    q_val = q or ""
    filtros_html = f"""
    <form method="get" class="filters">
        <input type="text" name="q" value="{q_val}" placeholder="Buscar por nombre, telefono o email..." class="input input-search">
        <select name="estado" class="select">{opt_estado}</select>
        <select name="ciudad" class="select">{opt_ciudad}</select>
        <select name="especialidad" class="select">{opt_esp}</select>
        <select name="orden" class="select">{opt_orden}</select>
        <button type="submit" class="btn btn-primary">Aplicar</button>
        <a href="/admin/contactos" class="btn btn-secondary">Limpiar</a>
    </form>
    """

    # Filas de tabla
    rows = ""
    for c in contactos:
        ini = iniciales(c.nombre or "", c.telefono)
        color = avatar_color(c.telefono)
        nombre = c.nombre or "Sin nombre"
        email = c.email or "—"
        ciudad_v = c.ciudad or "—"
        esp_v = c.especialidad or "—"
        ultimo = tiempo_relativo(c.ultimo_contacto)
        citas_class = " has-citas" if (c.citas_agendadas or 0) > 0 else ""

        rows += f"""
        <tr class="row-link" onclick="window.location='/admin/contactos/{c.telefono}'">
            <td>
                <div class="contact-cell">
                    <div class="avatar" style="background:{color}">{ini}</div>
                    <div class="contact-info">
                        <div class="contact-name">{nombre}</div>
                        <div class="contact-phone">{c.telefono}</div>
                    </div>
                </div>
            </td>
            <td>{email}</td>
            <td>{esp_v}</td>
            <td>{ciudad_v}</td>
            <td>{badge_estado_html(c.estado or "nuevo")}</td>
            <td><span class="metric-pill">{c.total_mensajes or 0}</span></td>
            <td><span class="metric-pill{citas_class}">{c.citas_agendadas or 0}</span></td>
            <td style="color:var(--gray-500);font-size:12px;font-weight:500">{ultimo}</td>
        </tr>
        """

    if not rows:
        rows = """
        <tr><td colspan="8">
            <div class="empty">
                <div class="empty-icon">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>
                </div>
                <h3>Sin contactos todavia</h3>
                <p>Cuando un doctor escriba a SofIA por WhatsApp,<br>aparecera aqui automaticamente.</p>
            </div>
        </td></tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Contactos - Lapora CRM</title>
    {CSS_BASE}
</head>
<body>
    <div class="app">
        {sidebar_html("contactos", stats)}
        <main class="main">
            <div class="page-header">
                <div>
                    <div class="page-title">Contactos</div>
                    <div class="page-subtitle">Gestiona tus leads y clientes del WhatsApp de Lapora</div>
                </div>
                <button class="btn btn-secondary" onclick="location.reload()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                    Actualizar
                </button>
            </div>

            {stats_html}

            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">Lista de contactos</div>
                        <div class="card-subtitle">{len(contactos)} resultado(s)</div>
                    </div>
                </div>
                {filtros_html}
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Contacto</th>
                                <th>Email</th>
                                <th>Especialidad</th>
                                <th>Ciudad</th>
                                <th>Estado</th>
                                <th>Mensajes</th>
                                <th>Citas</th>
                                <th>Ultimo</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            </div>
        </main>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/contactos/{telefono}", response_class=HTMLResponse)
async def detalle_contacto(telefono: str, user: str = Depends(verificar_credenciales)):
    """Vista detalle de un contacto."""
    async with async_session() as session:
        contacto = (await session.execute(
            select(Contacto).where(Contacto.telefono == telefono)
        )).scalar_one_or_none()

        if contacto is None:
            return HTMLResponse(f"<h1>Contacto {telefono} no encontrado</h1>", status_code=404)

        mensajes = (await session.execute(
            select(Mensaje).where(Mensaje.telefono == telefono).order_by(Mensaje.timestamp.asc())
        )).scalars().all()

    stats = await _obtener_stats()

    ini = iniciales(contacto.nombre or "", contacto.telefono)
    color = avatar_color(contacto.telefono)
    nombre = contacto.nombre or "Sin nombre"

    # Opciones de estado
    opt_estado = ""
    for e in ESTADOS:
        sel = " selected" if e == contacto.estado else ""
        opt_estado += f'<option value="{e}"{sel}>{ESTADOS_LABELS[e]}</option>'

    # Form
    form_html = f"""
    <form method="post" action="/admin/contactos/{telefono}/editar">
        <div class="form-grid">
            <div class="field">
                <label>Nombre</label>
                <input type="text" name="nombre" value="{contacto.nombre or ''}" class="input">
            </div>
            <div class="field">
                <label>Email</label>
                <input type="email" name="email" value="{contacto.email or ''}" class="input">
            </div>
            <div class="field">
                <label>Especialidad</label>
                <input type="text" name="especialidad" value="{contacto.especialidad or ''}" class="input">
            </div>
            <div class="field">
                <label>Ciudad</label>
                <input type="text" name="ciudad" value="{contacto.ciudad or ''}" class="input">
            </div>
            <div class="field">
                <label>Volumen pacientes / mes</label>
                <input type="text" name="volumen_pacientes" value="{contacto.volumen_pacientes or ''}" class="input">
            </div>
            <div class="field">
                <label>Presencia digital</label>
                <input type="text" name="presencia_digital" value="{contacto.presencia_digital or ''}" class="input">
            </div>
            <div class="field">
                <label>Perdida mensual estimada</label>
                <input type="text" name="perdida_mensual" value="{contacto.perdida_mensual or ''}" class="input">
            </div>
            <div class="field">
                <label>Estado del lead</label>
                <select name="estado" class="select">{opt_estado}</select>
            </div>
        </div>
        <div class="form-grid full">
            <div class="field">
                <label>Reto principal</label>
                <textarea name="reto_principal" rows="2">{contacto.reto_principal or ''}</textarea>
            </div>
            <div class="field">
                <label>Tags (separados por coma)</label>
                <input type="text" name="tags" value="{contacto.tags or ''}" placeholder="vip, dermatologia, ibague" class="input">
            </div>
            <div class="field">
                <label>Notas internas</label>
                <textarea name="notas" rows="4" placeholder="Notas privadas del equipo Lapora...">{contacto.notas or ''}</textarea>
            </div>
        </div>
        <div class="form-footer">
            <a href="/admin/contactos" class="btn btn-secondary">Cancelar</a>
            <button type="submit" class="btn btn-primary">Guardar cambios</button>
        </div>
    </form>
    """

    # Chat preview ultimos 10
    chat_html = ""
    msgs_recientes = list(mensajes)[-10:] if len(mensajes) > 10 else list(mensajes)
    for m in msgs_recientes:
        autor = "Cliente" if m.role == "user" else "SofIA"
        clase = "user" if m.role == "user" else "bot"
        contenido = (m.content or "").replace("\n", "<br>")
        ts = tiempo_relativo(m.timestamp)
        chat_html += f"""
        <div>
            <div class="chat-meta"><strong>{autor}</strong> · {ts}</div>
            <div class="chat-bubble {clase}">{contenido}</div>
        </div>
        """
    if not chat_html:
        chat_html = '<div style="padding:30px;text-align:center;color:var(--gray-500)">Sin mensajes todavia</div>'

    fecha_primer = contacto.primer_contacto.strftime("%d/%m/%Y %H:%M") if contacto.primer_contacto else "—"
    fecha_ultimo = tiempo_relativo(contacto.ultimo_contacto)

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{nombre} - Lapora CRM</title>
    {CSS_BASE}
</head>
<body>
    <div class="app">
        {sidebar_html("contactos", stats)}
        <main class="main">
            <div class="breadcrumb">
                <a href="/admin/contactos">Contactos</a>
                <span class="breadcrumb-sep">/</span>
                <span>{nombre}</span>
            </div>

            <div class="page-header">
                <div style="display:flex;align-items:center;gap:16px">
                    <div class="avatar avatar-lg" style="background:{color}">{ini}</div>
                    <div>
                        <div class="page-title">{nombre}</div>
                        <div class="page-subtitle">
                            {contacto.telefono} · {badge_estado_html(contacto.estado or "nuevo")}
                        </div>
                    </div>
                </div>
                <a href="/admin/conversaciones/{contacto.telefono}" class="btn btn-primary">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                    Ver chat completo
                </a>
            </div>

            <div class="detail-grid">
                <div>
                    <div class="card">
                        <div class="card-header">
                            <div>
                                <div class="card-title">Informacion del contacto</div>
                                <div class="card-subtitle">Edita los datos del lead</div>
                            </div>
                        </div>
                        {form_html}
                    </div>
                </div>

                <div>
                    <div class="card">
                        <div class="card-header">
                            <div class="card-title">Resumen</div>
                        </div>
                        <div class="info-list">
                            <div class="info-row">
                                <span class="info-label">Total mensajes</span>
                                <span class="info-value">{contacto.total_mensajes or 0}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Citas agendadas</span>
                                <span class="info-value">{contacto.citas_agendadas or 0}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Fuente</span>
                                <span class="info-value">{contacto.fuente or "WhatsApp"}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Primer contacto</span>
                                <span class="info-value" style="font-size:12px">{fecha_primer}</span>
                            </div>
                            <div class="info-row">
                                <span class="info-label">Ultimo contacto</span>
                                <span class="info-value">{fecha_ultimo}</span>
                            </div>
                        </div>
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <div>
                                <div class="card-title">Ultimos mensajes</div>
                                <div class="card-subtitle">{len(mensajes)} mensajes en total</div>
                            </div>
                        </div>
                        <div class="chat-preview">
                            {chat_html}
                        </div>
                    </div>
                </div>
            </div>
        </main>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.post("/contactos/{telefono}/editar")
async def editar_contacto(
    telefono: str,
    nombre: str = Form(""),
    email: str = Form(""),
    especialidad: str = Form(""),
    ciudad: str = Form(""),
    volumen_pacientes: str = Form(""),
    presencia_digital: str = Form(""),
    perdida_mensual: str = Form(""),
    reto_principal: str = Form(""),
    estado: str = Form("nuevo"),
    tags: str = Form(""),
    notas: str = Form(""),
    user: str = Depends(verificar_credenciales),
):
    """Actualiza los datos de un contacto."""
    async with async_session() as session:
        contacto = (await session.execute(
            select(Contacto).where(Contacto.telefono == telefono)
        )).scalar_one_or_none()
        if contacto is None:
            raise HTTPException(status_code=404, detail="Contacto no encontrado")

        contacto.nombre = nombre
        contacto.email = email
        contacto.especialidad = especialidad
        contacto.ciudad = ciudad
        contacto.volumen_pacientes = volumen_pacientes
        contacto.presencia_digital = presencia_digital
        contacto.perdida_mensual = perdida_mensual
        contacto.reto_principal = reto_principal
        contacto.estado = estado
        contacto.tags = tags
        contacto.notas = notas

        await session.commit()

    return RedirectResponse(url=f"/admin/contactos/{telefono}", status_code=303)


# ════════════════════════════════════════════════════════════
# CONVERSACIONES
# ════════════════════════════════════════════════════════════

@router.get("/conversaciones", response_class=HTMLResponse)
async def listar_conversaciones(user: str = Depends(verificar_credenciales)):
    """Lista de conversaciones agrupadas por telefono."""
    async with async_session() as session:
        result = await session.execute(
            select(
                Mensaje.telefono,
                func.count(Mensaje.id).label("total"),
                func.max(Mensaje.timestamp).label("ultimo"),
            )
            .group_by(Mensaje.telefono)
            .order_by(func.max(Mensaje.timestamp).desc())
        )
        conversaciones = result.all()

        # Buscar nombres asociados
        contactos_dict = {}
        if conversaciones:
            tels = [c.telefono for c in conversaciones]
            contactos_query = await session.execute(
                select(Contacto).where(Contacto.telefono.in_(tels))
            )
            for c in contactos_query.scalars().all():
                contactos_dict[c.telefono] = c

    stats = await _obtener_stats()

    rows = ""
    for c in conversaciones:
        contacto_obj = contactos_dict.get(c.telefono)
        nombre = contacto_obj.nombre if contacto_obj and contacto_obj.nombre else "Sin nombre"
        ini = iniciales(nombre if nombre != "Sin nombre" else "", c.telefono)
        color = avatar_color(c.telefono)
        estado = contacto_obj.estado if contacto_obj else "nuevo"
        ultimo = tiempo_relativo(c.ultimo)
        rows += f"""
        <tr class="row-link" onclick="window.location='/admin/conversaciones/{c.telefono}'">
            <td>
                <div class="contact-cell">
                    <div class="avatar" style="background:{color}">{ini}</div>
                    <div class="contact-info">
                        <div class="contact-name">{nombre}</div>
                        <div class="contact-phone">{c.telefono}</div>
                    </div>
                </div>
            </td>
            <td>{badge_estado_html(estado)}</td>
            <td><span class="metric-pill">{c.total}</span></td>
            <td style="color:var(--gray-500);font-size:12px;font-weight:500">{ultimo}</td>
        </tr>
        """
    if not rows:
        rows = """
        <tr><td colspan="4">
            <div class="empty">
                <div class="empty-icon">
                    <svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
                </div>
                <h3>Sin conversaciones</h3>
                <p>Cuando alguien escriba a SofIA,<br>las conversaciones apareceran aqui.</p>
            </div>
        </td></tr>
        """

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Conversaciones - Lapora CRM</title>
    {CSS_BASE}
</head>
<body>
    <div class="app">
        {sidebar_html("conversaciones", stats)}
        <main class="main">
            <div class="page-header">
                <div>
                    <div class="page-title">Conversaciones</div>
                    <div class="page-subtitle">Historial de chats de WhatsApp con SofIA</div>
                </div>
                <button class="btn btn-secondary" onclick="location.reload()">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
                    Actualizar
                </button>
            </div>

            <div class="stats-grid">
                <div class="stat-card stat-card-total">
                    <div class="stat-card-label">Conversaciones activas</div>
                    <div class="stat-card-value">{stats["total_conversaciones"]}</div>
                </div>
                <div class="stat-card">
                    <div class="stat-card-label"><span class="stat-dot" style="background:#FF3B30"></span>Mensajes totales</div>
                    <div class="stat-card-value">{stats["total_mensajes"]}</div>
                </div>
            </div>

            <div class="card">
                <div class="card-header">
                    <div>
                        <div class="card-title">Todas las conversaciones</div>
                        <div class="card-subtitle">{len(conversaciones)} chat(s)</div>
                    </div>
                </div>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr>
                                <th>Contacto</th>
                                <th>Estado</th>
                                <th>Mensajes</th>
                                <th>Ultimo mensaje</th>
                            </tr>
                        </thead>
                        <tbody>{rows}</tbody>
                    </table>
                </div>
            </div>
        </main>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@router.get("/conversaciones/{telefono}", response_class=HTMLResponse)
async def ver_conversacion(telefono: str, user: str = Depends(verificar_credenciales)):
    """Chat estilo WhatsApp."""
    async with async_session() as session:
        mensajes = (await session.execute(
            select(Mensaje).where(Mensaje.telefono == telefono).order_by(Mensaje.timestamp.asc())
        )).scalars().all()

        contacto = (await session.execute(
            select(Contacto).where(Contacto.telefono == telefono)
        )).scalar_one_or_none()

    if not mensajes:
        return HTMLResponse(f"<h1>Conversacion {telefono} no encontrada</h1>", status_code=404)

    stats = await _obtener_stats()

    nombre = contacto.nombre if contacto and contacto.nombre else "Sin nombre"
    ini = iniciales(nombre if nombre != "Sin nombre" else "", telefono)
    color = avatar_color(telefono)
    estado = contacto.estado if contacto else "nuevo"

    chat = ""
    for m in mensajes:
        clase = "msg-user" if m.role == "user" else "msg-bot"
        autor = "Cliente" if m.role == "user" else "SofIA"
        contenido = (m.content or "").replace("\n", "<br>")
        ts = m.timestamp.strftime("%d/%m/%Y %H:%M")
        chat += f"""
        <div class="message {clase}">
            <div class="bubble">
                <div class="bubble-author">{autor}</div>
                <div class="bubble-content">{contenido}</div>
                <div class="bubble-time">{ts}</div>
            </div>
        </div>"""

    html = f"""<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Chat {nombre} - Lapora CRM</title>
    {CSS_BASE}
    <style>
        .chat-container {{
            max-width: 820px;
            margin: 0 auto;
            background: linear-gradient(180deg, #FAFAF9 0%, #F5F5F4 100%);
            border: 1px solid var(--gray-200);
            border-radius: var(--radius-lg);
            padding: 24px;
            min-height: 60vh;
        }}
        .message {{ display: flex; margin-bottom: 14px; }}
        .msg-user {{ justify-content: flex-end; }}
        .msg-bot {{ justify-content: flex-start; }}
        .bubble {{
            max-width: 75%;
            padding: 12px 16px;
            border-radius: var(--radius-md);
            box-shadow: var(--shadow-sm);
        }}
        .msg-user .bubble {{
            background: white;
            border: 1px solid var(--gray-200);
            border-bottom-right-radius: 2px;
        }}
        .msg-bot .bubble {{
            background: var(--lapora-red);
            color: white;
            border-bottom-left-radius: 2px;
        }}
        .bubble-author {{
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 4px;
            opacity: 0.7;
        }}
        .msg-bot .bubble-author {{ color: white; }}
        .bubble-content {{
            font-size: 14px;
            line-height: 1.5;
            word-wrap: break-word;
        }}
        .bubble-time {{
            font-size: 11px;
            opacity: 0.6;
            margin-top: 6px;
            text-align: right;
            font-variant-numeric: tabular-nums;
        }}
    </style>
</head>
<body>
    <div class="app">
        {sidebar_html("conversaciones", stats)}
        <main class="main">
            <div class="breadcrumb">
                <a href="/admin/conversaciones">Conversaciones</a>
                <span class="breadcrumb-sep">/</span>
                <span>{nombre}</span>
            </div>

            <div class="page-header">
                <div style="display:flex;align-items:center;gap:16px">
                    <div class="avatar avatar-lg" style="background:{color}">{ini}</div>
                    <div>
                        <div class="page-title">{nombre}</div>
                        <div class="page-subtitle">
                            {telefono} · {badge_estado_html(estado)} · {len(mensajes)} mensajes
                        </div>
                    </div>
                </div>
                <a href="/admin/contactos/{telefono}" class="btn btn-secondary">
                    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2"/><circle cx="12" cy="7" r="4"/></svg>
                    Ver ficha contacto
                </a>
            </div>

            <div class="chat-container">
                {chat}
            </div>
        </main>
    </div>
</body>
</html>"""
    return HTMLResponse(content=html)

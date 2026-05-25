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
import csv
import html
import secrets
import hashlib
import time as _time
from datetime import datetime
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status, Request, Form, UploadFile, File
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from io import StringIO
import re as _re
import hashlib as _hashlib
import httpx as _httpx
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
        transition: grid-template-columns 0.25s cubic-bezier(0.4, 0, 0.2, 1);
    }
    .app.sidebar-collapsed {
        grid-template-columns: 0 1fr;
    }
    .app.sidebar-collapsed .sidebar {
        transform: translateX(-100%);
        pointer-events: none;
    }

    /* BOTÓN HAMBURGUESA */
    .menu-toggle {
        position: fixed;
        top: 16px;
        left: 16px;
        z-index: 1000;
        width: 42px;
        height: 42px;
        border: none;
        background: white;
        border: 1px solid var(--gray-200);
        border-radius: var(--radius-md);
        cursor: pointer;
        display: flex;
        align-items: center;
        justify-content: center;
        box-shadow: var(--shadow-md);
        transition: var(--transition);
        color: var(--gray-700);
    }
    .menu-toggle:hover {
        background: var(--lapora-red-50);
        border-color: var(--lapora-red);
        color: var(--lapora-red);
        transform: scale(1.05);
    }
    .menu-toggle:active { transform: scale(0.95); }
    .menu-toggle svg { width: 22px; height: 22px; }
    .menu-toggle .icon-open  { display: none; }
    .menu-toggle .icon-close { display: block; }
    .app.sidebar-collapsed .menu-toggle .icon-open  { display: block; }
    .app.sidebar-collapsed .menu-toggle .icon-close { display: none; }

    /* SIDEBAR */
    .sidebar {
        background: white;
        border-right: 1px solid var(--gray-200);
        padding: 24px 16px 24px 64px;
        position: sticky;
        top: 0;
        height: 100vh;
        overflow-y: auto;
        transition: transform 0.25s cubic-bezier(0.4, 0, 0.2, 1);
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
        ("funnel", "Funnel Lapora", "/admin/funnel", 0,
         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>'),
        ("prospectos", "Prospectos", "/admin/prospectos", 0,
         '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><line x1="9" y1="10" x2="15" y2="10"/><line x1="9" y1="14" x2="13" y2="14"/></svg>'),
    ]

    links_html = ""
    for key, label, url, count, icon in nav:
        clase = "nav-link active" if key == activa else "nav-link"
        badge = f'<span class="nav-badge">{count}</span>' if count > 0 else ""
        links_html += f'<a href="{url}" class="{clase}">{icon}<span>{label}</span>{badge}</a>'

    return f"""
    <button class="menu-toggle" id="menuToggle" aria-label="Mostrar u ocultar menu" type="button"
            onclick="toggleSidebar()">
        <svg class="icon-close" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="3" y1="6"  x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
        <svg class="icon-open" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">
            <line x1="3" y1="6"  x2="21" y2="6"/>
            <line x1="3" y1="12" x2="21" y2="12"/>
            <line x1="3" y1="18" x2="21" y2="18"/>
        </svg>
    </button>
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
    <script>
        // Toggle sidebar — persiste estado en localStorage + atajo Ctrl+B
        (function() {{
            var KEY = 'lapora.sidebarCollapsed';
            var app = document.querySelector('.app');
            if (!app) {{ return; }}
            // Restaurar estado al cargar
            if (localStorage.getItem(KEY) === '1') {{
                app.classList.add('sidebar-collapsed');
            }}
            window.toggleSidebar = function() {{
                app.classList.toggle('sidebar-collapsed');
                localStorage.setItem(KEY, app.classList.contains('sidebar-collapsed') ? '1' : '0');
            }};
            // Atajo de teclado: Ctrl+B (Windows/Linux) o Cmd+B (Mac)
            document.addEventListener('keydown', function(e) {{
                if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === 'b') {{
                    e.preventDefault();
                    window.toggleSidebar();
                }}
            }});
        }})();
    </script>
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


# ════════════════════════════════════════════════════════════
# FUNNEL LAPORA — Organigrama estrategico
# ════════════════════════════════════════════════════════════

FUNNEL_MERMAID = """
flowchart TD
    INICIO([Doctor potencial<br/>no nos conoce]):::start

    INICIO --> F1[FASE 1: CAPTACION<br/>Generar visibilidad]:::fase
    F1 --> ORG[Contenido organico<br/>Instagram - TikTok - LinkedIn]
    F1 --> PAID[Anuncios pagados<br/>Meta Ads + Google Ads]
    F1 --> SEO[SEO Local Ibague-Tolima<br/>Bogota-Medellin-Cali]
    F1 --> NET[Networking medico<br/>Camara Comercio - Eventos]
    F1 --> REF1[Referidos de<br/>clientes actuales]:::referral

    ORG --> ORG_TIPO{Tipo de contenido}
    ORG_TIPO --> POV[POV de pacientes]
    ORG_TIPO --> CASOS[Casos de exito]
    ORG_TIPO --> EDU[Tips marketing<br/>para medicos]
    ORG_TIPO --> AUTH[Autoridad medica<br/>Pizarra/Podcast]

    POV --> WEB
    CASOS --> WEB
    EDU --> WEB
    AUTH --> WEB
    PAID --> WEB[lapora.studio<br/>Landing + Diagnostico]:::lapora
    SEO --> WEB
    NET --> WEB
    REF1 --> WEB

    WEB --> DIAG[Diagnostico Digital Gratis<br/>5 preguntas - 2 min]:::lapora
    DIAG --> CALC[Calculo automatico:<br/>Perdida mensual estimada<br/>15M - 35M COP / mes]:::lapora
    CALC --> CTA[CTA: Hablar con SofIA<br/>en WhatsApp]:::lapora

    CTA --> SOFIA[FASE 2: SofIA WhatsApp<br/>+57 322 878 3019]:::fase
    SOFIA --> CTX[SofIA recibe contexto<br/>del diagnostico]:::lapora
    CTX --> CRM[Auto-creacion en CRM<br/>Lead Nuevo]:::lapora
    CRM --> QUAL{FASE 3: Filtro<br/>Califica?}:::decision

    QUAL -->|NO califica| NURT[Secuencia de nurturing<br/>Contenido educativo<br/>3 meses]:::recovery
    QUAL -->|SI califica| AGENDA[Agendamiento automatico<br/>Google Calendar]:::lapora

    NURT --> NURT_LOOP[Recalificacion<br/>cada 30 dias]:::recovery
    NURT_LOOP -.->|Califica despues| QUAL

    AGENDA --> REM1[Recordatorio SofIA<br/>1h antes - automatico]:::lapora
    REM1 --> REUNION1[FASE 4: Diagnostico Profundo<br/>30 min - Zoom/Meet]:::fase
    REUNION1 --> AUDIT[Auditoria completa:<br/>Google - Instagram - Web<br/>Reviews - Anuncios]
    AUDIT --> PROP_REC[Recomendacion<br/>personalizada en vivo]

    PROP_REC --> INT{Interesado en<br/>propuesta?}:::decision
    INT -->|NO ahora| FOLLOWUP[Follow-up estrategico<br/>No agresivo - valor]:::recovery
    FOLLOWUP -.->|Cambia de opinion| INT
    INT -->|SI| PROP[FASE 5: Propuesta<br/>Personalizada]:::fase

    PROP --> TIERS[3 tiers de pricing:<br/>Starter - Growth - Premium]
    PROP --> CASOS_EX[Casos de exito<br/>Otaima - Nutrifit - etc.]
    PROP --> GARANT[Garantia:<br/>Mes 1 sin resultados<br/>= ajuste sin costo]
    TIERS --> CIERRE{Firma<br/>contrato?}:::decision
    CASOS_EX --> CIERRE
    GARANT --> CIERRE

    CIERRE -->|NO| NURT_LONG[Nurturing largo plazo<br/>+ casos nuevos]:::recovery
    NURT_LONG -.->|6 meses despues| INT
    CIERRE -->|SI| PAGO[Anticipo 50 porciento<br/>USD 1.500 - 5.000]:::dinero

    PAGO --> ONBOARD[FASE 6: Onboarding<br/>Cliente nuevo]:::fase
    ONBOARD --> KICKOFF[Kickoff meeting<br/>Estrategia 30/60/90 dias]
    KICKOFF --> SETUP[Setup tecnico:<br/>Bot IA - Accesos - Branding<br/>Pixel - Analytics]

    SETUP --> EJEC[FASE 7: Ejecucion mensual]:::fase
    EJEC --> CONTENIDO[Produccion contenido<br/>Reels - Posts - Videos]
    EJEC --> ADS_GEST[Gestion anuncios<br/>Meta - Google - TikTok]
    EJEC --> SEO_OPT[Optimizacion SEO<br/>Local + nacional]
    EJEC --> BOT_LIVE[Bot IA WhatsApp<br/>activo 24/7]:::lapora
    EJEC --> REPORTES[Reportes semanales<br/>KPIs - Costo por paciente]

    REPORTES --> MES1{Mes 1 exitoso?<br/>Alcance - Leads - Citas}:::decision
    MES1 -->|NO| AJUSTE[Ajuste sin costo<br/>Garantia Lapora]:::recovery
    AJUSTE --> EJEC
    MES1 -->|SI| PAGO_REC[Pago recurrente<br/>USD 1.000 - 4.000/mes]:::dinero

    PAGO_REC --> RET[FASE 8: Retencion<br/>Mes 3+]:::fase
    RET --> KPI_OK[KPIs estables<br/>ROAS 3x - 8x]
    RET --> UPSELL[Upsell servicios:<br/>+ Bot IA - + SEO - + Web]:::dinero
    RET --> CASOS_DOC[Documentar caso<br/>de exito en video]

    CASOS_DOC --> AMB[FASE 9: Lapora Ambassador]:::referral
    UPSELL --> AMB
    KPI_OK --> AMB
    AMB --> INCENT[Incentivos por referido:<br/>15 porciento comision o<br/>1 mes gratis]:::referral
    AMB --> TESTIM[Testimonios en video<br/>para marketing]:::referral
    INCENT --> NUEVO_REF[Nuevo doctor<br/>recomendado]:::referral
    TESTIM --> ORG
    NUEVO_REF -->|Cierra el ciclo| REF1

    click F1 call mostrarInfo("F1")
    click ORG call mostrarInfo("ORG")
    click PAID call mostrarInfo("PAID")
    click SEO call mostrarInfo("SEO")
    click NET call mostrarInfo("NET")
    click REF1 call mostrarInfo("REF1")
    click POV call mostrarInfo("POV")
    click CASOS call mostrarInfo("CASOS")
    click EDU call mostrarInfo("EDU")
    click AUTH call mostrarInfo("AUTH")
    click WEB call mostrarInfo("WEB")
    click DIAG call mostrarInfo("DIAG")
    click CALC call mostrarInfo("CALC")
    click CTA call mostrarInfo("CTA")
    click SOFIA call mostrarInfo("SOFIA")
    click CTX call mostrarInfo("CTX")
    click CRM call mostrarInfo("CRM")
    click QUAL call mostrarInfo("QUAL")
    click NURT call mostrarInfo("NURT")
    click AGENDA call mostrarInfo("AGENDA")
    click REM1 call mostrarInfo("REM1")
    click REUNION1 call mostrarInfo("REUNION1")
    click AUDIT call mostrarInfo("AUDIT")
    click PROP_REC call mostrarInfo("PROP_REC")
    click INT call mostrarInfo("INT")
    click FOLLOWUP call mostrarInfo("FOLLOWUP")
    click PROP call mostrarInfo("PROP")
    click TIERS call mostrarInfo("TIERS")
    click CASOS_EX call mostrarInfo("CASOS_EX")
    click GARANT call mostrarInfo("GARANT")
    click CIERRE call mostrarInfo("CIERRE")
    click NURT_LONG call mostrarInfo("NURT_LONG")
    click PAGO call mostrarInfo("PAGO")
    click ONBOARD call mostrarInfo("ONBOARD")
    click KICKOFF call mostrarInfo("KICKOFF")
    click SETUP call mostrarInfo("SETUP")
    click EJEC call mostrarInfo("EJEC")
    click CONTENIDO call mostrarInfo("CONTENIDO")
    click ADS_GEST call mostrarInfo("ADS_GEST")
    click SEO_OPT call mostrarInfo("SEO_OPT")
    click BOT_LIVE call mostrarInfo("BOT_LIVE")
    click REPORTES call mostrarInfo("REPORTES")
    click MES1 call mostrarInfo("MES1")
    click AJUSTE call mostrarInfo("AJUSTE")
    click PAGO_REC call mostrarInfo("PAGO_REC")
    click RET call mostrarInfo("RET")
    click KPI_OK call mostrarInfo("KPI_OK")
    click UPSELL call mostrarInfo("UPSELL")
    click CASOS_DOC call mostrarInfo("CASOS_DOC")
    click AMB call mostrarInfo("AMB")
    click INCENT call mostrarInfo("INCENT")
    click TESTIM call mostrarInfo("TESTIM")
    click NUEVO_REF call mostrarInfo("NUEVO_REF")

    classDef start fill:#1f1f1f,stroke:#444,color:#fff,stroke-width:1px
    classDef fase fill:#0d9488,stroke:#0d9488,color:#fff,stroke-width:2px,font-weight:bold
    classDef lapora fill:#FF3B30,stroke:#FF3B30,color:#fff,stroke-width:2px,font-weight:bold
    classDef dinero fill:#84cc16,stroke:#65a30d,color:#1a2e05,stroke-width:2px,font-weight:bold
    classDef referral fill:#7c3aed,stroke:#7c3aed,color:#fff,stroke-width:2px,font-weight:bold
    classDef decision fill:#f87171,stroke:#dc2626,color:#fff,stroke-width:2px,font-weight:bold
    classDef recovery fill:#f59e0b,stroke:#d97706,color:#1a1a1a,stroke-width:2px,font-weight:bold
"""


@router.get("/funnel", response_class=HTMLResponse)
async def vista_funnel(user: str = Depends(verificar_credenciales)):
    """Vista del organigrama del funnel completo de Lapora."""
    stats = await _obtener_stats()

    # Las fases del funnel para la lista lateral
    fases_html = """
    <div class="info-list">
        <div class="info-row"><span class="info-label">Fase 1</span><span class="info-value">Captacion (TOFU)</span></div>
        <div class="info-row"><span class="info-label">Fase 2</span><span class="info-value">Diagnostico Digital</span></div>
        <div class="info-row"><span class="info-label">Fase 3</span><span class="info-value">SofIA califica</span></div>
        <div class="info-row"><span class="info-label">Fase 4</span><span class="info-value">Reunion 1</span></div>
        <div class="info-row"><span class="info-label">Fase 5</span><span class="info-value">Propuesta</span></div>
        <div class="info-row"><span class="info-label">Fase 6</span><span class="info-value">Onboarding</span></div>
        <div class="info-row"><span class="info-label">Fase 7</span><span class="info-value">Ejecucion</span></div>
        <div class="info-row"><span class="info-label">Fase 8</span><span class="info-value">Retencion</span></div>
        <div class="info-row"><span class="info-label">Fase 9</span><span class="info-value">Referral Engine</span></div>
    </div>
    """

    kpis_html = """
    <div class="info-list">
        <div class="info-row"><span class="info-label">Visitas/mes</span><span class="info-value">5.000+</span></div>
        <div class="info-row"><span class="info-label">Conv. diagnostico</span><span class="info-value">>15%</span></div>
        <div class="info-row"><span class="info-label">Calificados</span><span class="info-value">>40%</span></div>
        <div class="info-row"><span class="info-label">Show rate</span><span class="info-value">>75%</span></div>
        <div class="info-row"><span class="info-label">Win rate</span><span class="info-value">>30%</span></div>
        <div class="info-row"><span class="info-label">Ticket promedio</span><span class="info-value">USD 2K/mes</span></div>
        <div class="info-row"><span class="info-label">MRR objetivo</span><span class="info-value" style="color:#10b981">USD 136K/mes</span></div>
    </div>
    """

    legend_html = """
    <div class="info-list">
        <div class="info-row"><span class="info-label">Lapora / SofIA</span><span class="badge" style="background:#FFE4E1;color:#991B1B"><span class="badge-dot" style="background:#FF3B30"></span>Rojo</span></div>
        <div class="info-row"><span class="info-label">Fase clave</span><span class="badge" style="background:#CCFBF1;color:#115E59"><span class="badge-dot" style="background:#0d9488"></span>Teal</span></div>
        <div class="info-row"><span class="info-label">Dinero entra</span><span class="badge" style="background:#ECFCCB;color:#3F6212"><span class="badge-dot" style="background:#84cc16"></span>Verde</span></div>
        <div class="info-row"><span class="info-label">Referidos</span><span class="badge" style="background:#EDE9FE;color:#5B21B6"><span class="badge-dot" style="background:#7c3aed"></span>Purpura</span></div>
        <div class="info-row"><span class="info-label">Decision</span><span class="badge" style="background:#FEE2E2;color:#991B1B"><span class="badge-dot" style="background:#f87171"></span>Coral</span></div>
        <div class="info-row"><span class="info-label">Recuperacion</span><span class="badge" style="background:#FEF3C7;color:#92400E"><span class="badge-dot" style="background:#f59e0b"></span>Ambar</span></div>
    </div>
    """

    html_header = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Funnel Lapora - CRM</title>
"""
    html_body = f"""
    {CSS_BASE}
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/svg-pan-zoom@3.6.1/dist/svg-pan-zoom.min.js"></script>
    <style>
        .funnel-canvas {{
            background: #0d0d0d;
            border-radius: var(--radius-lg);
            padding: 0;
            overflow: hidden;
            min-height: 75vh;
            height: 75vh;
            border: 1px solid #1f1f1f;
            position: relative;
        }}
        .mermaid {{
            background: transparent;
            width: 100%;
            height: 100%;
        }}
        .mermaid svg {{
            width: 100% !important;
            height: 100% !important;
            max-width: none !important;
            cursor: grab;
        }}
        .mermaid svg:active {{ cursor: grabbing; }}
        .mermaid .node {{
            cursor: pointer !important;
            transition: filter 0.2s, transform 0.2s;
        }}
        .mermaid .node:hover {{
            filter: brightness(1.25) drop-shadow(0 0 8px rgba(255,255,255,0.3));
        }}
        .funnel-grid {{
            display: grid;
            grid-template-columns: 1fr 280px;
            gap: 20px;
        }}
        @media (max-width: 1100px) {{
            .funnel-grid {{ grid-template-columns: 1fr; }}
        }}

        /* Controles de zoom */
        .zoom-controls {{
            position: absolute;
            bottom: 16px;
            right: 16px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            background: rgba(20,20,20,0.85);
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 4px;
            z-index: 10;
            backdrop-filter: blur(8px);
        }}
        .zoom-btn {{
            width: 36px;
            height: 36px;
            background: transparent;
            border: none;
            color: #ccc;
            font-size: 18px;
            font-weight: 600;
            cursor: pointer;
            border-radius: 6px;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.15s;
        }}
        .zoom-btn:hover {{
            background: rgba(255,59,48,0.15);
            color: var(--lapora-red);
        }}
        .zoom-hint {{
            position: absolute;
            top: 16px;
            left: 16px;
            background: rgba(20,20,20,0.85);
            border: 1px solid #2a2a2a;
            border-radius: 10px;
            padding: 8px 14px;
            font-size: 12px;
            color: #888;
            z-index: 10;
            backdrop-filter: blur(8px);
            display: flex;
            align-items: center;
            gap: 8px;
        }}
        .zoom-hint kbd {{
            background: #2a2a2a;
            border: 1px solid #3a3a3a;
            border-radius: 4px;
            padding: 1px 6px;
            font-size: 10px;
            color: #ccc;
            font-family: 'Inter';
        }}

        /* Modal de info */
        .info-modal-bg {{
            position: fixed;
            inset: 0;
            background: rgba(0,0,0,0.6);
            backdrop-filter: blur(4px);
            z-index: 1000;
            opacity: 0;
            pointer-events: none;
            transition: opacity 0.2s;
        }}
        .info-modal-bg.show {{
            opacity: 1;
            pointer-events: auto;
        }}
        .info-modal {{
            position: fixed;
            top: 0;
            right: 0;
            bottom: 0;
            width: 480px;
            max-width: 95vw;
            background: white;
            box-shadow: -10px 0 40px rgba(0,0,0,0.3);
            transform: translateX(100%);
            transition: transform 0.3s cubic-bezier(0.4,0,0.2,1);
            z-index: 1001;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }}
        .info-modal.show {{
            transform: translateX(0);
        }}
        .info-modal-header {{
            padding: 20px 24px;
            border-bottom: 1px solid var(--gray-200);
            display: flex;
            justify-content: space-between;
            align-items: flex-start;
            gap: 12px;
        }}
        .info-modal-title-wrap {{
            flex: 1;
            min-width: 0;
        }}
        .info-modal-badge {{
            display: inline-block;
            padding: 4px 10px;
            border-radius: 999px;
            font-size: 11px;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: 0.5px;
            margin-bottom: 8px;
        }}
        .info-modal-title {{
            font-size: 22px;
            font-weight: 700;
            color: var(--gray-900);
            letter-spacing: -0.3px;
            line-height: 1.2;
        }}
        .info-modal-close {{
            width: 36px;
            height: 36px;
            border-radius: 8px;
            background: var(--gray-100);
            border: none;
            color: var(--gray-600);
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.15s;
            flex-shrink: 0;
        }}
        .info-modal-close:hover {{
            background: var(--lapora-red);
            color: white;
        }}
        .info-modal-body {{
            flex: 1;
            overflow-y: auto;
            padding: 24px;
        }}
        .info-section {{
            margin-bottom: 20px;
        }}
        .info-section:last-child {{ margin-bottom: 0; }}
        .info-section h4 {{
            font-size: 11px;
            font-weight: 700;
            color: var(--gray-500);
            text-transform: uppercase;
            letter-spacing: 0.7px;
            margin-bottom: 8px;
        }}
        .info-section p {{
            color: var(--gray-700);
            font-size: 14px;
            line-height: 1.6;
        }}
        .info-section ul {{
            list-style: none;
            padding: 0;
        }}
        .info-section ul li {{
            position: relative;
            padding-left: 22px;
            font-size: 14px;
            line-height: 1.5;
            color: var(--gray-700);
            margin-bottom: 8px;
        }}
        .info-section ul li::before {{
            content: "";
            position: absolute;
            left: 0;
            top: 8px;
            width: 6px;
            height: 6px;
            border-radius: 50%;
            background: var(--lapora-red);
        }}
        .info-stat-grid {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 10px;
        }}
        .info-stat {{
            background: var(--gray-50);
            border: 1px solid var(--gray-200);
            border-radius: 10px;
            padding: 12px;
        }}
        .info-stat-label {{
            font-size: 11px;
            color: var(--gray-500);
            text-transform: uppercase;
            font-weight: 600;
            letter-spacing: 0.3px;
            margin-bottom: 4px;
        }}
        .info-stat-value {{
            font-size: 18px;
            font-weight: 700;
            color: var(--gray-900);
        }}
        .info-modal-footer {{
            padding: 16px 24px;
            border-top: 1px solid var(--gray-200);
            background: var(--gray-50);
            font-size: 12px;
            color: var(--gray-500);
            text-align: center;
        }}
    </style>
</head>
<body>
    <div class="app">
        {sidebar_html("funnel", stats)}
        <main class="main">
            <div class="page-header">
                <div>
                    <div class="page-title">Funnel Completo Lapora</div>
                    <div class="page-subtitle">Click en cualquier casilla para ver detalles &middot; Scroll para zoom &middot; Arrastra para mover</div>
                </div>
                <div style="display:flex;gap:8px">
                    <button class="btn btn-secondary" onclick="window.print()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 6 2 18 2 18 9"/><path d="M6 18H4a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2"/><rect x="6" y="14" width="12" height="8"/></svg>
                        Imprimir
                    </button>
                    <button class="btn btn-primary" onclick="downloadSVG()">
                        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                        Descargar SVG
                    </button>
                </div>
            </div>

            <div class="funnel-grid">
                <div class="card">
                    <div class="card-header">
                        <div>
                            <div class="card-title">Diagrama del Funnel</div>
                            <div class="card-subtitle">9 fases &middot; Click en cualquier nodo para ver detalles</div>
                        </div>
                    </div>
                    <div class="funnel-canvas" id="funnel-canvas">
                        <div class="zoom-hint">
                            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/></svg>
                            <span>Click para info &middot; <kbd>scroll</kbd> zoom &middot; <kbd>drag</kbd> mover</span>
                        </div>
                        <div class="zoom-controls">
                            <button class="zoom-btn" onclick="zoomIn()" title="Zoom in">+</button>
                            <button class="zoom-btn" onclick="zoomOut()" title="Zoom out">&minus;</button>
                            <button class="zoom-btn" onclick="zoomReset()" title="Reset" style="font-size:14px">&#8634;</button>
                            <button class="zoom-btn" onclick="zoomFit()" title="Ajustar" style="font-size:13px">&#9633;</button>
                        </div>
                        <div class="mermaid" id="funnel-diagram">
{FUNNEL_MERMAID}
                        </div>
                    </div>
                </div>

                <div>
                    <div class="card">
                        <div class="card-header">
                            <div class="card-title">Fases del Funnel</div>
                        </div>
                        {fases_html}
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <div class="card-title">KPIs objetivo</div>
                        </div>
                        {kpis_html}
                    </div>

                    <div class="card">
                        <div class="card-header">
                            <div class="card-title">Leyenda de colores</div>
                        </div>
                        {legend_html}
                    </div>
                </div>
            </div>
        </main>
    </div>

    <!-- Modal de info -->
    <div class="info-modal-bg" id="modalBg" onclick="cerrarModal()"></div>
    <div class="info-modal" id="infoModal">
        <div class="info-modal-header">
            <div class="info-modal-title-wrap">
                <span class="info-modal-badge" id="modalBadge"></span>
                <div class="info-modal-title" id="modalTitle"></div>
            </div>
            <button class="info-modal-close" onclick="cerrarModal()" title="Cerrar">
                <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
            </button>
        </div>
        <div class="info-modal-body" id="modalBody"></div>
        <div class="info-modal-footer">Funnel Lapora &middot; Estrategia 2026</div>
    </div>

    <script>
        // ============================================
        // INFORMACION DETALLADA DE CADA NODO
        // ============================================
        const NODE_INFO = {{
            F1: {{
                cat: "Fase 1", catColor: "#0d9488",
                title: "Captacion - Top of Funnel",
                descripcion: "Objetivo: que doctores potenciales descubran a Lapora a traves de multiples canales digitales y offline.",
                acciones: ["Contenido organico en redes", "Anuncios pagados Meta + Google", "SEO local (Ibague, Tolima, Bogota)", "Networking medico y eventos", "Referidos de clientes activos"],
                kpis: [["Visitas/mes", "5.000+"], ["Conv. a diagnostico", ">15%"]]
            }},
            ORG: {{
                cat: "Canal", catColor: "#1f2937",
                title: "Contenido Organico",
                descripcion: "Construir audiencia y autoridad con contenido educativo de alto valor en Instagram, TikTok y LinkedIn.",
                acciones: ["Reels 3-5 por semana", "Carruseles educativos", "Stories diarias", "Lives mensuales con casos", "Hashtags locales (#MarketingMedicoIbague)"],
                kpis: [["Posts/semana", "12+"], ["Engagement", ">5%"]]
            }},
            PAID: {{
                cat: "Canal", catColor: "#1f2937",
                title: "Anuncios Pagados",
                descripcion: "Meta Ads y Google Ads para acelerar el alcance hacia el ICP (Ideal Customer Profile).",
                acciones: ["Campanas Meta a doctores 30-55 anos", "Google Ads en busquedas tipo 'marketing medico'", "Retargeting de visitas a lapora.studio", "Test A/B semanal"],
                kpis: [["CAC", "<USD 80"], ["ROAS", ">3x"]]
            }},
            SEO: {{
                cat: "Canal", catColor: "#1f2937",
                title: "SEO Local",
                descripcion: "Posicionar lapora.studio en busquedas locales y nacionales relacionadas con marketing para medicos.",
                acciones: ["Keywords: 'marketing digital medicos', 'marketing odontologos Ibague'", "Google My Business optimizado", "Backlinks de clinicas y blogs medicos", "Contenido blog 2x/mes"],
                kpis: [["Keywords top 10", "30+"], ["Trafico organico", "1.5K/mes"]]
            }},
            NET: {{
                cat: "Canal", catColor: "#1f2937",
                title: "Networking Medico",
                descripcion: "Construir relaciones directas en eventos del sector salud para generar leads de alto ticket.",
                acciones: ["Asistir a congresos medicos", "Camara de Comercio Ibague", "Patrocinar eventos pequenos", "Almuerzos 1:1 con KOLs"],
                kpis: [["Eventos/mes", "2-3"], ["Leads/evento", "5-10"]]
            }},
            REF1: {{
                cat: "Referidos", catColor: "#7c3aed",
                title: "Referidos de Clientes",
                descripcion: "El canal mas rentable: clientes felices recomiendan a sus colegas. CAC casi cero.",
                acciones: ["Pedir referidos mes 3 + mes 6", "Incentivo 15% comision o 1 mes gratis", "Carta de presentacion + caso de exito"],
                kpis: [["Referidos/cliente/ano", ">1"], ["Conv. referido", ">60%"]]
            }},
            POV: {{
                cat: "Tipo contenido", catColor: "#1f2937",
                title: "POV de Pacientes",
                descripcion: "Videos cortos en primera persona del paciente mostrando su experiencia con el medico. Altamente viral.",
                acciones: ["Grabar testimonios en consulta", "Edicion vertical para Reels/TikTok", "Subtitulos llamativos", "Hook en primeros 3 segundos"]
            }},
            CASOS: {{
                cat: "Tipo contenido", catColor: "#1f2937",
                title: "Casos de Exito",
                descripcion: "Documentar antes/despues de clientes para social proof. Muestran ROI tangible.",
                acciones: ["Capturas de stats reales", "Video del doctor contando resultados", "Comparativas mes 1 vs mes 6", "Numero de pacientes nuevos"]
            }},
            EDU: {{
                cat: "Tipo contenido", catColor: "#1f2937",
                title: "Tips de Marketing Medico",
                descripcion: "Contenido educativo que posiciona a Lapora como autoridad en marketing para el sector salud.",
                acciones: ["Hooks tipo 'el error #1 que cometen los medicos'", "Carruseles con 5-7 tips", "Estadisticas del sector salud", "CTA suaves a lapora.studio"]
            }},
            AUTH: {{
                cat: "Tipo contenido", catColor: "#1f2937",
                title: "Autoridad Medica",
                descripcion: "Formato pizarra o podcast clips para construir autoridad de marca y atraer doctores premium.",
                acciones: ["Videos pizarra estilo Whiteboard", "Clips de podcast con expertos", "Entrevistas a medicos exitosos", "Series tematicas mensuales"]
            }},
            WEB: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "lapora.studio - Landing + Diagnostico",
                descripcion: "Sitio web principal donde converge todo el trafico. Optimizado para conversion a diagnostico digital.",
                acciones: ["Landing con propuesta de valor clara", "CTA principal: Diagnostico Gratis", "Casos de exito visibles", "FAQ + testimonios", "WhatsApp directo +57 322 878 3019"],
                kpis: [["Conv. visitor &rarr; diag", ">15%"], ["Tiempo en pagina", ">2 min"]]
            }},
            DIAG: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "Diagnostico Digital Gratis",
                descripcion: "Lead magnet de 5 preguntas en 2 minutos. Califica al lead y genera contexto para SofIA.",
                acciones: ["Pregunta 1: Especialidad", "Pregunta 2: Ciudad", "Pregunta 3: Volumen pacientes/mes", "Pregunta 4: Presencia digital actual", "Pregunta 5: Reto principal"],
                kpis: [["Tasa completacion", ">80%"], ["Conv. a WhatsApp", ">70%"]]
            }},
            CALC: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "Calculo de Perdida Mensual",
                descripcion: "Algoritmo que estima cuanto dinero pierde el doctor cada mes en pacientes que van a la competencia.",
                acciones: ["Base de datos por especialidad", "Multiplicador por presencia digital", "Multiplicador por volumen", "Rango tipico: COP 15M-35M/mes"],
                kpis: [["Impacto emocional", "Alto"], ["Justifica precio", "Si"]]
            }},
            CTA: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "CTA a WhatsApp con SofIA",
                descripcion: "Boton final del diagnostico que abre WhatsApp con el contexto completo del doctor.",
                acciones: ["Boton verde llamativo", "Pre-fill mensaje con datos del diagnostico", "Tracking de conversion", "Numero: +57 322 878 3019"]
            }},
            SOFIA: {{
                cat: "Fase 2", catColor: "#0d9488",
                title: "SofIA - Bot IA WhatsApp",
                descripcion: "Asistente virtual que califica leads, agenda citas y nutre relaciones 24/7 sin intervencion humana.",
                acciones: ["Powered by Claude Sonnet 4.6", "Memoria persistente en PostgreSQL", "Tool Use con Google Calendar", "Recordatorios automaticos 1h antes"],
                kpis: [["Disponibilidad", "24/7"], ["Tiempo respuesta", "<5s"]]
            }},
            CTX: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "Contexto del Diagnostico",
                descripcion: "SofIA recibe automaticamente la especialidad, ciudad, volumen, presencia y reto del doctor sin re-preguntar.",
                acciones: ["Mensaje inicial con todo el contexto", "Personalizacion inmediata", "No re-pregunta lo ya sabido", "Pasa directo a soluciones"]
            }},
            CRM: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "Auto-creacion en CRM",
                descripcion: "Cada lead nuevo se crea automaticamente como contacto en el CRM de Lapora con estado 'Nuevo'.",
                acciones: ["Crea Contacto con telefono", "Guarda nombre, especialidad, ciudad", "Estado inicial: Nuevo", "Visible en /admin/contactos"]
            }},
            QUAL: {{
                cat: "Decision", catColor: "#f87171",
                title: "Filtro de Calificacion",
                descripcion: "SofIA evalua si el doctor cumple el ICP de Lapora. Solo los calificados pasan a agendamiento.",
                acciones: ["Especialidad de alto ticket: Si", "Ciudad cubierta: Si", "Volumen aceptable: Si", "Presupuesto razonable: Si"],
                kpis: [["Tasa calificacion", ">40%"]]
            }},
            NURT: {{
                cat: "Recuperacion", catColor: "#f59e0b",
                title: "Secuencia de Nurturing",
                descripcion: "Doctores que no califican aun reciben contenido educativo por 3 meses para madurar la oportunidad.",
                acciones: ["Email semanal con casos", "Contenido educativo segmentado", "Webinars mensuales", "Recalificacion cada 30 dias"]
            }},
            AGENDA: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "Agendamiento Automatico",
                descripcion: "SofIA agenda directamente en Google Calendar del equipo Lapora sin intervencion humana.",
                acciones: ["Verifica disponibilidad real", "Crea evento en Google Calendar", "Confirma con doctor por WhatsApp", "Envia recordatorio 1h antes"]
            }},
            REM1: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "Recordatorio 1h antes",
                descripcion: "SofIA envia automaticamente mensaje 1h antes para confirmar asistencia y reducir no-shows.",
                acciones: ["Mensaje personalizado con nombre", "Hora exacta en formato local", "Opcion de reagendar facilmente", "Reduce no-shows ~25%"],
                kpis: [["Show rate", ">75%"]]
            }},
            REUNION1: {{
                cat: "Fase 4", catColor: "#0d9488",
                title: "Diagnostico Profundo",
                descripcion: "Llamada de 30 minutos en Zoom/Meet donde se audita la presencia digital completa del doctor en vivo.",
                acciones: ["Conexion personal", "Auditoria pantalla compartida", "Identificar 3-5 fugas digitales", "Plantear plan de solucion"],
                kpis: [["Duracion", "30 min"], ["Conv. a propuesta", ">50%"]]
            }},
            AUDIT: {{
                cat: "Proceso", catColor: "#1f2937",
                title: "Auditoria Completa",
                descripcion: "Revision detallada de Google My Business, Instagram, sitio web, reviews y anuncios actuales.",
                acciones: ["Google My Business score", "Instagram engagement rate", "Web speed + UX score", "Reviews promedio", "Calidad de anuncios actuales"]
            }},
            PROP_REC: {{
                cat: "Proceso", catColor: "#1f2937",
                title: "Recomendacion Personalizada",
                descripcion: "En vivo durante la reunion se presenta una solucion adaptada a los hallazgos del diagnostico.",
                acciones: ["Plan a medida con prioridades", "Casos similares de exito", "Timeline 30/60/90 dias", "Pre-vista del ROI esperado"]
            }},
            INT: {{
                cat: "Decision", catColor: "#f87171",
                title: "Interesado en Propuesta?",
                descripcion: "Punto de decision tras el diagnostico profundo. Si esta listo se envia propuesta formal.",
                acciones: ["Si: pasar a Fase 5", "No ahora: follow-up estrategico", "Documentar objeciones", "Programar reach-out futuro"]
            }},
            FOLLOWUP: {{
                cat: "Recuperacion", catColor: "#f59e0b",
                title: "Follow-up Estrategico",
                descripcion: "Seguimiento no agresivo basado en valor: enviar casos relevantes, novedades de Lapora, sin presion.",
                acciones: ["Tocar cada 2-3 semanas", "Compartir casos similares", "No insistir en venta", "Estar top-of-mind"]
            }},
            PROP: {{
                cat: "Fase 5", catColor: "#0d9488",
                title: "Propuesta Personalizada",
                descripcion: "Documento formal con plan a medida, pricing en 3 tiers, casos relevantes y garantia explicita.",
                acciones: ["PDF profesional personalizado", "Pricing claro y transparente", "Timeline detallado", "Casos de exito relevantes"],
                kpis: [["Win rate", ">30%"]]
            }},
            TIERS: {{
                cat: "Componente", catColor: "#1f2937",
                title: "3 Tiers de Pricing",
                descripcion: "Starter (USD 1.000/mes), Growth (USD 2.000/mes), Premium (USD 4.000/mes) con anticipo 50%.",
                acciones: ["Starter: Bot IA + contenido organico", "Growth: + anuncios pagados + SEO", "Premium: + web nueva + email marketing"]
            }},
            CASOS_EX: {{
                cat: "Componente", catColor: "#1f2937",
                title: "Casos de Exito",
                descripcion: "Otaima, Nutrifit y otros clientes con resultados documentados. Social proof clave para cerrar.",
                acciones: ["Video testimonios", "Numeros reales del cliente", "Antes/despues medibles", "Especialidad similar al prospecto"]
            }},
            GARANT: {{
                cat: "Componente", catColor: "#1f2937",
                title: "Garantia Mes 1",
                descripcion: "Si al finalizar el mes 1 no hay resultados medibles (alcance, leads, citas), Lapora ajusta sin costo.",
                acciones: ["Reduce friccion de cierre", "Doctor no teme probar", "Demuestra confianza en el sistema", "Diferenciador vs competencia"]
            }},
            CIERRE: {{
                cat: "Decision", catColor: "#f87171",
                title: "Firma del Contrato",
                descripcion: "Momento de cierre. Si firma, se procesa el anticipo y se inicia onboarding.",
                acciones: ["Contrato digital", "Firma electronica", "Pago anticipo 50%", "Calendarizar kickoff"]
            }},
            NURT_LONG: {{
                cat: "Recuperacion", catColor: "#f59e0b",
                title: "Nurturing Largo Plazo",
                descripcion: "Los que no firman entran a nurturing de 6 meses con nuevos casos y actualizaciones de servicio.",
                acciones: ["Newsletter mensual", "Compartir nuevos casos exitosos", "Eventos exclusivos online", "Re-pitch en mes 6"]
            }},
            PAGO: {{
                cat: "Dinero entra", catColor: "#84cc16",
                title: "Anticipo 50%",
                descripcion: "Primer pago del cliente: USD 1.500 - 5.000 segun tier elegido. Confirma compromiso real.",
                acciones: ["Wise / PayPal / Bancolombia", "Factura electronica", "Confirmacion automatica", "Trigger onboarding"],
                kpis: [["Ticket promedio", "USD 2.500"]]
            }},
            ONBOARD: {{
                cat: "Fase 6", catColor: "#0d9488",
                title: "Onboarding",
                descripcion: "Proceso estructurado de 7 dias para configurar todo lo necesario antes de empezar la ejecucion.",
                acciones: ["Welcome kit digital", "Acceso a Slack/WhatsApp privado", "Calendarizar kickoff meeting", "Solicitar accesos a herramientas"]
            }},
            KICKOFF: {{
                cat: "Proceso", catColor: "#1f2937",
                title: "Kickoff Meeting",
                descripcion: "Reunion inicial para alinear expectativas y presentar estrategia 30/60/90 dias del proyecto.",
                acciones: ["Equipo Lapora completo presente", "Roadmap visual del proyecto", "Definir KPIs especificos", "Asignar punto de contacto unico"]
            }},
            SETUP: {{
                cat: "Proceso", catColor: "#1f2937",
                title: "Setup Tecnico",
                descripcion: "Configuracion de todas las herramientas y accesos necesarios para empezar la ejecucion.",
                acciones: ["Configurar Bot IA WhatsApp", "Instalar pixeles + analytics", "Conectar Google Ads / Meta", "Setup branding consistente"]
            }},
            EJEC: {{
                cat: "Fase 7", catColor: "#0d9488",
                title: "Ejecucion Mensual",
                descripcion: "Operacion mensual con entregables fijos y reportes semanales transparentes para el cliente.",
                acciones: ["Produccion contenido continuo", "Gestion de anuncios", "Optimizacion SEO", "Bot IA activo 24/7", "Reportes semanales"]
            }},
            CONTENIDO: {{
                cat: "Entregable", catColor: "#1f2937",
                title: "Produccion de Contenido",
                descripcion: "Reels, posts, videos y stories profesionales producidos por el equipo Lapora cada mes.",
                acciones: ["12-20 reels/mes", "8-12 posts/mes", "Stories diarias", "1-2 videos largos/mes"]
            }},
            ADS_GEST: {{
                cat: "Entregable", catColor: "#1f2937",
                title: "Gestion de Anuncios",
                descripcion: "Campanas activas en Meta Ads, Google Ads y TikTok Ads con optimizacion continua.",
                acciones: ["Test A/B semanal", "Optimizacion de audiencias", "Creativos nuevos cada 15 dias", "Reportes ROAS"]
            }},
            SEO_OPT: {{
                cat: "Entregable", catColor: "#1f2937",
                title: "Optimizacion SEO",
                descripcion: "Trabajo continuo en SEO local y nacional para escalar trafico organico del cliente.",
                acciones: ["Auditorias mensuales", "Contenido SEO blog", "Backlinks de calidad", "Google My Business updates"]
            }},
            BOT_LIVE: {{
                cat: "Lapora", catColor: "#FF3B30",
                title: "Bot IA WhatsApp Activo",
                descripcion: "El cliente recibe su propio bot personalizado que atiende a sus pacientes 24/7.",
                acciones: ["Bot con tono del medico", "Agenda citas automatico", "FAQ del consultorio", "Escalamiento a humano cuando aplica"]
            }},
            REPORTES: {{
                cat: "Entregable", catColor: "#1f2937",
                title: "Reportes Semanales",
                descripcion: "Reportes transparentes cada semana con KPIs claros y plan de accion para la siguiente semana.",
                acciones: ["Alcance total", "Leads generados", "Citas agendadas", "Costo por paciente", "ROAS por canal"]
            }},
            MES1: {{
                cat: "Decision", catColor: "#f87171",
                title: "Mes 1 Exitoso?",
                descripcion: "Punto de evaluacion critico al finalizar el mes 1. Si no hay resultados, garantia se activa.",
                acciones: ["Revisar KPIs vs baseline", "Reunion de evaluacion", "Si: continuar plan", "No: ajuste sin costo"]
            }},
            AJUSTE: {{
                cat: "Recuperacion", catColor: "#f59e0b",
                title: "Ajuste sin Costo",
                descripcion: "Cuando mes 1 no cumple, Lapora ajusta la estrategia sin cobrar extra. Cumplir la garantia.",
                acciones: ["Diagnostico de que fallo", "Nueva estrategia propuesta", "Recursos adicionales", "Sin cobro adicional"]
            }},
            PAGO_REC: {{
                cat: "Dinero entra", catColor: "#84cc16",
                title: "Pago Recurrente Mensual",
                descripcion: "USD 1.000 - 4.000 por mes segun tier. Ingreso predecible y compuesto.",
                acciones: ["Cobro automatico mes 2 en adelante", "Factura electronica mensual", "Renovacion anual con descuento"],
                kpis: [["MRR objetivo", "USD 136K/mes"]]
            }},
            RET: {{
                cat: "Fase 8", catColor: "#0d9488",
                title: "Retencion - Mes 3+",
                descripcion: "Cliente estable con KPIs predecibles. Momento de buscar upsell y documentar caso de exito.",
                acciones: ["Reunion estrategica mensual", "Identificar oportunidades de crecimiento", "Construir relacion personal", "Anticipar renovacion anual"],
                kpis: [["Retencion mes 6", ">70%"]]
            }},
            KPI_OK: {{
                cat: "Resultado", catColor: "#1f2937",
                title: "KPIs Estables",
                descripcion: "ROAS de 3x a 8x sostenido. Costo por paciente nuevo bajo control. Doctor satisfecho.",
                acciones: ["ROAS 3x-8x", "CAC paciente: COP 50K-150K", "LTV/CAC ratio > 3", "NPS > 50"]
            }},
            UPSELL: {{
                cat: "Dinero entra", catColor: "#84cc16",
                title: "Upsell de Servicios",
                descripcion: "Ofrecer servicios adicionales: Bot IA premium, SEO avanzado, web nueva, email marketing.",
                acciones: ["Audit cada trimestre", "Proponer mejoras incrementales", "Pricing transparente", "Trial 30 dias"]
            }},
            CASOS_DOC: {{
                cat: "Proceso", catColor: "#1f2937",
                title: "Documentar Caso de Exito",
                descripcion: "Producir video y caso de estudio con permiso del cliente para usar en marketing de Lapora.",
                acciones: ["Entrevista grabada en alta calidad", "Numeros reales documentados", "Antes/despues visual", "Permiso escrito firmado"]
            }},
            AMB: {{
                cat: "Fase 9", catColor: "#0d9488",
                title: "Lapora Ambassador",
                descripcion: "Programa formal donde clientes felices generan nuevos clientes a cambio de incentivos atractivos.",
                acciones: ["Carta de bienvenida al programa", "Materiales de venta personalizados", "Comisiones claras y rapidas", "Reconocimiento publico"]
            }},
            INCENT: {{
                cat: "Referidos", catColor: "#7c3aed",
                title: "Incentivos por Referido",
                descripcion: "15% de comision del primer pago O 1 mes gratis de servicio. Doctor elige el incentivo.",
                acciones: ["15% de USD 1.500 = USD 225", "1 mes gratis vale USD 1.000+", "Pago inmediato post-firma", "Sin limite anual"]
            }},
            TESTIM: {{
                cat: "Referidos", catColor: "#7c3aed",
                title: "Testimonios en Video",
                descripcion: "Clientes ambassadors graban testimonios que se usan en marketing de Lapora.",
                acciones: ["Set profesional o remoto guiado", "Preguntas estructuradas", "Edicion premium", "Distribucion en redes + web"]
            }},
            NUEVO_REF: {{
                cat: "Referidos", catColor: "#7c3aed",
                title: "Nuevo Doctor Recomendado",
                descripcion: "Doctor nuevo llega via referido. Entra al funnel con conversion ~60% vs ~30% trafico frio.",
                acciones: ["WhatsApp directo presentado", "Caso del ambassador como prueba", "Skip de Fase 1-2", "Directo a diagnostico profundo"]
            }}
        }};

        // ============================================
        // MODAL DE INFO
        // ============================================
        function mostrarInfo(nodeId) {{
            const data = NODE_INFO[nodeId];
            if (!data) return;

            document.getElementById('modalBadge').textContent = data.cat;
            document.getElementById('modalBadge').style.background = (data.catColor || '#1f2937') + '22';
            document.getElementById('modalBadge').style.color = data.catColor || '#1f2937';
            document.getElementById('modalTitle').textContent = data.title;

            let bodyHTML = '';
            if (data.descripcion) {{
                bodyHTML += '<div class="info-section"><h4>Descripcion</h4><p>' + data.descripcion + '</p></div>';
            }}
            if (data.acciones && data.acciones.length) {{
                bodyHTML += '<div class="info-section"><h4>Acciones / Tacticas</h4><ul>';
                data.acciones.forEach(a => bodyHTML += '<li>' + a + '</li>');
                bodyHTML += '</ul></div>';
            }}
            if (data.kpis && data.kpis.length) {{
                bodyHTML += '<div class="info-section"><h4>KPIs Clave</h4><div class="info-stat-grid">';
                data.kpis.forEach(k => {{
                    bodyHTML += '<div class="info-stat"><div class="info-stat-label">' + k[0] + '</div><div class="info-stat-value">' + k[1] + '</div></div>';
                }});
                bodyHTML += '</div></div>';
            }}

            document.getElementById('modalBody').innerHTML = bodyHTML;
            document.getElementById('infoModal').classList.add('show');
            document.getElementById('modalBg').classList.add('show');
        }}

        function cerrarModal() {{
            document.getElementById('infoModal').classList.remove('show');
            document.getElementById('modalBg').classList.remove('show');
        }}

        document.addEventListener('keydown', function(e) {{
            if (e.key === 'Escape') cerrarModal();
        }});

        // ============================================
        // MERMAID + PAN/ZOOM
        // ============================================
        let panZoomInstance = null;

        mermaid.initialize({{
            startOnLoad: true,
            securityLevel: 'loose',
            theme: 'dark',
            themeVariables: {{
                primaryColor: '#1f2937',
                primaryTextColor: '#fff',
                primaryBorderColor: '#374151',
                lineColor: '#6b7280',
                secondaryColor: '#374151',
                tertiaryColor: '#111827',
                background: '#0d0d0d',
                mainBkg: '#1f2937',
                secondBkg: '#111827',
                tertiaryBkg: '#1a1a1a',
                fontFamily: 'Inter, sans-serif',
                fontSize: '13px',
            }},
            flowchart: {{
                curve: 'basis',
                padding: 20,
                nodeSpacing: 60,
                rankSpacing: 60,
                useMaxWidth: false,
            }}
        }});

        // Esperar a que Mermaid termine de renderizar y aplicar pan/zoom
        function inicializarZoom() {{
            const svg = document.querySelector('#funnel-diagram svg');
            if (!svg) {{
                setTimeout(inicializarZoom, 200);
                return;
            }}
            // Limpiar atributos que limitan tamaño
            svg.removeAttribute('width');
            svg.removeAttribute('height');
            svg.removeAttribute('style');
            svg.setAttribute('width', '100%');
            svg.setAttribute('height', '100%');

            panZoomInstance = svgPanZoom(svg, {{
                zoomEnabled: true,
                controlIconsEnabled: false,
                fit: true,
                center: true,
                minZoom: 0.1,
                maxZoom: 50,
                zoomScaleSensitivity: 0.5,
                mouseWheelZoomEnabled: true,
                preventMouseEventsDefault: true,
                dblClickZoomEnabled: false,
            }});
        }}
        setTimeout(inicializarZoom, 500);

        function zoomIn() {{ if (panZoomInstance) panZoomInstance.zoomBy(1.6); }}
        function zoomOut() {{ if (panZoomInstance) panZoomInstance.zoomBy(0.62); }}
        function zoomReset() {{ if (panZoomInstance) {{ panZoomInstance.resetZoom(); panZoomInstance.center(); }} }}
        function zoomFit() {{ if (panZoomInstance) {{ panZoomInstance.fit(); panZoomInstance.center(); }} }}

        function downloadSVG() {{
            const svg = document.querySelector('.mermaid svg');
            if (!svg) {{
                alert('Esperando que se renderice el diagrama...');
                return;
            }}
            const serializer = new XMLSerializer();
            const svgString = serializer.serializeToString(svg);
            const blob = new Blob([svgString], {{ type: 'image/svg+xml' }});
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url;
            link.download = 'lapora-funnel.svg';
            document.body.appendChild(link);
            link.click();
            document.body.removeChild(link);
            URL.revokeObjectURL(url);
        }}
    </script>
</body>
</html>"""
    return HTMLResponse(content=html_header + html_body)


# ════════════════════════════════════════════════════════════
# PROSPECTOS — CRM de outreach con estado de respuestas
# ════════════════════════════════════════════════════════════

PROSPECTOS_DIR = Path(__file__).parent.parent / "data" / "prospectos"

# Cache con TTL para evitar leer CSV en cada request
_PROSPECTOS_CACHE: dict = {"data": None, "loaded_at": 0, "mtimes": {}}
_PROSPECTOS_CACHE_TTL_SEC = 60  # Refresca cada 60s o si cambia mtime


def _mtime_or_zero(p: Path) -> float:
    try:
        return p.stat().st_mtime
    except OSError:
        return 0.0


def cargar_prospectos_csv() -> tuple[list[dict], dict[str, dict], dict[str, dict]]:
    """Retorna (prospectos, envios_por_id, estados_por_id) con cache TTL 60s."""
    p_csv = PROSPECTOS_DIR / "prospectos_200_reales.csv"
    e_csv = PROSPECTOS_DIR / "envios_log.csv"
    s_csv = PROSPECTOS_DIR / "estados_prospectos.csv"

    ahora = _time.time()
    mtimes_actuales = {
        "p": _mtime_or_zero(p_csv),
        "e": _mtime_or_zero(e_csv),
        "s": _mtime_or_zero(s_csv),
    }

    cache_valido = (
        _PROSPECTOS_CACHE["data"] is not None
        and (ahora - _PROSPECTOS_CACHE["loaded_at"]) < _PROSPECTOS_CACHE_TTL_SEC
        and _PROSPECTOS_CACHE["mtimes"] == mtimes_actuales
    )
    if cache_valido:
        return _PROSPECTOS_CACHE["data"]

    prospectos, envios, estados = [], {}, {}
    if p_csv.exists():
        with open(p_csv, "r", encoding="utf-8") as f:
            prospectos = list(csv.DictReader(f))
    if e_csv.exists():
        with open(e_csv, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("estado") == "enviado":
                    envios[row["id"]] = row
    if s_csv.exists():
        with open(s_csv, "r", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                estados[row["id"]] = row

    _PROSPECTOS_CACHE["data"] = (prospectos, envios, estados)
    _PROSPECTOS_CACHE["loaded_at"] = ahora
    _PROSPECTOS_CACHE["mtimes"] = mtimes_actuales
    return prospectos, envios, estados


@router.get("/prospectos", response_class=HTMLResponse)
async def vista_prospectos(user: str = Depends(verificar_credenciales),
                            filtro: Optional[str] = None,
                            buscar: Optional[str] = None):
    """Vista de prospectos de outreach con estado de respuesta (lee de PostgreSQL)."""
    # Lazy import para evitar acoplar dashboard.py al modelo
    from agent.memory import listar_prospectos, contar_prospectos_por_estado

    # Datos desde DB
    prospectos_db = await listar_prospectos(estado=filtro, buscar=buscar, solo_verificados=True)
    counts = await contar_prospectos_por_estado()

    # Enriquecer prospectos en formato dict para reusar el rendering
    enriquecidos: list[dict] = []
    for pr in prospectos_db:
        enriquecidos.append({
            "id": str(pr.id),
            "nombre_negocio": pr.nombre_negocio or "",
            "email": pr.email or "",
            "telefono": pr.telefono or "",
            "direccion": pr.direccion or "",
            "especialidad": pr.especialidad or "",
            "tipo": pr.tipo or "",
            "_estado": pr.estado or "no_enviado",
            "_fecha_envio": pr.fecha_envio.strftime("%Y-%m-%d %H:%M") if pr.fecha_envio else "",
            "_fecha_resp": pr.fecha_respuesta.strftime("%Y-%m-%d %H:%M") if pr.fecha_respuesta else "",
            "_asunto_resp": pr.asunto_respuesta or "",
            "_preview_resp": pr.preview_respuesta or "",
            "_cupon": pr.cupon or "",
        })

    todos_count    = sum(counts.values()) or 0
    respondio      = counts.get("respondido", 0) + counts.get("interesado", 0) + counts.get("cliente", 0)
    enviados_count = todos_count - counts.get("no_enviado", 0)
    sin_resp       = counts.get("enviado_sin_respuesta", 0)
    no_env         = counts.get("no_enviado", 0)

    stats = {
        "total": todos_count,
        "enviados": enviados_count,
        "respondieron": respondio,
        "pendientes": no_env,
    }

    label_estado = {
        "respondido": ("Respondió", "#10B981", "✉"),
        "interesado": ("Interesado", "#10B981", "✓"),
        "cliente": ("Cliente", "#10B981", "★"),
        "enviado_sin_respuesta": ("Enviado", "#F59E0B", "⏳"),
        "no_enviado": ("Pendiente", "#78716C", "○"),
        "rebotado": ("Rebotó", "#EF4444", "✗"),
    }

    filas_html = ""
    for p in enriquecidos:
        est = p["_estado"]
        label, color, icono = label_estado.get(est, (est, "#78716C", "•"))
        bg = {
            "respondido": "rgba(16,185,129,0.06)",
            "interesado": "rgba(16,185,129,0.10)",
            "cliente": "rgba(16,185,129,0.14)",
            "enviado_sin_respuesta": "rgba(245,158,11,0.04)",
            "rebotado": "rgba(239,68,68,0.05)",
        }.get(est, "transparent")

        # Escape completo contra XSS (<, >, &, ", ')
        nombre    = html.escape((p.get("nombre_negocio") or ""), quote=True)
        email     = html.escape((p.get("email") or ""), quote=True)
        tel       = html.escape((p.get("telefono") or ""), quote=True)
        direccion = html.escape((p.get("direccion") or "")[:60], quote=True)
        preview   = html.escape((p.get("_preview_resp") or p.get("_asunto_resp") or "")[:80], quote=True)
        cupon     = html.escape((p.get("_cupon") or "—"), quote=True)

        filas_html += f"""
        <tr style="background:{bg}">
          <td style="padding:14px 12px;font-weight:600;color:#1c1917;">{nombre}</td>
          <td style="padding:14px 12px;">
            <span style="background:{color}15;color:{color};padding:4px 10px;border-radius:999px;font-size:12px;font-weight:700;white-space:nowrap;">
              {icono} {label}
            </span>
          </td>
          <td style="padding:14px 12px;"><a href="mailto:{email}" style="color:#0066CC;font-size:13px;">{email}</a></td>
          <td style="padding:14px 12px;font-family:monospace;font-size:13px;color:#57534e;">{tel}</td>
          <td style="padding:14px 12px;font-size:13px;color:#57534e;">{direccion}</td>
          <td style="padding:14px 12px;font-family:monospace;font-size:12px;font-weight:700;color:#FF3B30;">{cupon}</td>
          <td style="padding:14px 12px;font-size:12px;color:#78716c;font-style:italic;">{preview}</td>
        </tr>"""

    # Filtros (botones)
    filtros_disponibles = [
        ("todos", f"Todos ({todos_count})", "#1c1917"),
        ("respondido", f"Respondieron ({respondio})", "#10B981"),
        ("enviado_sin_respuesta", f"Enviados ({sin_resp})", "#F59E0B"),
        ("no_enviado", f"Pendientes ({no_env})", "#78716C"),
    ]
    chips = ""
    for key, lab, col in filtros_disponibles:
        activo = filtro == key or (not filtro and key == "todos")
        bg_chip = col if activo else "transparent"
        txt_chip = "#fff" if activo else col
        chips += f"""<a href="/admin/prospectos?filtro={key}" style="background:{bg_chip};color:{txt_chip};border:1.5px solid {col};padding:8px 16px;border-radius:999px;font-size:13px;font-weight:600;text-decoration:none;display:inline-block;margin-right:8px;margin-bottom:8px;">{lab}</a>"""

    busqueda_val = html.escape(buscar or "", quote=True)

    html_header = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Prospectos Outreach - Lapora CRM</title>
"""
    if todos_count == 0:
        boton_seed = (
            '<a href="/admin/prospectos/seed" '
            'style="background:#FF3B30;color:#fff;text-decoration:none;padding:10px 18px;'
            'border-radius:10px;font-size:13px;font-weight:600;display:inline-block;'
            'box-shadow:0 4px 12px rgba(255,59,48,0.25);">'
            '↑ Cargar prospectos desde CSV</a>'
        )
    else:
        boton_seed = (
            '<div style="display:flex;gap:10px;flex-wrap:wrap;">'
            '<a href="/admin/prospectos/whatsapp" '
            'style="background:#25D366;color:#fff;text-decoration:none;padding:10px 18px;'
            'border-radius:10px;font-size:13px;font-weight:600;display:inline-block;'
            'box-shadow:0 4px 12px rgba(37,211,102,0.25);">'
            '📲 Enviar WhatsApp a respondieron</a>'
            '<a href="/admin/prospectos/seed" '
            'style="background:transparent;color:#1c1917;text-decoration:none;padding:10px 18px;'
            'border-radius:10px;font-size:13px;font-weight:600;display:inline-block;'
            'border:1.5px solid #e7e5e4;">'
            '↑ Recargar CSVs</a>'
            '</div>'
        )

    html_body = f"""
    {CSS_BASE}
<body>
  <div class="app">
    {sidebar_html("prospectos", stats)}
    <main class="main">
      <div style="padding:32px 40px;border-bottom:1px solid #e7e5e4;background:#fff;display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap;">
        <div>
          <h1 style="margin:0;font-size:28px;font-weight:800;letter-spacing:-0.5px;color:#1c1917;">
            Prospectos de Outreach
          </h1>
          <p style="margin:8px 0 0;color:#78716c;font-size:14px;">
            Campaña de email a {todos_count} clínicas en Ibagué + 60 km · Lectura desde PostgreSQL
          </p>
        </div>
        <div>{boton_seed}</div>
      </div>

      <div style="padding:24px 40px;background:#fafaf9;border-bottom:1px solid #e7e5e4;">
        <form method="get" action="/admin/prospectos" style="display:flex;gap:12px;margin-bottom:16px;">
          <input type="text" name="buscar" value="{busqueda_val}" placeholder="Buscar por nombre, email o especialidad..."
                 style="flex:1;padding:12px 16px;border:1.5px solid #e7e5e4;border-radius:10px;font-size:14px;outline:none;"
                 onfocus="this.style.borderColor='#FF3B30'" onblur="this.style.borderColor='#e7e5e4'">
          <button type="submit" style="background:#1c1917;color:#fff;border:none;padding:0 28px;border-radius:10px;font-size:14px;font-weight:600;cursor:pointer;">Buscar</button>
        </form>
        <div>{chips}</div>
      </div>

      <div style="padding:24px 40px 0;">
        <p style="background:#FFF1F0;color:#8B0000;padding:12px 16px;border-radius:10px;font-size:13px;border-left:4px solid #FF3B30;">
          💡 ¿Faltan datos? Sube los CSVs en <a href="/admin/prospectos/seed" style="font-weight:700;">/admin/prospectos/seed</a> para cargar/actualizar la base.
        </p>
      </div>

      <div style="padding:24px 40px;">
        <div style="background:#fff;border:1px solid #e7e5e4;border-radius:14px;overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,0.04);">
          <table style="width:100%;border-collapse:collapse;">
            <thead>
              <tr style="background:#1c1917;color:#fff;">
                <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Negocio</th>
                <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Estado</th>
                <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Email</th>
                <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Teléfono</th>
                <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Dirección</th>
                <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Cupón</th>
                <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Última actividad</th>
              </tr>
            </thead>
            <tbody>
              {filas_html if filas_html else '<tr><td colspan="7" style="padding:60px;text-align:center;color:#78716c;font-style:italic;">No hay prospectos para mostrar con este filtro</td></tr>'}
            </tbody>
          </table>
        </div>
        <p style="text-align:center;color:#a8a29e;font-size:12px;margin-top:16px;">
          {len(enriquecidos)} prospectos mostrados · Datos actualizados {datetime.now().strftime('%d/%m/%Y %H:%M')}
        </p>
      </div>
    </main>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_header + html_body)


# ════════════════════════════════════════════════════════════
# SEED — Cargar prospectos desde CSVs subidos por el usuario
# ════════════════════════════════════════════════════════════

@router.get("/prospectos/seed", response_class=HTMLResponse)
async def vista_seed_prospectos(user: str = Depends(verificar_credenciales)):
    """Muestra formulario para subir las 3 CSVs de outreach."""
    html_header = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Cargar Prospectos - Lapora CRM</title>
"""
    html_body = f"""
    {CSS_BASE}
<body>
  <div class="app">
    {sidebar_html("prospectos")}
    <main class="main">
      <div style="padding:32px 40px;border-bottom:1px solid #e7e5e4;background:#fff;">
        <h1 style="margin:0;font-size:28px;font-weight:800;letter-spacing:-0.5px;color:#1c1917;">
          Cargar Prospectos desde CSV
        </h1>
        <p style="margin:8px 0 0;color:#78716c;font-size:14px;">
          Sube los 3 archivos CSV de outreach. La base de datos se actualizará automáticamente.
        </p>
      </div>

      <div style="padding:40px;">
        <div style="max-width:680px;background:#fff;border:1px solid #e7e5e4;border-radius:14px;padding:32px;box-shadow:var(--shadow-md);">
          <form method="post" action="/admin/prospectos/seed" enctype="multipart/form-data">

            <div style="margin-bottom:20px;">
              <label style="display:block;font-weight:700;font-size:14px;color:#1c1917;margin-bottom:6px;">
                1. prospectos_200_reales.csv <span style="color:#FF3B30;">*</span>
              </label>
              <p style="font-size:12px;color:#78716c;margin-bottom:8px;">
                Lista maestra de 200 prospectos con email_verificado
              </p>
              <input type="file" name="prospectos_csv" accept=".csv" required
                     style="width:100%;padding:10px;border:1.5px dashed #e7e5e4;border-radius:10px;font-size:14px;cursor:pointer;">
            </div>

            <div style="margin-bottom:20px;">
              <label style="display:block;font-weight:700;font-size:14px;color:#1c1917;margin-bottom:6px;">
                2. envios_log.csv <span style="color:#78716c;font-weight:400;">(opcional)</span>
              </label>
              <p style="font-size:12px;color:#78716c;margin-bottom:8px;">
                Log de emails enviados con cupones generados
              </p>
              <input type="file" name="envios_csv" accept=".csv"
                     style="width:100%;padding:10px;border:1.5px dashed #e7e5e4;border-radius:10px;font-size:14px;cursor:pointer;">
            </div>

            <div style="margin-bottom:28px;">
              <label style="display:block;font-weight:700;font-size:14px;color:#1c1917;margin-bottom:6px;">
                3. estados_prospectos.csv <span style="color:#78716c;font-weight:400;">(opcional)</span>
              </label>
              <p style="font-size:12px;color:#78716c;margin-bottom:8px;">
                Estados de respuesta detectados por el monitor automático
              </p>
              <input type="file" name="estados_csv" accept=".csv"
                     style="width:100%;padding:10px;border:1.5px dashed #e7e5e4;border-radius:10px;font-size:14px;cursor:pointer;">
            </div>

            <button type="submit"
                    style="width:100%;background:#FF3B30;color:#fff;border:none;padding:14px;border-radius:10px;font-size:15px;font-weight:700;cursor:pointer;box-shadow:0 4px 12px rgba(255,59,48,0.3);transition:all 0.2s;">
              ↑ Cargar a PostgreSQL
            </button>

            <p style="font-size:12px;color:#a8a29e;margin-top:16px;text-align:center;">
              Los datos se hacen upsert (no se duplican). Puedes subir los mismos archivos varias veces sin problema.
            </p>
          </form>
        </div>
      </div>
    </main>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html_header + html_body)


def _parse_dt_csv(s: str) -> Optional[datetime]:
    if not s:
        return None
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(s[:19], fmt)
        except ValueError:
            continue
    return None


@router.post("/prospectos/seed", response_class=HTMLResponse)
async def procesar_seed_prospectos(
    user: str = Depends(verificar_credenciales),
    prospectos_csv: UploadFile = File(...),
    envios_csv: Optional[UploadFile] = File(None),
    estados_csv: Optional[UploadFile] = File(None),
):
    """Procesa los CSVs subidos y hace upsert en la tabla prospectos."""
    from agent.memory import async_session, Prospecto

    # Leer contenido en memoria
    contenido_p = (await prospectos_csv.read()).decode("utf-8", errors="replace")
    rows_prospectos = list(csv.DictReader(StringIO(contenido_p)))

    envios_map: dict[str, dict] = {}
    if envios_csv and envios_csv.filename:
        contenido_e = (await envios_csv.read()).decode("utf-8", errors="replace")
        for row in csv.DictReader(StringIO(contenido_e)):
            if row.get("estado") == "enviado":
                envios_map[row["id"]] = row

    estados_map: dict[str, dict] = {}
    if estados_csv and estados_csv.filename:
        contenido_s = (await estados_csv.read()).decode("utf-8", errors="replace")
        for row in csv.DictReader(StringIO(contenido_s)):
            estados_map[row["id"]] = row

    # Upsert por email
    creados = actualizados = 0
    async with async_session() as session:
        for p in rows_prospectos:
            email_p = p.get("email", "").strip()
            if not email_p:
                continue

            env = envios_map.get(p["id"], {})
            est = estados_map.get(p["id"], {})
            estado_outreach = est.get("estado") or ("enviado_sin_respuesta" if p["id"] in envios_map else "no_enviado")

            datos = {
                "nombre_negocio":     p.get("nombre_negocio", ""),
                "nombre_doctor":      p.get("nombre_doctor", ""),
                "especialidad":       p.get("especialidad", ""),
                "email":              email_p,
                "telefono":           p.get("telefono", ""),
                "direccion":          p.get("direccion", ""),
                "tipo":               p.get("tipo", ""),
                "prioridad":          p.get("prioridad", "media"),
                "website":            p.get("website", ""),
                "email_verificado":   p.get("email_verificado", "PENDIENTE").upper(),
                "estado":             estado_outreach,
                "cupon":              env.get("codigo_cupon", ""),
                "fecha_envio":        _parse_dt_csv(env.get("timestamp", "") or est.get("fecha_envio", "")),
                "fecha_respuesta":    _parse_dt_csv(est.get("fecha_respuesta", "")),
                "tipo_respuesta":     est.get("tipo_respuesta", ""),
                "asunto_respuesta":   est.get("asunto_respuesta", "")[:300],
                "preview_respuesta":  est.get("preview_respuesta", ""),
                "notas":              est.get("notas", ""),
            }

            q = select(Prospecto).where(Prospecto.email == email_p)
            existing = (await session.execute(q)).scalar_one_or_none()
            ahora = datetime.utcnow()
            if existing is None:
                session.add(Prospecto(creado_en=ahora, actualizado_en=ahora, **datos))
                creados += 1
            else:
                for k, v in datos.items():
                    if v is not None and v != "":
                        setattr(existing, k, v)
                existing.actualizado_en = ahora
                actualizados += 1
        await session.commit()

    # Invalidar cache si la endpoint anterior aun usa CSV cache (legacy)
    _PROSPECTOS_CACHE["data"] = None

    return HTMLResponse(f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Carga completa</title>{CSS_BASE}</head>
<body><div class="app">{sidebar_html("prospectos")}<main class="main">
<div style="padding:40px;max-width:680px;margin:auto;">
  <div style="background:#fff;border:1px solid #e7e5e4;border-radius:14px;padding:32px;text-align:center;">
    <div style="font-size:48px;margin-bottom:16px;">✅</div>
    <h1 style="margin:0;font-size:24px;color:#10B981;">Carga completa</h1>
    <p style="margin:16px 0;color:#57534e;">
      <strong style="color:#10B981;">{creados}</strong> nuevos · <strong style="color:#0066CC;">{actualizados}</strong> actualizados
    </p>
    <p style="color:#78716c;font-size:14px;">
      Total procesados: {len(rows_prospectos)} prospectos · {len(envios_map)} envíos · {len(estados_map)} estados
    </p>
    <a href="/admin/prospectos"
       style="display:inline-block;margin-top:24px;background:#1c1917;color:#fff;text-decoration:none;padding:12px 28px;border-radius:10px;font-weight:600;">
      Ver prospectos
    </a>
  </div>
</div>
</main></div></body></html>""")


# ════════════════════════════════════════════════════════════
# WHATSAPP OUTREACH — Enviar mensaje persuasivo via Meta API
# ════════════════════════════════════════════════════════════

WA_SENT_MARKER = "WA-SENT:"


def _wa_normalizar_telefono(tel: str) -> Optional[str]:
    """Convierte cualquier formato a 57XXXXXXXXXX listo para Meta (sin +)."""
    if not tel:
        return None
    digitos = _re.sub(r"\D", "", tel)
    if digitos.startswith("57") and len(digitos) > 10:
        digitos = digitos[2:]
    if len(digitos) != 10 or not digitos.startswith("3"):
        return None
    return f"57{digitos}"


def _wa_generar_cupon(nombre: str, pid: int) -> str:
    prefijo = "".join(c for c in (nombre or "").upper() if c.isalpha())[:3] or "LAP"
    h = _hashlib.md5(f"lapora-wa-{pid}-{nombre}".encode()).hexdigest().upper()
    return f"LAP{prefijo}{h[:5]}"


def _wa_construir_mensaje(nombre_doctor: str, nombre_negocio: str, cupon: str) -> str:
    return (
        f"Hola {nombre_doctor or 'Doctor'}, soy Michael de *Lapora Marketing Digital* 👋\n\n"
        f"Te escribo por aquí porque vi que respondiste al email sobre IA para {nombre_negocio}. ¡Excelente!\n\n"
        f"Para que veas rápido cómo funciona:\n"
        f"💰 *Ganar 2-3x más* con pacientes atraídos por IA\n"
        f"⏰ O *trabajar 70% menos* con un bot que agenda solo\n\n"
        f"Tu cupón único de *15% OFF* sigue activo:\n"
        f"🎁 `{cupon}`\n\n"
        f"Diagnóstico gratis (2 min): https://lapora.studio?cupon={cupon}\n\n"
        f"¿Te organizo una llamada de 15 min esta semana? Cuéntame qué día te queda mejor."
    )


async def _wa_enviar_via_meta(telefono: str, mensaje: str) -> tuple[bool, str]:
    """Envia via Meta Cloud API usando las credenciales del bot."""
    token = os.getenv("META_ACCESS_TOKEN", "")
    phone_id = os.getenv("META_PHONE_NUMBER_ID", "")
    if not token or not phone_id:
        return False, "Faltan META_ACCESS_TOKEN o META_PHONE_NUMBER_ID en Railway"
    url = f"https://graph.facebook.com/v21.0/{phone_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": telefono,
        "type": "text",
        "text": {"preview_url": True, "body": mensaje},
    }
    try:
        async with _httpx.AsyncClient(timeout=20.0) as client:
            r = await client.post(url, json=payload, headers=headers)
        if r.status_code == 200:
            return True, r.json().get("messages", [{}])[0].get("id", "OK")
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except Exception as e:
        return False, f"Error: {e}"


@router.get("/prospectos/whatsapp", response_class=HTMLResponse)
async def vista_whatsapp_outreach(user: str = Depends(verificar_credenciales)):
    """Muestra prospectos que respondieron y permite enviar WhatsApp."""
    from agent.memory import Prospecto

    async with async_session() as session:
        q = (
            select(Prospecto)
            .where(Prospecto.estado.in_(["respondido", "interesado"]))
            .where(Prospecto.email_verificado == "SI")
            .order_by(Prospecto.fecha_respuesta.desc().nulls_last())
        )
        prospectos = list((await session.execute(q)).scalars().all())

    # Clasificar
    pendientes_send: list = []
    ya_enviados: list = []
    sin_telefono: list = []

    for p in prospectos:
        tel_norm = _wa_normalizar_telefono(p.telefono or "")
        if not tel_norm:
            sin_telefono.append(p)
        elif WA_SENT_MARKER in (p.notas or ""):
            ya_enviados.append(p)
        else:
            pendientes_send.append(p)

    filas_html = ""
    for p in pendientes_send:
        tel_norm = _wa_normalizar_telefono(p.telefono or "") or ""
        cupon = p.cupon or _wa_generar_cupon(p.nombre_negocio or "", p.id)
        nombre = html.escape(p.nombre_negocio or "", quote=True)
        doctor = html.escape(p.nombre_doctor or "", quote=True)
        filas_html += f"""
        <tr>
          <td style="padding:14px 12px;font-weight:600;">{nombre}<div style="font-size:12px;color:#78716c;font-weight:400;">{doctor}</div></td>
          <td style="padding:14px 12px;font-family:monospace;font-size:13px;color:#57534e;">+{tel_norm}</td>
          <td style="padding:14px 12px;font-family:monospace;font-size:12px;font-weight:700;color:#FF3B30;">{cupon}</td>
          <td style="padding:14px 12px;">
            <form method="post" action="/admin/prospectos/whatsapp" style="margin:0;">
              <input type="hidden" name="prospecto_id" value="{p.id}">
              <button type="submit" name="action" value="enviar_uno"
                      style="background:#25D366;color:#fff;border:none;padding:8px 14px;border-radius:8px;font-size:12px;font-weight:600;cursor:pointer;">
                📲 Enviar
              </button>
            </form>
          </td>
        </tr>"""

    if not pendientes_send:
        filas_html = '<tr><td colspan="4" style="padding:60px;text-align:center;color:#78716c;font-style:italic;">No hay prospectos pendientes de WhatsApp 👌</td></tr>'

    bulk_button = ""
    if pendientes_send:
        bulk_button = f"""
        <form method="post" action="/admin/prospectos/whatsapp" style="margin:0;display:inline-block;"
              onsubmit="return confirm('¿Enviar WhatsApp a los {len(pendientes_send)} prospectos pendientes?');">
          <button type="submit" name="action" value="enviar_todos"
                  style="background:#25D366;color:#fff;border:none;padding:12px 22px;border-radius:10px;font-size:14px;font-weight:700;cursor:pointer;box-shadow:0 4px 12px rgba(37,211,102,0.3);">
            📲 Enviar a los {len(pendientes_send)} pendientes
          </button>
        </form>"""

    html_header = """<!DOCTYPE html>
<html lang="es"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>WhatsApp Outreach - Lapora CRM</title>"""
    html_body = f"""
    {CSS_BASE}
<body>
  <div class="app">
    {sidebar_html("prospectos")}
    <main class="main">
      <div style="padding:32px 40px;border-bottom:1px solid #e7e5e4;background:#fff;display:flex;align-items:center;justify-content:space-between;gap:24px;flex-wrap:wrap;">
        <div>
          <h1 style="margin:0;font-size:28px;font-weight:800;letter-spacing:-0.5px;color:#1c1917;">
            WhatsApp Outreach Manual
          </h1>
          <p style="margin:8px 0 0;color:#78716c;font-size:14px;">
            Envía mensaje persuasivo via SofIA (+57 322 878 3019) a prospectos que respondieron al email
          </p>
        </div>
        <div>{bulk_button}</div>
      </div>

      <div style="padding:24px 40px;display:grid;grid-template-columns:repeat(3,1fr);gap:16px;">
        <div style="background:#fff;border:1px solid #e7e5e4;border-radius:14px;padding:20px;">
          <div style="font-size:12px;color:#78716c;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Pendientes</div>
          <div style="font-size:32px;font-weight:800;color:#25D366;margin-top:6px;">{len(pendientes_send)}</div>
          <div style="font-size:12px;color:#78716c;margin-top:4px;">listos para enviar</div>
        </div>
        <div style="background:#fff;border:1px solid #e7e5e4;border-radius:14px;padding:20px;">
          <div style="font-size:12px;color:#78716c;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Ya enviados</div>
          <div style="font-size:32px;font-weight:800;color:#0066CC;margin-top:6px;">{len(ya_enviados)}</div>
          <div style="font-size:12px;color:#78716c;margin-top:4px;">no se duplica</div>
        </div>
        <div style="background:#fff;border:1px solid #e7e5e4;border-radius:14px;padding:20px;">
          <div style="font-size:12px;color:#78716c;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Sin celular</div>
          <div style="font-size:32px;font-weight:800;color:#78716C;margin-top:6px;">{len(sin_telefono)}</div>
          <div style="font-size:12px;color:#78716c;margin-top:4px;">teléfono fijo o inválido</div>
        </div>
      </div>

      <div style="padding:0 40px 40px;">
        <div style="background:#fff;border:1px solid #e7e5e4;border-radius:14px;overflow:hidden;">
          <table style="width:100%;border-collapse:collapse;">
            <thead><tr style="background:#1c1917;color:#fff;">
              <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Negocio</th>
              <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Teléfono</th>
              <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Cupón</th>
              <th style="padding:14px 12px;text-align:left;font-size:11px;text-transform:uppercase;letter-spacing:1px;font-weight:700;">Acción</th>
            </tr></thead>
            <tbody>{filas_html}</tbody>
          </table>
        </div>
      </div>
    </main>
  </div>
</body></html>"""
    return HTMLResponse(content=html_header + html_body)


@router.post("/prospectos/whatsapp", response_class=HTMLResponse)
async def procesar_whatsapp_outreach(
    user: str = Depends(verificar_credenciales),
    action: str = Form(...),
    prospecto_id: Optional[int] = Form(None),
):
    """Envia WhatsApp a uno o todos los pendientes."""
    from agent.memory import Prospecto

    async with async_session() as session:
        if action == "enviar_uno" and prospecto_id:
            q = select(Prospecto).where(Prospecto.id == prospecto_id)
            candidatos = list((await session.execute(q)).scalars().all())
        else:  # enviar_todos
            q = (
                select(Prospecto)
                .where(Prospecto.estado.in_(["respondido", "interesado"]))
                .where(Prospecto.email_verificado == "SI")
            )
            todos = list((await session.execute(q)).scalars().all())
            candidatos = [p for p in todos if _wa_normalizar_telefono(p.telefono or "")
                          and WA_SENT_MARKER not in (p.notas or "")]

    exitos = fallos = 0
    detalles: list[str] = []
    for p in candidatos:
        tel_norm = _wa_normalizar_telefono(p.telefono or "")
        if not tel_norm:
            fallos += 1
            detalles.append(f"{html.escape(p.nombre_negocio or '')}: sin celular válido")
            continue
        cupon = p.cupon or _wa_generar_cupon(p.nombre_negocio or "", p.id)
        msg = _wa_construir_mensaje(p.nombre_doctor or "Doctor", p.nombre_negocio or "", cupon)
        ok, info = await _wa_enviar_via_meta(tel_norm, msg)
        if ok:
            # Marcar como enviado
            async with async_session() as s2:
                pp = (await s2.execute(select(Prospecto).where(Prospecto.id == p.id))).scalar_one()
                marca = f"\n{WA_SENT_MARKER} {datetime.utcnow():%Y-%m-%d %H:%M} (msg_id={info[:20]})"
                pp.notas = (pp.notas or "") + marca
                pp.actualizado_en = datetime.utcnow()
                await s2.commit()
            exitos += 1
            detalles.append(f"✓ {html.escape(p.nombre_negocio or '')}")
        else:
            fallos += 1
            detalles.append(f"✗ {html.escape(p.nombre_negocio or '')}: {html.escape(info[:80])}")

    detalles_html = "<br>".join(detalles) if detalles else "Sin candidatos válidos"

    return HTMLResponse(f"""
<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Envío completo</title>{CSS_BASE}</head>
<body><div class="app">{sidebar_html("prospectos")}<main class="main">
<div style="padding:40px;max-width:760px;margin:auto;">
  <div style="background:#fff;border:1px solid #e7e5e4;border-radius:14px;padding:32px;">
    <h1 style="margin:0;font-size:24px;color:#1c1917;">📲 Envío WhatsApp</h1>
    <p style="margin:16px 0;color:#57534e;font-size:18px;">
      <strong style="color:#25D366;">✓ {exitos}</strong> enviados ·
      <strong style="color:#EF4444;">✗ {fallos}</strong> fallos
    </p>
    <div style="background:#fafaf9;border:1px solid #e7e5e4;border-radius:10px;padding:16px;font-size:13px;color:#57534e;max-height:400px;overflow-y:auto;line-height:1.8;">
      {detalles_html}
    </div>
    <div style="margin-top:24px;display:flex;gap:12px;">
      <a href="/admin/prospectos/whatsapp"
         style="background:#1c1917;color:#fff;text-decoration:none;padding:12px 24px;border-radius:10px;font-weight:600;">
        ← Volver
      </a>
      <a href="/admin/prospectos"
         style="background:transparent;color:#1c1917;border:1.5px solid #1c1917;text-decoration:none;padding:12px 24px;border-radius:10px;font-weight:600;">
        Ver prospectos
      </a>
    </div>
  </div>
</div>
</main></div></body></html>""")

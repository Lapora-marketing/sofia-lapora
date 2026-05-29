# -*- coding: utf-8 -*-
# agent/clinic_billing.py — Monetización con MercadoPago Preapproval (Colombia)
# Lapora Marketing Digital — Sprint Monetización v1

"""
Integración MercadoPago Preapproval para suscripciones recurrentes en Colombia.

Por qué MercadoPago (no Stripe):
- Stripe NO acepta empresas colombianas como merchants
- MercadoPago Preapproval es el estándar de SaaS recurrente en LATAM
- Acepta tarjeta crédito/débito + cuenta MercadoPago
- Comisión 3.49% + IVA
- Hosted checkout (sin widget JS complicado)

Configuración por env vars (en Railway):
- MERCADOPAGO_ACCESS_TOKEN     (APP_USR-... de developers.mercadopago.com)
- MERCADOPAGO_WEBHOOK_SECRET   (key generada en Tu cuenta → Webhooks)
- PUBLIC_BASE_URL              (para back_url, default Railway)

Flow:
1. Clínica en trial → click "Subir a Pro" en /clinic/app/billing
2. Backend crea Preapproval en MercadoPago → URL del checkout hosted
3. Cliente entra a MercadoPago.com, conecta tarjeta o cuenta MP
4. MercadoPago redirige a /clinic/billing/success
5. MercadoPago envía webhook (notificación) con el preapproval_id
6. Webhook activa estado_pago=activo + guarda preapproval_id
7. MercadoPago cobra automáticamente cada mes
8. Webhook authorized_payment.created por cada cobro mensual
"""

import os
import logging
from datetime import datetime
from typing import Optional
import httpx

logger = logging.getLogger("agentkit")


# ════════════════════════════════════════════════════════════
# CONFIGURACIÓN
# ════════════════════════════════════════════════════════════

PRECIOS_USD = {
    "pro":    100,
    "studio": 250,
}

# Conversión aproximada para mostrar al cliente.
# MercadoPago Colombia cobra en COP, así que convertimos.
USD_A_COP = 4000  # ajustable según tasa actual

PRECIOS_COP = {
    "pro":    PRECIOS_USD["pro"]    * USD_A_COP,    # 400.000 COP
    "studio": PRECIOS_USD["studio"] * USD_A_COP,    # 1.000.000 COP
}


def mp_access_token() -> Optional[str]:
    return os.getenv("MERCADOPAGO_ACCESS_TOKEN") or None


def mp_webhook_secret() -> Optional[str]:
    return os.getenv("MERCADOPAGO_WEBHOOK_SECRET") or None


def base_url_publica() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://sofia-lapora-production.up.railway.app").rstrip("/")


def mercadopago_disponible() -> bool:
    """True si MercadoPago está configurado."""
    return bool(mp_access_token())


# Alias para mantener retrocompatibilidad con imports antiguos
stripe_disponible = mercadopago_disponible


# ════════════════════════════════════════════════════════════
# HELPER GENÉRICO PARA MERCADOPAGO API
# ════════════════════════════════════════════════════════════

async def _mp_request(
    method: str,
    path: str,
    json_data: Optional[dict] = None,
) -> tuple[bool, dict, str]:
    """Request a MercadoPago API. Retorna (exito, response, error_msg)."""
    token = mp_access_token()
    if not token:
        return False, {}, "MERCADOPAGO_ACCESS_TOKEN no configurado"

    url = f"https://api.mercadopago.com{path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            if method.upper() == "POST":
                r = await client.post(url, json=json_data or {}, headers=headers)
            elif method.upper() == "PUT":
                r = await client.put(url, json=json_data or {}, headers=headers)
            else:
                r = await client.get(url, headers=headers)
        if 200 <= r.status_code < 300:
            return True, r.json(), ""
        return False, {}, f"MercadoPago {r.status_code}: {r.text[:300]}"
    except Exception as e:
        return False, {}, str(e)[:300]


# ════════════════════════════════════════════════════════════
# PREAPPROVAL — Crear suscripción recurrente
# ════════════════════════════════════════════════════════════

async def crear_checkout_session(clinica, plan: str) -> tuple[bool, str, str]:
    """Crea un Preapproval (suscripción) en MercadoPago.

    Retorna URL del init_point para redirect al cliente.

    Args:
        clinica: instancia de Clinica
        plan: "pro" | "studio"

    Returns:
        (exito, init_point_url, error_msg)
    """
    plan = (plan or "").lower()
    if plan not in ("pro", "studio"):
        return False, "", "Plan inválido"

    if not mp_access_token():
        return False, "", "MercadoPago no configurado (falta MERCADOPAGO_ACCESS_TOKEN)"

    base = base_url_publica()
    monto_cop = PRECIOS_COP[plan]

    # Pre-llenar email del owner si lo tenemos
    payer_email = ""
    from agent.memory import async_session
    from agent.clinic_models import UsuarioClinic
    from sqlalchemy import select
    async with async_session() as session:
        owner = (await session.execute(
            select(UsuarioClinic)
            .where(UsuarioClinic.clinica_id == clinica.id)
            .where(UsuarioClinic.rol == "owner")
            .limit(1)
        )).scalar_one_or_none()
        if owner:
            payer_email = owner.email

    body = {
        "reason": f"Lapora Clinic {plan.capitalize()} - Suscripción mensual",
        "external_reference": f"clinica_{clinica.id}_{plan}",
        "payer_email": payer_email,
        "back_url": f"{base}/clinic/billing/success?clinica={clinica.id}&plan={plan}",
        "auto_recurring": {
            "frequency": 1,
            "frequency_type": "months",
            "transaction_amount": float(monto_cop),
            "currency_id": "COP",
        },
        "status": "pending",
    }

    exito, data, err = await _mp_request("POST", "/preapproval", body)
    if not exito:
        logger.error(f"[billing] preapproval creation falló: {err}")
        return False, "", err

    # MercadoPago devuelve init_point (URL del checkout hosted)
    init_point = data.get("init_point", "")
    preapproval_id = data.get("id", "")

    if not init_point:
        return False, "", "MercadoPago no devolvió init_point"

    # Guardamos el preapproval_id provisional en BD para correlación
    async with async_session() as session:
        from agent.clinic_models import Clinica as _Clinica
        c = (await session.execute(
            select(_Clinica).where(_Clinica.id == clinica.id)
        )).scalar_one()
        c.stripe_subscription_id = preapproval_id  # reutilizamos el campo (nombre legacy)
        await session.commit()

    return True, init_point, ""


# ════════════════════════════════════════════════════════════
# PORTAL CLIENTE — MercadoPago no tiene un "Customer Portal" como Stripe
# pero podemos redirigir al cliente a su cuenta MP para gestionar
# ════════════════════════════════════════════════════════════

async def crear_portal_session(clinica) -> tuple[bool, str, str]:
    """MercadoPago no tiene portal hosted como Stripe.

    En su lugar:
    - Si tiene preapproval activo → link directo a MP para ver/cancelar
    - El cliente gestiona desde su cuenta MercadoPago

    Returns: (exito, url, error)
    """
    sub_id = clinica.stripe_subscription_id  # preapproval_id
    if not sub_id:
        return False, "", "No tienes suscripción activa para gestionar"

    # MercadoPago URL: el usuario logueado en su cuenta MP puede ver
    # https://www.mercadopago.com.co/subscriptions
    url = "https://www.mercadopago.com.co/subscriptions/list"
    return True, url, ""


async def cancelar_suscripcion(clinica) -> tuple[bool, str]:
    """Cancela la suscripción MercadoPago vía API.

    Returns: (exito, error_msg)
    """
    sub_id = clinica.stripe_subscription_id
    if not sub_id:
        return False, "Sin preapproval_id"

    exito, data, err = await _mp_request(
        "PUT", f"/preapproval/{sub_id}", {"status": "cancelled"}
    )
    if not exito:
        return False, err

    # Update local
    from agent.memory import async_session
    from agent.clinic_models import Clinica as _Clinica
    from sqlalchemy import select
    async with async_session() as session:
        c = (await session.execute(
            select(_Clinica).where(_Clinica.id == clinica.id)
        )).scalar_one()
        c.estado_pago = "cancelado"
        await session.commit()

    return True, ""


# ════════════════════════════════════════════════════════════
# WEBHOOK — recibir notificaciones de MercadoPago
# ════════════════════════════════════════════════════════════

def verificar_webhook_signature(payload: bytes, signature_header: str, request_id: str = "") -> bool:
    """Verifica firma del webhook de MercadoPago.

    MercadoPago envía:
    - Header `x-signature`: ts=1234567890,v1=hash
    - Header `x-request-id`: id del evento

    El hash es HMAC-SHA256 sobre: id=<event_id>;request-id=<req_id>;ts=<ts>;
    usando MERCADOPAGO_WEBHOOK_SECRET como clave.
    """
    import hmac
    import hashlib
    import time
    import json as _json

    secret = mp_webhook_secret()
    if not secret or not signature_header:
        # Si no hay secret configurado, aceptamos (modo dev) pero logueamos
        if not secret:
            logger.warning("[billing webhook] MERCADOPAGO_WEBHOOK_SECRET no configurado, omitiendo verificación")
            return True
        return False

    try:
        partes = dict(p.strip().split("=", 1) for p in signature_header.split(","))
        ts = partes.get("ts", "")
        v1 = partes.get("v1", "")
        if not ts or not v1:
            return False

        # Replay protection (max 5 min)
        if abs(time.time() - int(ts)) > 300:
            logger.warning("[billing webhook] timestamp fuera de ventana 5min")
            return False

        # Extraer event_id del payload
        try:
            body = _json.loads(payload)
        except Exception:
            return False
        event_id = str(body.get("data", {}).get("id", ""))

        # Manifest a firmar
        manifest = f"id:{event_id};request-id:{request_id};ts:{ts};"
        esperada = hmac.new(
            secret.encode("utf-8"),
            manifest.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(esperada, v1)
    except Exception as e:
        logger.error(f"[billing webhook] error verificando firma: {e}")
        return False


async def procesar_webhook(notification: dict) -> dict:
    """Procesa una notificación de MercadoPago ya parseada.

    Tipos importantes:
    - `subscription_preapproval`: estado del preapproval cambió (auth, paused, cancelled)
    - `subscription_authorized_payment`: cobro mensual exitoso
    - `payment`: pago individual (para pago único, no suscripción)
    """
    from agent.memory import async_session
    from agent.clinic_models import Clinica
    from sqlalchemy import select

    tipo = notification.get("type", "")
    action = notification.get("action", "")
    data_id = notification.get("data", {}).get("id", "")

    logger.info(f"[billing webhook MP] type={tipo} action={action} id={data_id}")

    # === Preapproval (suscripción) update ===
    if tipo == "subscription_preapproval" and data_id:
        # Consultar detalles del preapproval
        exito, preapp, err = await _mp_request("GET", f"/preapproval/{data_id}")
        if not exito:
            return {"ok": False, "razon": f"No se pudo consultar preapproval: {err}"}

        # external_reference tiene formato "clinica_{id}_{plan}"
        ext_ref = preapp.get("external_reference", "")
        partes = ext_ref.split("_")
        if len(partes) != 3 or partes[0] != "clinica":
            return {"ok": False, "razon": f"external_reference inválido: {ext_ref}"}

        try:
            clinica_id = int(partes[1])
        except ValueError:
            return {"ok": False, "razon": "clinica_id inválido"}
        plan = partes[2]

        status = preapp.get("status", "")  # authorized | paused | cancelled | pending

        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.id == clinica_id)
            )).scalar_one_or_none()
            if not c:
                return {"ok": False, "razon": "Clínica no encontrada"}

            c.stripe_subscription_id = data_id  # preapproval id

            if status == "authorized":
                # Suscripción autorizada → activar plan
                c.plan = plan if plan in ("pro", "studio") else "pro"
                c.monto_mensual_usd = PRECIOS_USD.get(c.plan, 100)
                c.estado_pago = "activo"
                c.congelada = False
                c.razon_freeze = ""
                c.ultimo_pago_en = datetime.utcnow()
                # MercadoPago retorna next_payment_date
                next_date = preapp.get("next_payment_date")
                if next_date:
                    try:
                        # Format: 2026-06-29T10:00:00.000-05:00
                        c.proximo_cobro_en = datetime.fromisoformat(
                            next_date.replace("Z", "+00:00")
                        ).replace(tzinfo=None)
                    except Exception:
                        pass
            elif status == "paused":
                c.estado_pago = "vencido"
            elif status == "cancelled":
                c.estado_pago = "cancelado"
                c.congelada = True
                c.razon_freeze = "Suscripción cancelada en MercadoPago"
                c.fecha_suspension = datetime.utcnow()
                c.motivo_suspension = "Suscripción cancelada"

            await session.commit()

        return {"ok": True, "accion": f"preapproval_{status}", "clinica_id": clinica_id}

    # === Authorized payment (cobro mensual exitoso) ===
    if tipo == "subscription_authorized_payment" and data_id:
        # Consultar detalles
        exito, payment, err = await _mp_request(
            "GET", f"/authorized_payments/{data_id}"
        )
        if not exito:
            return {"ok": False, "razon": err}

        preapproval_id = payment.get("preapproval_id", "")
        status = payment.get("status", "")  # processed | scheduled | rejected

        if not preapproval_id:
            return {"ok": False, "razon": "Sin preapproval_id en payment"}

        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.stripe_subscription_id == preapproval_id)
            )).scalar_one_or_none()
            if not c:
                return {"ok": False, "razon": "Clínica no encontrada por preapproval"}

            if status == "processed":
                c.estado_pago = "activo"
                c.congelada = False
                c.razon_freeze = ""
                c.ultimo_pago_en = datetime.utcnow()
                # Sumar 30 días para próximo
                from datetime import timedelta as _td
                c.proximo_cobro_en = datetime.utcnow() + _td(days=30)
            elif status == "rejected":
                c.estado_pago = "vencido"
                # Gracia: MercadoPago reintenta. NO congelamos aún.

            await session.commit()

        return {"ok": True, "accion": f"payment_{status}", "clinica_id": c.id}

    return {"ok": True, "accion": "ignorado", "tipo": tipo}


# ════════════════════════════════════════════════════════════
# WORKER — auto-freeze de trials expirados
# ════════════════════════════════════════════════════════════

async def auto_freeze_trials_expirados() -> int:
    """Congela clínicas cuyo trial expiró sin suscribirse."""
    from agent.memory import async_session
    from agent.clinic_models import Clinica
    from sqlalchemy import select

    ahora = datetime.utcnow()
    congeladas = 0

    async with async_session() as session:
        result = await session.execute(
            select(Clinica)
            .where(Clinica.estado_pago == "trial")
            .where(Clinica.trial_termina_en.isnot(None))
            .where(Clinica.trial_termina_en < ahora)
            .where(Clinica.congelada == False)  # noqa: E712
        )
        for c in result.scalars().all():
            c.congelada = True
            c.estado_pago = "vencido"
            c.fecha_suspension = ahora
            c.razon_freeze = "Prueba de 14 días expirada sin suscripción"
            c.motivo_suspension = "Trial expirado"
            congeladas += 1
        if congeladas:
            await session.commit()
            logger.info(f"[billing] auto-freeze: {congeladas} clínicas con trial expirado")

    return congeladas


# ════════════════════════════════════════════════════════════
# MÉTRICAS — MRR real
# ════════════════════════════════════════════════════════════

async def mrr_real() -> dict:
    """MRR real basado en suscripciones activas."""
    from agent.memory import async_session
    from agent.clinic_models import Clinica
    from sqlalchemy import select, func

    async with async_session() as session:
        activas = list((await session.execute(
            select(Clinica)
            .where(Clinica.estado_pago == "activo")
            .where(Clinica.congelada == False)  # noqa: E712
        )).scalars().all())

        mrr_usd = sum(c.monto_mensual_usd or 0 for c in activas)
        mrr_cop_estimado = mrr_usd * USD_A_COP

        trials = list((await session.execute(
            select(Clinica)
            .where(Clinica.estado_pago == "trial")
            .where(Clinica.congelada == False)  # noqa: E712
        )).scalars().all())
        pipeline_usd = sum(PRECIOS_USD.get(c.plan, 100) for c in trials)

        vencidos = (await session.execute(
            select(func.count(Clinica.id))
            .where(Clinica.estado_pago == "vencido")
            .where(Clinica.congelada == False)  # noqa: E712
        )).scalar() or 0

        from datetime import timedelta as _td
        hace_30 = datetime.utcnow() - _td(days=30)
        churn_30d = (await session.execute(
            select(func.count(Clinica.id))
            .where(Clinica.estado_pago == "cancelado")
            .where(Clinica.fecha_suspension >= hace_30)
        )).scalar() or 0

    return {
        "mrr_usd": mrr_usd,
        "mrr_cop_estimado": mrr_cop_estimado,
        "clientes_activos": len(activas),
        "trials_pipeline_usd": pipeline_usd,
        "trials_count": len(trials),
        "vencidos_en_gracia": int(vencidos),
        "churn_30d": int(churn_30d),
    }

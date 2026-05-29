# -*- coding: utf-8 -*-
# agent/clinic_billing.py — Monetización con Stripe
# Lapora Marketing Digital — Sprint Monetización v1

"""
Integración Stripe para suscripciones recurrentes.

Funcionalidades:
1. checkout_session_url(clinica, plan) → URL del Stripe Checkout
2. portal_url(clinica) → URL del Stripe Customer Portal (cambiar tarjeta, cancelar)
3. webhook_event(payload, sig) → procesa eventos Stripe (paid, failed, canceled)
4. sincronizar_desde_stripe(clinica) → fuerza sync del estado

Configuración por env vars (en Railway):
- STRIPE_SECRET_KEY            (sk_live_... o sk_test_...)
- STRIPE_WEBHOOK_SECRET        (whsec_... de Dashboard → Webhooks)
- STRIPE_PRICE_PRO             (price_... del plan Pro $100/mes)
- STRIPE_PRICE_STUDIO          (price_... del plan Studio $250/mes)
- PUBLIC_BASE_URL              (para success/cancel URLs, default Railway)

Flow típico:
1. Clínica en trial → click "Subir a Pro" en /clinic/app/billing
2. Backend crea Stripe Checkout Session → redirect a Stripe-hosted page
3. Cliente pega tarjeta y paga
4. Stripe redirige a /clinic/billing/success?clinica=...
5. Stripe envía webhook checkout.session.completed
6. Webhook actualiza clinica.estado_pago=activo + stripe_subscription_id
7. Renovaciones mensuales: webhook invoice.payment_succeeded
8. Fallo de pago: webhook invoice.payment_failed → congelar
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


def stripe_secret_key() -> Optional[str]:
    return os.getenv("STRIPE_SECRET_KEY") or None


def stripe_webhook_secret() -> Optional[str]:
    return os.getenv("STRIPE_WEBHOOK_SECRET") or None


def stripe_price_id(plan: str) -> Optional[str]:
    """Devuelve el price_id de Stripe según el plan."""
    plan = (plan or "").lower()
    if plan == "pro":
        return os.getenv("STRIPE_PRICE_PRO") or None
    if plan == "studio":
        return os.getenv("STRIPE_PRICE_STUDIO") or None
    return None


def base_url_publica() -> str:
    return os.getenv("PUBLIC_BASE_URL", "https://sofia-lapora-production.up.railway.app").rstrip("/")


def stripe_disponible() -> bool:
    """True si las credenciales mínimas de Stripe están configuradas."""
    return bool(stripe_secret_key())


# ════════════════════════════════════════════════════════════
# HELPER GENÉRICO PARA STRIPE API
# ════════════════════════════════════════════════════════════

async def _stripe_request(
    method: str,
    path: str,
    form_data: Optional[dict] = None,
) -> tuple[bool, dict, str]:
    """Hace request a la API de Stripe. Retorna (exito, response_dict, error_msg).

    Stripe API usa form-urlencoded para POST.
    """
    key = stripe_secret_key()
    if not key:
        return False, {}, "STRIPE_SECRET_KEY no configurada"

    url = f"https://api.stripe.com/v1{path}"
    headers = {"Authorization": f"Bearer {key}"}

    try:
        async with httpx.AsyncClient(timeout=20.0) as client:
            if method.upper() == "POST":
                r = await client.post(url, data=form_data or {}, headers=headers)
            else:
                r = await client.get(url, params=form_data or {}, headers=headers)
        if 200 <= r.status_code < 300:
            return True, r.json(), ""
        return False, {}, f"Stripe {r.status_code}: {r.text[:300]}"
    except Exception as e:
        return False, {}, str(e)[:300]


# ════════════════════════════════════════════════════════════
# CHECKOUT SESSION — crear URL para que el cliente pague
# ════════════════════════════════════════════════════════════

async def crear_checkout_session(clinica, plan: str) -> tuple[bool, str, str]:
    """Crea una Stripe Checkout Session.

    Args:
        clinica: instancia de Clinica
        plan: "pro" | "studio"

    Returns:
        (exito, checkout_url, error_msg)
    """
    plan = (plan or "").lower()
    if plan not in ("pro", "studio"):
        return False, "", "Plan inválido"

    price = stripe_price_id(plan)
    if not price:
        return False, "", f"STRIPE_PRICE_{plan.upper()} no configurado en env vars"

    base = base_url_publica()
    success_url = f"{base}/clinic/billing/success?clinica={clinica.id}&plan={plan}"
    cancel_url = f"{base}/clinic/app/billing?canceled=1"

    # Pasamos clinica.id en metadata para identificar al recibir webhook
    form = {
        "mode": "subscription",
        "payment_method_types[0]": "card",
        "line_items[0][price]": price,
        "line_items[0][quantity]": "1",
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(clinica.id),
        "subscription_data[metadata][clinica_id]": str(clinica.id),
        "subscription_data[metadata][plan]": plan,
        "allow_promotion_codes": "true",
    }
    # Si ya tenemos stripe_customer_id reutilizarlo (mantiene historial)
    if clinica.stripe_customer_id:
        form["customer"] = clinica.stripe_customer_id
    else:
        # Pasar email del primer usuario para pre-llenar
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
            form["customer_email"] = owner.email

    exito, data, err = await _stripe_request("POST", "/checkout/sessions", form)
    if not exito:
        return False, "", err

    return True, data.get("url", ""), ""


# ════════════════════════════════════════════════════════════
# CUSTOMER PORTAL — cliente cambia tarjeta, cancela, ve facturas
# ════════════════════════════════════════════════════════════

async def crear_portal_session(clinica) -> tuple[bool, str, str]:
    """Crea Stripe Customer Portal session."""
    if not clinica.stripe_customer_id:
        return False, "", "Sin Stripe customer ID — primero hay que suscribirse"

    base = base_url_publica()
    form = {
        "customer": clinica.stripe_customer_id,
        "return_url": f"{base}/clinic/app/billing",
    }
    exito, data, err = await _stripe_request("POST", "/billing_portal/sessions", form)
    if not exito:
        return False, "", err
    return True, data.get("url", ""), ""


# ════════════════════════════════════════════════════════════
# WEBHOOK — procesar eventos de Stripe
# ════════════════════════════════════════════════════════════

def verificar_webhook_signature(payload: bytes, signature_header: str) -> bool:
    """Verifica que el webhook viene de Stripe (HMAC SHA256).

    Stripe firma cada webhook con el signing secret de Dashboard → Webhooks.
    """
    import hmac
    import hashlib
    import time

    secret = stripe_webhook_secret()
    if not secret or not signature_header:
        return False

    try:
        # Header format: "t=1234567890,v1=abc123,v0=..."
        partes = dict(p.split("=", 1) for p in signature_header.split(","))
        timestamp = partes.get("t", "")
        sig_v1 = partes.get("v1", "")
        if not timestamp or not sig_v1:
            return False

        # Verificar que no sea replay (max 5 min)
        if abs(time.time() - int(timestamp)) > 300:
            return False

        # Computar HMAC
        firmado = f"{timestamp}.{payload.decode('utf-8', errors='ignore')}"
        esperada = hmac.new(
            secret.encode("utf-8"),
            firmado.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(esperada, sig_v1)
    except Exception as e:
        logger.error(f"[billing] error verificando webhook: {e}")
        return False


async def procesar_webhook(event: dict) -> dict:
    """Procesa un evento de Stripe ya parseado y verificado.

    Eventos clave:
    - checkout.session.completed: alguien acaba de suscribirse exitosamente
    - invoice.payment_succeeded: renovación mensual ok
    - invoice.payment_failed: cobro falló
    - customer.subscription.deleted: canceló
    - customer.subscription.updated: cambio de plan, pausa, etc.
    """
    from agent.memory import async_session
    from agent.clinic_models import Clinica
    from sqlalchemy import select

    tipo = event.get("type", "")
    obj = event.get("data", {}).get("object", {})
    logger.info(f"[billing webhook] {tipo}")

    async def _por_clinica_id(clinica_id: int):
        async with async_session() as session:
            return (await session.execute(
                select(Clinica).where(Clinica.id == clinica_id)
            )).scalar_one_or_none()

    async def _por_subscription_id(sub_id: str):
        async with async_session() as session:
            return (await session.execute(
                select(Clinica).where(Clinica.stripe_subscription_id == sub_id)
            )).scalar_one_or_none()

    async def _por_customer_id(cust_id: str):
        async with async_session() as session:
            return (await session.execute(
                select(Clinica).where(Clinica.stripe_customer_id == cust_id)
            )).scalar_one_or_none()

    # === checkout.session.completed ===
    if tipo == "checkout.session.completed":
        clinica_id_str = obj.get("client_reference_id") or ""
        if not clinica_id_str.isdigit():
            return {"ok": False, "razon": "client_reference_id inválido"}
        clinica = await _por_clinica_id(int(clinica_id_str))
        if not clinica:
            return {"ok": False, "razon": "Clínica no encontrada"}

        sub_id = obj.get("subscription", "")
        cust_id = obj.get("customer", "")
        metadata = obj.get("metadata", {}) or {}
        plan = (metadata.get("plan") or "pro").lower()

        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.id == clinica.id)
            )).scalar_one()
            c.stripe_subscription_id = sub_id
            c.stripe_customer_id = cust_id
            c.plan = plan if plan in ("pro", "studio") else "pro"
            c.monto_mensual_usd = PRECIOS_USD.get(c.plan, 100)
            c.estado_pago = "activo"
            c.congelada = False
            c.razon_freeze = ""
            c.ultimo_pago_en = datetime.utcnow()
            c.actualizado_en = datetime.utcnow()
            await session.commit()

        logger.info(
            f"[billing] checkout completed clinica={clinica.id} "
            f"plan={plan} sub={sub_id[:20]}..."
        )
        return {"ok": True, "accion": "subscribed", "clinica_id": clinica.id}

    # === invoice.payment_succeeded (renovación mensual) ===
    if tipo == "invoice.payment_succeeded":
        sub_id = obj.get("subscription", "")
        clinica = await _por_subscription_id(sub_id) if sub_id else None
        if not clinica:
            return {"ok": False, "razon": f"Clínica no encontrada para sub {sub_id}"}

        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.id == clinica.id)
            )).scalar_one()
            c.estado_pago = "activo"
            c.congelada = False
            c.razon_freeze = ""
            c.ultimo_pago_en = datetime.utcnow()
            # Próximo cobro: en ~30 días
            from datetime import timedelta as _td
            period_end = obj.get("lines", {}).get("data", [{}])[0].get("period", {}).get("end")
            if period_end:
                c.proximo_cobro_en = datetime.fromtimestamp(int(period_end))
            else:
                c.proximo_cobro_en = datetime.utcnow() + _td(days=30)
            await session.commit()
        return {"ok": True, "accion": "renewed", "clinica_id": clinica.id}

    # === invoice.payment_failed ===
    if tipo == "invoice.payment_failed":
        sub_id = obj.get("subscription", "")
        clinica = await _por_subscription_id(sub_id) if sub_id else None
        if not clinica:
            return {"ok": False, "razon": f"Clínica no encontrada para sub {sub_id}"}

        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.id == clinica.id)
            )).scalar_one()
            c.estado_pago = "vencido"
            # Damos gracia: NO congelar inmediatamente. Stripe reintenta 3 días.
            # Si después de N intentos sigue fallando → subscription.deleted lo congela
            await session.commit()
        return {"ok": True, "accion": "payment_failed_grace", "clinica_id": clinica.id}

    # === customer.subscription.deleted ===
    if tipo == "customer.subscription.deleted":
        sub_id = obj.get("id", "")
        clinica = await _por_subscription_id(sub_id) if sub_id else None
        if not clinica:
            return {"ok": False, "razon": f"Clínica no encontrada para sub {sub_id}"}

        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.id == clinica.id)
            )).scalar_one()
            c.estado_pago = "cancelado"
            c.congelada = True
            c.fecha_suspension = datetime.utcnow()
            c.razon_freeze = "Suscripción cancelada o cobros fallidos repetidos"
            c.motivo_suspension = "Suscripción cancelada"
            await session.commit()
        return {"ok": True, "accion": "frozen", "clinica_id": clinica.id}

    # === customer.subscription.updated ===
    if tipo == "customer.subscription.updated":
        sub_id = obj.get("id", "")
        clinica = await _por_subscription_id(sub_id) if sub_id else None
        if not clinica:
            return {"ok": False, "razon": "Clínica no encontrada"}

        status = obj.get("status", "")  # active | past_due | canceled | trialing | unpaid

        async with async_session() as session:
            c = (await session.execute(
                select(Clinica).where(Clinica.id == clinica.id)
            )).scalar_one()
            if status == "active":
                c.estado_pago = "activo"
                c.congelada = False
            elif status in ("past_due", "unpaid"):
                c.estado_pago = "vencido"
            elif status == "canceled":
                c.estado_pago = "cancelado"
                c.congelada = True
                c.razon_freeze = "Suscripción cancelada"
            await session.commit()
        return {"ok": True, "accion": f"status_{status}", "clinica_id": clinica.id}

    return {"ok": True, "accion": "ignorado", "tipo": tipo}


# ════════════════════════════════════════════════════════════
# WORKER — auto-freeze de trials expirados y cuentas vencidas
# ════════════════════════════════════════════════════════════

async def auto_freeze_trials_expirados() -> int:
    """Congela clínicas cuyo trial expiró sin que se hayan suscrito.

    Llamado periódicamente desde voice_workers (o un cron dedicado).
    Returns: cantidad de clínicas congeladas.
    """
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
# MÉTRICAS — MRR real para super admin
# ════════════════════════════════════════════════════════════

async def mrr_real() -> dict:
    """Calcula MRR real basado en suscripciones activas."""
    from agent.memory import async_session
    from agent.clinic_models import Clinica
    from sqlalchemy import select, func

    async with async_session() as session:
        # MRR real: solo clinicas con estado_pago=activo
        activas = list((await session.execute(
            select(Clinica)
            .where(Clinica.estado_pago == "activo")
            .where(Clinica.congelada == False)  # noqa: E712
        )).scalars().all())

        mrr_usd = sum(c.monto_mensual_usd or 0 for c in activas)
        mrr_cop_estimado = mrr_usd * 4000  # estimado COP

        # Pipeline: trials activos (potencial MRR si convierten)
        trials = list((await session.execute(
            select(Clinica)
            .where(Clinica.estado_pago == "trial")
            .where(Clinica.congelada == False)  # noqa: E712
        )).scalars().all())
        pipeline_usd = sum(PRECIOS_USD.get(c.plan, 100) for c in trials)

        # Vencidos (cobro falló, en gracia)
        vencidos = (await session.execute(
            select(func.count(Clinica.id))
            .where(Clinica.estado_pago == "vencido")
            .where(Clinica.congelada == False)  # noqa: E712
        )).scalar() or 0

        # Churn 30 días: cancelados en último mes
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

# 🏥 Lapora Clinic — Guía de despliegue y operación

> **SaaS multi-tenant para clínicas y consultorios médicos.**
> WhatsApp + Instagram + Pacientes + IA en una sola plataforma.

---

## 🚀 Estado del producto

| Módulo | Estado | Notas |
|--------|--------|-------|
| 📝 Onboarding (registro + login) | ✅ Producción | Cookie de sesión 30 días |
| 📊 Dashboard con vista "Hoy" | ✅ Producción | KPIs reales + tareas del día |
| 👥 CRUD Pacientes | ✅ Producción | Con búsqueda, filtros, timeline |
| 📥 Inbox unificado | ✅ Producción | WhatsApp/IG/Email tipo Slack |
| 📞 Bitácora llamadas | ✅ Producción | Resultados coloreados |
| 📝 Plantillas | ✅ Producción | 7 categorías + variables |
| ⚙️ Configuración + integraciones | ✅ Producción | WA, IG, Sheets, branding |
| 🪝 Webhook WhatsApp | ✅ Producción | Receptor de mensajes por clínica |
| 📊 Sync Google Sheets | ✅ Producción | Upsert por tel/email |
| 📥 Import CSV pacientes | ✅ Producción | Upsert automático |
| 📤 Export CSV pacientes | ✅ Producción | Descarga directa |
| 🔍 Búsqueda global | ✅ Producción | En sidebar |
| 🎁 Datos demo | ✅ Producción | Botón "cargar ejemplo" |
| 🚀 Landing público | ✅ Producción | Con pricing |
| 🤖 IA SofIA per-tenant | ⏳ Pendiente | Reusar SofIA del CRM |
| 🔑 Recuperar contraseña | ⏳ Pendiente | Día 31 |
| 📨 Emails transaccionales | ⏳ Pendiente | Día 31 |

---

## 📁 Estructura de archivos

```
whatsapp-agentkit/
├── agent/
│   ├── main.py              ← App FastAPI principal (registra routers)
│   ├── memory.py            ← Modelos SofIA (Mensaje, Contacto, Prospecto)
│   ├── clinic_models.py     ← Modelos Lapora Clinic (multi-tenant)
│   ├── clinic.py            ← Router /clinic/* con TODA la app
│   ├── dashboard.py         ← CRM interno de Lapora (/admin/*)
│   ├── brain.py             ← Bot SofIA (IA Anthropic Claude)
│   └── providers/           ← WhatsApp providers (Meta, Twilio)
├── data/prospectos/         ← (gitignored) CSVs de outreach
└── config/                  ← prompts.yaml + business.yaml
```

---

## 🌐 URLs en producción

**Base:** `https://sofia-lapora-production.up.railway.app`

### Públicas (sin login)
| URL | Función |
|-----|---------|
| `/clinic/landing` | Página de marketing con pricing |
| `/clinic/registro` | Onboarding de nueva clínica |
| `/clinic/login` | Login |

### Privadas (con cookie de sesión)
| URL | Función |
|-----|---------|
| `/clinic/app/` | Dashboard con vista "Hoy" |
| `/clinic/app/inbox` | Inbox unificado WhatsApp + IG + Email |
| `/clinic/app/pacientes` | CRM completo de pacientes |
| `/clinic/app/pacientes/{id}` | Ficha del paciente con timeline |
| `/clinic/app/pacientes/importar` | Importar CSV |
| `/clinic/app/pacientes/exportar` | Exportar CSV |
| `/clinic/app/llamadas` | Bitácora |
| `/clinic/app/plantillas` | Respuestas rápidas |
| `/clinic/app/buscar?q=...` | Búsqueda global |
| `/clinic/app/configuracion` | Integraciones WA/IG/Sheets/branding |
| `/clinic/app/configuracion/sync-sheets` (POST) | Sincronizar pacientes desde Sheets |

### Webhooks (públicos, por clínica)
| URL | Función |
|-----|---------|
| `GET /clinic/webhook/whatsapp/{slug}` | Verificación Meta (hub.challenge) |
| `POST /clinic/webhook/whatsapp/{slug}` | Recibe mensajes de WhatsApp |

### Health
| URL | Función |
|-----|---------|
| `/clinic/health` | Status del módulo (DB ok / degraded) |

---

## 🛠️ Variables de entorno necesarias

En Railway → Variables del servicio:

```env
# Base de datos (Railway PostgreSQL)
DATABASE_URL=postgresql://...

# Para el bot SofIA del CRM interno (opcional para Lapora Clinic)
ANTHROPIC_API_KEY=sk-ant-...
META_ACCESS_TOKEN=EAAm...
META_PHONE_NUMBER_ID=1109673485567186
META_VERIFY_TOKEN=lapora-sofia-2026
WHATSAPP_PROVIDER=meta

# Servidor
PORT=8000
ENVIRONMENT=production
```

> **Nota:** Cada clínica configura sus PROPIAS credenciales de WhatsApp/IG desde `/clinic/app/configuracion`. Las variables de entorno globales son SOLO para el bot SofIA de Lapora.

---

## 📋 Manual de uso — Para clínicas (clientes finales)

### 1️⃣ Cómo arranca una clínica nueva

1. Va a `/clinic/landing` y hace click "Probar gratis"
2. Llena formulario: nombre de clínica, especialidad, ciudad, email, contraseña
3. Cuenta creada → sesión activa 30 días
4. Aterriza en dashboard con guía de 3 pasos + botón "Cargar datos demo"

### 2️⃣ Conectar WhatsApp Business (Cloud API)

1. Va a Configuración
2. Llena Phone Number ID + Access Token (los obtiene en developers.facebook.com)
3. En Meta Developers: configurar webhook con esta URL:
   ```
   https://sofia-lapora-production.up.railway.app/clinic/webhook/whatsapp/{su-slug}
   ```
   donde `{su-slug}` es el slug autogenerado (ej: `clinica-tolima`)
4. Verify Token: usar el Phone Number ID
5. Suscribirse a `messages`

### 3️⃣ Importar pacientes existentes

**Opción A — Google Sheets (automático):**
1. Publicar la hoja en web como CSV (Archivo > Compartir > Publicar)
2. Configuración → pegar URL/ID de Sheets
3. Click "Sincronizar ahora"

**Opción B — CSV manual:**
1. Pacientes → "↑ Importar"
2. Subir archivo .csv con columnas: `nombre, telefono, email, tratamiento, notas`

### 4️⃣ Día a día

- **Mañana**: revisar Dashboard → vista "Hoy"
  - 📅 Citas hoy
  - ⚠️ Mensajes sin responder de ayer
  - 📞 Llamadas pendientes
  - 🆕 Nuevos pacientes esta semana
- **Durante**: usar Inbox para responder mensajes
- **Tarde**: registrar llamadas hechas + crear plantillas para preguntas repetidas

---

## 🔧 Operación técnica — Para admin de Lapora

### Despliegue en Railway

```bash
# Push a main → autodeploy en Railway
git add .
git commit -m "feat: ..."
git push origin main
```

Railway detecta el push y redeploya automáticamente. Las tablas nuevas se crean al arrancar (en `inicializar_db()`).

### Verificar salud de Lapora Clinic

```bash
curl https://sofia-lapora-production.up.railway.app/clinic/health
```

Debe devolver `{"status":"ok","service":"lapora_clinic","db":"ok"}`.

### Crear una clínica desde código (para soporte)

```python
from agent.clinic_models import crear_clinica
import asyncio

asyncio.run(crear_clinica(
    nombre="Clínica X",
    email_admin="dr@example.com",
    password_admin="lapora123",
    nombre_admin="Dr. Juan",
    especialidad="Dermatología",
    ciudad="Ibagué",
))
```

### Backup de la BD

```bash
# Desde Railway
railway run --service postgres pg_dump > backup.sql

# Restaurar
railway run --service postgres psql < backup.sql
```

### Logs

```bash
railway logs --service sofia-lapora
```

---

## 💰 Pricing y monetización

| Plan | Precio (COP) | Pacientes | Usuarios | IA | Branding |
|------|--------------|-----------|----------|-----|---------|
| **Free** | $0/mes | 100 | 1 | ❌ | "Powered by Lapora" |
| **Pro** ⭐ | $190.000/mes | Ilimitado | 5 | ✅ | Tu logo |
| **Studio** | $390.000/mes | Ilimitado | Ilimitado | ✅ | Dominio propio |

**Proyección 6 meses (escenario real):**
- 12 Free (lead-gen)
- 6 Pro = $1.140.000/mes
- 2 Studio = $780.000/mes
- **Total: ~$1.920.000 MRR**

Costos infra: $25-150 USD/mes (Railway + Anthropic + Meta).
**Margen bruto: ~95%.**

---

## 🐛 Troubleshooting

### "Email o contraseña incorrectos"
- Verificar mayúsculas en el email (se guarda lowercase)
- Si recién registró: la sesión expira a los 30 días

### Inbox vacío aunque mandé mensaje
- Verificar que el webhook esté configurado en Meta
- El slug de la URL debe coincidir EXACTO con el de la clínica
- Mirar logs: `railway logs | grep webhook`

### "No se pudo descargar Sheets"
- La hoja debe estar **publicada en web** (no solo "compartida")
- Archivo > Compartir > Publicar en web > CSV

### Plantillas no aparecen en el inbox
- Refrescar la página después de crear plantillas
- Verificar que se hayan guardado (Plantillas → ver lista)

---

## 📞 Soporte

- **Email**: laporamarketingdigital@gmail.com
- **WhatsApp**: +57 322 878 3019
- **Web**: https://lapora.studio

---

> **Construido por Lapora Marketing Digital**
> Marketing digital para médicos premium en Ibagué y el Tolima.

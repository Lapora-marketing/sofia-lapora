# ════════════════════════════════════════════════════════════
# Dockerfile — Imagen Docker de SofIA (Lapora) para Railway
# Generado por AgentKit
# ════════════════════════════════════════════════════════════

FROM python:3.12-slim

# Directorio de trabajo
WORKDIR /app

# Variables de entorno
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Instalar dependencias del sistema (minimas)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Instalar dependencias de Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copiar codigo del agente
COPY . .

# Puerto expuesto (Railway sobrescribe con $PORT)
EXPOSE 8000

# Comando de arranque — usa $PORT de Railway o 8000 por defecto
CMD ["sh", "-c", "uvicorn agent.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

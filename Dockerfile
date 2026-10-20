# DataForce hosted image: API + built frontend in one container (docs/HOSTING-PLAN.md, HOSTED-MODE-CONTRACT.md §5).
# Build from the repository root: `make image`.

# Stage 1: build the frontend
FROM node:22-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: runtime
FROM python:3.13-slim
ENV PORT=8080 \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app/backend
COPY backend/requirements.lock ./
RUN pip install --no-cache-dir --require-hashes -r requirements.lock

# The package is installed in editable mode on purpose: settings and Alembic find alembic.ini and
# ../frontend/dist relative to the source tree (BACKEND_DIR in app/config.py), which a copy in
# site-packages would break.
COPY backend/pyproject.toml backend/alembic.ini ./
COPY backend/app ./app
COPY backend/alembic ./alembic
RUN pip install --no-cache-dir --no-deps -e .

COPY --from=frontend /build/frontend/dist /app/frontend/dist

RUN useradd --system --no-create-home --uid 10001 dataforce
USER dataforce
EXPOSE 8080
CMD ["dataforce", "serve"]

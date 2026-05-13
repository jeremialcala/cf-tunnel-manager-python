-- =====================================================================
-- Tunnel Orchestrator — DB bootstrap (executed once by docker entrypoint)
-- =====================================================================
-- Real schema is owned by Alembic migrations (`make migrate`).
-- This file just sets DB-level defaults Alembic relies on.
-- =====================================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- Optional: row-level security baseline for multi-tenant tables
ALTER DATABASE tunnel_orchestrator SET row_security = on;

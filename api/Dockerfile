# api/Dockerfile — LexBot API image (uvicorn serve).
# Build context MUST be the repo root:  docker build -f api/Dockerfile .
# (lexbot-ingest and lexbot-agent are local src-layout packages, not on PyPI,
# so the image installs all three editable from the copied monorepo.)

FROM python:3.12-slim

WORKDIR /app

# Copy the monorepo so editable installs and repo-root path resolution work
# (db/init.sql for the D5 startup schema apply; docs for the D6 auto-seed).
COPY db/init.sql db/init.sql
COPY ingest ingest
COPY agent agent
COPY api api
COPY docs docs

RUN pip install --no-cache-dir \
        -e /app/ingest \
        -e /app/agent \
        -e /app/api

EXPOSE 8000

# create_app() is the app factory (DI); uvicorn --factory calls it with no
# args and the runtime deps come from env (DATABASE_URL, LLM_PROVIDER, ...).
CMD ["uvicorn", "lexbot_api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
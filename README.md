# Tchek-Am

**Tchek am before you pay.** A WhatsApp bot that helps buyers in Cameroon check a seller's number, product photo or message before paying by MoMo / Orange Money, and lets scam victims report with evidence (AI-assisted, human-reviewed).

## Docs
- [MVP PRD v1.0](docs/features/tchek-am-mvp/PRD.md): the build spec
- [PRD background](docs/prd.md): rationale and detail
- [Architecture](docs/architecture.md): how (draft)
- [Decision record (ADR)](docs/ADR.md): every decision, with the question and the answer
- [Glossary](docs/CONTEXT.md): domain terms
- [Idea brief](docs/idea-brief.md): market research and original ideas

Status: pre-MVP, planning.


## Getting started

Prerequisites: [uv](https://docs.astral.sh/uv/) (installs Python 3.13 for you) and Docker.

```bash
docker compose up -d        # Postgres 16 + pgvector, S3 (SeaweedFS, http://localhost:8333)
cp .env.example .env
uv sync
uv run python src/manage.py migrate
uv run python src/manage.py runserver
uv run pytest               # needs the db service running
```

Health check: `GET http://localhost:8000/healthz`.

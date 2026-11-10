# Ticket Routing System

A small FastAPI starter for creating tickets and routing queued tickets to background workers.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Run

```powershell
uvicorn app.main:app --reload
```

The API is available at `http://127.0.0.1:8000`; interactive documentation is at `/docs`.
Create a ticket with `POST /tickets` using `{"subject": "...", "description": "..."}`. Use `GET /tickets` to list tickets and `GET /health` for the health check. Workers change queued tickets to `routed` and record the worker name.

Set `DATABASE_URL` and `WORKER_COUNT` environment variables to configure persistence and worker concurrency. The default database is a local SQLite file. The queue is in-process; tickets still queued at restart are reloaded from the database.

## Tests

```powershell
pytest
```
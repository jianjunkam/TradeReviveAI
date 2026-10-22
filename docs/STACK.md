# Stack

Confirmed by the human in GigaLab on 2026-10-22.

| Layer | Choice | Why |
|---|---|---|
| Frontend | Plain HTML, CSS and JavaScript | No build step and nothing to install, as GigaLab itself; fine for forms, lists and dashboards |
| Backend | Python: FastAPI | GigaLab's own stack: small, fast and typed; you add sign-in and an admin with libraries |
| Database | PostgreSQL | A managed database for many customers and several servers; pgvector adds embeddings |
| Hosting | A hosting platform (PaaS) | Push code and it runs, with a managed database; pay more, look after less |
| Extras | none | |

## Commands
- Install: `pip install -r requirements.txt`
- Run the tests: `pytest -q`
- Run the app: `uvicorn app.main:app --reload`

## Who looks after it
- Reads best: Neither yet. Team: Two to five people. Runs a Linux server: No. Live updates: No.

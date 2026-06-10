# Streamlit frontend

Frontend locale per usare il backend FastAPI del Digital Twin con file `.fit`.

## Installazione

Dal root del repository:

```bash
python -m pip install -e .[frontend]
```

Per sviluppo completo:

```bash
python -m pip install -e .[dev,frontend]
```

## Avvio

Terminale 1 — backend FastAPI:

```bash
python -m uvicorn api_app:app --reload --host 127.0.0.1 --port 8000
```

Terminale 2 — frontend Streamlit:

```bash
streamlit run streamlit_frontend/app.py
```

Apri poi l'URL mostrato da Streamlit, di solito `http://localhost:8501`.

## Funzioni disponibili

- Upload di uno o più FIT per `/test/propose`
- Summary singola attività via `/ride/summary`
- Rolling power curve in sessione via `/ride/ingest`
- Snapshot metabolico via `/profile/snapshot`

## Note

Lo stato della rolling curve è mantenuto nella sessione Streamlit del browser. Per persistenza reale serve collegare un database o storage esterno.

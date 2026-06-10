"""Streamlit UI for the DDTraining Digital Twin FastAPI backend.

Run the API first:
    python -m uvicorn api_app:app --reload --host 127.0.0.1 --port 8000

Then run this frontend:
    streamlit run streamlit_frontend/app.py
"""

from __future__ import annotations

import json
from datetime import date
from typing import Any

import pandas as pd
import requests
import streamlit as st

DEFAULT_API_URL = "http://127.0.0.1:8000"


st.set_page_config(
    page_title="DDTraining Digital Twin",
    page_icon="🚴",
    layout="wide",
)


def _api_url() -> str:
    return st.session_state.get("api_url", DEFAULT_API_URL).rstrip("/")


def _request(method: str, path: str, **kwargs: Any) -> Any:
    url = f"{_api_url()}{path}"
    try:
        response = requests.request(method, url, timeout=120, **kwargs)
    except requests.RequestException as exc:
        raise RuntimeError(f"Backend non raggiungibile: {exc}") from exc
    if not response.ok:
        detail: Any
        try:
            detail = response.json()
        except ValueError:
            detail = response.text
        raise RuntimeError(f"Errore backend {response.status_code}: {detail}")
    try:
        return response.json()
    except ValueError as exc:
        raise RuntimeError("Il backend ha risposto senza JSON valido.") from exc


def _fit_files(uploaded_files: list[Any]) -> list[tuple[str, bytes, str]]:
    return [(f.name, f.getvalue(), "application/octet-stream") for f in uploaded_files]


def _json_download(label: str, payload: Any, file_name: str) -> None:
    st.download_button(
        label,
        data=json.dumps(payload, indent=2, ensure_ascii=False),
        file_name=file_name,
        mime="application/json",
    )


def _show_json(payload: Any, expanded: bool = False) -> None:
    with st.expander("JSON completo", expanded=expanded):
        st.json(payload)


def _curve_to_frame(curve: dict[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for duration, value in curve.items():
        if isinstance(value, dict):
            watts = value.get("watts", value.get("power", value.get("mean_w")))
            wkg = value.get("wkg")
            ride_id = value.get("ride_id") or value.get("source") or value.get("file")
        else:
            watts = value
            wkg = None
            ride_id = None
        try:
            duration_s = int(duration)
        except (TypeError, ValueError):
            continue
        rows.append({"duration_s": duration_s, "watts": watts, "wkg": wkg, "source": ride_id})
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values("duration_s")
    return df


def _summary_metrics(summary: dict[str, Any]) -> dict[str, Any]:
    candidates = summary.get("metrics") if isinstance(summary.get("metrics"), dict) else summary
    keys = [
        "duration_s",
        "distance_km",
        "np",
        "normalized_power",
        "tss",
        "if",
        "intensity_factor",
        "max_power",
        "max_watts",
        "work_kj",
    ]
    return {k: candidates.get(k) for k in keys if candidates.get(k) is not None}


def _health_card() -> None:
    try:
        health = _request("GET", "/health")
    except RuntimeError as exc:
        st.error(str(exc))
        st.caption("Avvia il backend con: python -m uvicorn api_app:app --reload --port 8000")
        return
    st.success(f"Backend connesso: {health.get('service', 'API')} {health.get('version', '')}")


with st.sidebar:
    st.title("DDTraining")
    st.session_state["api_url"] = st.text_input("Backend FastAPI", value=_api_url())
    if st.button("Verifica connessione"):
        _health_card()
    st.divider()
    st.caption("1. Avvia FastAPI. 2. Avvia Streamlit. 3. Carica uno o più FIT.")

st.title("🚴 Digital Twin — Frontend Streamlit")
st.write("Interfaccia rapida per usare il backend FastAPI con file `.fit`.")

_health_card()

tab_proposal, tab_summary, tab_curve, tab_snapshot = st.tabs(
    ["Profilo da FIT", "Summary attività", "Rolling curve", "Snapshot metabolico"]
)

with tab_proposal:
    st.subheader("Proposta profilo da uno o più FIT")
    files = st.file_uploader("Carica FIT", type=["fit"], accept_multiple_files=True, key="proposal_files")
    if st.button("Calcola proposta", disabled=not files):
        with st.spinner("Analisi FIT in corso..."):
            try:
                proposal = _request("POST", "/test/propose", files=[("files", f) for f in _fit_files(files)])
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                st.session_state["last_proposal"] = proposal
                status = proposal.get("status", "unknown")
                confidence = proposal.get("confidence")
                col1, col2 = st.columns(2)
                col1.metric("Status", status)
                col2.metric("Confidence", f"{confidence:.3f}" if isinstance(confidence, (int, float)) else "n/d")
                if proposal.get("warnings"):
                    st.warning("\n".join(str(w) for w in proposal["warnings"]))
                _json_download("Scarica proposta JSON", proposal, "profile_proposal.json")
                _show_json(proposal, expanded=True)

with tab_summary:
    st.subheader("Riepilogo singola attività")
    col_a, col_b, col_c = st.columns(3)
    weight = col_a.number_input("Peso kg", min_value=30.0, max_value=130.0, value=70.0, step=0.5)
    ftp = col_b.number_input("FTP opzionale", min_value=0.0, value=0.0, step=5.0)
    lthr = col_c.number_input("LTHR opzionale", min_value=0.0, value=0.0, step=1.0)
    summary_file = st.file_uploader("Carica un FIT", type=["fit"], key="summary_file")
    if st.button("Calcola summary", disabled=summary_file is None):
        with st.spinner("Calcolo summary..."):
            data = {"weight_kg": str(weight), "gender": "MALE", "training_years": "10", "discipline": "ENDURANCE"}
            if ftp > 0:
                data["ftp"] = str(ftp)
            if lthr > 0:
                data["lthr"] = str(lthr)
            try:
                summary = _request(
                    "POST",
                    "/ride/summary",
                    data=data,
                    files={"file": (summary_file.name, summary_file.getvalue(), "application/octet-stream")},
                )
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                metrics = _summary_metrics(summary)
                if metrics:
                    cols = st.columns(min(4, len(metrics)))
                    for idx, (key, value) in enumerate(metrics.items()):
                        cols[idx % len(cols)].metric(key, value)
                _json_download("Scarica summary JSON", summary, "ride_summary.json")
                _show_json(summary)

with tab_curve:
    st.subheader("Rolling power curve")
    st.write("Carica FIT in sequenza: il frontend mantiene la curva in sessione e la passa a `/ride/ingest`.")
    col_a, col_b = st.columns(2)
    curve_weight = col_a.number_input("Peso kg", min_value=30.0, max_value=130.0, value=70.0, step=0.5, key="curve_weight")
    ride_date = col_b.date_input("Data attività", value=date.today())
    curve_file = st.file_uploader("Carica FIT da aggiungere alla curva", type=["fit"], key="curve_file")
    if "stored_curve" not in st.session_state:
        st.session_state["stored_curve"] = None
    if st.button("Ingest FIT", disabled=curve_file is None):
        with st.spinner("Aggiornamento curva..."):
            form = {"ride_date": ride_date.isoformat(), "weight_kg": str(curve_weight)}
            if st.session_state["stored_curve"]:
                form["stored_curve_json"] = json.dumps(st.session_state["stored_curve"])
            try:
                result = _request(
                    "POST",
                    "/ride/ingest",
                    data=form,
                    files={"file": (curve_file.name, curve_file.getvalue(), "application/octet-stream")},
                )
            except RuntimeError as exc:
                st.error(str(exc))
            else:
                st.session_state["stored_curve"] = result.get("curve")
                st.success(f"Ride usable: {result.get('ride_usable')} · refresh profile: {result.get('profile_should_refresh')}")
                if result.get("notes"):
                    st.info("\n".join(str(n) for n in result["notes"]))
                df = _curve_to_frame(result.get("curve", {}))
                if not df.empty:
                    st.dataframe(df, use_container_width=True)
                    st.line_chart(df.set_index("duration_s")["watts"])
                _json_download("Scarica curva JSON", result, "rolling_power_curve.json")
                _show_json(result)
    if st.button("Reset curva in sessione"):
        st.session_state["stored_curve"] = None
        st.success("Curva resettata.")

with tab_snapshot:
    st.subheader("Snapshot metabolico da MMP")
    st.write("Incolla una MMP/curve JSON, ad esempio `{\"300\": 310, \"1200\": 260}`.")
    col_a, col_b = st.columns(2)
    snap_weight = col_a.number_input("Peso kg", min_value=30.0, max_value=130.0, value=70.0, step=0.5, key="snap_weight")
    mmp_text = st.text_area("MMP JSON", value=json.dumps({"5": 850, "60": 460, "300": 310, "1200": 250}, indent=2), height=180)
    if st.button("Genera snapshot"):
        try:
            mmp = json.loads(mmp_text)
        except json.JSONDecodeError as exc:
            st.error(f"JSON non valido: {exc}")
        else:
            payload = {"athlete": {"weight_kg": snap_weight, "gender": "MALE", "training_years": 10, "discipline": "ENDURANCE"}, "mmp": mmp}
            with st.spinner("Calcolo snapshot..."):
                try:
                    snapshot = _request("POST", "/profile/snapshot", json=payload)
                except RuntimeError as exc:
                    st.error(str(exc))
                else:
                    st.session_state["last_snapshot"] = snapshot
                    _json_download("Scarica snapshot JSON", snapshot, "metabolic_snapshot.json")
                    _show_json(snapshot, expanded=True)

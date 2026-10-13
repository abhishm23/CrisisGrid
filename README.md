# CrisisGrid — Seismic Transit & Emergency Evacuation Routing

Proof-of-concept emergency transit routing and evacuation network simulator built with FastAPI, NetworkX, and Jinja2.

## Overview
CrisisGrid dynamically computes multi-modal evacuation routes during municipal seismic events, modeling structural damage probabilities and blocked transportation arteries across a city grid graph.

## Tech Stack
- **Backend**: Python 3.11, FastAPI, NetworkX graph routing algorithms
- **Frontend**: Jinja2 HTML templates, interactive canvas / leaflet map
- **Tests**: Pytest test suite (`test_suite.py`)

## Running
```bash
uvicorn app:app --reload --port 8000
```

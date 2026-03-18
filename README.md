# SmartFill

AI-assisted PDF form filling system.

## Overview

SmartFill helps users upload PDF forms, extract fields, and complete filling workflows with AI-assisted mapping.

## Tech Stack

- Frontend: React + TypeScript + Vite
- Backend: FastAPI (Python)
- PDF: pypdf and related processing pipeline

## Quick Start

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate  # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --port 8000
```

Backend docs: `http://localhost:8000/docs`

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
npm run dev
```

Frontend: `http://localhost:3000`

## API

- `GET /api/v1/health`
- `POST /api/v1/upload`
- `POST /api/v1/extract-fields`
- `POST /api/v1/fill`

## Repository Layout

```text
SmartFill/
├── frontend/
├── backend/
├── docs/
└── .claude/skills/
```

## Skills Used In Development

Development skills are managed in `.claude/skills`.  
Current skills include:

- `pm`
- `architect-designer`
- `front-end-designer`
- `researcher`

You can inspect each skill's behavior in its `SKILL.md`.

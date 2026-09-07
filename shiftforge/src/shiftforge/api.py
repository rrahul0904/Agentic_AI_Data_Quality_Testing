from __future__ import annotations

from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from .engine import ConversionEngine
from .models import ConvertRequest

app = FastAPI(title="ShiftForge", version="0.1.0")
engine = ConversionEngine()


@app.get("/health")
def health():
    return {"status": "ok", "service": "shiftforge"}


@app.post("/api/convert")
def convert(req: ConvertRequest):
    return engine.convert_sql(req.sql, req.model_name, req.hints).model_dump()


@app.get("/", response_class=HTMLResponse)
def index():
    template = Path(__file__).parent / "templates" / "index.html"
    return template.read_text()

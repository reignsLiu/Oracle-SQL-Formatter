from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend.formatter import format_oracle_sql

app = FastAPI(title="Oracle SQL Formatter")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class FormatRequest(BaseModel):
    sql: str = Field(..., min_length=1, description="Raw Oracle SQL to format")


class FormatResponse(BaseModel):
    formatted: str


@app.post("/api/format", response_model=FormatResponse)
def format_sql(req: FormatRequest):
    try:
        result = format_oracle_sql(req.sql)
        return FormatResponse(formatted=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


frontend_dir = Path(__file__).resolve().parent.parent / "frontend"
if frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")

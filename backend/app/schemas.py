"""Pydantic request/response schemas."""

from pydantic import BaseModel, Field


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""


class ProjectOut(BaseModel):
    id: str
    name: str
    description: str
    created_at: str


class CorpusOut(BaseModel):
    id: str
    project_id: str
    filename: str
    n_rows: int
    columns: list[str]
    suggested_text_column: str | None = None
    parse_info: dict = {}
    preview: list[dict] | None = None
    created_at: str


class ConstructCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = ""
    reference: str = ""
    items: list[str] = Field(min_length=1)


class ConstructOut(BaseModel):
    id: str
    name: str
    description: str
    reference: str
    items: list[str]
    is_seed: bool


class JobCreate(BaseModel):
    project_id: str
    corpus_id: str
    construct_id: str
    text_column: str
    model_name: str = "sentence-transformers/all-MiniLM-L6-v2"


class JobOut(BaseModel):
    id: str
    project_id: str
    corpus_id: str
    construct_id: str
    construct_name: str = ""
    corpus_filename: str = ""
    text_column: str
    model_name: str
    status: str
    progress: float
    error: str
    created_at: str
    started_at: str
    finished_at: str

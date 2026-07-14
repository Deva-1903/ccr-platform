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
    last_activity_at: str = ""  # latest run creation, else project creation
    n_runs: int = 0
    archived: bool = False


class ProjectPatch(BaseModel):
    archived: bool | None = None


class RegisterIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=200)
    name: str = Field(min_length=1, max_length=120)


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


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
    reverse_scored: list[bool] | None = None  # parallel to items; defaults to all False
    language: str = "en"


class ConstructOut(BaseModel):
    id: str
    name: str
    description: str
    reference: str
    items: list[str]
    reverse_scored: list[bool] = []
    is_seed: bool
    version: int = 1
    verification_status: str = "draft"
    language: str = "en"
    category: str = ""
    item_hash: str = ""  # first 16 hex chars for display


class JobCreate(BaseModel):
    project_id: str
    corpus_id: str
    construct_id: str
    text_column: str
    model_name: str = "all-minilm-l6-v2"  # registry id (spec 0003)
    language: str = "en"


class JobOut(BaseModel):
    id: str
    project_id: str
    corpus_id: str
    construct_id: str
    construct_name: str = ""
    corpus_filename: str = ""
    text_column: str
    model_name: str
    language: str = "en"
    status: str
    progress: float
    error: str
    created_at: str
    started_at: str
    finished_at: str

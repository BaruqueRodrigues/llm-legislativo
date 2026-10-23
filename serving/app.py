"""Serviço HTTP (FastAPI) para servir o LLM Legislativo Brasileiro.

Carrega os pesos publicados em `BaruqRodrigues/llm-legislativo` no Hugging Face
Hub e expõe geração de texto. Pensado para rodar como um Hugging Face Space
(SDK Docker) ou em qualquer host de container (Render, Railway, Fly.io, Modal).

Variáveis de ambiente:
    MODEL_REPO          Repo no Hub (default: BaruqRodrigues/llm-legislativo)
    API_TOKEN           Se definido, exige `Authorization: Bearer <token>`
    ALLOW_ORIGINS       Lista separada por vírgula para CORS (default: *)
    MAX_NEW_TOKENS_CAP  Teto de tokens por requisição (default: 256)
"""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

import torch
from fastapi import FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from huggingface_hub import snapshot_download
from pydantic import BaseModel, Field

MODEL_REPO = os.environ.get("MODEL_REPO", "BaruqRodrigues/llm-legislativo")
API_TOKEN = os.environ.get("API_TOKEN", "").strip()
ALLOW_ORIGINS = [o.strip() for o in os.environ.get("ALLOW_ORIGINS", "*").split(",") if o.strip()]
MAX_NEW_TOKENS_CAP = int(os.environ.get("MAX_NEW_TOKENS_CAP", "256"))

state: dict = {}


def _load_model() -> dict:
    """Baixa o pacote de inferência + pesos do Hub e instancia o modelo."""
    snapshot = Path(
        snapshot_download(
            MODEL_REPO,
            allow_patterns=[
                "modeling/**",
                "model_config.json",
                "tokenizer.json",
                "model.safetensors",
            ],
        )
    )
    # O pacote do Hub expõe o módulo `legislm` dentro de `modeling/`.
    sys.path.insert(0, str(snapshot / "modeling"))

    from safetensors.torch import load_file
    from tokenizers import Tokenizer

    from legislm.model.config import GPTConfig
    from legislm.model.generation import generate
    from legislm.model.gpt import GPTModel

    config = GPTConfig.from_dict(
        json.loads((snapshot / "model_config.json").read_text(encoding="utf-8"))
    )
    tokenizer = Tokenizer.from_file(str(snapshot / "tokenizer.json"))
    model = GPTModel(config)
    model.load_state_dict(load_file(str(snapshot / "model.safetensors")), strict=True)
    model.eval()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model.to(device)
    return {
        "config": config,
        "tokenizer": tokenizer,
        "model": model,
        "generate": generate,
        "device": device,
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    state.update(_load_model())
    yield
    state.clear()


app = FastAPI(title="LLM Legislativo", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=1)
    max_new_tokens: int = Field(128, ge=1)
    temperature: float = Field(0.8, gt=0.0, le=2.0)
    top_k: int = Field(40, ge=0)
    greedy: bool = False
    seed: Optional[int] = None


class GenerateResponse(BaseModel):
    text: str
    prompt_tokens: int
    generated_tokens: int


def _check_auth(authorization: Optional[str]) -> None:
    if not API_TOKEN:
        return
    if authorization != f"Bearer {API_TOKEN}":
        raise HTTPException(status_code=401, detail="unauthorized")


@app.get("/health")
def health() -> dict:
    return {
        "status": "ok",
        "model": MODEL_REPO,
        "device": state.get("device"),
        "loaded": "model" in state,
    }


@app.post("/generate", response_model=GenerateResponse)
def generate_text(
    req: GenerateRequest, authorization: Optional[str] = Header(default=None)
) -> GenerateResponse:
    _check_auth(authorization)
    if "model" not in state:
        raise HTTPException(status_code=503, detail="modelo ainda carregando")

    tokenizer = state["tokenizer"]
    model = state["model"]
    ids = tokenizer.encode(req.prompt).ids
    if not ids:
        raise HTTPException(status_code=400, detail="prompt vazio")

    max_new_tokens = min(req.max_new_tokens, MAX_NEW_TOKENS_CAP)
    output = state["generate"](
        model,
        ids,
        max_new_tokens=max_new_tokens,
        temperature=req.temperature,
        top_k=req.top_k or None,
        eos_token_id=state["config"].eos_token_id,
        greedy=req.greedy,
        seed=req.seed,
    )
    return GenerateResponse(
        text=tokenizer.decode(output[0].tolist(), skip_special_tokens=True),
        prompt_tokens=len(ids),
        generated_tokens=int(output.size(1)) - len(ids),
    )

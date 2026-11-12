"""Agent configuration file / API schema (FR-03).

A config is versioned like a scenario: once used by a run it is locked, and editing it creates
a new version. Provider secrets are never part of a config (they live in server env vars).
"""

import re
from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.taxonomy import ToolName
from app.services.agent_graph.rule_based import PROFILES

PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts"
Provider = Literal["rule_based", "gemini", "openai"]
GEMINI_MODEL_ID = re.compile(r"default|gemini-[a-z0-9][a-z0-9.\-]{1,60}")


@lru_cache
def load_prompt(prompt_version: str) -> str:
    path = PROMPTS_DIR / f"{prompt_version}.md"
    if not path.is_file():
        raise ValueError(f"unknown prompt_version '{prompt_version}'")
    return path.read_text(encoding="utf-8").strip()


class AgentConfigSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: str = Field(pattern=r"^[a-z][a-z0-9-]{2,60}$")
    version: int = Field(default=1, ge=1)
    description: str = Field(default="", max_length=1000)
    provider: Provider
    model_id: str = Field(min_length=1, max_length=100)
    temperature: float = Field(default=0.0, ge=0, le=2)
    prompt_version: str = Field(default="agent_system_v1", pattern=r"^[a-z0-9_]+$")
    system_prompt: str | None = Field(
        default=None, max_length=20_000, description="Defaults to the prompt_version file"
    )
    tools: list[ToolName] = Field(default_factory=lambda: list(ToolName), min_length=1)
    max_steps: int = Field(default=8, ge=1, le=20)
    max_tool_calls: int = Field(default=10, ge=1, le=30)
    timeout_s: int = Field(default=60, ge=5, le=300)
    max_retries: int = Field(default=2, ge=0, le=5)

    @field_validator("tools")
    @classmethod
    def _unique_tools(cls, tools: list[ToolName]) -> list[ToolName]:
        if len(set(tools)) != len(tools):
            raise ValueError("tools must not contain duplicates")
        return tools

    @model_validator(mode="after")
    def _resolve_and_check(self) -> "AgentConfigSpec":
        if self.provider == "rule_based" and self.model_id not in PROFILES:
            raise ValueError(f"rule_based model_id must be one of {', '.join(PROFILES)}")
        if self.provider == "gemini" and not GEMINI_MODEL_ID.fullmatch(self.model_id):
            raise ValueError(
                "gemini model_id must be 'default' (the server's GEMINI_MODEL) or a Gemini "
                "model ID such as 'gemini-3.5-flash'"
            )
        if self.system_prompt is None:
            self.system_prompt = load_prompt(self.prompt_version)
        return self

    @property
    def is_llm(self) -> bool:
        return self.provider != "rule_based"

"""Request/response and routine-step models for the HTTP/WS API."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, Field

from .config import MAX_ROUTINE_STEPS


class JogRequest(BaseModel):
    joint: str
    delta: float  # radians, relative to current target


class CalibrationRequest(BaseModel):
    offsets: dict[str, float]


class KeyframePlayRequest(BaseModel):
    names: list[str]
    segment_duration: float | None = None
    dry_run: bool = False


class ReachRequest(BaseModel):
    x: float
    y: float
    duration: float | None = None
    dry_run: bool = False


# --- Routines: scripted sequences of the primitives above ---------------------


class CommandStep(BaseModel):
    type: Literal["command"]
    command: str
    params: dict = Field(default_factory=dict)


class BehaviorStep(BaseModel):
    type: Literal["behavior"]
    behavior: str


class KeyframesStep(BaseModel):
    type: Literal["keyframes"]
    names: list[str]


class ReachStep(BaseModel):
    type: Literal["reach"]
    x: float
    y: float


class WaitStep(BaseModel):
    type: Literal["wait"]
    seconds: float


RoutineStep = Annotated[
    CommandStep | BehaviorStep | KeyframesStep | ReachStep | WaitStep,
    Field(discriminator="type"),
]


class RoutineBody(BaseModel):
    steps: list[RoutineStep] = Field(min_length=1, max_length=MAX_ROUTINE_STEPS)


class AIRoutineRequest(BaseModel):
    text: str
    name: str
    run: bool = False


class AICommandRequest(BaseModel):
    text: str


class AIPlanStepResult(BaseModel):
    command: str
    params: dict = Field(default_factory=dict)
    executed: bool
    detail: str | None = None


class AICommandResponse(BaseModel):
    explanation: str
    steps: list[AIPlanStepResult]
    fully_executed: bool
    repaired: bool = False

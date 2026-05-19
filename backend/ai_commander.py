from __future__ import annotations

import logging
from typing import Any

from anthropic import APIError, AsyncAnthropic
from pydantic import BaseModel, Field

from .behaviors import BEHAVIOR_DESCRIPTIONS
from .models import RobotStatus

logger = logging.getLogger("steelmind.ai")

DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """너는 휴머노이드 로봇 제어 AI다.
자연어 입력을 받아 로봇이 실행할 명령 시퀀스로 변환한다.

사용 가능한 명령:
- stand: 일어선다. IDLE / WALKING 에서 STANDING 으로 전환.
- walk: 걷는다. STANDING 에서만 가능. IDLE 이면 먼저 stand 가 필요하다.
- idle: 휴식/앉기 자세. STANDING / WALKING / EXECUTING 에서 IDLE 로 전환.
- execute: 정의된 behavior 를 실행한다. params.behavior 에 이름을 넣는다.

사용 가능한 behavior:
{behaviors}

규칙:
1. 현재 상태에서 시작하는 유효한 명령 시퀀스를 만든다. 예) IDLE 에서 walk 를 요구하면 [stand, walk].
2. 입력이 단일 동작이면 steps 에 한 개만 넣는다.
3. 입력이 "일어서서 걸어서 손 흔들어" 같은 복합 동작이면 stand → walk → (멈춤 위해 stand) → execute(wave) 처럼 여러 단계로 풀어준다.
4. walk 후 execute 를 하려면 먼저 stand 로 전이해야 한다.
5. explanation 은 전체 계획을 한국어 한 문장으로 요약.
6. 출력은 도구 호출(tool_use)로만 한다."""

TOOL = {
    "name": "execute_robot_plan",
    "description": "휴머노이드 로봇에 단일 또는 다단계 명령 시퀀스를 내린다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "steps": {
                "type": "array",
                "minItems": 1,
                "maxItems": 6,
                "items": {
                    "type": "object",
                    "properties": {
                        "command": {
                            "type": "string",
                            "enum": ["stand", "walk", "idle", "execute"],
                        },
                        "params": {
                            "type": "object",
                            "additionalProperties": True,
                        },
                    },
                    "required": ["command"],
                },
            },
            "explanation": {
                "type": "string",
                "description": "전체 계획의 의도를 한국어 한 문장으로.",
            },
        },
        "required": ["steps", "explanation"],
    },
}


class PlanStep(BaseModel):
    command: str
    params: dict[str, Any] = Field(default_factory=dict)


class AIPlanResult(BaseModel):
    steps: list[PlanStep]
    explanation: str

    @property
    def first(self) -> PlanStep:
        return self.steps[0]


class AICommanderError(Exception):
    pass


class AICommander:
    def __init__(self, api_key: str | None, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            self._client: AsyncAnthropic | None = None
        else:
            self._client = AsyncAnthropic(api_key=api_key)
        self.model = model
        behaviors_block = "\n".join(f"  - {n}: {d}" for n, d in BEHAVIOR_DESCRIPTIONS.items())
        self._system_prompt = SYSTEM_PROMPT.format(behaviors=behaviors_block)

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def translate(self, text: str, status: RobotStatus) -> AIPlanResult:
        if self._client is None:
            raise AICommanderError("ANTHROPIC_API_KEY is not configured")

        user_content = (
            f"현재 로봇 상태: {status.state.value}\n"
            f"이전 상태: {status.previous_state.value if status.previous_state else 'none'}\n"
            f"현재 behavior: {status.current_behavior or 'none'}\n"
            f"\n사용자 입력: {text}"
        )

        try:
            response = await self._client.messages.create(
                model=self.model,
                max_tokens=512,
                system=[
                    {
                        "type": "text",
                        "text": self._system_prompt,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=[TOOL],
                tool_choice={"type": "tool", "name": TOOL["name"]},
                messages=[{"role": "user", "content": user_content}],
            )
        except APIError as e:
            logger.exception("Anthropic API error")
            raise AICommanderError(f"Anthropic API error: {e}") from e

        for block in response.content:
            if block.type == "tool_use" and block.name == TOOL["name"]:
                data = block.input or {}
                try:
                    return AIPlanResult(**data)
                except Exception as e:
                    raise AICommanderError(f"invalid tool input: {data!r}") from e

        raise AICommanderError("model did not produce a tool_use block")

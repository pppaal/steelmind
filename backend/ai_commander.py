from __future__ import annotations

import logging
from typing import Any

from anthropic import APIError, AsyncAnthropic
from pydantic import BaseModel, Field

from .models import RobotStatus

logger = logging.getLogger("steelmind.ai")

DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = """너는 휴머노이드 로봇 제어 AI다.
자연어 입력을 받아 로봇이 실행할 단일 명령으로 변환한다.

사용 가능한 명령:
- stand: 일어선다. IDLE / WALKING 에서 STANDING 으로 전환.
- walk: 걷는다. STANDING 에서만 가능. IDLE 이면 먼저 stand 가 필요하니 stand 를 선택한다.
- idle: 휴식/앉기 자세. STANDING / WALKING / EXECUTING 에서 IDLE 로 전환.
- execute: 정의된 behavior 를 실행한다. params.behavior 에 이름을 넣는다 (없으면 "demo").

규칙:
1. 입력이 모호하거나 여러 동작을 요구하면 "다음에 해야 할 한 단계"만 고른다.
2. 현재 상태를 반드시 고려해 유효 전이만 선택한다.
3. explanation 은 한국어 한 문장으로 간결하게.
4. 출력은 도구 호출(tool_use)로만 한다."""

TOOL = {
    "name": "execute_robot_command",
    "description": "휴머노이드 로봇에 단일 명령을 내린다.",
    "input_schema": {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "enum": ["stand", "walk", "idle", "execute"],
                "description": "실행할 명령.",
            },
            "params": {
                "type": "object",
                "description": "명령 파라미터. execute 의 경우 {\"behavior\": \"demo\"} 형태.",
                "additionalProperties": True,
            },
            "explanation": {
                "type": "string",
                "description": "이 명령을 고른 이유를 한국어 한 문장으로.",
            },
        },
        "required": ["command", "explanation"],
    },
}


class AICommandResult(BaseModel):
    command: str
    params: dict[str, Any] = Field(default_factory=dict)
    explanation: str


class AICommanderError(Exception):
    pass


class AICommander:
    def __init__(self, api_key: str | None, model: str = DEFAULT_MODEL) -> None:
        if not api_key:
            self._client: AsyncAnthropic | None = None
        else:
            self._client = AsyncAnthropic(api_key=api_key)
        self.model = model

    @property
    def enabled(self) -> bool:
        return self._client is not None

    async def translate(self, text: str, status: RobotStatus) -> AICommandResult:
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
                        "text": SYSTEM_PROMPT,
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
                    return AICommandResult(**data)
                except Exception as e:
                    raise AICommanderError(f"invalid tool input: {data!r}") from e

        raise AICommanderError("model did not produce a tool_use block")

"""Jinja2 helpers for chat setup templates."""

from __future__ import annotations

from jinja2 import StrictUndefined, TemplateError
from jinja2.sandbox import SandboxedEnvironment

from .schemas import ChatMode


_TEMPLATE_ENV = SandboxedEnvironment(
    autoescape=False,
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def render_template(template: str, **context: str) -> str:
    return _TEMPLATE_ENV.from_string(template or "").render(**context).strip()


def render_chat_mode(
    mode: ChatMode,
    *,
    character_name: str,
    user_persona_name: str,
) -> tuple[str, str]:
    context = {
        "character_name": character_name,
        "user_persona_name": user_persona_name,
    }
    return (
        render_template(mode.premise_template, **context),
        render_template(mode.situation_template, **context),
    )


def validate_chat_mode_templates(mode: ChatMode) -> None:
    render_chat_mode(
        mode,
        character_name="キャラクター",
        user_persona_name="ユーザー",
    )


__all__ = [
    "TemplateError",
    "render_chat_mode",
    "render_template",
    "validate_chat_mode_templates",
]

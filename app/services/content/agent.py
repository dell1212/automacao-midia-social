"""Turning a plain-language brief into a proposed generation plan.

The autonomous part of the "agent" already exists and has for a while — the
automation scheduler generates proactively, the approval engine decides, the
dispatcher publishes, and every decision lands in the audit log under a
`system:` actor. What was missing is a way to *tell* it what to make.

This module is that one missing piece. It proposes; it never commits. The
human confirms the proposal, and only then does anything get created.
"""
import json
import re
from typing import List, Optional

from loguru import logger
from pydantic import BaseModel

from app.models.content import ContentPieceType
from app.services import llm

_MAX_BRIEF_LENGTH = 2000
_MAX_ITEMS = 10


class ProposedPiece(BaseModel):
    type: ContentPieceType
    generation_prompt: str
    narration_script: Optional[str] = None
    caption: Optional[str] = None


class AgentProposal(BaseModel):
    summary: str
    pieces: List[ProposedPiece]
    # True when the LLM was unreachable or returned something unusable and the
    # deterministic fallback produced this instead. The UI says so rather than
    # passing a canned plan off as the model's work.
    is_fallback: bool = False


_PROMPT = """Você é um planejador de conteúdo para redes sociais de uma clínica.

A partir do briefing abaixo, proponha até {max_items} peças de conteúdo.

Responda SOMENTE com um objeto JSON, sem texto ao redor, neste formato:
{{"summary": "uma frase resumindo o plano",
  "pieces": [
    {{"type": "image|video|audio",
      "generation_prompt": "descrição visual do que gerar",
      "narration_script": "texto falado, só para video/audio",
      "caption": "legenda do post"}}
  ]}}

Regras:
- `generation_prompt` descreve a IMAGEM ou VÍDEO a ser gerado, não o texto do post.
- `caption` é o texto que o público lê no feed.
- Use "image" quando não houver narração.
- Escreva em português do Brasil.

Briefing:
{brief}
"""


def _parse(response: str) -> Optional[AgentProposal]:
    """Same tolerance as _parse_social_metadata: models wrap JSON in prose or
    a markdown fence often enough that a strict parse throws away usable
    answers."""
    data = None
    try:
        data = json.loads(response)
    except Exception:
        match = re.search(r"\{.*\}", response or "", re.DOTALL)
        if match:
            try:
                data = json.loads(match.group())
            except Exception:
                return None
    if not isinstance(data, dict):
        return None

    raw_pieces = data.get("pieces")
    if not isinstance(raw_pieces, list) or not raw_pieces:
        return None

    pieces: List[ProposedPiece] = []
    for item in raw_pieces[:_MAX_ITEMS]:
        if not isinstance(item, dict):
            continue
        prompt = (item.get("generation_prompt") or "").strip()
        if not prompt:
            continue
        raw_type = (item.get("type") or "image").strip().lower()
        try:
            piece_type = ContentPieceType(raw_type)
        except ValueError:
            piece_type = ContentPieceType.image
        pieces.append(
            ProposedPiece(
                type=piece_type,
                generation_prompt=prompt,
                narration_script=(item.get("narration_script") or None),
                caption=(item.get("caption") or None),
            )
        )

    if not pieces:
        return None
    return AgentProposal(
        summary=(data.get("summary") or "Plano de conteúdo proposto.").strip(),
        pieces=pieces,
    )


def _fallback(brief: str) -> AgentProposal:
    """A usable proposal when the LLM is unavailable.

    One piece echoing the brief — enough for the human to edit into something
    real, and honest about being a fallback rather than a generated plan.
    """
    text = (brief or "").strip() or "Conteúdo para a campanha"
    return AgentProposal(
        summary="O modelo não respondeu; esta é uma proposta mínima a partir do briefing.",
        pieces=[
            ProposedPiece(
                type=ContentPieceType.image,
                generation_prompt=text[:500],
                caption=text[:500],
            )
        ],
        is_fallback=True,
    )


def propose_from_brief(brief: str) -> AgentProposal:
    brief = (brief or "").strip()[:_MAX_BRIEF_LENGTH]
    if not brief:
        return _fallback("")

    try:
        response = llm._generate_response(
            prompt=_PROMPT.format(brief=brief, max_items=_MAX_ITEMS)
        )
    except Exception as error:
        logger.warning(f"agent brief: LLM call failed ({type(error).__name__})")
        return _fallback(brief)

    if not response or response.startswith("Error:"):
        logger.warning("agent brief: LLM returned an empty or error response")
        return _fallback(brief)

    parsed = _parse(response)
    if parsed is None:
        logger.warning("agent brief: could not parse a proposal from the response")
        return _fallback(brief)
    return parsed

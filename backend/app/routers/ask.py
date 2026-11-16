"""The Ask page's endpoint: a question in, an answer (and how it was worked out) out."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.ai.chat import PrivacyError, ask
from app.ai.providers import AIError, AINotConfigured, Provider, get_provider
from app.db import get_session
from app.schemas import AskIn, AskOut, AskStep

router = APIRouter(tags=["ask"])


def provider_dependency() -> Provider:
    try:
        return get_provider()
    except AINotConfigured as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(e)) from None


@router.post("/ask")
def ask_question(
    body: AskIn,
    session: Annotated[Session, Depends(get_session)],
    provider: Annotated[Provider, Depends(provider_dependency)],
) -> AskOut:
    try:
        answer = ask(session, provider, body.question, [(t.role, t.text) for t in body.history])
    except PrivacyError as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from None
    except AIError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from None
    return AskOut(
        answer=answer.text,
        steps=[AskStep(tool=s.tool, arguments=s.arguments, result=s.result) for s in answer.steps],
    )

"""Application configuration - root APIRouter

Defines all FastAPI application endpoints.

Resources:
    1. https://fastapi.tiangolo.com/tutorial/bigger-applications

"""

from fastapi import APIRouter

from app.controllers import ping
from app.controllers.v1 import llm, video
from app.controllers.v1.content import (
    approval_rules,
    avatars,
    campaigns,
    clients,
    generation_templates,
    models,
    pieces,
    providers,
    publications,
    social_accounts,
    tenants,
    ui,
)

root_api_router = APIRouter()
root_api_router.include_router(ping.router)

# v1
root_api_router.include_router(video.router)
root_api_router.include_router(llm.router)

# v1 content
root_api_router.include_router(tenants.router)
root_api_router.include_router(clients.router)
root_api_router.include_router(social_accounts.router)
root_api_router.include_router(avatars.router)
root_api_router.include_router(campaigns.router)
root_api_router.include_router(approval_rules.router)
root_api_router.include_router(generation_templates.router)
root_api_router.include_router(pieces.router)
root_api_router.include_router(providers.router)
root_api_router.include_router(publications.router)
root_api_router.include_router(models.router)
root_api_router.include_router(ui.router)

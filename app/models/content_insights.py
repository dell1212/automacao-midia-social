from datetime import datetime
from typing import Optional

from sqlalchemy import JSON, Column
from sqlmodel import Field, SQLModel


class ContentPublicationInsight(SQLModel, table=True):
    """Um snapshot de engajamento por (publicação, coleta) — nunca sobrescrito.

    Um post publicado hoje continua acumulando curtida por dias; sobrescrever
    uma linha destruiria a resposta para "quando isso aconteceu". Uma coleta
    que falhou também vira linha, com as cinco métricas nulas e `error_code`
    preenchido — assim um token quebrado fica visível na mesma tabela em vez
    de virar silêncio, e "quando foi a última tentativa" não precisa de
    estado separado.

    Ver docs/superpowers/specs/2026-09-05-coleta-metricas-engajamento-design.md.
    """

    __tablename__ = "content_publication_insights"

    id: Optional[int] = Field(default=None, primary_key=True)
    tenant_id: int = Field(foreign_key="content_tenants.id", index=True)
    client_id: int = Field(foreign_key="content_clients.id", index=True)
    content_piece_id: int = Field(foreign_key="content_pieces.id", index=True)
    publication_id: int = Field(
        foreign_key="content_social_publications.id", index=True
    )
    social_account_id: int = Field(
        foreign_key="content_social_accounts.id", index=True
    )
    platform: str
    # Espelha ContentSocialPublication.publication_cycle: republicar uma peça
    # gera um post novo na plataforma, e as métricas do post antigo não podem
    # se misturar com as do novo.
    publication_cycle: int
    collected_at: datetime = Field(default_factory=datetime.utcnow)

    # Alcance (pessoas únicas) só existe de verdade no Instagram e no
    # Facebook. As outras quatro plataformas só publicam impressions (volume
    # de exibição, não de gente) — por isso as duas colunas são separadas e
    # nuláveis, nunca uma soma sob um rótulo só. Ver a tabela de métricas por
    # plataforma no design spec.
    reach: Optional[int] = None
    impressions: Optional[int] = None
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    # A resposta como chegou. As APIs adicionam campo sem avisar; quando um
    # número parecer errado, isto é a única forma de saber se o bug é nosso
    # ou deles.
    raw: dict = Field(default_factory=dict, sa_column=Column(JSON))

    error_code: Optional[str] = None
    error_message: Optional[str] = None

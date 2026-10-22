from collections.abc import Iterator

from fastapi import Request
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_sessionmaker(database_url: str) -> sessionmaker[Session]:
    return sessionmaker(create_engine(database_url, pool_pre_ping=True), expire_on_commit=False)


def get_session(request: Request) -> Iterator[Session]:
    """Uma sessão por requisição; cada rota faz o próprio commit."""
    with request.app.state.sessionmaker() as session:
        yield session

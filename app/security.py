import hashlib
import hmac
import secrets

# Tokens do MVP, sem login: admin_token (organizador) e invite_token (cada
# participante). São longos e aleatórios, e o banco guarda só o SHA-256: quem lê
# o banco não consegue se passar por ninguém. Com 256 bits de entropia, não
# precisa de sal nem de hash lento.

TOKEN_BYTES = 32


def new_token() -> str:
    return secrets.token_urlsafe(TOKEN_BYTES)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def token_matches(token: str, token_hash: str) -> bool:
    return hmac.compare_digest(hash_token(token), token_hash)

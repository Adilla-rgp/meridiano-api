import math
import threading
import time
from collections import deque
from collections.abc import Callable

from fastapi import HTTPException

from app.security import hash_token

# Limite simples de requisições por token nas rotas caras: interpretação do
# texto livre (que vai virar chamada a um LLM) e geração de planos (roda o motor).
# Janela deslizante em memória: vale por processo da API, o que basta enquanto
# ela roda com um só processo. Com vários, troque por um contador compartilhado.

WINDOW_SECONDS = 60.0


class RateLimiter:
    def __init__(
        self, limit: int, window: float = WINDOW_SECONDS, clock: Callable[[], float] = time.monotonic
    ):
        self.limit = limit
        self.window = window
        self.clock = clock
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def check(self, token: str) -> None:
        """Conta uma requisição do token. Passou do limite na janela: 429 com Retry-After."""
        if self.limit <= 0:
            return
        key = hash_token(token)
        now = self.clock()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window:
                hits.popleft()
            if len(hits) >= self.limit:
                retry_after = max(1, math.ceil(hits[0] + self.window - now))
                raise HTTPException(
                    429,
                    f"Muitas tentativas em pouco tempo. Tente de novo em {retry_after} segundos.",
                    headers={"Retry-After": str(retry_after)},
                )
            hits.append(now)
            self._prune(now)

    def _prune(self, now: float) -> None:
        """Esquece os tokens sem requisição na janela, para a memória não crescer sem limite."""
        expired = [key for key, hits in self._hits.items() if not hits or hits[-1] <= now - self.window]
        for key in expired:
            del self._hits[key]

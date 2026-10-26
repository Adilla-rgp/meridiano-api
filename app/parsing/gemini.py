from typing import Any

# Cliente do Gemini para o LLMParser: saída em JSON pelo schema de Extraction,
# temperatura 0, timeout curto e sem novas tentativas (a falha cai nas regras).


class GeminiClient:
    def __init__(self, api_key: str, model: str, timeout_seconds: float, client: Any = None):
        from google.genai import Client, types

        self.types = types
        self.model = model
        self.client = client or Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=int(timeout_seconds * 1000), retry_options=types.HttpRetryOptions(attempts=1)
            ),
        )

    def generate(self, *, system: str, prompt: str, schema: dict) -> str:
        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=self.types.GenerateContentConfig(
                system_instruction=system,
                response_mime_type="application/json",
                response_json_schema=schema,
                temperature=0,
            ),
        )
        if not response.text:
            raise ValueError("Resposta vazia do Gemini.")
        return response.text

import pytest
from fastapi.testclient import TestClient

from app.main import create_app
from tests.api.conftest import create_july_trip

# O front só avisa que o texto passa por um serviço de IA externo quando a API
# diz que interpreta com um LLM. O campo segue CONSTRAINT_PARSER.


@pytest.mark.parametrize("parser", ["rules", "llm"])
def test_trip_and_invite_report_the_configured_parser(client, settings, parser):
    # A fixture client apaga as viagens no fim, inclusive as criadas por este app.
    app = create_app(settings.model_copy(update={"constraint_parser": parser}))
    with TestClient(app) as configured:
        trip = create_july_trip(configured)

        trip_detail = configured.get(f"/trips/{trip.id}", headers=trip.admin)
        invite = configured.get(f"/invite/{trip.tokens['Eva']}")

    assert trip_detail.status_code == 200, trip_detail.text
    assert invite.status_code == 200, invite.text
    assert trip_detail.json()["constraint_parser"] == parser
    assert invite.json()["constraint_parser"] == parser


def test_default_parser_is_rules(client, july):
    detail = client.get(f"/trips/{july.id}", headers=july.admin).json()
    assert detail["constraint_parser"] == "rules"
    assert client.get(f"/invite/{july.tokens['Ana']}").json()["constraint_parser"] == "rules"

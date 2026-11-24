"""Privacy Policy / Terms of Service pages.

TikTok's app review rejects: the two links pointing at the same document, an operating entity that differs
from the verified developer entity, and unfinished placeholders. These tests pin all three, for every
entity a deployment can be configured with.
"""
from typing import get_args

import pytest

from app.core.config import Settings
from app.legal import ENTITIES, FACTS, facts, render


@pytest.mark.parametrize("path,title", [("/privacy", "Privacy Policy"), ("/terms", "Terms of Service")])
async def test_page_served_publicly(client, path, title):
    r = await client.get(path)  # no auth header: reviewers open these in a plain browser
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    assert f"SailReels {title}" in r.text
    assert FACTS["entity_name"] == "SAILSON PTE LTD" and FACTS["entity_name"] in r.text
    assert "BANG ENTERTAINMENT" not in r.text  # SailShort / former ZorvTales entity, not SailReels
    assert "82-5480616" not in r.text


async def test_two_distinct_documents_linking_each_other(client):
    privacy, terms = (await client.get("/privacy")).text, (await client.get("/terms")).text
    assert privacy != terms
    assert 'href="/terms"' in privacy
    assert 'href="/privacy"' in terms


@pytest.mark.parametrize("entity", sorted(ENTITIES))
@pytest.mark.parametrize("page", ["privacy", "terms"])
def test_every_entity_renders_completely(entity, page):
    values = facts(entity, "TestApp", "help@example.com")
    text = render(page, values)
    assert "TODO" not in text
    assert "$" not in text.replace("USD", ""), "unfilled placeholder"
    assert values["entity_name"] in text and values["entity_address"] in text
    # Another entity's identity or home jurisdiction must never leak into this one's documents.
    for other, other_values in ENTITIES.items():
        if other != entity:
            assert other_values["entity_name"] not in text
            if other_values["registration_line"]:
                assert other_values["registration_line"].replace("<br>", "") not in text
            if page == "privacy":
                assert f"We are based in {other_values['home_base']}" not in text


def test_hk_privacy_uses_hk_law():
    text = render("privacy", facts("sailson_hk", "SailTale", "help@example.com"))
    assert "Personal Data (Privacy) Ordinance" in text and "PDPA" not in text
    assert "SailTale Privacy Policy" in text
    assert "82-5480616" not in text and "BANG ENTERTAINMENT" not in text


def test_us_privacy_and_terms_use_bang_facts():
    values = facts("bang_us", "SailShort", "user1@example.com")
    privacy = render("privacy", values)
    terms = render("terms", values)
    for text in (privacy, terms):
        assert "BANG ENTERTAINMENT INC." in text
        assert "100 S. Birch Rd., Suite 901, Jackson Tower, Fort Lauderdale, FL 33316, US" in text
        assert "Company registration number: 82-5480616" in text
        assert "user1@example.com" in text
        assert "SAILSON PTE LTD" not in text and "Sailson HK Limited" not in text
        assert "PDPA" not in text and "Personal Data (Privacy) Ordinance" not in text
    assert "SailShort Privacy Policy" in privacy
    assert "We are based in Florida, United States" in privacy
    assert "We are a Florida company" in privacy
    assert "laws of the State of Florida" in terms
    assert "courts of the State of Florida" in terms


def test_legal_entity_setting_matches_entities():
    assert set(get_args(Settings.model_fields["legal_entity"].annotation)) == set(ENTITIES)


def test_registration_line_is_omitted_when_empty():
    text = render("privacy", facts("sailson_sg", "SailReels", "help@example.com"))
    assert "Company registration number" not in text
    assert "408538<br>Email" in text


async def test_not_in_openapi_contract(client):
    paths = (await client.get("/openapi.json")).json()["paths"]
    assert "/privacy" not in paths and "/terms" not in paths

"""Privacy Policy and Terms of Service pages, linked from the Dev Portal (ppLink / tosLink).

TikTok's review requires two *separate* documents whose operating entity matches the verified developer
entity, and whose governing law has a real connection to the users / the entity. The same code serves
several apps under different entities, so each entity's facts — including its home-jurisdiction privacy
wording — live in ENTITIES below, and a deployment picks one with LEGAL_ENTITY. Edit facts here, not in
the HTML. Legal wording is curated in code on purpose: it is not free text in a server .env.

The HTML uses string.Template ($name) placeholders. substitute() raises on any missing key, so a typo in
a template fails at import time (and in tests) instead of shipping a literal "$foo" to users.
"""
from pathlib import Path
from string import Template

from app.core.config import get_settings

ENTITIES: dict[str, dict[str, str]] = {
    # SailReels. Must match the entity verified in the Dev Portal for this app.
    # BANG ENTERTAINMENT INC. is SailShort (bang_us), and was also ZorvTales'; do not use it here.
    "sailson_sg": {
        "entity_name": "SAILSON PTE LTD",
        "entity_address": "8 Ubi Road 2, #08-16, Zervex, Singapore 408538",
        "registration_line": "",
        "home_base": "Singapore",
        # Governing law follows the operating entity (TikTok requires a real connection).
        "governing_law": "Singapore",
        "venue": "Singapore",
        "home_rights": (
            "<b>Singapore.</b> We are a Singapore company and handle personal information in accordance with "
            "the Personal Data Protection Act 2012 (PDPA). You may withdraw consent, or request access to or "
            "correction of your personal data, by contacting our Data Protection Officer at "
            '<a href="mailto:$contact_email">$contact_email</a>. Withdrawing consent may mean we can no longer '
            "provide parts of the Service to you."
        ),
    },
    # SailTale.
    "sailson_hk": {
        "entity_name": "Sailson HK Limited",
        "entity_address": "Room 1307, 13/F, Kenbo Commercial Building, 335-339 Queen's Road West, Hong Kong",
        "registration_line": "",
        "home_base": "Hong Kong",
        "governing_law": "the Hong Kong Special Administrative Region",
        "venue": "the Hong Kong Special Administrative Region",
        "home_rights": (
            "<b>Hong Kong.</b> We are a Hong Kong company and handle personal data in accordance with the "
            "Personal Data (Privacy) Ordinance (Cap. 486). You may request access to or correction of your "
            "personal data by contacting our Data Protection Officer at "
            '<a href="mailto:$contact_email">$contact_email</a>. We may charge a fee for a data access request '
            "where the Ordinance allows."
        ),
    },
    # SailShort. US company; not the Singapore or Hong Kong Sailson entities.
    "bang_us": {
        "entity_name": "BANG ENTERTAINMENT INC.",
        "entity_address": "100 S. Birch Rd., Suite 901, Jackson Tower, Fort Lauderdale, FL 33316, US",
        # Must end with <br>. The contact template is ${registration_line}Email, so a missing break
        # would glue this line to "Email". Entities without a number we were given use "".
        "registration_line": "Company registration number: 82-5480616<br>",
        "home_base": "Florida, United States",
        "governing_law": "the State of Florida",
        "venue": "the State of Florida",
        "home_rights": (
            "<b>United States.</b> We are a Florida company and handle personal information in accordance with "
            "applicable United States federal and state privacy laws. You may request access to, correction of, "
            "or deletion of your personal information, or appeal a decision on such a request, by contacting our "
            "Data Protection Officer at "
            '<a href="mailto:$contact_email">$contact_email</a>.'
        ),
    },
}

_CSS = (
    "body{margin:0;background:#fff;color:#1d1d1f;font:16px/1.6 -apple-system,BlinkMacSystemFont,'Segoe UI',"
    "Roboto,Helvetica,Arial,sans-serif}main{max-width:760px;margin:0 auto;padding:32px 20px 64px}"
    "h1{font-size:28px;line-height:1.25;margin:0 0 4px}h2{font-size:20px;margin:32px 0 8px}"
    "h3{font-size:16px;margin:20px 0 4px}.meta{color:#6e6e73;margin:0 0 24px}ul{padding-left:22px}"
    "li{margin:6px 0}a{color:#0066cc}"
)

_DIR = Path(__file__).parent


def facts(entity: str, app_name: str, contact_email: str) -> dict[str, str]:
    base = {"app_name": app_name, "contact_email": contact_email, "effective_date": "October 29, 2026"}
    entry = ENTITIES[entity]
    # home_rights itself contains $contact_email; resolve it before it lands in the page template.
    return {**base, **entry, "home_rights": Template(entry["home_rights"]).substitute(base)}


def render(name: str, values: dict[str, str]) -> str:
    return Template((_DIR / f"{name}.html").read_text(encoding="utf-8")).substitute(values, css=_CSS)


_s = get_settings()
FACTS = facts(_s.legal_entity, _s.app_name, _s.legal_contact_email)
PRIVACY_HTML = render("privacy", FACTS)
TERMS_HTML = render("terms", FACTS)

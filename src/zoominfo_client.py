import logging
import time
from typing import Optional

import requests

from src.config import ZOOMINFO_BASE_URL, ZOOMINFO_USERNAME, ZOOMINFO_PASSWORD
from src.models import (
    Attendee,
    CompanyData,
    ContactProfile,
    IntentSignal,
    NewsItem,
    TechStack,
    ZoomInfoEnrichment,
)

logger = logging.getLogger(__name__)

# ZoomInfo API v1 endpoints under /gtm/data/v1
ENRICH_CONTACT_PATH = "/gtm/data/v1/contacts/enrich"
SEARCH_CONTACT_PATH = "/gtm/data/v1/contacts/search"
ENRICH_COMPANY_PATH = "/gtm/data/v1/companies/enrich"
SEARCH_COMPANY_PATH = "/gtm/data/v1/companies/search"
INTENT_PATH = "/gtm/data/v1/intent/search"
NEWS_PATH = "/gtm/data/v1/news/search"
TECH_PATH = "/gtm/data/v1/technographics/search"

MAX_RETRIES = 3
RETRY_DELAY = 2  # seconds


class ZoomInfoClient:
    """Client for ZoomInfo API with Bearer token authentication."""

    def __init__(
        self,
        base_url: str = ZOOMINFO_BASE_URL,
        username: str = ZOOMINFO_USERNAME,
        password: str = ZOOMINFO_PASSWORD,
    ):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.access_token: Optional[str] = None
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        # Cache: domain -> CompanyData to avoid duplicate company lookups
        self._company_cache: dict[str, CompanyData] = {}
        # Cache: domain -> company_id
        self._company_id_cache: dict[str, str] = {}

    def authenticate(self) -> None:
        """Authenticate and obtain a Bearer token.

        Uses username/password JWT flow. Swap this method out if you
        move to OAuth2/PKCE in the future.
        """
        if not self.username or not self.password:
            raise ValueError(
                "ZoomInfo credentials not configured. "
                "Set ZOOMINFO_USERNAME and ZOOMINFO_PASSWORD in .env"
            )

        logger.info("Authenticating with ZoomInfo API...")
        resp = self._post(
            "/authenticate",
            json={"username": self.username, "password": self.password},
            auth_required=False,
        )
        self.access_token = resp.get("jwt", resp.get("access_token", ""))
        if not self.access_token:
            raise RuntimeError("ZoomInfo authentication failed — no token returned")
        self.session.headers["Authorization"] = f"Bearer {self.access_token}"
        logger.info("ZoomInfo authentication successful")

    def _post(
        self,
        path: str,
        json: dict,
        auth_required: bool = True,
    ) -> dict:
        """Make a POST request with retry logic."""
        if auth_required and not self.access_token:
            self.authenticate()

        url = f"{self.base_url}{path}"

        for attempt in range(MAX_RETRIES):
            try:
                resp = self.session.post(url, json=json, timeout=30)
                if resp.status_code == 401 and auth_required and attempt == 0:
                    logger.warning("ZoomInfo token expired, re-authenticating...")
                    self.authenticate()
                    continue
                resp.raise_for_status()
                return resp.json()
            except requests.exceptions.HTTPError as e:
                if resp.status_code == 429:
                    wait = RETRY_DELAY * (2 ** attempt)
                    logger.warning("Rate limited, waiting %ds...", wait)
                    time.sleep(wait)
                    continue
                logger.error("ZoomInfo API error: %s", e)
                raise
            except requests.exceptions.RequestException as e:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                logger.error("ZoomInfo request failed: %s", e)
                raise

        return {}

    # --- Contact endpoints ---

    def search_contact(self, email: str) -> Optional[ContactProfile]:
        """Search for a contact by email address."""
        try:
            data = self._post(
                SEARCH_CONTACT_PATH,
                json={
                    "filter": {"emailAddress": [email]},
                    "outputFields": [
                        "id", "fullName", "jobTitle", "phone",
                        "linkedinUrl", "employmentHistory", "education",
                    ],
                    "rpp": 1,
                },
            )
            contacts = data.get("data", [])
            if not contacts:
                logger.info("No ZoomInfo contact found for %s", email)
                return None
            return self._parse_contact(contacts[0])
        except Exception as e:
            logger.warning("Failed to search contact %s: %s", email, e)
            return None

    def enrich_contact(self, contact_id: str) -> Optional[ContactProfile]:
        """Enrich a contact by ZoomInfo contact ID."""
        try:
            data = self._post(
                ENRICH_CONTACT_PATH,
                json={
                    "matchPersonInput": [{"personId": contact_id}],
                    "outputFields": [
                        "id", "fullName", "jobTitle", "phone",
                        "linkedinUrl", "employmentHistory", "education",
                    ],
                },
            )
            results = data.get("data", [])
            if not results:
                return None
            return self._parse_contact(results[0])
        except Exception as e:
            logger.warning("Failed to enrich contact %s: %s", contact_id, e)
            return None

    # --- Company endpoints ---

    def search_company(self, domain: str) -> Optional[CompanyData]:
        """Search for a company by domain. Results are cached."""
        if domain in self._company_cache:
            return self._company_cache[domain]

        try:
            data = self._post(
                SEARCH_COMPANY_PATH,
                json={
                    "filter": {"websiteUrl": [domain]},
                    "outputFields": [
                        "id", "name", "website", "revenue", "employeeCount",
                        "industry", "funding", "description", "street",
                        "city", "state", "country", "yearFounded",
                    ],
                    "rpp": 1,
                },
            )
            companies = data.get("data", [])
            if not companies:
                logger.info("No ZoomInfo company found for %s", domain)
                return None
            company = self._parse_company(companies[0])
            self._company_cache[domain] = company
            company_id = companies[0].get("id", "")
            if company_id:
                self._company_id_cache[domain] = str(company_id)
            return company
        except Exception as e:
            logger.warning("Failed to search company %s: %s", domain, e)
            return None

    # --- Technographics ---

    def get_tech_stack(self, domain: str) -> list[TechStack]:
        """Get technology stack for a company by domain."""
        company_id = self._company_id_cache.get(domain)
        if not company_id:
            # Try to get company first to populate cache
            self.search_company(domain)
            company_id = self._company_id_cache.get(domain)
        if not company_id:
            return []

        try:
            data = self._post(
                TECH_PATH,
                json={
                    "filter": {"companyId": [company_id]},
                    "outputFields": ["category", "product"],
                    "rpp": 100,
                },
            )
            techs = data.get("data", [])
            # Group by category
            categories: dict[str, list[str]] = {}
            for tech in techs:
                cat = tech.get("category", "Other")
                product = tech.get("product", "")
                if product:
                    categories.setdefault(cat, []).append(product)
            return [
                TechStack(category=cat, technologies=prods)
                for cat, prods in categories.items()
            ]
        except Exception as e:
            logger.warning("Failed to get tech stack for %s: %s", domain, e)
            return []

    # --- Intent signals ---

    def get_intent_signals(self, domain: str) -> list[IntentSignal]:
        """Get buying intent signals for a company."""
        company_id = self._company_id_cache.get(domain)
        if not company_id:
            self.search_company(domain)
            company_id = self._company_id_cache.get(domain)
        if not company_id:
            return []

        try:
            data = self._post(
                INTENT_PATH,
                json={
                    "filter": {"companyId": [company_id]},
                    "outputFields": ["topic", "score", "signalDate"],
                    "rpp": 25,
                },
            )
            intents = data.get("data", [])
            return [
                IntentSignal(
                    topic=item.get("topic", ""),
                    score=item.get("score", 0),
                    signal_date=item.get("signalDate", ""),
                )
                for item in intents
                if item.get("topic")
            ]
        except Exception as e:
            logger.warning("Failed to get intent signals for %s: %s", domain, e)
            return []

    # --- News / Scoops ---

    def get_news(self, domain: str) -> list[NewsItem]:
        """Get recent news and scoops for a company."""
        company_id = self._company_id_cache.get(domain)
        if not company_id:
            self.search_company(domain)
            company_id = self._company_id_cache.get(domain)
        if not company_id:
            return []

        try:
            data = self._post(
                NEWS_PATH,
                json={
                    "filter": {"companyId": [company_id]},
                    "outputFields": [
                        "headline", "summary", "publishedDate", "url", "source",
                    ],
                    "rpp": 10,
                },
            )
            news_items = data.get("data", [])
            return [
                NewsItem(
                    headline=item.get("headline", ""),
                    summary=item.get("summary", ""),
                    date=item.get("publishedDate", ""),
                    url=item.get("url", ""),
                    source=item.get("source", ""),
                )
                for item in news_items
                if item.get("headline")
            ]
        except Exception as e:
            logger.warning("Failed to get news for %s: %s", domain, e)
            return []

    # --- Full enrichment orchestrator ---

    def enrich_attendee(self, attendee: Attendee) -> ZoomInfoEnrichment:
        """Run full ZoomInfo enrichment for a single attendee.

        Fetches contact profile, company data, tech stack, intent signals,
        and news. Each sub-call is wrapped to gracefully degrade on failure.
        """
        logger.info("Enriching attendee: %s (%s)", attendee.name, attendee.email)

        contact = self.search_contact(attendee.email)
        company = self.search_company(attendee.domain)
        tech_stack = self.get_tech_stack(attendee.domain)
        intent_signals = self.get_intent_signals(attendee.domain)
        news = self.get_news(attendee.domain)

        return ZoomInfoEnrichment(
            contact=contact,
            company=company,
            tech_stack=tech_stack,
            intent_signals=intent_signals,
            news=news,
        )

    # --- Parsers ---

    @staticmethod
    def _parse_contact(raw: dict) -> ContactProfile:
        location_parts = [raw.get("city", ""), raw.get("state", "")]
        return ContactProfile(
            full_name=raw.get("fullName", ""),
            title=raw.get("jobTitle", ""),
            phone=raw.get("phone", raw.get("directPhone", "")),
            linkedin_url=raw.get("linkedinUrl", ""),
            employment_history=raw.get("employmentHistory", []),
            education=raw.get("education", []),
            zoominfo_contact_id=str(raw.get("id", "")),
        )

    @staticmethod
    def _parse_company(raw: dict) -> CompanyData:
        hq_parts = [
            raw.get("city", ""),
            raw.get("state", ""),
            raw.get("country", ""),
        ]
        headquarters = ", ".join(p for p in hq_parts if p)
        revenue = raw.get("revenue", "")
        if isinstance(revenue, (int, float)):
            revenue = f"${revenue:,.0f}"

        employee_count = raw.get("employeeCount", "")
        if isinstance(employee_count, (int, float)):
            employee_count = f"{employee_count:,.0f}"

        return CompanyData(
            name=raw.get("name", ""),
            domain=raw.get("website", ""),
            revenue=str(revenue),
            employee_count=str(employee_count),
            industry=raw.get("industry", ""),
            funding=str(raw.get("funding", "")),
            description=raw.get("description", ""),
            headquarters=headquarters,
            founded_year=str(raw.get("yearFounded", "")),
            zoominfo_company_id=str(raw.get("id", "")),
        )

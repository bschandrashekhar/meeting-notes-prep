from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field


class Attendee(BaseModel):
    name: str
    email: str
    domain: str = ""
    is_organizer: bool = False

    def model_post_init(self, __context: object) -> None:
        if not self.domain and self.email:
            self.domain = self.email.split("@")[-1]


class Meeting(BaseModel):
    title: str
    start_time: datetime
    end_time: datetime
    location: str = ""
    description: str = ""
    attendees: list[Attendee] = Field(default_factory=list)
    meet_link: str = ""
    calendar_id: str = ""


# --- ZoomInfo enrichment models ---


class ContactProfile(BaseModel):
    full_name: str = ""
    title: str = ""
    phone: str = ""
    linkedin_url: str = ""
    employment_history: list[dict] = Field(default_factory=list)
    education: list[dict] = Field(default_factory=list)
    zoominfo_contact_id: Optional[str] = None


class CompanyData(BaseModel):
    name: str = ""
    domain: str = ""
    revenue: str = ""
    employee_count: str = ""
    industry: str = ""
    funding: str = ""
    description: str = ""
    headquarters: str = ""
    founded_year: str = ""
    zoominfo_company_id: Optional[str] = None


class TechStack(BaseModel):
    category: str
    technologies: list[str] = Field(default_factory=list)


class IntentSignal(BaseModel):
    topic: str
    score: int = 0
    signal_date: str = ""


class NewsItem(BaseModel):
    headline: str
    summary: str = ""
    date: str = ""
    url: str = ""
    source: str = ""


class ZoomInfoEnrichment(BaseModel):
    contact: Optional[ContactProfile] = None
    company: Optional[CompanyData] = None
    tech_stack: list[TechStack] = Field(default_factory=list)
    intent_signals: list[IntentSignal] = Field(default_factory=list)
    news: list[NewsItem] = Field(default_factory=list)


# --- Brief models ---


class AttendeeInsight(BaseModel):
    attendee: Attendee
    zoominfo: Optional[ZoomInfoEnrichment] = None
    web_research_summary: str = ""
    talking_points: list[str] = Field(default_factory=list)


class MeetingBrief(BaseModel):
    meeting: Meeting
    attendee_insights: list[AttendeeInsight] = Field(default_factory=list)
    key_themes: list[str] = Field(default_factory=list)
    suggested_questions: list[str] = Field(default_factory=list)


class DailyBrief(BaseModel):
    target_date: date
    meeting_briefs: list[MeetingBrief] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=datetime.now)

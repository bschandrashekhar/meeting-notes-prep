"""Pydantic data models for the meeting preparation pipeline."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Attendee(BaseModel):
    """A single meeting attendee parsed from the calendar description."""
    name: str
    title: str = ""
    linkedin_url: str = ""


class MeetingInput(BaseModel):
    """Raw meeting parsed from Google Calendar (before enrichment)."""
    subject: str
    agenda: str
    company_information: str
    company_tech_info: str = ""
    prospect_industry: str
    company_country: str
    attendees: list[Attendee] = Field(default_factory=list)
    attachments: list[dict[str, Any]] = Field(default_factory=list)
    start_time: datetime
    end_time: datetime
    calendar_event_id: str = ""


class EnrichedMeeting(BaseModel):
    """Meeting after enrichment (Stage 1 complete)."""
    input: MeetingInput

    # Derived fields
    prospect_context: str = ""
    prospect_technologies: list[str] = Field(default_factory=list)
    normalized_country: str = ""

    # Matching results
    case_study_matches: list[dict[str, Any]] = Field(default_factory=list)
    client_matches: list[dict[str, Any]] = Field(default_factory=list)
    brand_result: dict[str, Any] = Field(default_factory=dict)

    # Claude-generated conversational bullets for each case study
    case_study_narrative: list[str] = Field(default_factory=list)

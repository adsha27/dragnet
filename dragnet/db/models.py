import enum
from datetime import datetime
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class ATSType(str, enum.Enum):
    greenhouse = "greenhouse"
    lever = "lever"
    ashby = "ashby"
    naukri = "naukri"
    linkedin = "linkedin"
    unknown = "unknown"


class RemoteScope(str, enum.Enum):
    global_ = "global"
    us_only = "us_only"
    eu_only = "eu_only"
    specific_countries = "specific_countries"
    unknown = "unknown"


class IndiaEligible(str, enum.Enum):
    yes = "yes"
    no = "no"
    likely_yes = "likely_yes"
    likely_no = "likely_no"
    unknown = "unknown"


class Seniority(str, enum.Enum):
    entry = "entry"
    mid = "mid"
    senior = "senior"
    staff = "staff"
    lead = "lead"
    manager = "manager"
    unknown = "unknown"


class ApplicationState(str, enum.Enum):
    discovered = "discovered"
    eligible = "eligible"
    ineligible = "ineligible"
    tailored = "tailored"
    human_review = "human_review"
    human_rejected = "human_rejected"
    submitted = "submitted"
    screened = "screened"
    interviewing = "interviewing"
    offer = "offer"
    rejected = "rejected"
    ghosted = "ghosted"


class FailureType(str, enum.Enum):
    captcha = "captcha"
    login_wall = "login_wall"
    unknown_field = "unknown_field"
    submit_failed = "submit_failed"
    rate_limited = "rate_limited"


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(255), nullable=False)
    ats_type: Mapped[ATSType] = mapped_column(Enum(ATSType), nullable=False)
    website: Mapped[str | None] = mapped_column(String(500))
    employee_count: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    postings: Mapped[list["Posting"]] = relationship(back_populates="company")
    founder_contacts: Mapped[list["FounderContact"]] = relationship(back_populates="company")

    __table_args__ = (UniqueConstraint("slug", "ats_type", name="uq_company_slug_ats"),)


class Posting(Base):
    __tablename__ = "postings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    external_id: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    location: Mapped[str | None] = mapped_column(String(500))
    apply_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    raw_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    content_text: Mapped[str | None] = mapped_column(Text)

    # Classification results (M2)
    remote_scope: Mapped[RemoteScope | None] = mapped_column(Enum(RemoteScope))
    india_eligible: Mapped[IndiaEligible | None] = mapped_column(Enum(IndiaEligible))
    comp_min: Mapped[int | None] = mapped_column(Integer)
    comp_max: Mapped[int | None] = mapped_column(Integer)
    seniority: Mapped[Seniority | None] = mapped_column(Enum(Seniority))
    stack_tags: Mapped[list[str] | None] = mapped_column(JSON)
    eor_signals: Mapped[list[str] | None] = mapped_column(JSON)
    stack_match_score: Mapped[float | None] = mapped_column(Float)
    rank_score: Mapped[float | None] = mapped_column(Float)
    classified_at: Mapped[datetime | None] = mapped_column(DateTime)

    discovered_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    dedup_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)

    company: Mapped[Company] = relationship(back_populates="postings")
    application: Mapped["Application | None"] = relationship(back_populates="posting", uselist=False)


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    posting_id: Mapped[int] = mapped_column(ForeignKey("postings.id"), nullable=False, unique=True)
    state: Mapped[ApplicationState] = mapped_column(Enum(ApplicationState), nullable=False, default=ApplicationState.discovered)

    # Tailoring outputs
    resume_path: Mapped[str | None] = mapped_column(String(1000))
    resume_typst_hash: Mapped[str | None] = mapped_column(String(64))
    answers: Mapped[dict[str, str] | None] = mapped_column(JSON)
    firewall_passed: Mapped[bool | None] = mapped_column(Boolean)

    # Submission
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime)
    confirmation_screenshot: Mapped[str | None] = mapped_column(String(1000))
    failure_type: Mapped[FailureType | None] = mapped_column(Enum(FailureType))
    failure_detail: Mapped[str | None] = mapped_column(Text)

    # CRM tracking
    last_state_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    follow_up_sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    posting: Mapped[Posting] = relationship(back_populates="application")
    state_history: Mapped[list["StateTransition"]] = relationship(back_populates="application")


class StateTransition(Base):
    __tablename__ = "state_transitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    application_id: Mapped[int] = mapped_column(ForeignKey("applications.id"), nullable=False)
    from_state: Mapped[ApplicationState | None] = mapped_column(Enum(ApplicationState))
    to_state: Mapped[ApplicationState] = mapped_column(Enum(ApplicationState), nullable=False)
    trigger: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    application: Mapped[Application] = relationship(back_populates="state_history")


class AnswerCache(Base):
    __tablename__ = "answer_cache"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    company: Mapped[str] = mapped_column(String(255), nullable=False)
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    answer_text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    __table_args__ = (UniqueConstraint("question_hash", "company", name="uq_answer_cache"),)


class FounderContact(Base):
    __tablename__ = "founder_contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    title: Mapped[str | None] = mapped_column(String(255))
    email: Mapped[str | None] = mapped_column(String(255))
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False)
    linkedin_url: Mapped[str | None] = mapped_column(String(500))
    enriched_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    company: Mapped[Company] = relationship(back_populates="founder_contacts")
    outreach_emails: Mapped[list["OutreachEmail"]] = relationship(back_populates="contact")


class OutreachEmail(Base):
    __tablename__ = "outreach_emails"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    contact_id: Mapped[int] = mapped_column(ForeignKey("founder_contacts.id"), nullable=False)
    subject: Mapped[str] = mapped_column(String(500), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    gmail_message_id: Mapped[str | None] = mapped_column(String(255))
    sent_at: Mapped[datetime | None] = mapped_column(DateTime)
    replied_at: Mapped[datetime | None] = mapped_column(DateTime)
    reply_text: Mapped[str | None] = mapped_column(Text)

    contact: Mapped[FounderContact] = relationship(back_populates="outreach_emails")

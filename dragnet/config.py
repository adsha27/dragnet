from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM — required for eligibility classification and resume tailoring
    anthropic_api_key: str = ""

    # Search
    exa_api_key: str

    # Browser (Browserbase removed; local Playwright used instead)
    browserbase_api_key: str = ""
    browserbase_project_id: str = ""

    # DB
    database_url: str = "postgresql+asyncpg://postgres:dragnet@localhost:5432/dragnet"

    # Gmail
    gmail_credentials_file: Path = Path("credentials.json")
    gmail_token_file: Path = Path("token.json")
    gmail_sender_address: str = ""

    # Identity
    applicant_name: str = "Aditya Sharma"
    applicant_email: str = ""
    applicant_phone: str = "+91 98293 68698"
    applicant_github: str = "https://github.com/adsha27"
    applicant_linkedin: str = "https://linkedin.com/in/adsha/"
    applicant_location: str = "Delhi, India"

    # LinkedIn credentials for Easy Apply automation
    linkedin_email: str = ""
    linkedin_password: str = ""

    # Reddit OAuth (register a free app at reddit.com/prefs/apps → script type)
    reddit_client_id: str = ""
    reddit_client_secret: str = ""

    # Limits
    max_concurrent_sessions: int = 3
    max_applications_per_company_per_day: int = 1
    max_founder_emails_per_day: int = 15
    ghost_timeout_days: int = 14

    # Approval gate
    approval_gate_count: int = 50
    approval_sample_rate: float = 0.10

    # Models — local Qwen3 via Ollama
    ollama_model: str = "qwen3:14b"
    ollama_base_url: str = "http://localhost:11434/v1"

    # Kept for fallback only — primary is Ollama
    classification_model: str = "claude-haiku-4-5-20251001"
    tailoring_model: str = "claude-sonnet-4-6"

    # Project root
    @property
    def root(self) -> Path:
        return Path(__file__).parent.parent

    @property
    def facts_path(self) -> Path:
        return self.root / "facts.yaml"

    @property
    def output_dir(self) -> Path:
        d = self.root / "output"
        d.mkdir(exist_ok=True)
        return d

    @property
    def screenshots_dir(self) -> Path:
        d = self.output_dir / "screenshots"
        d.mkdir(exist_ok=True)
        return d

    @property
    def resumes_dir(self) -> Path:
        d = self.output_dir / "resumes"
        d.mkdir(exist_ok=True)
        return d


settings = Settings()

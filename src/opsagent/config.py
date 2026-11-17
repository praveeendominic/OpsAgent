"""Settings for OpsAgent. Everything comes from the environment or a .env file at the project root."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]
PACKAGE_ROOT = Path(__file__).resolve().parent


def _find_env_file() -> Path | None:
    for candidate in (Path.cwd() / ".env", PROJECT_ROOT / ".env"):
        if candidate.exists():
            return candidate
    return None


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=_find_env_file(), env_file_encoding="utf-8", extra="ignore")

    # Azure OpenAI (LiteLLM "azure/" route)
    azure_api_key: str = Field(default="", alias="AZURE_API_KEY")
    azure_api_base: str = Field(default="", alias="AZURE_API_BASE")
    azure_api_version: str = Field(default="2024-10-21", alias="AZURE_API_VERSION")
    azure_deployment: str = Field(default="gpt-4o", alias="AZURE_DEPLOYMENT")
    llm_temperature: float = Field(default=0.1, alias="OPSAGENT_LLM_TEMPERATURE")

    # Notifications
    teams_webhook_url: str = Field(default="", alias="TEAMS_WEBHOOK_URL")
    smtp_host: str = Field(default="", alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_user: str = Field(default="", alias="SMTP_USER")
    smtp_password: str = Field(default="", alias="SMTP_PASSWORD")
    smtp_from: str = Field(default="", alias="SMTP_FROM")
    smtp_to: str = Field(default="", alias="SMTP_TO")
    # ServiceNow ITSM (Table API). Instance is the subdomain (dev12345) or the full https URL.
    servicenow_instance: str = Field(default="", alias="SERVICENOW_INSTANCE")
    servicenow_user: str = Field(default="", alias="SERVICENOW_USER")
    servicenow_password: str = Field(default="", alias="SERVICENOW_PASSWORD")
    servicenow_token: str = Field(default="", alias="SERVICENOW_TOKEN")
    servicenow_assignment_group: str = Field(default="", alias="SERVICENOW_ASSIGNMENT_GROUP")
    servicenow_caller_id: str = Field(default="", alias="SERVICENOW_CALLER_ID")
    servicenow_category: str = Field(default="software", alias="SERVICENOW_CATEGORY")
    servicenow_resolve_on_close: bool = Field(default=False, alias="SERVICENOW_RESOLVE_ON_CLOSE")
    # xMatters heads-up call: the trigger URL (the instance's Send Alert form under /api/xm/1/forms/<id>/triggers, or
    # a Flow Designer trigger) raises one event at stage 1; the xM API credentials (a REST user, or an API key id and
    # secret) authenticate the form trigger and terminate the event on close.
    xmatters_trigger_url: str = Field(default="", alias="XMATTERS_TRIGGER_URL")
    xmatters_user: str = Field(default="", alias="XMATTERS_USER")
    xmatters_password: str = Field(default="", alias="XMATTERS_PASSWORD")
    xmatters_recipients: str = Field(default="", alias="XMATTERS_RECIPIENTS")
    # Devices to ring, comma-separated xMatters device names ("Mobile Phone, Work Phone"); empty notifies every
    # device the recipients own, email included.
    xmatters_devices: str = Field(default="", alias="XMATTERS_DEVICES")
    # "payload_key=Form Property" pairs, comma-separated, for forms whose layout does not carry OpsAgent's property
    # names (the stock Send Alert form: "summary=Summary,details=Message"). Empty sends every key under its own name.
    xmatters_properties: str = Field(default="", alias="XMATTERS_PROPERTIES")
    xmatters_terminate_on_close: bool = Field(default=True, alias="XMATTERS_TERMINATE_ON_CLOSE")

    # Optional integrations and feature flags
    aws_docs_mcp: bool = Field(default=False, alias="AWS_DOCS_MCP")
    self_healing: bool = Field(default=False, alias="OPSAGENT_SELF_HEALING")
    langfuse_public_key: str = Field(default="", alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: str = Field(default="", alias="LANGFUSE_SECRET_KEY")
    langfuse_host: str = Field(default="", alias="LANGFUSE_HOST")

    # Paths (relative paths resolve against the project root)
    state_dir: Path = Field(default=Path(".opsagent"), alias="OPSAGENT_STATE_DIR")
    outbox_dir: Path = Field(default=Path("outbox"), alias="OPSAGENT_OUTBOX_DIR")
    runs_dir: Path = Field(default=Path("runs"), alias="OPSAGENT_RUNS_DIR")
    inventory_file: Path = Field(default=Path("config/instances.yaml"), alias="OPSAGENT_INVENTORY")
    severity_policy_file: Path = Field(default=Path("config/severity.yaml"), alias="OPSAGENT_SEVERITY_POLICY")
    embedding_model: str = Field(default="BAAI/bge-small-en-v1.5", alias="OPSAGENT_EMBEDDING_MODEL")

    # Behaviour
    brand: str = "The Ark Enterprise"
    stage1_target_seconds: int = 60
    watchdog_seconds: int = 300
    dedupe_window_minutes: int = 15
    crew_max_iter: int = 3
    crew_max_execution_time: int = 180

    # ------------------------------------------------------------------ helpers
    def resolve(self, p: Path) -> Path:
        return p if p.is_absolute() else (PROJECT_ROOT / p)

    @property
    def state_path(self) -> Path:
        return self.resolve(self.state_dir)

    @property
    def outbox_path(self) -> Path:
        return self.resolve(self.outbox_dir)

    @property
    def runs_path(self) -> Path:
        return self.resolve(self.runs_dir)

    @property
    def kb_path(self) -> Path:
        return self.state_path / "kb"

    @property
    def flows_db(self) -> Path:
        return self.state_path / "flows.db"

    @property
    def inventory_path(self) -> Path:
        return self.resolve(self.inventory_file)

    @property
    def severity_policy_path(self) -> Path:
        return self.resolve(self.severity_policy_file)

    @property
    def azure_resource_base(self) -> str:
        """LiteLLM's azure route wants the resource root, not the /openai/v1 path."""
        base = self.azure_api_base.strip().rstrip("/")
        for suffix in ("/openai/v1", "/openai"):
            if base.endswith(suffix):
                base = base[: -len(suffix)]
        return base

    @property
    def teams_enabled(self) -> bool:
        return bool(self.teams_webhook_url.strip())

    @property
    def email_enabled(self) -> bool:
        return bool(self.smtp_host.strip() and self.smtp_from.strip() and self.smtp_to.strip())

    @property
    def servicenow_base_url(self) -> str:
        inst = self.servicenow_instance.strip().rstrip("/")
        if not inst:
            return ""
        if inst.startswith("http://") or inst.startswith("https://"):
            return inst
        if "." in inst:
            return f"https://{inst}"
        return f"https://{inst}.service-now.com"

    @property
    def servicenow_enabled(self) -> bool:
        has_auth = bool(self.servicenow_token.strip()) or bool(self.servicenow_user.strip() and self.servicenow_password)
        return bool(self.servicenow_base_url) and has_auth

    @property
    def xmatters_enabled(self) -> bool:
        return self.xmatters_trigger_url.strip().startswith(("https://", "http://"))

    @property
    def xmatters_api_enabled(self) -> bool:
        return self.xmatters_enabled and bool(self.xmatters_user.strip() and self.xmatters_password)

    @property
    def xmatters_property_map(self) -> dict[str, str]:
        """payload key -> form property name, parsed from XMATTERS_PROPERTIES; empty means no mapping."""
        out: dict[str, str] = {}
        for pair in self.xmatters_properties.split(","):
            key, sep, name = pair.partition("=")
            if sep and key.strip() and name.strip():
                out[key.strip()] = name.strip()
        return out

    @property
    def xmatters_device_names(self) -> list[str]:
        return [d.strip() for d in self.xmatters_devices.split(",") if d.strip()]

    @property
    def xmatters_base_url(self) -> str:
        """Scheme and host of the trigger URL: the xM API lives on the same host under /api/xm/1."""
        url = self.xmatters_trigger_url.strip()
        if not url:
            return ""
        scheme, _, rest = url.partition("://")
        host = rest.split("/", 1)[0].split("?", 1)[0]
        return f"{scheme}://{host}" if scheme and host else ""

    @property
    def llm_configured(self) -> bool:
        return bool(self.azure_api_key and self.azure_api_base)

    def export_llm_env(self) -> None:
        """Expose the Azure settings to LiteLLM through the environment it reads."""
        if self.azure_api_key:
            os.environ.setdefault("AZURE_API_KEY", self.azure_api_key)
        if self.azure_api_base:
            os.environ["AZURE_API_BASE"] = self.azure_resource_base
        if self.azure_api_version:
            os.environ.setdefault("AZURE_API_VERSION", self.azure_api_version)
        # keep CrewAI quiet about telemetry/tracing in a client environment
        os.environ.setdefault("CREWAI_DISABLE_TELEMETRY", "true")
        os.environ.setdefault("OTEL_SDK_DISABLED", "true")
        os.environ.setdefault("CREWAI_TRACING_ENABLED", "false")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings()
    for p in (s.state_path, s.outbox_path, s.runs_path, s.kb_path):
        p.mkdir(parents=True, exist_ok=True)
    return s

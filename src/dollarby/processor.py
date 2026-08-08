"""Load declarative statement processors from YAML."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Final, Self, override

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictStr,
    StringConstraints,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    SettingsError,
    YamlConfigSettingsSource,
)

DEFAULT_PROCESSOR_PATH: Final = Path(__file__).parents[2] / "processors" / "nab-2026.yaml"
CANONICAL_COLUMNS: Final = frozenset(
    {
        "date",
        "amount",
        "account_number",
        "transaction_type",
        "transaction_details",
        "balance",
        "source_category",
        "merchant_name",
        "processed_on",
    },
)

NonEmptyString = Annotated[
    StrictStr,
    StringConstraints(min_length=1),
]
NonEmptyStrings = Annotated[tuple[NonEmptyString, ...], Field(min_length=1)]


class ProcessorError(ValueError):
    """Indicate that a statement processor is missing or invalid."""


class ProcessorModel(BaseModel):
    """Provide consistent validation for nested processor settings."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class DateSettings(ProcessorModel):
    """Describe date fields in a statement export."""

    columns: NonEmptyStrings
    format: NonEmptyString


class StatementSettings(ProcessorModel):
    """Map a source statement onto Dollarby's canonical transaction fields."""

    columns: dict[NonEmptyString, NonEmptyString]
    ignored_columns: tuple[NonEmptyString, ...]
    dates: DateSettings


class TagRule(ProcessorModel):
    """Add tags when a transaction value matches a regular expression."""

    regex: StrictStr = Field(min_length=1)
    tags: NonEmptyStrings
    final: StrictBool = False

    @field_validator("regex")
    @classmethod
    def validate_regex(cls, expression: str) -> str:
        """Reject malformed regular expressions while loading the processor."""
        try:
            re.compile(expression)
        except re.error as error:
            message = f"invalid regex: {error}"
            raise ValueError(message) from error
        return expression

    def compile(self, *, case_sensitive: bool) -> re.Pattern[str]:
        """Compile this rule with the processor's case-sensitivity setting."""
        flags = re.NOFLAG if case_sensitive else re.IGNORECASE
        return re.compile(self.regex, flags)


class ColumnRules(ProcessorModel):
    """Group tag rules evaluated against one canonical transaction column."""

    column: NonEmptyString
    matches: Annotated[tuple[TagRule, ...], Field(min_length=1)]


class TaggingSettings(ProcessorModel):
    """Configure ordered automatic transaction tagging."""

    case_sensitive: StrictBool
    rules: tuple[ColumnRules, ...]


class StatementProcessor(BaseSettings):
    """Describe one statement export and its automatic tagging rules."""

    model_config = SettingsConfigDict(extra="forbid", frozen=True)

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    name: NonEmptyString
    statement: StatementSettings
    tagging: TaggingSettings

    @classmethod
    @override
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        """Treat the selected processor file as the complete configuration."""
        del cls, settings_cls, env_settings, dotenv_settings, file_secret_settings
        return (init_settings,)

    @model_validator(mode="after")
    def validate_canonical_columns(self) -> Self:
        """Require a complete mapping and valid canonical-column references."""
        configured = list(self.statement.columns.values())
        duplicates = sorted({name for name in configured if configured.count(name) > 1})
        missing = sorted(CANONICAL_COLUMNS - set(configured))
        unexpected = sorted(set(configured) - CANONICAL_COLUMNS)

        problems: list[str] = []
        if duplicates:
            problems.append(f"duplicate canonical columns: {', '.join(duplicates)}")
        if missing:
            problems.append(f"missing canonical columns: {', '.join(missing)}")
        if unexpected:
            problems.append(f"unknown canonical columns: {', '.join(unexpected)}")

        referenced_columns = {
            *self.statement.dates.columns,
            *(column_rule.column for column_rule in self.tagging.rules),
        }
        unknown_references = sorted(referenced_columns - CANONICAL_COLUMNS)
        if unknown_references:
            problems.append(f"references unknown columns: {', '.join(unknown_references)}")

        if problems:
            message = f"invalid canonical column configuration ({'; '.join(problems)})"
            raise ValueError(message)
        return self

    def source_column(self, canonical_column: str) -> str:
        """Return the export column mapped to a canonical Dollarby column."""
        for source_column, canonical_name in self.statement.columns.items():
            if canonical_name == canonical_column:
                return source_column

        message = f"Processor does not map canonical column {canonical_column!r}"
        raise ProcessorError(message)


def load_processor(path: Path) -> StatementProcessor:
    """Load and validate a YAML statement processor."""
    try:
        source = YamlConfigSettingsSource(StatementProcessor, yaml_file=path)
        return StatementProcessor.model_validate(source())
    except (
        OSError,
        SettingsError,
        TypeError,
        UnicodeDecodeError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        message = f"Could not load processor {path}: {error}"
        raise ProcessorError(message) from error

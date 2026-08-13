"""Load, validate, and persist declarative statement processors."""

from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Self

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

DEFAULT_PROCESSOR_PATH: Final = Path(__file__).parents[2] / "processors" / "nab-2026.yaml"
PROCESSOR_SCHEMA_VERSION: Final = 3
MISSING_MATCH_MESSAGE: Final = "Enter text to match"
MISSING_TAGS_MESSAGE: Final = "Enter at least one tag"
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


class TagRuleField(StrEnum):
    """Choose a text field supported by the interactive Add Tag action."""

    MERCHANT = "merchant_name"
    DETAILS = "transaction_details"


class TagRule(ProcessorModel):
    """Add tags when a transaction value contains one of the configured literals."""

    contains: NonEmptyString | NonEmptyStrings
    tags: NonEmptyStrings
    final: StrictBool = True

    @property
    def literals(self) -> tuple[str, ...]:
        """Return the configured scalar or sequence in one iterable form."""
        if isinstance(self.contains, str):
            return (self.contains,)
        return self.contains

    def compile(self, *, case_sensitive: bool) -> re.Pattern[str]:
        """Compile escaped literals with whole-value word-edge matching."""
        flags = re.NOFLAG if case_sensitive else re.IGNORECASE
        alternatives = "|".join(re.escape(literal) for literal in self.literals)
        return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", flags)


class NewTagRule(ProcessorModel):
    """Represent one normalised rule entered through the Add Tag dialog."""

    field: TagRuleField
    contains: StrictStr
    tags: tuple[StrictStr, ...]

    @field_validator("contains")
    @classmethod
    def normalise_contains(cls, value: str) -> str:
        """Require usable literal match text."""
        value = value.strip()
        if not value:
            raise ValueError(MISSING_MATCH_MESSAGE)
        return value

    @field_validator("tags")
    @classmethod
    def normalise_tags(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        """Strip and case-insensitively deduplicate entered tags."""
        tags: list[str] = []
        seen: set[str] = set()
        for raw_tag in values:
            tag = raw_tag.strip()
            identity = tag.casefold()
            if tag and identity not in seen:
                seen.add(identity)
                tags.append(tag)
        if not tags:
            raise ValueError(MISSING_TAGS_MESSAGE)
        return tuple(tags)

    def as_tag_rule(self) -> TagRule:
        """Build the persisted processor rule represented by this input."""
        return TagRule(contains=self.contains, tags=self.tags)


class ColumnRules(ProcessorModel):
    """Group tag rules evaluated against one canonical transaction column."""

    column: NonEmptyString
    matches: Annotated[tuple[TagRule, ...], Field(min_length=1)]


class TaggingSettings(ProcessorModel):
    """Configure ordered automatic transaction tagging."""

    case_sensitive: StrictBool
    rules: tuple[ColumnRules, ...]


class StatementProcessor(ProcessorModel):
    """Describe one statement export and its automatic tagging rules."""

    schema_version: Annotated[
        int,
        Field(strict=True, ge=PROCESSOR_SCHEMA_VERSION, le=PROCESSOR_SCHEMA_VERSION),
    ]
    name: NonEmptyString
    statement: StatementSettings
    tagging: TaggingSettings

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

    def with_tag_rule(self, new_rule: NewTagRule) -> Self:
        """Return a validated processor with one interactive rule added or merged."""
        replacement = new_rule.as_tag_rule()
        updated_groups: list[ColumnRules] = []
        found_column = False

        for column_rules in self.tagging.rules:
            if column_rules.column != new_rule.field.value:
                updated_groups.append(column_rules)
                continue

            found_column = True
            updated_groups.append(_upsert_tag_rule(column_rules, replacement))

        if not found_column:
            updated_groups.append(
                ColumnRules(column=new_rule.field.value, matches=(replacement,)),
            )

        tagging = TaggingSettings(
            case_sensitive=self.tagging.case_sensitive,
            rules=tuple(updated_groups),
        )
        return type(self)(
            schema_version=self.schema_version,
            name=self.name,
            statement=self.statement,
            tagging=tagging,
        )


@dataclass(slots=True)
class ProcessorDocument:
    """Coordinate one validated processor with its writable YAML document."""

    path: Path
    processor: StatementProcessor
    _source_text: str = field(repr=False)

    @classmethod
    def load(cls, path: Path) -> Self:
        """Load a processor while retaining the exact source used for conflict checks."""
        processor, source_text = _read_processor(path)
        return cls(path=path, processor=processor, _source_text=source_text)

    def add_tag_rule(self, new_rule: NewTagRule) -> StatementProcessor:
        """Persist one rule and return the processor now represented on disk."""
        updated = self.processor.with_tag_rule(new_rule)
        if updated == self.processor:
            return self.processor
        self.save(updated)
        return updated

    def save(self, processor: StatementProcessor) -> None:
        """Atomically replace an unchanged source document with a validated model."""
        try:
            current_source = self.path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as error:
            message = f"Could not read processor before saving {self.path}: {error}"
            raise ProcessorError(message) from error

        if current_source != self._source_text:
            message = (
                f"Processor {self.path} changed after Dollarby loaded it; reload before saving"
            )
            raise ProcessorError(message)

        source_text = _dump_processor(processor)
        _atomic_write(self.path, source_text)
        self.processor = processor
        self._source_text = source_text


def load_processor(path: Path) -> StatementProcessor:
    """Load and validate a YAML statement processor."""
    processor, _source_text = _read_processor(path)
    return processor


def _read_processor(path: Path) -> tuple[StatementProcessor, str]:
    """Read and validate a processor while preserving its source text."""
    try:
        source_text = path.read_text(encoding="utf-8")
        source = yaml.safe_load(source_text)
        return StatementProcessor.model_validate(source), source_text
    except (
        OSError,
        TypeError,
        UnicodeDecodeError,
        ValidationError,
        yaml.YAMLError,
    ) as error:
        message = f"Could not load processor {path}: {error}"
        raise ProcessorError(message) from error


def _dump_processor(processor: StatementProcessor) -> str:
    """Render a processor as canonical application-managed YAML."""
    try:
        return yaml.safe_dump(
            processor.model_dump(mode="json", exclude_defaults=True),
            allow_unicode=True,
            sort_keys=False,
        )
    except yaml.YAMLError as error:
        message = f"Could not serialise processor: {error}"
        raise ProcessorError(message) from error


def _atomic_write(path: Path, source_text: str) -> None:
    """Write text beside its target and atomically replace the target."""
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(source_text)
            temporary.flush()
            os.fsync(temporary.fileno())

        temporary_path.chmod(path.stat().st_mode)
        temporary_path.replace(path)
    except OSError as error:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        message = f"Could not save processor {path}: {error}"
        raise ProcessorError(message) from error


def _upsert_tag_rule(column_rules: ColumnRules, replacement: TagRule) -> ColumnRules:
    """Merge tags into an equivalent rule or append a new ordered rule."""
    replacement_identity = frozenset(value.casefold() for value in replacement.literals)
    matches: list[TagRule] = []
    found_match = False

    for existing in column_rules.matches:
        existing_identity = frozenset(value.casefold() for value in existing.literals)
        if existing_identity != replacement_identity:
            matches.append(existing)
            continue

        found_match = True
        tags = _merge_case_insensitive(existing.tags, replacement.tags)
        matches.append(
            TagRule(contains=existing.contains, tags=tags, final=existing.final),
        )

    if not found_match:
        matches.append(replacement)
    return ColumnRules(column=column_rules.column, matches=tuple(matches))


def _merge_case_insensitive(existing: tuple[str, ...], added: tuple[str, ...]) -> tuple[str, ...]:
    """Merge strings while preserving the first spelling and order encountered."""
    merged = list(existing)
    identities = {value.casefold() for value in existing}
    for value in added:
        identity = value.casefold()
        if identity not in identities:
            identities.add(identity)
            merged.append(value)
    return tuple(merged)

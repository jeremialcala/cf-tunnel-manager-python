from __future__ import annotations

import re
from dataclasses import dataclass

from shared.errors import InvalidHostname

_HOSTNAME_RE = re.compile(
    r"^(?=.{1,253}$)(?:(?!-)[A-Za-z0-9-]{1,63}(?<!-)\.)+[A-Za-z]{2,63}$"
)


@dataclass(frozen=True, slots=True)
class Hostname:
    """RFC-1123 / DNS-safe hostname value object.

    Stored normalised to lowercase. Construct via the factory
    :pymeth:`parse` to get a single error type for invalid input.
    """

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not self.value:
            raise InvalidHostname("hostname must be a non-empty string")
        if len(self.value) > 253:
            raise InvalidHostname("hostname exceeds 253 chars")
        if not _HOSTNAME_RE.match(self.value):
            raise InvalidHostname(f"invalid hostname format: {self.value!r}")
        # Frozen dataclass — bypass via object.__setattr__ for normalisation.
        object.__setattr__(self, "value", self.value.lower())

    @classmethod
    def parse(cls, raw: str) -> Hostname:
        return cls(raw.strip())

    @property
    def root_domain(self) -> str:
        """Return the apex / zone root, e.g. ``api.svc.example.com → example.com``.

        Naive implementation that returns the last two labels — sufficient
        for non-PSL-aware zone lookup. For complex TLDs the caller should
        pass the canonical zone explicitly.
        """
        parts = self.value.split(".")
        return ".".join(parts[-2:]) if len(parts) >= 2 else self.value

    @property
    def subdomain(self) -> str:
        parts = self.value.split(".")
        return ".".join(parts[:-2]) if len(parts) > 2 else ""

    def __str__(self) -> str:  # pragma: no cover
        return self.value

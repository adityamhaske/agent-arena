"""Exception hierarchy.

Every error the arena raises on its own carries enough context to point the
user at the line of config or the test file that caused it — a config typo
should never surface as a bare ``KeyError``.
"""


class ArenaError(Exception):
    """Base class for every error raised by Agent Arena."""


class ConfigError(ArenaError):
    """Project config is missing, malformed, or internally inconsistent."""


class TestCaseError(ArenaError):
    """A test file could not be read, or a test case is missing a required field."""


class ScorerError(ArenaError):
    """A scorer could not be resolved, constructed, or executed."""


class ConnectorError(ArenaError):
    """A model provider could not be resolved or failed to generate."""


class HookError(ArenaError):
    """A project-defined hook could not be loaded or raised while running."""


class SecretError(ArenaError):
    """A credential reference is malformed, unreadable, or unsafe to use."""

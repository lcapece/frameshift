"""
SQL identifier validation and quoting.

Frameshift builds SQL as text, so every identifier that reaches a statement
must pass through this module. Identifiers cannot be parameterized by a
driver -- there is no placeholder form for a table or column name -- so
they are validated against an allowlist and then quoted.

The two functions here are deliberately separate:

``quote_identifier`` is the mechanical part (double the quotes, wrap in
quotes). ``validate_identifier`` is the policy part (reject anything that
looks like an attack or a mistake). Callers should use ``quote_identifier``,
which validates first.
"""

import re

from frameshift.exceptions import ValidationError

# Redshift's documented identifier limit is 127 bytes.
MAX_IDENTIFIER_BYTES = 127

# Characters that must never appear in an identifier, even a quoted one.
# NUL is rejected by the server; the rest terminate lines in ways that can
# hide the tail of a statement from a human reading a log.
_FORBIDDEN_CHARS = re.compile(r"[\x00\r\n]")

# A conservative allowlist. Redshift permits more inside double quotes, but
# identifiers outside this set are almost always a bug or an attack, and
# rejecting them costs legitimate users very little.
_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_$]*$")


def validate_identifier(name: str, kind: str = "identifier") -> str:
    """
    Validate a SQL identifier, raising if it is unsafe.

    Args:
        name: The identifier to validate.
        kind: What the identifier names, used in error messages
            (e.g. "table", "column", "schema").

    Returns:
        The identifier, unchanged, if it is valid.

    Raises:
        ValidationError: If the identifier is empty, too long, contains
            forbidden characters, or falls outside the safe allowlist.
    """
    if not isinstance(name, str):
        raise ValidationError(
            f"{kind.capitalize()} name must be a string, got {type(name).__name__}",
            field=kind,
            received=repr(name),
        )

    if not name:
        raise ValidationError(
            f"{kind.capitalize()} name must not be empty",
            field=kind,
        )

    if _FORBIDDEN_CHARS.search(name):
        raise ValidationError(
            f"{kind.capitalize()} name contains a forbidden character "
            "(NUL, carriage return, or newline)",
            field=kind,
            received=repr(name),
        )

    encoded_length = len(name.encode("utf-8"))
    if encoded_length > MAX_IDENTIFIER_BYTES:
        raise ValidationError(
            f"{kind.capitalize()} name is {encoded_length} bytes, exceeding "
            f"Redshift's {MAX_IDENTIFIER_BYTES}-byte limit",
            field=kind,
            received=repr(name[:50] + "..." if len(name) > 50 else name),
        )

    if not _SAFE_IDENTIFIER.match(name):
        raise ValidationError(
            f"{kind.capitalize()} name {name!r} is not a valid Frameshift "
            "identifier. Names must start with a letter or underscore and "
            "contain only letters, digits, underscores, or dollar signs. "
            "If you need a name outside this set, rename the column before "
            "loading (e.g. df.rename(columns=...)).",
            field=kind,
            received=repr(name),
        )

    return name


def quote_identifier(name: str, kind: str = "identifier") -> str:
    """
    Validate and double-quote a SQL identifier.

    Any embedded double quote is doubled per the SQL standard. In practice
    ``validate_identifier`` rejects such names first; the doubling is kept
    so this function stays correct on its own terms if the allowlist is
    ever widened.

    Args:
        name: The identifier to quote.
        kind: What the identifier names, used in error messages.

    Returns:
        The identifier, quoted and safe to interpolate into SQL.

    Raises:
        ValidationError: If the identifier fails validation.
    """
    validate_identifier(name, kind=kind)
    escaped = name.replace('"', '""')
    return f'"{escaped}"'


def quote_qualified_name(
    table_name: str,
    schema_name: str | None = None,
) -> str:
    """
    Build a fully qualified, quoted table reference.

    Args:
        table_name: The table name.
        schema_name: The schema name, if any.

    Returns:
        Either ``"schema"."table"`` or ``"table"``.

    Raises:
        ValidationError: If either identifier fails validation.
    """
    quoted_table = quote_identifier(table_name, kind="table")
    if schema_name:
        quoted_schema = quote_identifier(schema_name, kind="schema")
        return f"{quoted_schema}.{quoted_table}"
    return quoted_table

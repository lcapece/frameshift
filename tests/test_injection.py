"""
Adversarial tests for SQL injection.

Frameshift builds SQL as text, so these tests are the load-bearing safety
net for the whole library.

The rule this file follows: never assert on the shape of the generated
string alone. Assert that a payload cannot escape its literal, by parsing
the generated SQL the way the server would -- under both interpretations
of a backslash, so that a change in server behavior surfaces here rather
than in production.

Redshift's literal semantics are inherited from PostgreSQL 8.0: inside an
ordinary ``'...'`` literal a backslash escapes the next character. Both
backslashes and quotes are therefore doubled, matching Redshift's own
QUOTE_LITERAL function.
"""

import json

import pandas as pd
import pytest

from frameshift.chunker import SQLGenerator
from frameshift.exceptions import DataTypeError, ValidationError
from frameshift.identifiers import quote_identifier, quote_qualified_name
from frameshift.schema import TableSchema
from frameshift.types import ColumnSpec, RedshiftType, python_to_sql_value

# --------------------------------------------------------------------------
# A miniature SQL literal parser, used to verify escaping from the server's
# point of view rather than by eyeballing backslashes.
# --------------------------------------------------------------------------


def parse_literal(literal: str, standard_conforming_strings: bool = True):
    """
    Parse one SQL string literal from the front of ``literal``.

    Implements the PostgreSQL/Redshift lexer rules for both plain ``'...'``
    literals and ``E'...'`` escape-string literals, under either setting of
    ``standard_conforming_strings``. Frameshift emits ``E''`` precisely so
    that the decoded value does not depend on that setting; these tests
    assert that property rather than assume it.

    Args:
        literal: Text beginning with a string literal.
        standard_conforming_strings: Emulates the server setting. Only
            affects plain literals; ``E''`` always honours backslash
            escapes.

    Returns:
        A ``(value, remainder)`` tuple: the decoded string, and whatever SQL
        followed the closing quote. A non-empty remainder means the payload
        escaped the literal.
    """
    if literal.startswith("E'"):
        backslash_escapes = True
        index = 2
    elif literal.startswith("'"):
        # In a plain literal, backslashes escape only in the legacy mode.
        backslash_escapes = not standard_conforming_strings
        index = 1
    else:
        raise AssertionError(f"not a string literal: {literal!r}")

    decoded: list[str] = []

    while index < len(literal):
        char = literal[index]

        if backslash_escapes and char == "\\" and index + 1 < len(literal):
            decoded.append(literal[index + 1])
            index += 2
            continue

        if char == "'":
            # A doubled quote is an escaped quote, not a terminator.
            if index + 1 < len(literal) and literal[index + 1] == "'":
                decoded.append("'")
                index += 2
                continue
            return "".join(decoded), literal[index + 1 :]

        decoded.append(char)
        index += 1

    raise AssertionError(f"unterminated literal: {literal!r}")


# Payloads that attempt to break out of a string literal. Each is a value an
# attacker could plausibly place in a DataFrame cell.
BREAKOUT_PAYLOADS = [
    "'; DROP TABLE users; --",
    "\\'; DROP TABLE users; --",
    "\\\\'; DROP TABLE users; --",
    "''; DELETE FROM accounts; --",
    "\\''; DELETE FROM accounts; --",
    "x' UNION SELECT password FROM users --",
    "\\x' UNION SELECT password FROM users --",
    "'||(SELECT password FROM users LIMIT 1)||'",
    "\\",
    "\\\\",
    "'",
    "''",
    "\\'",
    "test\\",
    "O'Brien",
    "50% \\ 100'",
]


class TestValueEscaping:
    """A value must never escape the literal that contains it."""

    @pytest.mark.parametrize("payload", BREAKOUT_PAYLOADS)
    @pytest.mark.parametrize("scs", [True, False], ids=["scs_on", "scs_off"])
    def test_payload_cannot_escape_literal(self, payload, scs):
        """
        Containment: no payload may terminate its literal early, under
        either interpretation of backslashes. This is the security property.
        """
        literal = python_to_sql_value(payload, RedshiftType.VARCHAR)
        _, remainder = parse_literal(literal, standard_conforming_strings=scs)

        assert remainder == "", (
            f"payload escaped its literal under "
            f"standard_conforming_strings={'on' if scs else 'off'}: "
            f"trailing SQL {remainder!r}"
        )

    @pytest.mark.parametrize("payload", BREAKOUT_PAYLOADS)
    def test_payload_round_trips_on_redshift(self, payload):
        """
        Fidelity: the value must decode back to itself under Redshift's
        literal semantics, in which a backslash escapes the next character.

        Fidelity is asserted only for that mode. Frameshift's escaping
        matches Redshift's QUOTE_LITERAL, and doubled backslashes are
        correct there; a server that treated backslashes literally would
        decode them doubled. Redshift does not, which is why the doubling
        is right for this library's only target.
        """
        literal = python_to_sql_value(payload, RedshiftType.VARCHAR)
        value, _ = parse_literal(literal, standard_conforming_strings=False)
        assert value == payload

    @pytest.mark.parametrize("payload", BREAKOUT_PAYLOADS)
    def test_payload_survives_full_insert(self, payload):
        """The same guarantee, through the real INSERT generation path."""
        df = pd.DataFrame({"name": [payload]})
        generator = SQLGenerator(
            table_name="t",
            schema_name="public",
            column_specs=[
                ColumnSpec(name="name", redshift_type=RedshiftType.VARCHAR, length=256)
            ],
        )
        sql = generator.generate_insert_statement(df)

        # Isolate the literal inside VALUES (...) and confirm it terminates
        # exactly where the statement expects, under Redshift's semantics.
        body = sql.split("VALUES\n", 1)[1]
        assert body.startswith("(")
        value, remainder = parse_literal(body[1:], standard_conforming_strings=False)
        assert value == payload
        assert remainder == ");"

    def test_matches_redshift_quote_literal(self):
        """
        Frameshift's escaping must match Redshift's QUOTE_LITERAL, which
        doubles both single quotes and backslashes and returns a plain
        literal.

        https://docs.aws.amazon.com/redshift/latest/dg/r_QUOTE_LITERAL.html
        """
        assert python_to_sql_value("CAT", RedshiftType.VARCHAR) == "'CAT'"
        assert python_to_sql_value("it's", RedshiftType.VARCHAR) == "'it''s'"
        assert python_to_sql_value("a\\b", RedshiftType.VARCHAR) == "'a\\\\b'"
        assert python_to_sql_value("\\'", RedshiftType.VARCHAR) == "'\\\\'''"

    def test_backslash_must_be_doubled(self):
        """
        The actual literal-escape vulnerability: leaving backslashes alone.

        On Redshift a backslash inside an ordinary literal escapes the next
        character, so an unescaped ``\\'`` would consume the closing quote
        and hand the remainder of the value to the parser as SQL. This test
        fails if anyone "modernizes" the escaping to PostgreSQL's current
        standard_conforming_strings=on semantics.
        """
        naive = "'" + "\\'; DROP TABLE users; --".replace("'", "''") + "'"
        _, escaped_remainder = parse_literal(naive, standard_conforming_strings=False)
        assert (
            escaped_remainder != ""
        ), "test premise is wrong: the naive rendering was expected to break out"

        safe = python_to_sql_value("\\'; DROP TABLE users; --", RedshiftType.VARCHAR)
        _, remainder = parse_literal(safe, standard_conforming_strings=False)
        assert remainder == ""

    def test_escape_replacements_commute(self):
        """
        Documents a non-bug, to stop it being "fixed" again.

        Doubling quotes and doubling backslashes are order-independent:
        neither replacement introduces the other's target character. Their
        order has never been the vulnerability, and swapping it changes
        nothing.
        """

        def quotes_first(text: str) -> str:
            return text.replace("'", "''").replace("\\", "\\\\")

        def backslashes_first(text: str) -> str:
            return text.replace("\\", "\\\\").replace("'", "''")

        for payload in BREAKOUT_PAYLOADS:
            assert quotes_first(payload) == backslashes_first(payload)

    def test_nul_byte_rejected(self):
        with pytest.raises(DataTypeError):
            python_to_sql_value("before\x00after", RedshiftType.VARCHAR)

    def test_unicode_round_trips(self):
        for text in ("café", "日本語", "😀", "Ω≈ç√"):
            literal = python_to_sql_value(text, RedshiftType.VARCHAR)
            value, remainder = parse_literal(literal)
            assert value == text
            assert remainder == ""


class TestSuperEscaping:
    """SUPER values are JSON-serialized, then escaped as literals."""

    def test_injection_via_dict_value(self):
        payload = {"note": "\\'; DROP TABLE users; --"}
        sql = python_to_sql_value(payload, RedshiftType.SUPER)

        assert sql.startswith("JSON_PARSE('")
        inner = sql[len("JSON_PARSE(") : -1]

        # Containment under either backslash interpretation.
        for scs in (True, False):
            _, remainder = parse_literal(inner, standard_conforming_strings=scs)
            assert remainder == ""

        # Fidelity under Redshift's semantics: the literal must decode to
        # the exact JSON document.
        value, _ = parse_literal(inner, standard_conforming_strings=False)
        assert json.loads(value) == payload

    def test_containers_do_not_crash_null_check(self):
        """
        ``pd.isna`` raises on list-like input rather than returning a bool,
        so containers must be checked before it is consulted.
        """
        assert (
            python_to_sql_value([1, 2, 3], RedshiftType.SUPER)
            == "JSON_PARSE('[1, 2, 3]')"
        )
        assert python_to_sql_value({}, RedshiftType.SUPER) == "JSON_PARSE('{}')"


class TestIdentifierValidation:
    """Identifiers cannot be parameterized, so they are allowlisted."""

    @pytest.mark.parametrize(
        "name",
        [
            'users" ; DROP TABLE x; --',
            'id" , "evil',
            'a" ON "b',
            "tab\tname",
            "line\nbreak",
            "carriage\rreturn",
            "nul\x00byte",
            "",
            "1_starts_with_digit",
            "has space",
            "has-hyphen",
            "has;semicolon",
            "has'quote",
            "a" * 200,
        ],
    )
    def test_unsafe_identifiers_rejected(self, name):
        with pytest.raises(ValidationError):
            quote_identifier(name, kind="column")

    @pytest.mark.parametrize(
        "name",
        ["users", "user_id", "_private", "col$1", "MixedCase", "a", "t123"],
    )
    def test_safe_identifiers_accepted(self, name):
        assert quote_identifier(name) == f'"{name}"'

    def test_qualified_name(self):
        assert quote_qualified_name("events", "analytics") == '"analytics"."events"'
        assert quote_qualified_name("events") == '"events"'

    def test_injection_via_table_name_is_rejected(self):
        generator = SQLGenerator(
            table_name='t" ; DROP TABLE x; --', schema_name="public"
        )
        with pytest.raises(ValidationError):
            _ = generator.full_table_name

    def test_injection_via_column_name_is_rejected(self):
        spec = ColumnSpec(name='id" , "evil', redshift_type=RedshiftType.INTEGER)
        with pytest.raises(ValidationError):
            spec.to_sql()

    def test_injection_via_distkey_is_rejected(self):
        schema = TableSchema(
            table_name="events",
            columns=[ColumnSpec(name="id", redshift_type=RedshiftType.INTEGER)],
            distkey='id") ; DROP TABLE x; --',
        )
        with pytest.raises(ValidationError):
            schema.to_create_table_sql()

    def test_injection_via_default_is_rendered_as_literal(self):
        spec = ColumnSpec(
            name="note",
            redshift_type=RedshiftType.VARCHAR,
            length=64,
            default="'; DROP TABLE users; --",
        )
        sql = spec.to_sql()
        # The default must appear as an escaped literal, not as raw DDL.
        assert "DEFAULT '''; DROP TABLE users; --'" in sql

"""Reading SQL well enough to refuse it, without a database anywhere near it.

`backend/data_access/duckdb_source.py` says it is "the ONLY module in the
backend permitted to import duckdb", and that rule is why this file contains a
tokeniser rather than a call to a parser. It is also the right shape for the
job: a validator that needed an engine to decide whether a statement is safe
would have to hand the statement to the engine, and the whole point is that
model-written SQL never reaches one.

What it does
------------
Tokenises SQL into strings, comments, identifiers, numbers and punctuation,
then answers four questions from the token stream rather than from a regex over
raw text:

  * Is this ONE read-only statement?
  * Does it name anything it must not — a write, a DDL, a system catalogue, a
    file-reading function, an extension load?
  * Which TABLES does it read? (`FROM` and `JOIN` targets that are not CTE
    names defined in the same statement.)
  * Which COLUMNS does it name, qualified and unqualified?

Why a tokeniser and not a regex
--------------------------------
Because `SELECT 'DROP TABLE x' AS note` is safe and a regex for `DROP` rejects
it, and `SELECT/*safe*/ 1; DROP TABLE x` is not safe and a regex for a leading
`SELECT` accepts it. Both of those are ordinary, and a validator that gets
either wrong is a validator nobody can rely on. Strings and comments are
recognised and excluded from keyword matching; statement separators are counted
outside them.

What it is NOT
--------------
Not a SQL parser and not a substitute for one. It does not check that a
statement is well-formed, and it does not resolve which table an unqualified
column came from — `columns()` returns what was named and lets the caller check
each against the union of the permitted datasets' fields. Everything it does
is conservative: where it cannot tell, it reports what it saw and the caller
refuses, rather than guessing in favour of the statement.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from dataclasses import dataclass, field

SQLGUARD_VERSION = "3.0.0"

#: Statements and clauses that write, define, or hand out access. §8H's list,
#: plus the DuckDB-specific ones a list written for PostgreSQL would miss.
FORBIDDEN_KEYWORDS: frozenset[str] = frozenset({
    "insert", "update", "delete", "merge", "upsert", "drop", "alter",
    "create", "grant", "revoke", "copy", "truncate", "replace", "rename",
    "attach", "detach", "install", "load", "export", "import", "vacuum",
    "checkpoint", "pragma", "call", "prepare", "execute", "deallocate",
    "begin", "commit", "rollback", "savepoint", "lock", "comment", "reindex",
    "cluster", "refresh", "reset", "listen", "notify", "discard", "do",
})

#: `SET` is forbidden as a STATEMENT but is an ordinary word inside `UPDATE`
#: (already forbidden) and appears in `SET` operations nowhere else in a
#: SELECT. Kept separate so the message can say which.
FORBIDDEN_STATEMENT_STARTS: frozenset[str] = frozenset(
    FORBIDDEN_KEYWORDS | {"set", "show", "describe", "use", "explain",
                          "summarize", "unpivot_placeholder"})

#: Functions and identifiers that reach outside the governed data: the file
#: system, the network, the process, another tenant's schema, or the engine's
#: own internals.
FORBIDDEN_FUNCTIONS: frozenset[str] = frozenset({
    # File and network access
    "read_csv", "read_csv_auto", "read_parquet", "read_json",
    "read_json_auto", "read_ndjson", "read_text", "read_blob", "glob",
    "parquet_scan", "csv_scan", "json_scan", "iceberg_scan", "delta_scan",
    "postgres_scan", "sqlite_scan", "mysql_scan", "arrow_scan",
    "sniff_csv", "url", "httpfs", "s3", "gcs", "azure",
    # Process, environment and extensions
    "system", "shell", "getenv", "load_extension", "install_extension",
    "duckdb_extensions", "which_secret", "create_secret",
    # Engine internals and catalogues
    "duckdb_settings", "duckdb_tables", "duckdb_views", "duckdb_columns",
    "duckdb_databases", "duckdb_schemas", "duckdb_functions",
    "duckdb_constraints", "duckdb_dependencies", "duckdb_keywords",
    "pg_read_file", "pg_ls_dir", "pg_sleep", "pg_terminate_backend",
    "query", "query_table", "sql_auto_complete", "current_setting",
})

#: Schemas nothing may read. §8H's "unrestricted system catalog access".
FORBIDDEN_SCHEMAS: frozenset[str] = frozenset({
    "information_schema", "pg_catalog", "pg_temp", "pg_toast", "sys",
    "system", "temp", "main_temp", "duckdb_internal",
})

#: Where a table name follows. Everything else in a FROM list is an alias, a
#: subquery or a function call.
_TABLE_INTRODUCERS: frozenset[str] = frozenset({"from", "join", "using"})

#: Words that end a table reference, so `FROM x AS y WHERE` does not read
#: `where` as a second table.
_KEYWORDS: frozenset[str] = frozenset({
    "select", "from", "where", "group", "by", "having", "order", "limit",
    "offset", "join", "inner", "left", "right", "full", "outer", "cross",
    "on", "using", "as", "and", "or", "not", "in", "is", "null", "case",
    "when", "then", "else", "end", "with", "union", "all", "except",
    "intersect", "distinct", "asc", "desc", "over", "partition", "window",
    "between", "like", "ilike", "exists", "any", "some", "cast", "filter",
    "qualify", "nulls", "first", "last", "recursive", "lateral", "natural",
    "values", "row", "rows", "range", "preceding", "following", "current",
    "unbounded", "interval", "at", "time", "zone", "within", "collate",
    "true", "false", "unknown", "similar", "escape", "unpivot", "pivot",
})


@dataclass(frozen=True)
class Token:
    kind: str  # word | string | number | punct | comment
    text: str
    at: int

    @property
    def word(self) -> str:
        return self.text.lower() if self.kind == "word" else ""


_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$]*")
_NUMBER = re.compile(r"\d+(?:\.\d+)?(?:[eE][+-]?\d+)?")


def tokenise(sql: str) -> list[Token]:
    """SQL as tokens, with strings and comments recognised but kept.

    Kept rather than stripped so an offset in a message can point at the thing
    that was wrong, and so a caller can tell "the word DROP appears inside a
    string literal" from "this statement drops a table".
    """
    out: list[Token] = []
    i, n = 0, len(sql)
    while i < n:
        char = sql[i]
        if char in " \t\r\n":
            i += 1
            continue
        if char == "-" and sql.startswith("--", i):
            end = sql.find("\n", i)
            end = n if end < 0 else end
            out.append(Token("comment", sql[i:end], i))
            i = end
            continue
        if char == "/" and sql.startswith("/*", i):
            end = sql.find("*/", i + 2)
            end = n if end < 0 else end + 2
            out.append(Token("comment", sql[i:end], i))
            i = end
            continue
        if char in "'\"`":
            # A doubled quote inside a quoted run is an escaped quote, which is
            # why this walks rather than using a non-greedy match: `'it''s'` is
            # one string, and a regex that stopped at the second quote would
            # leave `s'` looking like the start of another.
            j = i + 1
            while j < n:
                if sql[j] == char:
                    if j + 1 < n and sql[j + 1] == char:
                        j += 2
                        continue
                    j += 1
                    break
                if sql[j] == "\\" and char == "'":
                    j += 2
                    continue
                j += 1
            kind = "identifier" if char in '"`' else "string"
            out.append(Token(kind, sql[i:j], i))
            i = j
            continue
        word = _WORD.match(sql, i)
        if word:
            out.append(Token("word", word.group(0), i))
            i = word.end()
            continue
        number = _NUMBER.match(sql, i)
        if number:
            out.append(Token("number", number.group(0), i))
            i = number.end()
            continue
        out.append(Token("punct", char, i))
        i += 1
    return out


def _code_tokens(tokens: list[Token]) -> Iterator[Token]:
    """Everything that is not a comment or a string literal."""
    for token in tokens:
        if token.kind in ("comment", "string"):
            continue
        yield token


@dataclass
class Reading:
    """What a statement turned out to be."""

    statements: int = 0
    first_word: str = ""
    tables: list[str] = field(default_factory=list)
    #: Which query scope each table was read in: the name of the CTE it sits
    #: inside, or "" for the outer query. Two base tables in the SAME scope are
    #: joined to each other; two in different CTEs are two separate reads whose
    #: results are combined afterwards, which is a different thing entirely and
    #: carries none of a join's fan-out risk.
    tables_by_scope: dict[str, list[str]] = field(default_factory=dict)
    cte_names: list[str] = field(default_factory=list)
    #: Names the statement itself introduces — column aliases and table
    #: aliases. Held apart from `columns` so a caller checking that every
    #: column exists does not refuse `AS ratio`, which names nothing in the
    #: book and is not meant to.
    aliases: list[str] = field(default_factory=list)
    columns: list[str] = field(default_factory=list)
    qualified_columns: list[tuple[str, str]] = field(default_factory=list)
    functions: list[str] = field(default_factory=list)
    schemas: list[str] = field(default_factory=list)
    keywords_used: list[str] = field(default_factory=list)
    aggregates: list[str] = field(default_factory=list)
    has_join: bool = False
    has_group_by: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "statements": self.statements, "first_word": self.first_word,
            "tables": list(self.tables), "cte_names": list(self.cte_names),
            "tables_by_scope": {k: list(v)
                                for k, v in self.tables_by_scope.items()},
            "columns": sorted(set(self.columns)),
            "aliases": sorted(set(self.aliases)),
            "qualified_columns": [f"{a}.{c}" for a, c in self.qualified_columns],
            "functions": sorted(set(self.functions)),
            "schemas": sorted(set(self.schemas)),
            "aggregates": sorted(set(self.aggregates)),
            "has_join": self.has_join, "has_group_by": self.has_group_by,
        }


#: Aggregations a metric may use, recognised so §8G can check that the
#: statement actually aggregates what the definition says it aggregates.
AGGREGATE_FUNCTIONS: frozenset[str] = frozenset({
    "sum", "count", "avg", "mean", "min", "max", "median", "stddev",
    "stddev_pop", "stddev_samp", "var_pop", "var_samp", "quantile",
    "quantile_cont", "approx_count_distinct", "first", "last", "any_value",
    "list", "string_agg", "array_agg", "bool_and", "bool_or",
})


def _unquote(text: str) -> str:
    if len(text) >= 2 and text[0] in '"`' and text[-1] == text[0]:
        return text[1:-1].replace(text[0] * 2, text[0])
    return text


def read(sql: str) -> Reading:
    """Everything the guard needs to know about a statement.

    Deliberately forgiving about SQL it does not fully understand and strict
    about what it reports: a table it could not resolve is still reported as a
    table, so the caller refuses it rather than letting an unrecognised
    construct through as "no tables found".
    """
    tokens = tokenise(sql)
    reading = Reading()

    code = list(_code_tokens(tokens))
    if not code:
        return reading

    # Statements: a `;` outside a string, ignoring a single trailing one.
    separators = [t for t in code if t.kind == "punct" and t.text == ";"]
    trailing = bool(separators) and separators[-1] is code[-1]
    reading.statements = 1 + len(separators) - (1 if trailing else 0)

    reading.first_word = next((t.word for t in code if t.kind == "word"), "")

    # CTE names: the identifier after WITH, and after each comma at depth 0
    # that is followed by `AS (`.
    depth = 0
    for index, token in enumerate(code):
        if token.kind == "punct":
            depth += 1 if token.text == "(" else (-1 if token.text == ")" else 0)
            continue
        if token.kind != "word" or token.word != "as":
            continue
        before = code[index - 1] if index else None
        after = code[index + 1] if index + 1 < len(code) else None
        if after is None:
            continue
        if (before is not None and before.kind in ("word", "identifier")
                and after.kind == "punct" and after.text == "("):
            name = _unquote(before.text)
            if name.lower() not in _KEYWORDS:
                reading.cte_names.append(name)
        elif after.kind in ("word", "identifier"):
            # `… AS ratio`, `FROM portfolio_facility AS p`. Either way the
            # name after AS is introduced BY the statement rather than read
            # from a dataset.
            name = _unquote(after.text)
            if name.lower() not in _KEYWORDS:
                reading.aliases.append(name)

    cte_lower = {c.lower() for c in reading.cte_names}

    reading.aliases.extend(_bare_aliases(code))
    scopes = _scopes(code, reading.cte_names)

    index = 0
    while index < len(code):
        token = code[index]
        if token.kind == "word":
            word = token.word
            if word in FORBIDDEN_KEYWORDS or word == "set":
                reading.keywords_used.append(word)
            if word in ("join", "using"):
                reading.has_join = True
            if word == "group":
                reading.has_group_by = True
            following = code[index + 1] if index + 1 < len(code) else None
            if (following is not None and following.kind == "punct"
                    and following.text == "("):
                if word not in _KEYWORDS:
                    reading.functions.append(word)
                if word in AGGREGATE_FUNCTIONS:
                    reading.aggregates.append(word)

            if word in _TABLE_INTRODUCERS:
                scope = scopes.get(index, "")
                index, named = _read_table(code, index + 1)
                for schema, name in named:
                    if schema:
                        reading.schemas.append(schema)
                    if name.lower() not in cte_lower:
                        reading.tables.append(name)
                        reading.tables_by_scope.setdefault(scope, [])
                        if name not in reading.tables_by_scope[scope]:
                            reading.tables_by_scope[scope].append(name)
                continue

        if token.kind in ("word", "identifier"):
            name = _unquote(token.text)
            following = code[index + 1] if index + 1 < len(code) else None
            preceding = code[index - 1] if index else None
            is_call = (following is not None and following.kind == "punct"
                       and following.text == "(")
            is_qualified = (following is not None and following.kind == "punct"
                            and following.text == ".")
            after_dot = (preceding is not None and preceding.kind == "punct"
                         and preceding.text == ".")
            if is_qualified and index + 2 < len(code):
                target = code[index + 2]
                if target.kind in ("word", "identifier"):
                    reading.qualified_columns.append(
                        (name, _unquote(target.text)))
                    index += 3
                    continue
            if (not is_call and not after_dot
                    and token.kind == "identifier" or
                    (token.kind == "word" and not is_call and not after_dot
                     and token.word not in _KEYWORDS)):
                reading.columns.append(name)
        index += 1

    return reading


def _read_table(code: list[Token], start: int) -> tuple[int, list[tuple[str, str]]]:
    """The table reference at `start`, as (schema, name) pairs.

    Returns the index to continue from. A subquery (`FROM (`) or a function
    call (`FROM read_parquet(`) yields no table NAME — the first is handled by
    walking on, and the second is caught by `functions` instead, which is where
    a file reader belongs.
    """
    found: list[tuple[str, str]] = []
    index = start
    if index >= len(code):
        return index, found
    token = code[index]
    if token.kind == "punct":
        return index + 1, found
    if token.kind not in ("word", "identifier"):
        return index + 1, found
    if token.kind == "word" and token.word in _KEYWORDS:
        return index + 1, found
    following = code[index + 1] if index + 1 < len(code) else None
    if following is not None and following.kind == "punct" and following.text == "(":
        # A table function — `FROM read_parquet('…')`. Return the index of the
        # function token itself, NOT past it, so the main loop records it in
        # `functions`. Returning past it was how `FROM read_parquet('/etc/
        # passwd')` reached `statement_problems` with no tables and no
        # functions, and was reported as safe.
        return index, found

    parts = [_unquote(token.text)]
    index += 1
    while (index + 1 < len(code) and code[index].kind == "punct"
           and code[index].text == "." and code[index + 1].kind in
           ("word", "identifier")):
        parts.append(_unquote(code[index + 1].text))
        index += 2
    if len(parts) == 1:
        found.append(("", parts[0]))
    else:
        found.append((parts[-2], parts[-1]))
    return index, found


def _scopes(code: list[Token], cte_names: list[str]) -> dict[int, str]:
    """Which CTE each token position sits inside, or "" for the outer query.

    Built by walking parentheses and remembering the CTE name that opened the
    current one. It is what lets `codeguard` tell "these two tables are joined
    to each other" from "these two tables are read in separate CTEs and their
    results are combined" — the second is how every composite metric's SQL
    looks, and refusing it would refuse the shape the builder is meant to
    prefer.
    """
    known = {c.lower() for c in cte_names}
    scopes: dict[int, str] = {}
    stack: list[str] = []
    current = ""
    pending = ""
    for index, token in enumerate(code):
        if token.kind == "punct" and token.text == "(":
            stack.append(current)
            if pending:
                current = pending
            pending = ""
            scopes[index] = current
            continue
        if token.kind == "punct" and token.text == ")":
            scopes[index] = current
            current = stack.pop() if stack else ""
            continue
        scopes[index] = current
        if (token.kind == "word" and token.word == "as" and index
                and code[index - 1].kind in ("word", "identifier")):
            name = _unquote(code[index - 1].text)
            if name.lower() in known:
                pending = name
    return scopes


def _bare_aliases(code: list[Token]) -> list[str]:
    """Table aliases written without AS: `FROM portfolio_facility p`.

    Common, and invisible to the AS sweep. Without this, `p` in `p.exposure`
    reads as a column nobody can find.
    """
    found: list[str] = []
    for index, token in enumerate(code):
        if token.kind != "word" or token.word not in _TABLE_INTRODUCERS:
            continue
        after = code[index + 1] if index + 1 < len(code) else None
        alias = code[index + 2] if index + 2 < len(code) else None
        if after is None or after.kind not in ("word", "identifier"):
            continue
        if after.kind == "word" and after.word in _KEYWORDS:
            continue
        if alias is None or alias.kind not in ("word", "identifier"):
            continue
        if alias.kind == "word" and alias.word in _KEYWORDS:
            continue
        found.append(_unquote(alias.text))
    return found


def statement_problems(sql: str, reading: Reading | None = None) -> list[str]:
    """§8H. Everything about this statement that makes it unsafe to run.

    Returned as sentences and all at once, so a repair packet can carry the
    whole picture rather than one refusal per round trip.
    """
    text = (sql or "").strip()
    if not text:
        return ["There is no SQL to check."]
    found: list[str] = []
    reading = reading or read(text)

    if reading.statements > 1:
        found.append(
            f"This is {reading.statements} statements. A metric is one "
            "read-only query; anything after the first semicolon is refused "
            "whatever it says.")

    if reading.first_word not in ("select", "with"):
        found.append(
            f"A metric's query must begin with SELECT or WITH. This one "
            f"begins with '{reading.first_word.upper() or '?'}'.")

    writes = sorted({k for k in reading.keywords_used})
    if writes:
        found.append(
            "This query contains " + ", ".join(w.upper() for w in writes)
            + ". A metric reads; it never writes, defines, loads or grants. "
              "Rewrite it as a SELECT over the governed datasets.")

    unsafe = sorted({f for f in reading.functions
                     if f in FORBIDDEN_FUNCTIONS
                     or f.startswith(("pg_", "duckdb_", "read_"))})
    if unsafe:
        found.append(
            "This query calls " + ", ".join(unsafe)
            + ", which reaches outside the governed datasets — the file "
              "system, the network, or the engine's own internals. A metric "
              "reads governed datasets by name and nothing else.")

    schemas = sorted({s.lower() for s in reading.schemas
                      if s.lower() in FORBIDDEN_SCHEMAS})
    if schemas:
        found.append(
            "This query reads " + ", ".join(schemas)
            + ", which are system catalogues rather than governed data.")

    # ANY explicit schema qualifier, not only a forbidden one. A metric names
    # a governed dataset and CreditProbe decides where it lives; a statement
    # that says `other_tenant.portfolio_facility` is asking to read somewhere
    # this deployment did not put the data, which is §8H's cross-tenant case.
    qualified = sorted({s for s in reading.schemas
                        if s.lower() not in FORBIDDEN_SCHEMAS})
    if qualified:
        found.append(
            "This query qualifies a table with a schema ("
            + ", ".join(qualified)
            + "). A metric names a governed dataset by its own name, and "
              "CreditProbe decides where that dataset lives.")
    return found


__all__ = [
    "AGGREGATE_FUNCTIONS", "FORBIDDEN_FUNCTIONS", "FORBIDDEN_KEYWORDS",
    "FORBIDDEN_SCHEMAS", "FORBIDDEN_STATEMENT_STARTS", "SQLGUARD_VERSION",
    "Reading", "Token", "read", "statement_problems", "tokenise",
]

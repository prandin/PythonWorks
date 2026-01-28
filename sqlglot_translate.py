# Requires: pip install sqlglot
import re
import sqlglot
from sqlglot import exp

# --------------------------------------------------
# Utilities
# --------------------------------------------------

def indent(level: int) -> str:
    return "\t" * level

def flatten(node, cls):
    """Flatten left-deep AND / OR trees."""
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]

# --------------------------------------------------
# Function translation
# --------------------------------------------------

def translate_function(node: exp.Expression) -> str:
    """Translate SQL functions into English."""
    # UPPER(TRIM(col))
    if isinstance(node, exp.Upper) and isinstance(node.this, exp.Trim):
        col = node.this.this.sql()
        return (
            f"the upper-case version of {col} "
            f"after removing leading and trailing whitespace"
        )

    # TRIM(col)
    if isinstance(node, exp.Trim):
        return f"the value of {node.this.sql()} after trimming whitespace"

    # Generic function
    if isinstance(node, exp.Func):
        return f"the result of {node.sql()}"

    # Column / literal fallback
    return node.sql()

# --------------------------------------------------
# NULL detection
# --------------------------------------------------

def detect_null_check(node):
    """Detect IS NULL / NOT IS NULL."""
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        return "is_not_null", node.this.this.sql()

    if isinstance(node, exp.Is):
        return "is_null", node.this.sql()

    return None, None

# --------------------------------------------------
# Core expression explainer
# --------------------------------------------------

def explain_expression(node, level: int, path: list[int]) -> str:
    label = ".".join(map(str, path))
    prefix = f"{indent(level)}Condition {label}: "

    # ---- NULL checks ----
    kind, lhs = detect_null_check(node)
    if kind == "is_null":
        return prefix + f"{lhs} is null"
    if kind == "is_not_null":
        return prefix + f"{lhs} is not null"

    # ---- AND ----
    if isinstance(node, exp.And):
        parts = flatten(node, exp.And)
        text = prefix + "All of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # ---- OR ----
    if isinstance(node, exp.Or):
        parts = flatten(node, exp.Or)
        text = prefix + "At least one of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # ---- IN (...) ----
    if isinstance(node, exp.In):
        lhs = translate_function(node.this)
        values = ", ".join(v.sql() for v in node.expressions)
        return prefix + f"{lhs} is one of ({values})"

    # ---- LIKE ----
    if isinstance(node, exp.Like):
        lhs = translate_function(node.this)
        pattern = node.expression.sql().strip("'")

        # %X% → contains substring
        if pattern.startswith("%") and pattern.endswith("%") and "_" not in pattern:
            substring = pattern.strip("%")
            return prefix + f"{lhs} contains '{substring}' as a substring"

        return prefix + f"{lhs} matches the pattern '{pattern}'"

    # ---- NOT LIKE ----
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Like):
        inner = node.this
        lhs = translate_function(inner.this)
        pattern = inner.expression.sql().strip("'")

        if pattern.startswith("%") and pattern.endswith("%") and "_" not in pattern:
            substring = pattern.strip("%")
            return prefix + f"{lhs} does not contain '{substring}' as a substring"

        return prefix + f"{lhs} does not match the pattern '{pattern}'"

    # ---- Binary operators (=, <>, !=, <, <=, >, >=) ----
    if isinstance(node, exp.Binary):
        lhs = translate_function(node.left)
        rhs = node.right.sql()
        op = node.op

        if op in ("<>", "!="):
            return prefix + f"{lhs} is not equal to {rhs}"
        if op == "=":
            return prefix + f"{lhs} equals {rhs}"
        if op == "<":
            return prefix + f"{lhs} is less than {rhs}"
        if op == "<=":
            return prefix + f"{lhs} is less than or equal to {rhs}"
        if op == ">":
            return prefix + f"{lhs} is greater than {rhs}"
        if op == ">=":
            return prefix + f"{lhs} is greater than or equal to {rhs}"

        return prefix + node.sql()

    # ---- Fallback ----
    return prefix + node.sql()

# --------------------------------------------------
# CASE + alias detection
# --------------------------------------------------

def find_case_and_alias(parsed):
    cases = list(parsed.find_all(exp.Case))
    if not cases:
        return None, None

    case = cases[0]

    for alias in parsed.find_all(exp.Alias):
        if alias.this is case:
            try:
                return case, alias.alias
            except Exception:
                a = alias.args.get("alias")
                return case, a.sql() if a else None

    # Regex fallback
    m = re.search(r"\bAS\s+([A-Za-z0-9_]+)\s*$", parsed.sql(), re.IGNORECASE)
    return case, m.group(1) if m else None

# --------------------------------------------------
# CASE explainer
# --------------------------------------------------

def explain_case_with_header(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)
    case, alias = find_case_and_alias(parsed)

    if case is None:
        raise ValueError("No CASE expression found.")

    header = (
        f"Column '{alias}' is computed as:"
        if alias else
        "Computed column is derived as:"
    )

    output = [header, ""]

    for i, when in enumerate(case.args.get("ifs", []), start=1):
        cond = when.this
        result = when.args.get("true")

        if isinstance(cond, (exp.And, exp.Or)):
            output.append(f"Condition {i}: IF")
            output.append(explain_expression(cond, 1, [i, 1]))
        else:
            output.append(explain_expression(cond, 1, [i]))

        output.append(f"\tTHEN return {result.sql()}\n")

    default = case.args.get("default")
    if default is not None:
        output.append(f"ELSE return {default.sql()}")

    return "\n".join(output)

# --------------------------------------------------
# Public API
# --------------------------------------------------

def translate_sql(sql_text: str) -> str:
    return explain_case_with_header(sql_text)

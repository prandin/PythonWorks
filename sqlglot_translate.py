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
    """
    Flatten left-deep AND / OR trees into a list.
    """
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]

# --------------------------------------------------
# Function translation
# --------------------------------------------------

def translate_function(node: exp.Expression) -> str:
    """
    Translate SQL functions into English.
    """
    # UPPER(TRIM(col))
    if isinstance(node, exp.Upper) and isinstance(node.this, exp.Trim):
        attr = node.this.this.sql()
        return (
            f"the upper-case version of {attr} "
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
    """
    Detect:
      - X IS NULL
      - NOT (X IS NULL)
    """
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        lhs = node.this.this.sql()
        return "is_not_null", lhs

    if isinstance(node, exp.Is):
        lhs = node.this.sql()
        return "is_null", lhs

    return None, None

# --------------------------------------------------
# Operator mapping
# --------------------------------------------------

OP_MAP = {
    "=": "equals",
    "==": "equals",
    "<": "is less than",
    "<=": "is less than or equal to",
    ">": "is greater than",
    ">=": "is greater than or equal to",
}

# --------------------------------------------------
# Core expression explainer
# --------------------------------------------------

def explain_expression(node, level: int, path: list[int]) -> str:
    """
    Recursively explain an AST node with hierarchical numbering.
    """
    label = ".".join(map(str, path))
    prefix = f"{indent(level)}Condition {label}: "

    # ---- NULL checks ----
    kind, lhs = detect_null_check(node)
    if kind == "is_not_null":
        return prefix + f"{lhs} is not null"
    if kind == "is_null":
        return prefix + f"{lhs} is null"

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

    # ---- NOT EQUAL (<> / !=) ----
    if isinstance(node, (exp.NEQ, exp.NotEq)):
        left = translate_function(node.left)
        right = node.right.sql()
        return prefix + f"{left} is not equal to {right}"

    # ---- LIKE ----
    if isinstance(node, exp.Like):
        left = translate_function(node.this)
        pattern = node.expression.sql().strip("'")

        # %X% → contains substring
        if pattern.startswith("%") and pattern.endswith("%") and "_" not in pattern:
            substring = pattern.strip("%")
            return prefix + f"{left} contains '{substring}' as a substring"

        return prefix + f"{left} matches the pattern '{pattern}'"

    # ---- NOT LIKE ----
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Like):
        inner = node.this
        left = translate_function(inner.this)
        pattern = inner.expression.sql().strip("'")

        if pattern.startswith("%") and pattern.endswith("%") and "_" not in pattern:
            substring = pattern.strip("%")
            return prefix + f"{left} does not contain '{substring}' as a substring"

        return prefix + f"{left} does not match the pattern '{pattern}'"

    # ---- Generic binary operators (=, <, >, etc.) ----
    if isinstance(node, exp.Binary):
        left = translate_function(node.left)
        right = node.right.sql()
        op = getattr(node, "op", None)
        op_text = OP_MAP.get(op, op)

        if op_text:
            return prefix + f"{left} {op_text} {right}"

        return prefix + node.sql()

    # ---- Fallback ----
    return prefix + node.sql()

# --------------------------------------------------
# CASE + alias detection
# --------------------------------------------------

def find_case_and_alias(parsed):
    """
    Locate the CASE expression and alias (AS column_name).
    """
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

        # Compound condition
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
    """
    Public entry point.
    """
    return explain_case_with_header(sql_text)

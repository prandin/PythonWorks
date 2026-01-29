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
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]

# --------------------------------------------------
# Function / expression translation
# --------------------------------------------------

def translate_expression(node: exp.Expression) -> str:
    """
    Translate expressions into controlled English.
    """

    # ---------- Column / literal ----------
    if isinstance(node, (exp.Column, exp.Identifier, exp.Literal)):
        return node.sql()

    # ---------- TRIM family ----------
    if isinstance(node, exp.LTrim):
        return f"{translate_expression(node.this)} with leading whitespace removed"

    if isinstance(node, exp.RTrim):
        return f"{translate_expression(node.this)} with trailing whitespace removed"

    if isinstance(node, exp.Trim):
        return f"{translate_expression(node.this)} with leading and trailing whitespace removed"

    # ---------- UPPER ----------
    if isinstance(node, exp.Upper):
        return f"the upper-case version of {translate_expression(node.this)}"

    # ---------- COALESCE ----------
    if isinstance(node, exp.Coalesce):
        args = ", ".join(translate_expression(a) for a in node.expressions)
        return f"the first non-null value among ({args})"

    # ---------- ROUND ----------
    if isinstance(node, exp.Round):
        expr = translate_expression(node.this)
        decimals = node.args.get("decimals")
        if decimals:
            return f"{expr} rounded to {decimals.sql()} decimal places"
        return f"{expr} rounded"

    # ---------- SUM ----------
    if isinstance(node, exp.Sum):
        return f"the sum of {translate_expression(node.this)}"

    # ---------- Arithmetic ----------
    if isinstance(node, exp.Add):
        return f"{translate_expression(node.left)} plus {translate_expression(node.right)}"

    if isinstance(node, exp.Sub):
        return f"{translate_expression(node.left)} minus {translate_expression(node.right)}"

    if isinstance(node, exp.Mul):
        return f"{translate_expression(node.left)} multiplied by {translate_expression(node.right)}"

    if isinstance(node, exp.Div):
        return f"{translate_expression(node.left)} divided by {translate_expression(node.right)}"

    # ---------- Fallback ----------
    return f"the result of {node.sql()}"

# --------------------------------------------------
# NULL detection
# --------------------------------------------------

def detect_null_check(node):
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        return "is_not_null", translate_expression(node.this.this)

    if isinstance(node, exp.Is):
        return "is_null", translate_expression(node.this)

    return None, None

# --------------------------------------------------
# Predicate explainer
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

    # ---- IN ----
    if isinstance(node, exp.In):
        lhs = translate_expression(node.this)
        values = ", ".join(v.sql() for v in node.expressions)
        return prefix + f"{lhs} is one of ({values})"

    # ---- LIKE ----
    if isinstance(node, exp.Like):
        lhs = translate_expression(node.this)
        pattern = node.expression.sql().strip("'")
        if pattern.startswith("%") and pattern.endswith("%") and "_" not in pattern:
            return prefix + f"{lhs} contains '{pattern.strip('%')}' as a substring"
        return prefix + f"{lhs} matches the pattern '{pattern}'"

    # ---- NOT LIKE ----
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Like):
        inner = node.this
        lhs = translate_expression(inner.this)
        pattern = inner.expression.sql().strip("'")
        if pattern.startswith("%") and pattern.endswith("%") and "_" not in pattern:
            return prefix + f"{lhs} does not contain '{pattern.strip('%')}' as a substring"
        return prefix + f"{lhs} does not match the pattern '{pattern}'"

    # ---- Binary comparisons ----
    if isinstance(node, exp.Binary):
        lhs = translate_expression(node.left)
        rhs = translate_expression(node.right)
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

    # ---- Fallback ----
    return prefix + node.sql()

# --------------------------------------------------
# CASE + alias
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

    m = re.search(r"\bAS\s+([A-Za-z0-9_]+)\s*$", parsed.sql(), re.IGNORECASE)
    return case, m.group(1) if m else None

# --------------------------------------------------
# CASE explainer
# --------------------------------------------------

def explain_case_with_header(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)
    case, alias = find_case_and_alias(parsed)

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

        output.append(f"\tTHEN return {translate_expression(result)}\n")

    default = case.args.get("default")
    if default:
        output.append(f"ELSE return {translate_expression(default)}")

    return "\n".join(output)

# --------------------------------------------------
# Public API
# --------------------------------------------------

def translate_sql(sql_text: str) -> str:
    return explain_case_with_header(sql_text)

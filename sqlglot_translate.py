# ===============================
# SQL CASE → English Translator
# ===============================

# pip install sqlglot
import re
import sqlglot
from sqlglot import exp


# -------------------------------
# Helpers
# -------------------------------

def indent(level: int) -> str:
    return "\t" * level


def flatten(node, cls):
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]


# -------------------------------
# Value / expression translation
# -------------------------------

def translate_expression(node: exp.Expression) -> str:
    if isinstance(node, (exp.Column, exp.Identifier)):
        return node.sql()

    if isinstance(node, exp.Literal):
        return node.sql()

    # TRIM family
    if isinstance(node, exp.Trim):
        expr = translate_expression(node.this)
        where = node.args.get("where")
        if where == "LEADING":
            return f"{expr} with leading whitespace removed"
        if where == "TRAILING":
            return f"{expr} with trailing whitespace removed"
        return f"{expr} with leading and trailing whitespace removed"

    if isinstance(node, exp.Upper):
        return f"the upper case of {translate_expression(node.this)}"

    if isinstance(node, exp.Coalesce):
        args = ", ".join(translate_expression(a) for a in node.expressions)
        return f"the first non-null value among ({args})"

    if isinstance(node, exp.Sum):
        return f"the sum of {translate_expression(node.this)}"

    if isinstance(node, exp.Round):
        expr = translate_expression(node.this)
        dec = node.args.get("decimals")
        if dec:
            return f"{expr} rounded to {dec.sql()} decimal places"
        return f"{expr} rounded"

    # Arithmetic
    if isinstance(node, exp.Add):
        return f"{translate_expression(node.left)} plus {translate_expression(node.right)}"
    if isinstance(node, exp.Sub):
        return f"{translate_expression(node.left)} minus {translate_expression(node.right)}"
    if isinstance(node, exp.Mul):
        return f"{translate_expression(node.left)} multiplied by {translate_expression(node.right)}"
    if isinstance(node, exp.Div):
        return f"{translate_expression(node.left)} divided by {translate_expression(node.right)}"

    return node.sql()


# -------------------------------
# NULL detection
# -------------------------------

def detect_null(node):
    if isinstance(node, exp.Is):
        return "is_null", translate_expression(node.this)
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        return "is_not_null", translate_expression(node.this.this)
    return None, None


# -------------------------------
# Predicate explanation
# -------------------------------

def explain_expression(node, level: int, path: list[int]) -> str:
    label = ".".join(map(str, path))
    prefix = f"{indent(level)}Condition {label}: "

    kind, target = detect_null(node)
    if kind == "is_null":
        return prefix + f"{target} is null"
    if kind == "is_not_null":
        return prefix + f"{target} is not null"

    # AND
    if isinstance(node, exp.And):
        parts = flatten(node, exp.And)
        text = prefix + "All of the following must be true:\n"
        for i, p in enumerate(parts, 1):
            text += explain_expression(p, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # OR
    if isinstance(node, exp.Or):
        parts = flatten(node, exp.Or)
        text = prefix + "At least one of the following must be true:\n"
        for i, p in enumerate(parts, 1):
            text += explain_expression(p, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # IN (...)
    if isinstance(node, exp.In):
        lhs = translate_expression(node.this)
        values = ", ".join(v.sql() for v in node.expressions)
        return prefix + f"{lhs} is one of ({values})"

    # LIKE
    if isinstance(node, exp.Like):
        lhs = translate_expression(node.this)
        pattern = node.expression.sql().strip("'")
        if pattern.startswith("%") and pattern.endswith("%"):
            return prefix + f"{lhs} contains '{pattern.strip('%')}' as a substring"
        return prefix + f"{lhs} matches the pattern '{pattern}'"

    # NOT LIKE
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Like):
        lhs = translate_expression(node.this.this)
        pattern = node.this.expression.sql().strip("'")
        if pattern.startswith("%") and pattern.endswith("%"):
            return prefix + f"{lhs} does not contain '{pattern.strip('%')}' as a substring"
        return prefix + f"{lhs} does not match the pattern '{pattern}'"

    # ---------------------------
    # Comparisons (NO node.op!)
    # ---------------------------

    if isinstance(node, exp.EQ):
        return prefix + f"{translate_expression(node.left)} equals {translate_expression(node.right)}"

    if isinstance(node, exp.NEQ):
        return prefix + f"{translate_expression(node.left)} is not equal to {translate_expression(node.right)}"

    if isinstance(node, exp.LT):
        return prefix + f"{translate_expression(node.left)} is less than {translate_expression(node.right)}"

    if isinstance(node, exp.LTE):
        return prefix + f"{translate_expression(node.left)} is less than or equal to {translate_expression(node.right)}"

    if isinstance(node, exp.GT):
        return prefix + f"{translate_expression(node.left)} is greater than {translate_expression(node.right)}"

    if isinstance(node, exp.GTE):
        return prefix + f"{translate_expression(node.left)} is greater than or equal to {translate_expression(node.right)}"

    return prefix + node.sql()


# -------------------------------
# CASE + alias detection
# -------------------------------

def extract_case_and_alias(parsed):
    case = next(parsed.find_all(exp.Case), None)
    alias = None

    for a in parsed.find_all(exp.Alias):
        if a.this is case:
            alias = a.alias
            break

    if not alias:
        m = re.search(r"\bAS\s+([A-Za-z0-9_]+)\s*$", parsed.sql(), re.IGNORECASE)
        if m:
            alias = m.group(1)

    return case, alias


# -------------------------------
# CASE explanation
# -------------------------------

def explain_case(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)
    case, alias = extract_case_and_alias(parsed)

    header = (
        f"Column '{alias}' is computed as:"
        if alias else
        "Computed column is derived as:"
    )

    output = [header, ""]

    for i, when in enumerate(case.args.get("ifs", []), 1):
        cond = when.this
        result = when.args["true"]

        output.append(f"Condition {i}: IF")
        output.append(explain_expression(cond, 1, [i, 1]))
        output.append(f"\tTHEN return {translate_expression(result)}\n")

    default = case.args.get("default")
    if default:
        output.append(f"ELSE return {translate_expression(default)}")

    return "\n".join(output)


# -------------------------------
# Public API
# -------------------------------

def translate_sql(sql_text: str) -> str:
    return explain_case(sql_text)

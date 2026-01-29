from typing import List
import sqlglot
from sqlglot import expressions as exp


# =====================================================
# PUBLIC ENTRY POINT
# =====================================================

def translate_sql(sql_text: str) -> str:
    return explain_case_with_header(sql_text)


# =====================================================
# CASE + HEADER
# =====================================================

def explain_case_with_header(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)

    alias = None
    if isinstance(parsed, exp.Alias):
        alias = parsed.alias
        case = parsed.this
    else:
        case = parsed.find(exp.Case)

    header = ""
    if alias:
        header = f"Column '{alias}' is computed as:\n\n"

    output = []

    for i, cond in enumerate(case.args.get("ifs", []), start=1):
        output.append(f"Condition {i}: IF")
        output.append(explain_expression(cond.this, 1, [i]))
        output.append(f"THEN return {translate_expression(cond.args['true'])}\n")

    if case.args.get("default"):
        output.append(f"ELSE return {translate_expression(case.args['default'])}")

    return header + "\n".join(output)


# =====================================================
# CONDITION EXPLANATION (NUMBERED)
# =====================================================

def explain_expression(node, level: int, path: List[int]) -> str:
    prefix = "    " * level
    label = f"Condition {'.'.join(map(str, path))}: "

    # AND
    if isinstance(node, exp.And):
        lines = [prefix + label + "All of the following must be true:"]
        for i, part in enumerate(node.flatten(), start=1):
            lines.append(explain_expression(part, level + 1, path + [i]))
        return "\n".join(lines)

    # OR
    if isinstance(node, exp.Or):
        lines = [prefix + label + "At least one of the following must be true:"]
        for i, part in enumerate(node.flatten(), start=1):
            lines.append(explain_expression(part, level + 1, path + [i]))
        return "\n".join(lines)

    # Comparisons
    if isinstance(node, (exp.EQ, exp.NEQ, exp.LT, exp.LTE, exp.GT, exp.GTE)):
        lhs = translate_expression(node.left)
        rhs = translate_expression(node.right)

        ops = {
            exp.EQ: "equals",
            exp.NEQ: "is not equal to",
            exp.LT: "is less than",
            exp.LTE: "is less than or equal to",
            exp.GT: "is greater than",
            exp.GTE: "is greater than or equal to",
        }
        return prefix + label + f"{lhs} {ops[type(node)]} {rhs}"

    # LIKE
    if isinstance(node, exp.Like):
        return prefix + label + f"{translate_expression(node.this)} contains {translate_expression(node.expression)} as a substring"

    if isinstance(node, exp.NotLike):
        return prefix + label + f"{translate_expression(node.this)} does not contain {translate_expression(node.expression)} as a substring"

    # IN
    if isinstance(node, exp.In):
        values = ", ".join(translate_expression(v) for v in node.expressions)
        return prefix + label + f"{translate_expression(node.this)} is one of ({values})"

    # NULL
    if isinstance(node, exp.Is):
        return prefix + label + f"{translate_expression(node.this)} is null"

    if isinstance(node, exp.IsNot):
        return prefix + label + f"{translate_expression(node.this)} is not null"

    # Fallback → translate expression, NOT sql()
    return prefix + label + translate_expression(node)


# =====================================================
# EXPRESSION TRANSLATION (FULL RECURSION)
# =====================================================

def translate_expression(node) -> str:
    if node is None:
        return ""

    # Columns / literals
    if isinstance(node, exp.Column):
        return node.sql()

    if isinstance(node, exp.Literal):
        return node.sql()

    # Arithmetic
    if isinstance(node, exp.Add):
        return f"{translate_expression(node.left)} plus {translate_expression(node.right)}"

    if isinstance(node, exp.Sub):
        return f"{translate_expression(node.left)} minus {translate_expression(node.right)}"

    if isinstance(node, exp.Mul):
        return f"{translate_expression(node.left)} multiplied by {translate_expression(node.right)}"

    if isinstance(node, exp.Div):
        return f"{translate_expression(node.left)} divided by {translate_expression(node.right)}"

    # Parentheses
    if isinstance(node, exp.Paren):
        return translate_expression(node.this)

    # ================= FUNCTIONS =================

    if isinstance(node, exp.Coalesce):
        args = ", ".join(translate_expression(a) for a in node.expressions)
        return f"the first non-null value among ({args})"

    if isinstance(node, exp.Sum):
        return f"the sum of {translate_expression(node.this)}"

    if isinstance(node, exp.Greatest):
        args = ", ".join(translate_expression(a) for a in node.expressions)
        return f"the greatest value among ({args})"

    if isinstance(node, exp.Round):
        return f"{translate_expression(node.this)} rounded"

    if isinstance(node, exp.Trim):
        return f"{translate_expression(node.this)} with whitespace removed"

    # ================= WINDOW FUNCTIONS =================

    if isinstance(node, exp.Window):
        base = translate_expression(node.this)
        parts = []

        if node.args.get("partition_by"):
            cols = ", ".join(c.sql() for c in node.args["partition_by"])
            parts.append(f"partitioned by {cols}")

        if node.args.get("order"):
            parts.append("ordered")

        suffix = ""
        if parts:
            suffix = " (" + ", ".join(parts) + ")"

        return base + suffix

    # CASE inside expressions
    if isinstance(node, exp.Case):
        return "a conditional value based on multiple conditions"

    # LAST SAFE FALLBACK
    return node.sql()

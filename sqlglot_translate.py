from typing import List
import sqlglot
from sqlglot import expressions as exp


# ---------------------------
# Public entry point
# ---------------------------

def translate_sql(sql_text: str) -> str:
    return explain_case_with_header(sql_text)


# ---------------------------
# CASE handling
# ---------------------------

def explain_case_with_header(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)
    case = parsed.find(exp.Case)

    alias = None
    if isinstance(parsed, exp.Alias):
        alias = parsed.alias

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


# ---------------------------
# Recursive explanation
# ---------------------------

def explain_expression(node, level: int, path: List[int]) -> str:
    prefix = "    " * level
    label = "Condition " + ".".join(map(str, path)) + ": "

    # AND / OR
    if isinstance(node, exp.And):
        lines = [prefix + label + "All of the following must be true:"]
        for i, part in enumerate(node.flatten(), start=1):
            lines.append(explain_expression(part, level + 1, path + [i]))
        return "\n".join(lines)

    if isinstance(node, exp.Or):
        lines = [prefix + label + "At least one of the following must be true:"]
        for i, part in enumerate(node.flatten(), start=1):
            lines.append(explain_expression(part, level + 1, path + [i]))
        return "\n".join(lines)

    # Comparisons
    if isinstance(node, (exp.EQ, exp.NEQ, exp.LT, exp.LTE, exp.GT, exp.GTE)):
        lhs = translate_expression(node.left)
        rhs = translate_expression(node.right)

        op_map = {
            exp.EQ: "equals",
            exp.NEQ: "is not equal to",
            exp.LT: "is less than",
            exp.LTE: "is less than or equal to",
            exp.GT: "is greater than",
            exp.GTE: "is greater than or equal to",
        }

        return prefix + label + f"{lhs} {op_map[type(node)]} {rhs}"

    # LIKE / NOT LIKE
    if isinstance(node, exp.Like):
        lhs = translate_expression(node.this)
        rhs = translate_expression(node.expression)
        return prefix + label + f"{lhs} contains {rhs} as a substring"

    if isinstance(node, exp.NotLike):
        lhs = translate_expression(node.this)
        rhs = translate_expression(node.expression)
        return prefix + label + f"{lhs} does not contain {rhs} as a substring"

    # IN
    if isinstance(node, exp.In):
        lhs = translate_expression(node.this)
        values = ", ".join(translate_expression(v) for v in node.expressions)
        return prefix + label + f"{lhs} is one of ({values})"

    # NULL checks
    if isinstance(node, exp.Is):
        lhs = translate_expression(node.this)
        return prefix + label + f"{lhs} is null"

    if isinstance(node, exp.IsNot):
        lhs = translate_expression(node.this)
        return prefix + label + f"{lhs} is not null"

    # Fallback (safe)
    return prefix + label + translate_expression(node)


# ---------------------------
# Expression translation
# ---------------------------

def translate_expression(node) -> str:
    if node is None:
        return ""

    if isinstance(node, exp.Column):
        return node.sql()

    if isinstance(node, exp.Literal):
        return node.sql()

    if isinstance(node, exp.Add):
        return f"{translate_expression(node.left)} plus {translate_expression(node.right)}"

    if isinstance(node, exp.Sub):
        return f"{translate_expression(node.left)} minus {translate_expression(node.right)}"

    if isinstance(node, exp.Mul):
        return f"{translate_expression(node.left)} multiplied by {translate_expression(node.right)}"

    if isinstance(node, exp.Div):
        return f"{translate_expression(node.left)} divided by {translate_expression(node.right)}"

    # -------- Functions --------

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

    # sqlglot represents LTRIM/RTRIM as Trim with flags
    if isinstance(node, exp.Trim):
        return f"{translate_expression(node.this)} with whitespace removed"

    # Parentheses
    if isinstance(node, exp.Paren):
        return translate_expression(node.this)

    # Default safe fallback
    return node.sql()

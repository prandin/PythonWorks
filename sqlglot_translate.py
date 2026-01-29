from typing import List
from sqlglot import parse_one, expressions as exp


# ----------------------------
# Formatting helpers
# ----------------------------

def indent(level: int) -> str:
    return "  " * level


# ----------------------------
# Entry point
# ----------------------------

def translate_sql(sql_text: str) -> str:
    tree = parse_one(sql_text)
    return explain_case_with_header(tree)


# ----------------------------
# CASE handling
# ----------------------------

def explain_case_with_header(sql_text: str) -> str:
    tree = parse_one(sql_text)

    case = tree.find(exp.Case)
    if not case:
        return translate_expression(tree)

    header = "Column is computed as:\n\n"
    return header + explain_case(case, 1)


def explain_case(case: exp.Case, level: int) -> str:
    """
    Correctly walks sqlglot CASE as a chain of exp.If nodes
    """
    out = []
    idx = 1

    current = case.args.get("ifs")

    while isinstance(current, exp.If):
        cond = current.this
        result = current.args.get("true")

        out.append(f"{indent(level)}Condition {idx}: IF")
        out.append(explain_condition(cond, level + 1, [idx]))
        out.append(
            f"{indent(level + 1)}THEN return {translate_expression(result)}"
        )

        idx += 1
        current = current.args.get("false")

    # ELSE
    if current is not None:
        out.append(
            f"{indent(level)}ELSE return {translate_expression(current)}"
        )

    return "\n".join(out)


# ----------------------------
# Conditions
# ----------------------------

def explain_condition(node, level: int, path: List[int]) -> str:
    label = ".".join(map(str, path))

    if isinstance(node, exp.And):
        out = [
            f"{indent(level)}Condition {label}: All of the following must be true:"
        ]
        for i, part in enumerate(node.flatten(), 1):
            out.append(
                explain_condition(part, level + 1, path + [i])
            )
        return "\n".join(out)

    if isinstance(node, exp.Or):
        out = [
            f"{indent(level)}Condition {label}: At least one of the following must be true:"
        ]
        for i, part in enumerate(node.flatten(), 1):
            out.append(
                explain_condition(part, level + 1, path + [i])
            )
        return "\n".join(out)

    return f"{indent(level)}Condition {label}: {translate_expression(node)}"


# ----------------------------
# Expression translation
# ----------------------------

def translate_expression(node) -> str:
    if node is None:
        return "NULL"

    # CASE inside CASE
    if isinstance(node, exp.Case):
        return f"(\n{explain_case(node, 2)}\n)"

    # Comparisons
    if isinstance(node, exp.EQ):
        return f"{translate_expression(node.left)} equals {translate_expression(node.right)}"

    if isinstance(node, (exp.NEQ, exp.Not)):
        return f"{translate_expression(node.left)} is not equal to {translate_expression(node.right)}"

    if isinstance(node, exp.GT):
        return f"{translate_expression(node.left)} is greater than {translate_expression(node.right)}"

    if isinstance(node, exp.GTE):
        return f"{translate_expression(node.left)} is greater than or equal to {translate_expression(node.right)}"

    if isinstance(node, exp.LT):
        return f"{translate_expression(node.left)} is less than {translate_expression(node.right)}"

    if isinstance(node, exp.LTE):
        return f"{translate_expression(node.left)} is less than or equal to {translate_expression(node.right)}"

    # LIKE / NOT LIKE (string-based, no class assumptions)
    if isinstance(node, exp.Like):
        return f"{translate_expression(node.this)} contains {translate_expression(node.expression)}"

    if isinstance(node, exp.Not) and isinstance(node.this, exp.Like):
        like = node.this
        return f"{translate_expression(like.this)} does not contain {translate_expression(like.expression)}"

    # IN / NOT IN
    if isinstance(node, exp.In):
        values = ", ".join(translate_expression(e) for e in node.expressions)
        return f"{translate_expression(node.this)} is one of ({values})"

    if isinstance(node, exp.Not) and isinstance(node.this, exp.In):
        values = ", ".join(translate_expression(e) for e in node.this.expressions)
        return f"{translate_expression(node.this.this)} is not one of ({values})"

    # NULL checks
    if isinstance(node, exp.Is):
        return f"{translate_expression(node.this)} is {translate_expression(node.expression)}"

    # Functions
    if isinstance(node, exp.Func):
        return translate_function(node)

    # Columns / literals
    if isinstance(node, exp.Column):
        return node.sql()

    if isinstance(node, exp.Literal):
        return node.sql()

    # Fallback
    return node.sql()


# ----------------------------
# Function translation
# ----------------------------

def translate_function(node: exp.Func) -> str:
    name = node.name.upper()
    args = node.expressions or []

    if name == "COALESCE":
        return f"first non-null of ({', '.join(map(translate_expression, args))})"

    if name == "SUM":
        return f"sum of ({translate_expression(args[0])})"

    if name == "GREATEST":
        return f"maximum of ({', '.join(map(translate_expression, args))})"

    if name == "CAST":
        value = translate_expression(args[0]) if args else "value"
        target = node.args.get("to")
        return f"{value} cast to {target.sql() if target else 'type'}"

    if name in ("LTRIM", "RTRIM", "TRIM"):
        return f"trimmed value of ({translate_expression(args[0])})"

    # Safe fallback – never crash
    return f"{name.lower()}({', '.join(map(translate_expression, args))})"

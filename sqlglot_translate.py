from sqlglot import parse_one, exp


# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------
def translate_sql(sql_text: str) -> str:
    tree = parse_one(sql_text)

    case = extract_case(tree)

    if not case:
        # No CASE expression found – return original SQL
        return sql_text

    return explain_case_with_header(case)


# ------------------------------------------------------------
# AST utilities
# ------------------------------------------------------------
def extract_case(node):
    """
    Recursively unwrap Alias / Select / expressions
    until a CASE expression is found.
    """
    if node is None:
        return None

    if isinstance(node, exp.Case):
        return node

    if isinstance(node, exp.Alias):
        return extract_case(node.this)

    if isinstance(node, exp.Select):
        for e in node.expressions:
            found = extract_case(e)
            if found:
                return found

    if hasattr(node, "this"):
        return extract_case(node.this)

    return None


# ------------------------------------------------------------
# CASE explanation
# ------------------------------------------------------------
def explain_case_with_header(case: exp.Case) -> str:
    header = "Column is computed as:\n\n"
    return header + explain_case(case, level=1)


def explain_case(case: exp.Case, level: int) -> str:
    output = []

    ifs = case.args.get("ifs") or []
    default = case.args.get("default")

    for idx, if_node in enumerate(ifs, start=1):
        cond = if_node.this
        result = if_node.args.get("true")

        output.append(f"{indent(level)}Condition {idx}: IF")

        output.append(
            explain_condition(cond, level + 1, idx)
        )

        if isinstance(result, exp.Case):
            output.append(f"{indent(level + 1)}THEN return:")
            output.append(explain_case(result, level + 2))
        else:
            output.append(
                f"{indent(level + 1)}THEN return {translate_expression(result)}"
            )

        output.append("")

    if default is not None:
        if isinstance(default, exp.Case):
            output.append(f"{indent(level)}ELSE return:")
            output.append(explain_case(default, level + 1))
        else:
            output.append(
                f"{indent(level)}ELSE return {translate_expression(default)}"
            )

    return "\n".join(output)


# ------------------------------------------------------------
# Condition handling
# ------------------------------------------------------------
def explain_condition(node, level: int, parent_idx: int) -> str:
    """
    Handles AND / OR trees safely.
    """
    if isinstance(node, exp.And):
        lines = [f"{indent(level)}All of the following must be true:"]
        left = explain_condition(node.left, level + 1, parent_idx)
        right = explain_condition(node.right, level + 1, parent_idx)
        return "\n".join([lines[0], left, right])

    if isinstance(node, exp.Or):
        lines = [f"{indent(level)}Any of the following must be true:"]
        left = explain_condition(node.left, level + 1, parent_idx)
        right = explain_condition(node.right, level + 1, parent_idx)
        return "\n".join([lines[0], left, right])

    return f"{indent(level)}Condition {parent_idx}.{level}: {translate_expression(node)}"


# ------------------------------------------------------------
# Expression translation
# ------------------------------------------------------------
def translate_expression(node) -> str:
    if node is None:
        return "NULL"

    # Comparisons
    if isinstance(node, exp.EQ):
        return f"{translate_expression(node.left)} equals {translate_expression(node.right)}"

    if isinstance(node, (exp.NEQ, exp.Not)):
        return f"{translate_expression(node.this)} is not equal to {translate_expression(node.expression)}"

    if isinstance(node, exp.GT):
        return f"{translate_expression(node.left)} is greater than {translate_expression(node.right)}"

    if isinstance(node, exp.GTE):
        return f"{translate_expression(node.left)} is greater than or equal to {translate_expression(node.right)}"

    if isinstance(node, exp.LT):
        return f"{translate_expression(node.left)} is less than {translate_expression(node.right)}"

    if isinstance(node, exp.LTE):
        return f"{translate_expression(node.left)} is less than or equal to {translate_expression(node.right)}"

    # IN / NOT IN
    if isinstance(node, exp.In):
        values = ", ".join(translate_expression(v) for v in node.expressions)
        return f"{translate_expression(node.this)} is one of ({values})"

    # LIKE
    if isinstance(node, exp.Like):
        return f"{translate_expression(node.this)} contains {translate_expression(node.expression)}"

    # NULL checks
    if isinstance(node, exp.Is):
        if isinstance(node.expression, exp.Null):
            return f"{translate_expression(node.this)} is null"

    # Literals
    if isinstance(node, exp.Literal):
        return node.sql()

    # Column reference
    if isinstance(node, exp.Column):
        return node.sql()

    # Functions (safe fallback)
    if isinstance(node, exp.Func):
        return node.sql()

    # Generic fallback
    return node.sql()


# ------------------------------------------------------------
# Formatting
# ------------------------------------------------------------
def indent(level: int) -> str:
    return "    " * (level - 1)

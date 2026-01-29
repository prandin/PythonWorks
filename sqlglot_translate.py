from sqlglot import parse_one, exp


# -------------------------------
# Public API
# -------------------------------
def translate_sql(sql_text: str) -> str:
    return explain_case_with_header(sql_text)


# -------------------------------
# CASE with column header
# -------------------------------
def explain_case_with_header(sql_text: str) -> str:
    tree = parse_one(sql_text)
    case = tree.find(exp.Case)

    alias = None
    if isinstance(tree, exp.Alias):
        alias = tree.alias

    header = ""
    if alias:
        header = f"Column '{alias}' is computed as:\n\n"

    return header + explain_case(case, 1)


# -------------------------------
# CASE explanation
# -------------------------------
def explain_case(case: exp.Case, level: int) -> str:
    out = []
    idx = 1

    for cond, result in case.args.get("ifs", []):
        out.append(f"{indent(level)}Condition {idx}: IF")
        out.append(explain_condition(cond, level + 1, [idx]))
        out.append(
            f"{indent(level + 1)}THEN return {translate_expression(result)}"
        )
        idx += 1

    if case.args.get("default"):
        out.append(
            f"{indent(level)}ELSE return {translate_expression(case.args['default'])}"
        )

    return "\n".join(out)


def explain_condition(node, level: int, path: list[int]) -> str:
    prefix = f"{indent(level)}Condition {'.'.join(map(str, path))}: "

    if isinstance(node, exp.And):
        lines = [prefix + "All of the following must be true:"]
        i = 1
        for arg in node.flatten():
            lines.append(explain_condition(arg, level + 1, path + [i]))
            i += 1
        return "\n".join(lines)

    return prefix + translate_expression(node)


# -------------------------------
# Expression translation
# -------------------------------
def translate_expression(node) -> str:
    if node is None:
        return "NULL"

    # Nested CASE
    if isinstance(node, exp.Case):
        return "(" + explain_case(node, 0) + ")"

    # CAST (FIXED — ONLY correct way)
    if isinstance(node, exp.Cast):
        expr = translate_expression(node.this)
        target = node.args["to"].sql()
        return f"{expr} cast to {target}"

    # Columns
    if isinstance(node, exp.Column):
        return node.sql()

    # Literals
    if isinstance(node, exp.Literal):
        return node.this

    # Comparisons
    if isinstance(node, exp.EQ):
        return f"{translate_expression(node.left)} equals {translate_expression(node.right)}"

    if isinstance(node, exp.NEQ):
        return f"{translate_expression(node.left)} is not equal to {translate_expression(node.right)}"

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
        if node.args.get("negated"):
            return f"{translate_expression(node.this)} is not one of ({values})"
        return f"{translate_expression(node.this)} is one of ({values})"

    # LIKE / NOT LIKE (no NotLike class exists!)
    if isinstance(node, exp.Like):
        lhs = translate_expression(node.this)
        pattern = node.args["expression"].this.replace("%", "")
        if node.args.get("negated"):
            return f"{lhs} does not contain '{pattern}' as a substring"
        return f"{lhs} contains '{pattern}' as a substring"

    # Functions
    if isinstance(node, exp.Func):
        return translate_function(node)

    return node.sql()


# -------------------------------
# Function translation
# -------------------------------
def translate_function(node: exp.Func) -> str:
    name = node.sql_name().upper()
    args = [translate_expression(a) for a in node.args.get("expressions", [])]

    if name == "COALESCE":
        return f"the first non-null value among ({', '.join(args)})"

    if name == "SUM":
        return f"the sum of {args[0]}" if args else "the sum of values"

    if name == "GREATEST":
        return f"the maximum of ({', '.join(args)})"

    if name == "LEAST":
        return f"the minimum of ({', '.join(args)})"

    if name == "LTRIM":
        return f"{args[0]} with leading spaces removed"

    if name == "RTRIM":
        return f"{args[0]} with trailing spaces removed"

    if name == "TRIM":
        return f"{args[0]} with leading and trailing spaces removed"

    # Window functions
    if node.args.get("over"):
        return f"{name.lower()} of {args[0]} over a window"

    return node.sql()


def indent(n: int) -> str:
    return "  " * n

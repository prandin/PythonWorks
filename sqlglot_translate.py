from sqlglot import parse_one, expressions as exp


# =========================
# Public entry point
# =========================
def translate_sql(sql_text: str) -> str:
    return explain_case_with_header(sql_text)


# =========================
# CASE with column header
# =========================
def explain_case_with_header(sql_text: str) -> str:
    tree = parse_one(sql_text)

    case_expr = tree.find(exp.Case)
    alias = tree.args.get("alias")

    column_name = alias.this if alias else "computed_column"

    output = [f"Column '{column_name}' is computed as:\n"]

    for i, cond in enumerate(case_expr.args.get("ifs", []), start=1):
        output.append(f"Condition {i}: IF")
        output.append(explain_expression(cond.this, 1, [i]))
        output.append(f"THEN return {translate_expression(cond.args['true'], 1)}\n")

    if case_expr.args.get("default"):
        output.append(f"ELSE return {translate_expression(case_expr.args['default'], 1)}")

    return "\n".join(output)


# =========================
# Condition explanation (numbered)
# =========================
def explain_expression(node, level: int, path: list[int]) -> str:
    prefix = "  " * level
    label = ".".join(map(str, path))

    # AND
    if isinstance(node, exp.And):
        lines = [f"{prefix}Condition {label}: All of the following must be true:"]
        for i, part in enumerate(node.flatten(), start=1):
            lines.append(explain_expression(part, level + 1, path + [i]))
        return "\n".join(lines)

    # OR
    if isinstance(node, exp.Or):
        lines = [f"{prefix}Condition {label}: At least one of the following must be true:"]
        for i, part in enumerate(node.flatten(), start=1):
            lines.append(explain_expression(part, level + 1, path + [i]))
        return "\n".join(lines)

    # Leaf predicate
    return f"{prefix}Condition {label}: {translate_expression(node)}"


# =========================
# Expression → English
# =========================
def translate_expression(node, indent: int = 0) -> str:
    pad = "  " * indent

    if node is None:
        return "NULL"

    # ---------- Nested CASE ----------
    if isinstance(node, exp.Case):
        return explain_case_inline(node, indent)

    # ---------- Column ----------
    if isinstance(node, exp.Column):
        return node.sql()

    # ---------- Literals ----------
    if isinstance(node, exp.Literal):
        return node.this

    # ---------- Comparisons ----------
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

    # ---------- IN / NOT IN ----------
    if isinstance(node, exp.In):
        values = ", ".join(translate_expression(e) for e in node.expressions)
        if node.args.get("negated"):
            return f"{translate_expression(node.this)} is not one of ({values})"
        return f"{translate_expression(node.this)} is one of ({values})"

    # ---------- LIKE / NOT LIKE ----------
    if isinstance(node, exp.Like):
        lhs = translate_expression(node.this)
        raw = node.args["expression"].this
        pattern = raw.replace("%", "")
        if node.args.get("negated"):
            return f"{lhs} does not contain '{pattern}' as a substring"
        return f"{lhs} contains '{pattern}' as a substring"

    # ---------- Functions ----------
    if isinstance(node, exp.Func):
        return translate_function(node)

    return node.sql()


# =========================
# Nested CASE expansion
# =========================
def explain_case_inline(node: exp.Case, indent: int) -> str:
    pad = "  " * indent
    lines = [f"\n{pad}CASE"]

    for when in node.args.get("ifs", []):
        lines.append(f"{pad}  WHEN {translate_expression(when.this)}")
        lines.append(f"{pad}  THEN {translate_expression(when.args['true'], indent + 1)}")

    if node.args.get("default"):
        lines.append(f"{pad}  ELSE {translate_expression(node.args['default'], indent + 1)}")

    lines.append(f"{pad}END")
    return "\n".join(lines)


# =========================
# Function translations
# =========================
def translate_function(node: exp.Func) -> str:
    name = node.sql_name().upper()
    args = [translate_expression(a) for a in node.args.get("expressions", [])]

    if name == "COALESCE":
        return f"the first non-null value among ({', '.join(args)})"

    if name == "SUM":
        return f"the sum of {args[0]}"

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

    if name == "CAST":
        return f"{args[0]} cast to {node.args['to'].sql()}"

    # Window function
    if node.args.get("over"):
        over = node.args["over"]
        parts = []
        if over.args.get("partition_by"):
            cols = ", ".join(c.sql() for c in over.args["partition_by"].expressions)
            parts.append(f"partitioned by {cols}")
        return f"{name.lower()} of {args[0]} ({', '.join(parts)})"

    return node.sql()

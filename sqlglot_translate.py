def translate_expression(node, indent: int = 0) -> str:
    pad = "  " * indent

    if node is None:
        return "NULL"

    # ---------- Nested CASE ----------
    if isinstance(node, exp.Case):
        return explain_case_inline(node, indent)

    # ---------- CAST (FIXED) ----------
    if isinstance(node, exp.Cast):
        expr = translate_expression(node.this)
        target = node.args["to"].sql()
        return f"{expr} cast to {target}"

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

    # ---------- Generic Functions ----------
    if isinstance(node, exp.Func):
        return translate_function(node)

    return node.sql()

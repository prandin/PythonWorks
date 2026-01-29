from sqlglot import parse_one, expressions as exp


# ===============================
# PUBLIC ENTRY POINT
# ===============================

def translate_sql(sql_text: str) -> str:
    if not isinstance(sql_text, str):
        raise TypeError("translate_sql() expects SQL STRING only")

    tree = parse_one(sql_text)
    return explain_tree(tree)


# ===============================
# TOP LEVEL DISPATCH
# ===============================

def explain_tree(node) -> str:
    if isinstance(node, exp.Select):
        return explain_select(node)

    if isinstance(node, exp.Expression):
        return translate_expression(node)

    return str(node)


# ===============================
# SELECT / ALIAS HANDLING
# ===============================

def explain_select(select: exp.Select) -> str:
    output = []

    for projection in select.expressions:
        if isinstance(projection, exp.Alias):
            col_name = projection.alias
            output.append(f"Column '{col_name}' is computed as:")
            output.append(explain_expression(projection.this, 1))
        else:
            output.append(explain_expression(projection, 1))

    return "\n".join(output)


# ===============================
# CASE EXPRESSIONS
# ===============================

def explain_expression(node, level=1) -> str:
    indent = "    " * level

    if isinstance(node, exp.Case):
        return explain_case(node, level)

    if isinstance(node, exp.Binary):
        return indent + translate_binary(node)

    if isinstance(node, exp.Unary):
        return indent + translate_expression(node.this, level)

    if isinstance(node, exp.Func):
        return indent + translate_function(node)

    if isinstance(node, exp.Literal):
        return indent + node.sql()

    if isinstance(node, exp.Column):
        return indent + node.sql()

    if isinstance(node, exp.Expression):
        return indent + node.sql()

    return indent + str(node)


def explain_case(case: exp.Case, level: int) -> str:
    indent = "    " * level
    output = []

    for idx, when in enumerate(case.args.get("ifs", []), start=1):
        output.append(f"{indent}Condition {idx}: IF")
        output.append(explain_expression(when.this, level + 1))
        output.append(f"{indent}THEN return")
        output.append(explain_expression(when.args['true'], level + 1))

    if case.args.get("default"):
        output.append(f"{indent}ELSE return")
        output.append(explain_expression(case.args["default"], level + 1))

    return "\n".join(output)


# ===============================
# BINARY OPERATORS
# ===============================

def translate_binary(node: exp.Binary) -> str:
    left = translate_expression(node.left)
    right = translate_expression(node.right)

    if isinstance(node, exp.EQ):
        return f"{left} equals {right}"

    if isinstance(node, (exp.NEQ, exp.Not)):
        return f"{left} is not equal to {right}"

    if isinstance(node, exp.GT):
        return f"{left} is greater than {right}"

    if isinstance(node, exp.GTE):
        return f"{left} is greater than or equal to {right}"

    if isinstance(node, exp.LT):
        return f"{left} is less than {right}"

    if isinstance(node, exp.LTE):
        return f"{left} is less than or equal to {right}"

    if isinstance(node, exp.And):
        return f"{left} AND {right}"

    if isinstance(node, exp.Or):
        return f"{left} OR {right}"

    if isinstance(node, exp.Add):
        return f"{left} plus {right}"

    if isinstance(node, exp.Sub):
        return f"{left} minus {right}"

    if isinstance(node, exp.Mul):
        return f"{left} multiplied by {right}"

    if isinstance(node, exp.Div):
        return f"{left} divided by {right}"

    return f"{left} {node.__class__.__name__} {right}"


# ===============================
# FUNCTION TRANSLATION
# ===============================

def translate_function(node: exp.Func) -> str:
    name = node.sql_name().upper()
    args = [translate_expression(a) for a in node.expressions]

    if name == "COALESCE":
        return f"first non-null of ({', '.join(args)})"

    if name == "SUM":
        return f"sum of ({args[0]})"

    if name == "GREATEST":
        return f"maximum of ({', '.join(args)})"

    if name == "LTRIM":
        return f"{args[0]} with leading spaces removed"

    if name == "RTRIM":
        return f"{args[0]} with trailing spaces removed"

    if name == "CAST":
        return f"{args[0]} cast to {node.args.get('to').sql()}"

    return f"{name}({', '.join(args)})"


# ===============================
# SAFE FALLBACK
# ===============================

def translate_expression(node) -> str:
    if isinstance(node, exp.Expression):
        return node.sql()
    return str(node)

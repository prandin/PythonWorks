import sqlglot
from sqlglot import exp


def indent(level: int) -> str:
    return "\t" * level


def flatten(node, cls):
    """
    Flattens left-deep AND / OR trees into a list.
    """
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]


def translate_function(node: exp.Expression) -> str:
    """
    Translates SQL functions into English.
    """
    # UPPER(TRIM(x))
    if isinstance(node, exp.Upper) and isinstance(node.this, exp.Trim):
        attr = node.this.this.sql()
        return (
            f"the upper-case version of {attr} "
            f"after removing leading and trailing whitespace"
        )

    # Generic function fallback
    if isinstance(node, exp.Func):
        return f"the result of {node.sql()}"

    return node.sql()


def explain_expression(node, level: int, path: list[int]) -> str:
    """
    Recursively explains an AST expression with correct numbering.
    """
    label = ".".join(map(str, path))
    prefix = f"{indent(level)}Condition {label}: "

    # AND
    if isinstance(node, exp.And):
        parts = flatten(node, exp.And)
        text = prefix + "All of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(
                part,
                level + 1,
                path + [i]
            ) + "\n"
        return text.rstrip()

    # OR
    if isinstance(node, exp.Or):
        parts = flatten(node, exp.Or)
        text = prefix + "At least one of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(
                part,
                level + 1,
                path + [i]
            ) + "\n"
        return text.rstrip()

    # IN predicate
    if isinstance(node, exp.In):
        lhs = translate_function(node.this)
        values = ", ".join(v.sql() for v in node.expressions)
        return prefix + f"{lhs} is one of ({values})"

    # IS NULL
    if isinstance(node, exp.Is):
        lhs = translate_function(node.this)
        return prefix + f"{lhs} is null"

    # IS NOT NULL
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        lhs = translate_function(node.this.this)
        return prefix + f"{lhs} is not null"

    # Binary comparisons (=, <, >, etc.)
    if isinstance(node, exp.Binary):
        left = translate_function(node.left)
        right = node.right.sql()
        return prefix + f"{left} {node.op} {right}"

    # Fallback
    return prefix + node.sql()


def explain_case(case_expr: exp.Case) -> str:
    """
    Explains a CASE expression using correct numbering and English phrasing.
    """
    output = []
    output.append("CASE evaluation logic:\n")

    for i, when in enumerate(case_expr.args["ifs"], 1):
        output.append(f"Condition {i}: IF")
        output.append(
            explain_expression(
                when.this,
                level=1,
                path=[i, 1]
            )
        )
        output.append(f"\tTHEN return '{when.args['true'].sql()}'\n")

    default = case_expr.args.get("default")
    if default:
        output.append(f"ELSE return '{default.sql()}'")

    return "\n".join(output)


def translate_sql_case(sql_text: str) -> str:
    """
    Entry point.
    """
    parsed = sqlglot.parse_one(sql_text)
    case_nodes = list(parsed.find_all(exp.Case))

    if not case_nodes:
        raise ValueError("No CASE expression found")

    return explain_case(case_nodes[0])

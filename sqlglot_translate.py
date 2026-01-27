import sqlglot
from sqlglot import exp


def indent(level: int) -> str:
    return "\t" * level


def explain_expression(node, level=0, counter=[1]) -> str:
    """
    Recursively translates a SQL AST node into numbered English text.
    """
    num = counter[0]
    prefix = f"{indent(level)}{num}. "

    # Logical AND
    if isinstance(node, exp.And):
        text = prefix + "All of the following must be true:\n"
        counter[0] = 1
        text += explain_expression(node.left, level + 1, counter) + "\n"
        counter[0] += 1
        text += explain_expression(node.right, level + 1, counter)
        return text

    # Logical OR
    if isinstance(node, exp.Or):
        text = prefix + "At least one of the following must be true:\n"
        counter[0] = 1
        text += explain_expression(node.left, level + 1, counter) + "\n"
        counter[0] += 1
        text += explain_expression(node.right, level + 1, counter)
        return text

    # IN predicate
    if isinstance(node, exp.In):
        col = node.this.sql()
        values = ", ".join(v.sql() for v in node.expressions)
        return prefix + f"{col} is one of ({values})"

    # IS NULL / IS NOT NULL
    if isinstance(node, exp.Is):
        return prefix + f"{node.this.sql()} is null"

    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        return prefix + f"{node.this.this.sql()} is not null"

    # Comparison operators (=, <, >, etc.)
    if isinstance(node, exp.Binary):
        return prefix + f"{node.left.sql()} {node.op} {node.right.sql()}"

    # Function calls
    if isinstance(node, exp.Func):
        return prefix + f"Result of function {node.sql()}"

    # Fallback
    return prefix + node.sql()


def explain_case(case_expr: exp.Case) -> str:
    """
    Explains a CASE expression using AST traversal.
    """
    output = []
    output.append("CASE evaluation logic:\n")

    for i, when in enumerate(case_expr.args["ifs"], 1):
        condition = when.this
        result = when.args["true"]

        output.append(f"{i}. IF:")
        output.append(explain_expression(condition, level=1))
        output.append(f"\tTHEN return '{result.sql()}'\n")

    default = case_expr.args.get("default")
    if default:
        output.append(f"ELSE return '{default.sql()}'")

    return "\n".join(output)


def translate_sql_case(sql_text: str) -> str:
    """
    Entry point: parses SQL and explains CASE expression.
    """
    parsed = sqlglot.parse_one(sql_text)

    case_nodes = list(parsed.find_all(exp.Case))
    if not case_nodes:
        raise ValueError("No CASE expression found")

    return explain_case(case_nodes[0])

import sqlglot
from sqlglot import exp

def indent(level: int) -> str:
    return "\t" * level

def flatten(node, cls):
    """Flatten left-deep AND/OR trees into a list of child expressions."""
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]

def translate_function(node: exp.Expression) -> str:
    """Translate common composed functions to human English."""
    # Handle UPPER(TRIM(x)) pattern
    if isinstance(node, exp.Upper) and isinstance(node.this, exp.Trim):
        attr = node.this.this.sql()
        return (
            f"the upper-case version of {attr} "
            f"after removing leading and trailing whitespace"
        )
    # If node is a Trim alone: describe it
    if isinstance(node, exp.Trim):
        return f"the value of {node.this.sql()} after trimming whitespace"
    # Generic function fallback
    if isinstance(node, exp.Func):
        return f"the result of {node.sql()}"
    # If it's a column/identifier expression, return its SQL
    return node.sql()

def detect_null_check(node):
    """
    Detect patterns:
      - X IS NULL  -> returns ('is_null', lhs_sql)
      - NOT (X IS NULL) -> returns ('is_not_null', lhs_sql)
    Returns (kind, lhs_sql) where kind is 'is_null'/'is_not_null' or (None, None).
    """
    # Case: NOT (X IS NULL)
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        inner = node.this
        lhs_sql = inner.this.sql()
        # try common attributes for right/null node
        right = getattr(inner, "expression", None) or getattr(inner, "right", None) or getattr(inner, "args", {}).get("expression", None)
        if isinstance(right, exp.Null) or (right is None and 'NULL' in inner.sql().upper()):
            return "is_not_null", lhs_sql

    # Case: X IS NULL
    if isinstance(node, exp.Is):
        lhs_sql = node.this.sql()
        right = getattr(node, "expression", None) or getattr(node, "right", None) or getattr(node, "args", {}).get("expression", None)
        if isinstance(right, exp.Null) or (right is None and 'NULL' in node.sql().upper()):
            return "is_null", lhs_sql

    return None, None

def explain_expression(node, level: int, path: list[int]) -> str:
    """Recursively explain node with stable numbering (path is the hierarchical index list)."""
    label = ".".join(map(str, path))
    prefix = f"{indent(level)}Condition {label}: "

    # Null checks (covers NOT ... IS NULL and X IS NULL)
    kind, lhs = detect_null_check(node)
    if kind == "is_not_null":
        return prefix + f"{lhs} is not null"
    if kind == "is_null":
        return prefix + f"{lhs} is null"

    # AND
    if isinstance(node, exp.And):
        parts = flatten(node, exp.And)
        text = prefix + "All of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # OR
    if isinstance(node, exp.Or):
        parts = flatten(node, exp.Or)
        text = prefix + "At least one of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # IN predicate
    if isinstance(node, exp.In):
        lhs = translate_function(node.this)
        values = ", ".join(v.sql() for v in node.expressions)
        return prefix + f"{lhs} is one of ({values})"

    # Binary comparisons (=, <, >, etc.)
    if isinstance(node, exp.Binary):
        left = translate_function(node.left)
        # right may be an expression or literal
        right = node.right.sql()
        return prefix + f"{left} {node.op} {right}"

    # Function call or identifier fallback
    if isinstance(node, exp.Func) or isinstance(node, exp.Column) or isinstance(node, exp.Identifier):
        return prefix + translate_function(node)

    # Generic fallback to SQL text
    return prefix + node.sql()

def explain_case(case_expr: exp.Case) -> str:
    output = []
    output.append("CASE evaluation logic:\n")

    for i, when in enumerate(case_expr.args["ifs"], 1):
        # when.this is the condition expression
        # when.args['true'] is the result expression
        output.append(f"Condition {i}: IF")
        output.append(explain_expression(when.this, level=1, path=[i, 1]))
        output.append(f"\tTHEN return '{when.args['true'].sql()}'\n")

    default = case_expr.args.get("default")
    if default:
        output.append(f"ELSE return '{default.sql()}'")

    return "\n".join(output)

def translate_sql_case(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)
    case_nodes = list(parsed.find_all(exp.Case))
    if not case_nodes:
        raise ValueError("No CASE expression found")
    return explain_case(case_nodes[0])

import re
import sqlglot
from sqlglot import exp


# -------------------------
# Utility helpers
# -------------------------

def indent(level: int) -> str:
    return "\t" * level


def flatten(node, cls):
    """
    Flatten left-deep AND / OR trees into a list.
    """
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]


# -------------------------
# Function translation
# -------------------------

def translate_function(node: exp.Expression) -> str:
    """
    Translate SQL functions into English.
    """
    # UPPER(TRIM(x))
    if isinstance(node, exp.Upper) and isinstance(node.this, exp.Trim):
        attr = node.this.this.sql()
        return (
            f"the upper-case version of {attr} "
            f"after removing leading and trailing whitespace"
        )

    # TRIM(x)
    if isinstance(node, exp.Trim):
        return f"the value of {node.this.sql()} after trimming whitespace"

    # Generic function fallback
    if isinstance(node, exp.Func):
        return f"the result of {node.sql()}"

    return node.sql()


# -------------------------
# NULL detection
# -------------------------

def detect_null_check(node):
    """
    Detect:
      - X IS NULL
      - NOT (X IS NULL)
    """
    # NOT (X IS NULL)
    if isinstance(node, exp.Not) and isinstance(node.this, exp.Is):
        inner = node.this
        lhs = inner.this.sql()
        return "is_not_null", lhs

    # X IS NULL
    if isinstance(node, exp.Is):
        lhs = node.this.sql()
        return "is_null", lhs

    return None, None


# -------------------------
# Recursive explanation
# -------------------------

def explain_expression(node, level: int, path: list[int]) -> str:
    """
    Recursively explain an AST expression with hierarchical numbering.
    """
    label = ".".join(map(str, path))
    prefix = f"{indent(level)}Condition {label}: "

    # NULL checks
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

    # Binary comparison (=, <, >, etc.)
    if isinstance(node, exp.Binary):
        left = translate_function(node.left)
        right = node.right.sql()
        return prefix + f"{left} {node.op} {right}"

    # Fallback
    return prefix + node.sql()


# -------------------------
# CASE + alias extraction
# -------------------------

def find_case_and_alias(parsed):
    """
    Extract the CASE expression and its alias (AS <column_name>).
    """
    case_nodes = list(parsed.find_all(exp.Case))
    if not case_nodes:
        return None, None

    case = case_nodes[0]

    # Preferred: AST-based alias detection
    for alias in parsed.find_all(exp.Alias):
        if alias.this is case:
            return case, alias.alias

    # Fallback: regex at end
    m = re.search(r"\bAS\s+([A-Za-z0-9_]+)\s*$", parsed.sql(), re.IGNORECASE)
    if m:
        return case, m.group(1)

    return case, None


# -------------------------
# CASE explanation
# -------------------------

def explain_case_with_header(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)
    case_node, alias_name = find_case_and_alias(parsed)

    if case_node is None:
        raise ValueError("No CASE expression found")

    header = (
        f"Column '{alias_name}' is computed as:"
        if alias_name
        else "Computed column is derived as:"
    )

    output = [header, ""]

    for i, when in enumerate(case_node.args.get("ifs", []), 1):
        output.append(f"Condition {i}: IF")
        output.append(
            explain_expression(
                when.this,
                level=1,
                path=[i, 1]
            )
        )
        output.append(f"\tTHEN return {when.args['true'].sql()}\n")

    default = case_node.args.get("default")
    if default:
        output.append(f"ELSE return {default.sql()}")

    return "\n".join(output)

def translate_sql(sql_text: str) -> str:
    """
    Public API.
    Call this function.
    """
    return explain_case_with_header(sql_text)

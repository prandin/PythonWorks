# Requires: pip install sqlglot
import re
import sqlglot
from sqlglot import exp

# -------------------------
# Small utilities
# -------------------------

def indent(level: int) -> str:
    return "\t" * level

def flatten(node, cls):
    """
    Flatten left-deep AND / OR trees into a list of child expressions.
    """
    if isinstance(node, cls):
        return flatten(node.left, cls) + flatten(node.right, cls)
    return [node]

# -------------------------
# Function translation
# -------------------------

def translate_function(node: exp.Expression) -> str:
    """
    Translate common function compositions to human English.
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

    # Generic function fallback (NVL, COALESCE, etc.)
    if isinstance(node, exp.Func):
        return f"the result of {node.sql()}"

    # Column/identifier/literal fallback
    return node.sql()

# -------------------------
# NULL detection
# -------------------------

def detect_null_check(node):
    """
    Detect forms:
      - X IS NULL
      - NOT (X IS NULL)  (or written as NOT X IS NULL)
    Returns ("is_null" | "is_not_null", lhs_sql) or (None, None)
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
# Binary operator -> word mapping
# -------------------------

OP_MAP = {
    "=": "equals",
    "==": "equals",
    "<>": "is not equal to",
    "!=": "is not equal to",
    "<": "is less than",
    "<=": "is less than or equal to",
    ">": "is greater than",
    ">=": "is greater than or equal to",
    "LIKE": "matches",
    "NOT LIKE": "does not match",
    "IN": "is one of",  # special-cased elsewhere
}

def op_to_text(op_token: str) -> str:
    if not op_token:
        return op_token
    key = op_token.upper() if isinstance(op_token, str) else str(op_token)
    # keep <> and != as is (they are not alphabetical)
    if key in OP_MAP:
        return OP_MAP[key]
    # try raw
    return op_token

# -------------------------
# Expression explainer (recursive)
# -------------------------

def explain_expression(node, level: int, path: list[int]) -> str:
    """
    Recursively explain an AST node with stable hierarchical numbering (path is index list).
    """
    label = ".".join(map(str, path))
    prefix = f"{indent(level)}Condition {label}: "

    # Null checks (X IS NULL / NOT X IS NULL)
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

    # IN predicate (special)
    if isinstance(node, exp.In):
        lhs = translate_function(node.this)
        # Join the right-hand expressions preserving SQL literal formatting
        values = ", ".join(v.sql() for v in node.expressions)
        return prefix + f"{lhs} is one of ({values})"

    # Binary comparisons (=, <>, !=, <, >, etc.)
    if isinstance(node, exp.Binary):
        # left can be function/column; right may be literal or expression
        left_text = translate_function(node.left)
        right_text = node.right.sql()
        # node.op should be operator string (sqlglot provides it). Fallback to raw SQL.
        op_token = getattr(node, "op", None)
        op_word = op_to_text(op_token) if op_token else None
        if op_word:
            return prefix + f"{left_text} {op_word} {right_text}"
        # fallback
        return prefix + node.sql()

    # Function / column / literal fallback
    if isinstance(node, (exp.Func, exp.Column, exp.Identifier, exp.Literal)):
        return prefix + translate_function(node)

    # Final fallback to raw SQL (safe)
    return prefix + node.sql()

# -------------------------
# CASE extraction + alias detection
# -------------------------

def find_case_and_alias(parsed):
    """
    Locate first CASE expression and the alias name after AS (if present).
    Returns (case_node, alias_name or None).
    """
    case_nodes = list(parsed.find_all(exp.Case))
    if not case_nodes:
        return None, None

    case = case_nodes[0]

    # AST-aware alias detection (Alias node whose .this is the CASE)
    for alias in parsed.find_all(exp.Alias):
        if getattr(alias, "this", None) is case:
            # alias.alias gives the alias name string or Identifier node in sqlglot older/newer versions:
            # try both
            try:
                return case, alias.alias
            except Exception:
                # alias.args.get("alias") might be an Identifier expression
                maybe = alias.args.get("alias")
                if maybe is not None:
                    return case, maybe.sql()
                return case, None

    # Fallback: regex at end of SQL text (loose)
    m = re.search(r"\bAS\s+([A-Za-z0-9_]+)\s*$", parsed.sql(), re.IGNORECASE)
    if m:
        return case, m.group(1)

    return case, None

# -------------------------
# Top-level CASE explainer
# -------------------------

def explain_case_with_header(sql_text: str) -> str:
    parsed = sqlglot.parse_one(sql_text)
    case_node, alias_name = find_case_and_alias(parsed)

    if case_node is None:
        raise ValueError("No CASE expression found in input SQL.")

    header = f"Column '{alias_name}' is computed as:" if alias_name else "Computed column is derived as:"
    output_lines = [header, ""]

    # sqlglot stores WHEN ... THEN blocks as case_node.args['ifs']
    for i, when in enumerate(case_node.args.get("ifs", []), start=1):
        condition_expr = when.this
        result_expr = when.args.get("true")
        output_lines.append(f"Condition {i}: IF")
        output_lines.append(explain_expression(condition_expr, level=1, path=[i, 1]))
        # keep THEN output as raw SQL for clarity (preserves quotes)
        output_lines.append(f"\tTHEN return {result_expr.sql()}\n")

    default = case_node.args.get("default")
    if default is not None:
        output_lines.append(f"ELSE return {default.sql()}")

    return "\n".join(output_lines)

# -------------------------
# Public wrapper (stable API)
# -------------------------

def translate_sql(sql_text: str) -> str:
    """
    Public entry point: returns English-like, numbered translation of a CASE expression.
    """
    return explain_case_with_header(sql_text)

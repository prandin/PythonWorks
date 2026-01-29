# robust_translator.py
# Paste this file as your translator (replace previous). Requires: pip install sqlglot

from typing import List
import sqlglot
from sqlglot import expressions as exp

# Helper ---------------------------------------------------------------------

def nodename(node) -> str:
    """Return the class name for a sqlglot node (safe)."""
    return node.__class__.__name__ if node is not None else ""

def get_attr(node, name, default=None):
    """Safe getattr for sqlglot node attributes."""
    return getattr(node, name, default)

def list_args(node):
    """Return list-like arguments for functions (coalesce, greatest) robustly."""
    # try common patterns
    if hasattr(node, "expressions") and node.expressions is not None:
        return list(node.expressions)
    if hasattr(node, "expressions_list"):  # fallback name (rare)
        return list(node.expressions_list)
    # some node types hold args in args dict
    args = get_attr(node, "args", {})
    if isinstance(args, dict):
        for k in ("expressions", "this", "args"):
            v = args.get(k)
            if isinstance(v, list):
                return v
    # single-arg fallback
    if get_attr(node, "this", None) is not None:
        return [node.this]
    return []

def flatten_same(node, typ_name):
    """Flatten nested AND/OR trees by nodename."""
    name = nodename(node)
    if name != typ_name:
        return [node]
    left = get_attr(node, "left", None) or get_attr(node, "this", None)
    right = get_attr(node, "right", None) or get_attr(node, "expression", None)
    parts = []
    if left is not None:
        parts.extend(flatten_same(left, typ_name))
    if right is not None:
        parts.extend(flatten_same(right, typ_name))
    return parts if parts else [node]

# Expression translation -----------------------------------------------------

def translate_expression(node) -> str:
    """Return an English-like translation for an expression node (recursive)."""
    if node is None:
        return ""

    name = nodename(node)

    # Column / identifier / literal
    if name in ("Column", "Identifier"):
        return node.sql()
    if name in ("Literal", "Numeric", "String"):
        return node.sql()

    # Parenthesis
    if name == "Paren":
        return translate_expression(get_attr(node, "this"))

    # Arithmetic
    if name == "Add":
        return f"{translate_expression(node.left)} plus {translate_expression(node.right)}"
    if name == "Sub":
        return f"{translate_expression(node.left)} minus {translate_expression(node.right)}"
    if name == "Mul":
        return f"{translate_expression(node.left)} multiplied by {translate_expression(node.right)}"
    if name == "Div":
        return f"{translate_expression(node.left)} divided by {translate_expression(node.right)}"

    # Functions (robust)
    if name == "Coalesce":
        args = list_args(node)
        return "the first non-null value among (" + ", ".join(translate_expression(a) for a in args) + ")"

    if name == "Sum":
        # SUM(expr) -> "the sum of <expr>"
        return f"the sum of {translate_expression(get_attr(node, 'this'))}"

    if name == "Greatest":
        args = list_args(node)
        return "the greatest value among (" + ", ".join(translate_expression(a) for a in args) + ")"

    if name == "Round":
        dec = get_attr(node, "decimals", None) or (node.args.get("decimals") if hasattr(node, "args") else None)
        base = translate_expression(get_attr(node, "this"))
        if dec:
            return f"{base} rounded to {dec.sql() if hasattr(dec, 'sql') else str(dec)} decimal places"
        return f"{base} rounded"

    # Trim family: TRIM, LTRIM, RTRIM
    if name == "Trim":
        where = node.args.get("where") if hasattr(node, "args") else None
        base = translate_expression(get_attr(node, "this"))
        if where == "LEADING":
            return f"{base} with leading whitespace removed"
        if where == "TRAILING":
            return f"{base} with trailing whitespace removed"
        return f"{base} with leading and trailing whitespace removed"
    # Some versions expose LTrim/RTrim as separate classes
    if name in ("LTrim", "RTrim"):
        base = translate_expression(get_attr(node, "this"))
        if name == "LTrim":
            return f"{base} with leading whitespace removed"
        return f"{base} with trailing whitespace removed"

    # Upper/Lower
    if name == "Upper":
        return f"the upper case of {translate_expression(get_attr(node, 'this'))}"
    if name == "Lower":
        return f"the lower case of {translate_expression(get_attr(node, 'this'))}"

    # Window functions: Window nodes often wrap a function
    if name == "Window":
        base = translate_expression(get_attr(node, "this"))
        parts = []
        partition = node.args.get("partition_by") if hasattr(node, "args") else None
        if partition:
            # partition_by may be a list or a single expression
            if isinstance(partition, list):
                cols = ", ".join(p.sql() if hasattr(p, "sql") else translate_expression(p) for p in partition)
            else:
                cols = partition.sql() if hasattr(partition, "sql") else translate_expression(partition)
            parts.append(f"partitioned by {cols}")
        order = node.args.get("order") if hasattr(node, "args") else None
        if order:
            parts.append("ordered by " + (order.sql() if hasattr(order, "sql") else str(order)))
        suffix = f" ({', '.join(parts)})" if parts else ""
        return base + suffix

    # CASE nested - short description
    if name == "Case":
        return "a conditional value (CASE expression)"

    # Fallback: try to produce something useful by inspecting node attributes
    # If node has left/right or this/expression, recursively translate them
    left = get_attr(node, "left", None)
    right = get_attr(node, "right", None)
    this = get_attr(node, "this", None)
    expr = get_attr(node, "expression", None)

    if left is not None and right is not None:
        return f"{translate_expression(left)} ? {translate_expression(right)}"  # placeholder if unknown operator

    if this is not None and expr is not None:
        return f"{translate_expression(this)} ({translate_expression(expr)})"

    # Last resort: return SQL text (rare)
    try:
        return node.sql()
    except Exception:
        return nodename(node)


# Predicate explanation ------------------------------------------------------

def explain_expression(node, level: int, path: List[int]) -> str:
    """
    Explain predicates with hierarchical numbering.
    Uses robust nodename checks and safe attribute access to support multiple sqlglot versions.
    """
    if node is None:
        return ""

    prefix = "    " * level
    label = f"Condition {'.'.join(map(str, path))}: "

    name = nodename(node)

    # Handle NOT wrapper: NOT <expr> -> explain as negation
    if name == "Not":
        inner = get_attr(node, "this", None) or get_attr(node, "expression", None)
        # If inner is a LIKE or IN or comparison, explain with negation
        inner_name = nodename(inner) if inner is not None else ""
        if inner_name == "Like":
            return prefix + label + f"{translate_expression(inner.this)} does not contain {translate_expression(inner.expression)} as a substring"
        if inner_name == "In":
            vals = ", ".join(translate_expression(v) for v in list_args(inner))
            return prefix + label + f"{translate_expression(inner.this)} is not one of ({vals})"
        if inner_name in ("EQ", "NEQ", "LT", "LTE", "GT", "GTE"):
            # invert meaning simply by adding "not"
            # rely on underlying comparison translator
            cmp_text = explain_expression(inner, level, path)  # this will produce "Condition x: lhs ... rhs"
            # replace "is" / "equals" phrases with negative; simplest: prepend "NOT: "
            return prefix + label + "NOT (" + cmp_text.strip() + ")"
        # generic NOT fallback
        return prefix + label + "NOT " + translate_expression(inner)

    # AND
    if name == "And":
        parts = flatten_same(node, "And")
        text = prefix + label + "All of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # OR
    if name == "Or":
        parts = flatten_same(node, "Or")
        text = prefix + label + "At least one of the following must be true:\n"
        for i, part in enumerate(parts, 1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # IN
    if name == "In":
        lhs = translate_expression(get_attr(node, "this", None))
        vals = list_args(node)
        vals_text = ", ".join(translate_expression(v) for v in vals)
        return prefix + label + f"{lhs} is one of ({vals_text})"

    # LIKE
    if name == "Like":
        lhs = translate_expression(get_attr(node, "this", None))
        rhs = translate_expression(get_attr(node, "expression", None))
        # detect %...% -> contains substring
        raw_pattern = None
        try:
            raw_pattern = node.expression.sql().strip("'")
        except Exception:
            raw_pattern = None
        if raw_pattern and raw_pattern.startswith("%") and raw_pattern.endswith("%"):
            return prefix + label + f"{lhs} contains '{raw_pattern.strip('%')}' as a substring"
        return prefix + label + f"{lhs} matches the pattern {rhs}"

    # Null check: IS / IS NOT
    if name == "Is":
        return prefix + label + f"{translate_expression(get_attr(node, 'this'))} is null"
    if name == "IsNot":
        return prefix + label + f"{translate_expression(get_attr(node, 'this'))} is not null"

    # Comparisons (EQ, NEQ, LT, LTE, GT, GTE)
    if name in ("EQ", "NEQ", "LT", "LTE", "GT", "GTE"):
        left = get_attr(node, "left", None) or get_attr(node, "this", None)
        right = get_attr(node, "right", None) or get_attr(node, "expression", None) or get_attr(node, "this", None)
        lhs = translate_expression(left)
        rhs = translate_expression(right)
        op_map = {
            "EQ": "equals",
            "NEQ": "is not equal to",
            "LT": "is less than",
            "LTE": "is less than or equal to",
            "GT": "is greater than",
            "GTE": "is greater than or equal to",
        }
        return prefix + label + f"{lhs} {op_map[name]} {rhs}"

    # Generic fallback: translate recursively (ensures functions inside arithmetic are expanded)
    return prefix + label + translate_expression(node)


# Top-level API --------------------------------------------------------------

def translate_case_sql(sql_text: str) -> str:
    """Public helper - alias for translate_sql for clarity."""
    return translate_sql(sql_text)


def translate_sql(sql_text: str) -> str:
    """
    Parse a CASE ... END AS <alias> expression (or just CASE expression),
    extract the alias where available, and produce the numbered English translation.
    """
    parsed = sqlglot.parse_one(sql_text)

    # handle alias wrapping
    alias = None
    case_node = None
    if nodename(parsed) == "Alias":
        alias = parsed.alias if hasattr(parsed, "alias") else None
        case_node = parsed.this
    else:
        # find first CASE (works for queries consisting only of the CASE)
        case_node = parsed.find(exp.Case)

    header = f"Column '{alias}' is computed as:\n\n" if alias else "Computed column is derived as:\n\n"

    output_lines = [header.rstrip(), ""]

    if case_node is None:
        return header + "No CASE expression found."

    # iterate through WHEN ... THEN clauses
    whens = case_node.args.get("ifs", []) if hasattr(case_node, "args") else []
    for i, when in enumerate(whens, start=1):
        cond = when.this if hasattr(when, "this") else when.args.get("this")
        result = when.args.get("true") if hasattr(when, "args") else getattr(when, "true", None)
        output_lines.append(f"Condition {i}: IF")
        output_lines.append(explain_expression(cond, 1, [i]))
        output_lines.append(f"THEN return {translate_expression(result)}\n")

    # default / ELSE
    default = case_node.args.get("default") if hasattr(case_node, "args") else None
    if default:
        output_lines.append(f"ELSE return {translate_expression(default)}")

    return "\n".join(output_lines)

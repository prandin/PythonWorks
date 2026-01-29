# robust_translator_v2.py
# Drop-in replacement translator that avoids sqlglot-version-specific attributes.
# Requires: pip install sqlglot

from typing import List, Optional
import sqlglot
from sqlglot import expressions as exp


# -------------------------
# Utility helpers
# -------------------------
def nodename(node) -> str:
    return node.__class__.__name__ if node is not None else ""


def safe_get(node, *names):
    """Return first attribute value found among names or None."""
    for n in names:
        if hasattr(node, n):
            val = getattr(node, n)
            if val is not None:
                return val
    # also check args dict if present
    if hasattr(node, "args") and isinstance(node.args, dict):
        for n in names:
            if n in node.args and node.args[n] is not None:
                return node.args[n]
    return None


def list_args(node):
    """Return a list of expressions for function-like nodes robustly."""
    # prefer common attributes
    if hasattr(node, "expressions") and node.expressions:
        return list(node.expressions)
    # check args dict for 'expressions' or 'this' arrays
    if hasattr(node, "args") and isinstance(node.args, dict):
        for key in ("expressions", "args", "expressions_list"):
            v = node.args.get(key)
            if isinstance(v, list):
                return v
    # sometimes functions keep arguments as node.this and node.expression, etc.
    this = safe_get(node, "this")
    expr = safe_get(node, "expression")
    if isinstance(this, list):
        return this
    if this is not None and expr is not None:
        return [this, expr]
    if this is not None:
        return [this]
    return []


def flatten_same(node, typename):
    """Flatten nested AND/OR nodes by class name (robust for versions)."""
    if nodename(node) != typename:
        return [node]
    left = safe_get(node, "left", "this")
    right = safe_get(node, "right", "expression")
    parts = []
    if left is not None:
        parts.extend(flatten_same(left, typename))
    if right is not None:
        parts.extend(flatten_same(right, typename))
    return parts or [node]


# -------------------------
# Expression -> English
# -------------------------
def translate_expression(node) -> str:
    if node is None:
        return ""

    name = nodename(node)

    # identifiers / literals
    if name in ("Column", "Identifier"):
        return node.sql()
    if name in ("Literal", "Numeric", "String"):
        return node.sql()

    # parentheses
    if name == "Paren":
        inner = safe_get(node, "this")
        return translate_expression(inner)

    # arithmetic
    if name == "Add":
        return f"{translate_expression(node.left)} plus {translate_expression(node.right)}"
    if name == "Sub":
        return f"{translate_expression(node.left)} minus {translate_expression(node.right)}"
    if name == "Mul":
        return f"{translate_expression(node.left)} multiplied by {translate_expression(node.right)}"
    if name == "Div":
        return f"{translate_expression(node.left)} divided by {translate_expression(node.right)}"

    # functions (robust)
    if name == "Coalesce":
        args = list_args(node)
        return "the first non-null value among (" + ", ".join(translate_expression(a) for a in args) + ")"

    if name == "Sum":
        # SUM(expr) -> "the sum of <expr>"
        inner = safe_get(node, "this")
        return f"the sum of {translate_expression(inner)}"

    if name == "Greatest":
        args = list_args(node)
        return "the greatest value among (" + ", ".join(translate_expression(a) for a in args) + ")"

    if name == "Round":
        dec = None
        if hasattr(node, "args") and isinstance(node.args, dict):
            dec = node.args.get("decimals")
        if dec:
            return f"{translate_expression(safe_get(node, 'this'))} rounded to {dec.sql() if hasattr(dec, 'sql') else str(dec)} decimals"
        return f"{translate_expression(safe_get(node, 'this'))} rounded"

    # trim family (Trim, LTrim, RTrim)
    if name == "Trim":
        # attempt to detect leading/trailing via args
        where = None
        if hasattr(node, "args") and isinstance(node.args, dict):
            where = node.args.get("where")
        base = translate_expression(safe_get(node, "this"))
        if where and str(where).upper().startswith("LEADING"):
            return f"{base} with leading whitespace removed"
        if where and str(where).upper().startswith("TRAILING"):
            return f"{base} with trailing whitespace removed"
        return f"{base} with leading and trailing whitespace removed"
    if name in ("LTrim", "RTrim"):
        base = translate_expression(safe_get(node, "this"))
        return f"{base} with {'leading' if name=='LTrim' else 'trailing'} whitespace removed"

    # case expression short form
    if name == "Case":
        return "a conditional value (CASE expression)"

    # upper/lower
    if name == "Upper":
        return f"the upper case of {translate_expression(safe_get(node, 'this'))}"
    if name == "Lower":
        return f"the lower case of {translate_expression(safe_get(node, 'this'))}"

    # window functions (Window node wraps function often)
    if name == "Window":
        base = translate_expression(safe_get(node, "this"))
        parts = []
        # partition_by
        partition = None
        if hasattr(node, "args") and isinstance(node.args, dict):
            partition = node.args.get("partition_by")
        if partition:
            if isinstance(partition, list):
                cols = ", ".join(p.sql() if hasattr(p, "sql") else translate_expression(p) for p in partition)
            else:
                cols = partition.sql() if hasattr(partition, "sql") else translate_expression(partition)
            parts.append(f"partitioned by {cols}")
        order = None
        if hasattr(node, "args") and isinstance(node.args, dict):
            order = node.args.get("order")
        if order:
            parts.append("ordered")
        suffix = f" ({', '.join(parts)})" if parts else ""
        return base + suffix

    # last resort: try to expand common left/right or this/expression attributes
    left = safe_get(node, "left", "this")
    right = safe_get(node, "right", "expression")
    if left is not None and right is not None:
        return f"{translate_expression(left)} ? {translate_expression(right)}"

    this = safe_get(node, "this")
    expr = safe_get(node, "expression")
    if this is not None and expr is not None:
        return f"{translate_expression(this)} ({translate_expression(expr)})"

    # fallback to node.sql() (only when necessary)
    try:
        return node.sql()
    except Exception:
        return nodename(node)


# -------------------------
# Predicate explanation with numbering
# -------------------------
def explain_expression(node, level: int, path: List[int]) -> str:
    """
    Explain a predicate node with numbering/indentation.
    This function uses class-name checks and safe attribute access to avoid AttributeError
    across different sqlglot releases.
    """
    prefix = "    " * level
    label = f"Condition {'.'.join(map(str, path))}: "

    if node is None:
        return prefix + label + ""

    name = nodename(node)

    # NOT wrapper: robustly handle Not + inner
    if name == "Not":
        inner = safe_get(node, "this") or safe_get(node, "expression")
        inner_name = nodename(inner) if inner is not None else ""
        # If inner is a Like, In or comparison, produce negated phrasing
        if inner_name == "Like":
            lhs = translate_expression(safe_get(inner, "this"))
            rhs = translate_expression(safe_get(inner, "expression"))
            return prefix + label + f"{lhs} does not contain {rhs} as a substring"
        if inner_name == "In":
            lhs = translate_expression(safe_get(inner, "this"))
            vals = list_args(inner)
            vals_text = ", ".join(translate_expression(v) for v in vals)
            return prefix + label + f"{lhs} is not one of ({vals_text})"
        # generic fallback for NOT
        return prefix + label + "NOT " + translate_expression(inner)

    # AND / OR - flatten nested trees
    if name == "And":
        parts = flatten_same(node, "And")
        text = prefix + label + "All of the following must be true:\n"
        for i, part in enumerate(parts, start=1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    if name == "Or":
        parts = flatten_same(node, "Or")
        text = prefix + label + "At least one of the following must be true:\n"
        for i, part in enumerate(parts, start=1):
            text += explain_expression(part, level + 1, path + [i]) + "\n"
        return text.rstrip()

    # IN
    if name == "In":
        lhs = translate_expression(safe_get(node, "this"))
        vals = list_args(node)
        vals_text = ", ".join(translate_expression(v) for v in vals)
        return prefix + label + f"{lhs} is one of ({vals_text})"

    # LIKE (and pattern translation)
    if name == "Like":
        lhs = translate_expression(safe_get(node, "this"))
        rhs_node = safe_get(node, "expression")
        rhs = translate_expression(rhs_node)
        # try to extract literal pattern string for nicer phrasing
        pattern = None
        try:
            if hasattr(rhs_node, "sql"):
                raw = rhs_node.sql()
                # strip quotes if present
                if raw.startswith("'") and raw.endswith("'"):
                    pattern = raw.strip("'")
        except Exception:
            pattern = None
        if pattern and pattern.startswith("%") and pattern.endswith("%"):
            return prefix + label + f"{lhs} contains '{pattern.strip('%')}' as a substring"
        return prefix + label + f"{lhs} matches the pattern {rhs}"

    # Null checks
    if name in ("Is",):
        return prefix + label + f"{translate_expression(safe_get(node, 'this'))} is null"
    if name in ("IsNot",):
        return prefix + label + f"{translate_expression(safe_get(node, 'this'))} is not null"

    # comparisons - robust by class-name
    cmp_map = {
        "EQ": "equals",
        "Equal": "equals",
        "Equals": "equals",
        "NEQ": "is not equal to",
        "NotEq": "is not equal to",
        "NotEqual": "is not equal to",
        "LT": "is less than",
        "LTE": "is less than or equal to",
        "LE": "is less than or equal to",
        "GT": "is greater than",
        "GTE": "is greater than or equal to",
    }
    if name in cmp_map:
        left = safe_get(node, "left", "this")
        right = safe_get(node, "right", "expression")
        lhs = translate_expression(left)
        rhs = translate_expression(right)
        return prefix + label + f"{lhs} {cmp_map[name]} {rhs}"

    # fallback for nodes that *look like* comparisons: if they have left & right attributes
    if hasattr(node, "left") and hasattr(node, "right"):
        lhs = translate_expression(getattr(node, "left"))
        rhs = translate_expression(getattr(node, "right"))
        # attempt to get operator text from node.sql() safely
        try:
            sql_repr = node.sql()
            # try to find operator substring between lhs and rhs in sql_repr
            # crude approach: remove lhs and rhs from ends and get middle
            mid = sql_repr
            if isinstance(lhs, str) and isinstance(rhs, str):
                mid = mid.replace(lhs, "", 1)
                mid = mid[::-1].replace(rhs[::-1], "", 1)[::-1]
            op_text = mid.strip()
            return prefix + label + f"{lhs} {op_text} {rhs}"
        except Exception:
            return prefix + label + f"{lhs} ? {rhs}"

    # final fallback: translate_expression
    return prefix + label + translate_expression(node)


# -------------------------
# Top-level API
# -------------------------
def translate_sql(sql_text: str) -> str:
    """
    Parse a CASE expression and produce a numbered English explanation.
    Handles both plain CASE ... END and CASE ... END AS alias forms.
    """
    parsed = sqlglot.parse_one(sql_text)

    # detect alias
    alias: Optional[str] = None
    case_node = None
    if nodename(parsed) == "Alias":
        # safe attribute access
        alias = getattr(parsed, "alias", None)
        case_node = getattr(parsed, "this", None)
    else:
        # find a Case node
        case_node = parsed.find(exp.Case)

    header = f"Column '{alias}' is computed as:\n\n" if alias else "Computed column is derived as:\n\n"

    if case_node is None:
        return header + "No CASE expression found."

    output = [header.rstrip(), ""]

    # iterate WHEN ... THEN
    whens = []
    if hasattr(case_node, "args") and isinstance(case_node.args, dict):
        whens = case_node.args.get("ifs", []) or []
    else:
        # attempt to find via attributes if args dict missing
        whens = safe_get(case_node, "ifs") or []

    for i, when in enumerate(whens, start=1):
        # extract condition and result robustly
        cond = safe_get(when, "this") or safe_get(when, "condition") or (when.args.get("this") if hasattr(when, "args") else None)
        result = safe_get(when, "true") or (when.args.get("true") if hasattr(when, "args") else None) or safe_get(when, "expression")
        output.append(f"Condition {i}: IF")
        output.append(explain_expression(cond, 1, [i]))
        output.append(f"THEN return {translate_expression(result)}\n")

    # default / else
    default = None
    if hasattr(case_node, "args") and isinstance(case_node.args, dict):
        default = case_node.args.get("default")
    if default:
        output.append(f"ELSE return {translate_expression(default)}")

    return "\n".join(output)


# alias
def translate_case_sql(sql_text: str) -> str:
    return translate_sql(sql_text)


# If this module is run directly you can test with a simple string (remove in production)
if __name__ == "__main__":
    sample = "CASE WHEN UPPER(TRIM(col)) IN ('A','B') THEN 'X' WHEN col IS NULL THEN 'Y' ELSE 'Z' END AS my_col"
    print(translate_sql(sample))

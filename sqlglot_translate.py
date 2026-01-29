from sqlglot import parse_one, exp

# ------------------------------------------------------------
# Entry point
# ------------------------------------------------------------
def translate_sql(sql_text: str) -> str:
    # Parse the SQL into an Abstract Syntax Tree (AST)
    tree = parse_one(sql_text)

    # Locate the main CASE statement
    case = extract_case(tree)

    if not case:
        return "No CASE statement found. \nOriginal: " + sql_text

    return explain_case_with_header(case)


# ------------------------------------------------------------
# AST Helper: Extract CASE node
# ------------------------------------------------------------
def extract_case(node):
    if node is None:
        return None
    if isinstance(node, exp.Case):
        return node
    if isinstance(node, exp.Alias):
        return extract_case(node.this)
    if isinstance(node, exp.Select):
        for e in node.expressions:
            found = extract_case(e)
            if found:
                return found
    if hasattr(node, "this"):
        return extract_case(node.this)
    return None


# ------------------------------------------------------------
# Main Logic: Explain CASE
# ------------------------------------------------------------
def explain_case_with_header(case: exp.Case) -> str:
    return "Column is computed as:\n\n" + explain_case(case, level=0)


def explain_case(case: exp.Case, level: int) -> str:
    output = []
    base_indent = indent(level)
    inner_indent = indent(level + 1)

    ifs = case.args.get("ifs") or []
    default = case.args.get("default")

    # Iterate through WHEN ... THEN blocks
    for idx, if_node in enumerate(ifs, start=1):
        cond_tree = if_node.this
        result_node = if_node.args.get("true")

        # Header for the block
        output.append(f"{base_indent}Step {idx}: Check if...")
        
        # 1. Flatten and explain conditions (Avoids deep nesting)
        conditions = flatten_conditions(cond_tree)
        if len(conditions) > 1:
            output.append(f"{inner_indent}ALL of the following are true:")
            for c_idx, c in enumerate(conditions, 1):
                output.append(f"{inner_indent}  {c_idx}. {translate_expression(c)}")
        else:
             output.append(f"{inner_indent}- {translate_expression(conditions[0])}")

        # 2. Explain the result (Handle nested CASE or Math)
        output.append(f"{base_indent}   -> THEN return:")
        
        if isinstance(result_node, exp.Case):
            # If the result is purely another CASE, recurse deeply
            output.append(explain_case(result_node, level + 2))
        else:
            # Otherwise translate the expression (handles math + nested cases in math)
            output.append(f"{indent(level + 2)}{translate_expression(result_node)}")

        output.append("") # Empty line for readability

    # Handle ELSE
    if default is not None:
        output.append(f"{base_indent}Step {len(ifs) + 1} (Default): ELSE return")
        if isinstance(default, exp.Case):
            output.append(explain_case(default, level + 1))
        else:
            output.append(f"{inner_indent}{translate_expression(default)}")
    else:
        output.append(f"{base_indent}Step {len(ifs) + 1}: ELSE return NULL")

    return "\n".join(output)


# ------------------------------------------------------------
# Helper: Flatten deeply nested ANDs
# ------------------------------------------------------------
def flatten_conditions(node):
    """
    Recursively collects all conditions joined by AND into a flat list.
    """
    if isinstance(node, exp.And):
        return flatten_conditions(node.left) + flatten_conditions(node.right)
    return [node]


# ------------------------------------------------------------
# Expression Translation (Math, Logic, Comparisons)
# ------------------------------------------------------------
def translate_expression(node) -> str:
    if node is None:
        return "NULL"

    # --- Nested CASE inside Math ---
    if isinstance(node, exp.Case):
        # We render nested cases inline but wrapped in brackets
        return f"(\n{explain_case(node, level=1)}\n)"

    # --- Arithmetic ---
    if isinstance(node, exp.Add):
        return f"{translate_expression(node.left)} + {translate_expression(node.right)}"
    if isinstance(node, exp.Sub):
        return f"{translate_expression(node.left)} - {translate_expression(node.right)}"
    if isinstance(node, exp.Mul):
        return f"{translate_expression(node.left)} * {translate_expression(node.right)}"
    if isinstance(node, exp.Div):
        return f"{translate_expression(node.left)} / {translate_expression(node.right)}"
    if isinstance(node, exp.Paren):
        return f"({translate_expression(node.this)})"

    # --- Comparisons ---
    if isinstance(node, exp.EQ):
        return f"{translate_expression(node.left)} is {translate_expression(node.right)}"
    if isinstance(node, exp.NEQ):
        return f"{translate_expression(node.left)} is NOT {translate_expression(node.right)}"
    if isinstance(node, exp.GT):
        return f"{translate_expression(node.left)} > {translate_expression(node.right)}"
    if isinstance(node, exp.GTE):
        return f"{translate_expression(node.left)} >= {translate_expression(node.right)}"
    if isinstance(node, exp.LT):
        return f"{translate_expression(node.left)} < {translate_expression(node.right)}"
    if isinstance(node, exp.LTE):
        return f"{translate_expression(node.left)} <= {translate_expression(node.right)}"

    # --- Logical ---
    if isinstance(node, exp.In):
        values = ", ".join(translate_expression(v) for v in node.expressions)
        return f"{translate_expression(node.this)} is in [{values}]"
    
    # Handle NOT (often wraps IN or IS NULL)
    if isinstance(node, exp.Not):
        return f"NOT ({translate_expression(node.this)})"

    # --- Special Functions ---
    if isinstance(node, exp.Is):
        if isinstance(node.expression, exp.Null):
            return f"{translate_expression(node.this)} is NULL"
    
    if isinstance(node, exp.Func):
        # Handle CAST specifically if needed, or generic functions
        if node.sql().lower().startswith("cast"):
            return f"CAST({translate_expression(node.this)})"
        if node.sql().lower().startswith("nullif"):
            # nullif(a, b) -> A (unless A equals B)
            args = node.expressions
            return f"NULLIF({translate_expression(args[0])}, {translate_expression(args[1])})"
        
        # Generic function fallback: func_name(arg1, arg2...)
        args = ", ".join([translate_expression(x) for x in node.expressions])
        return f"{node.key.upper()}({args})"

    # --- Literals & Columns ---
    if isinstance(node, exp.Literal):
        return node.sql()
    if isinstance(node, exp.Column):
        return node.sql()

    # Fallback for anything unknown
    return node.sql()


# ------------------------------------------------------------
# Formatting Utility
# ------------------------------------------------------------
def indent(level: int) -> str:
    return "    " * level

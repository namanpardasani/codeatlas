"""Cyclomatic complexity and nesting depth from a function's syntax tree.

Rules (also documented in NOTES.md):
  complexity = 1 + number of decision points inside the function
  * nested NAMED functions/classes are not counted (they are their own symbols);
    anonymous callbacks/lambdas ARE counted in the enclosing function
  * max_nesting = deepest nesting of control structures; `else if` does not add depth
"""
from dataclasses import dataclass
from typing import Callable

import tree_sitter as ts

from .base import text


@dataclass(frozen=True)
class Rules:
    skip: Callable[[ts.Node], bool]       # subtree that belongs to another symbol
    decision: Callable[[ts.Node], int]    # complexity added by this node
    nesting: Callable[[ts.Node], bool]    # does this node open a nesting level?


def measure(root: ts.Node, rules: Rules) -> tuple[int, int]:
    """(complexity, max_nesting) of the function rooted at `root`. Iterative: no recursion limit."""
    complexity, max_depth = 1, 0
    stack = [(c, 0) for c in reversed(root.children)]
    while stack:
        node, depth = stack.pop()
        if rules.skip(node):
            continue
        complexity += rules.decision(node)
        depth += 1 if rules.nesting(node) else 0
        max_depth = max(max_depth, depth)
        stack.extend((c, depth) for c in reversed(node.children))
    return complexity, max_depth


# ---- JavaScript / TypeScript ---------------------------------------------------------------
JS_FUNCTIONS = {"arrow_function", "function_expression", "function", "generator_function"}
JS_NAMED_DECLS = {"function_declaration", "generator_function_declaration", "method_definition",
                  "class_declaration", "abstract_class_declaration"}
JS_DECISIONS = {"if_statement", "for_statement", "for_in_statement", "while_statement",
                "do_statement", "switch_case", "catch_clause", "ternary_expression"}
JS_LOGICAL = {"&&", "||", "??"}
JS_LOGICAL_ASSIGN = {"&&=", "||=", "??="}
JS_NESTING = {"if_statement", "for_statement", "for_in_statement", "while_statement",
              "do_statement", "switch_statement", "try_statement"}


def _js_skip(n: ts.Node) -> bool:
    if n.type in JS_NAMED_DECLS:
        return True
    if n.type == "variable_declarator":
        v, name = n.child_by_field_name("value"), n.child_by_field_name("name")
        return v is not None and name is not None and name.type == "identifier" and \
            (v.type in JS_FUNCTIONS or v.type in ("class", "class_expression"))
    if n.type in ("public_field_definition", "field_definition"):
        v = n.child_by_field_name("value")
        return v is not None and v.type in JS_FUNCTIONS
    return False


def _js_decision(n: ts.Node) -> int:
    if n.type in JS_DECISIONS:
        return 1
    if n.type == "binary_expression":
        return int(text(n.child_by_field_name("operator")) in JS_LOGICAL)
    if n.type == "augmented_assignment_expression":
        return int(text(n.child_by_field_name("operator")) in JS_LOGICAL_ASSIGN)
    return 0


def _js_nesting(n: ts.Node) -> bool:
    if n.type == "if_statement":
        return n.parent is None or n.parent.type != "else_clause"  # `else if` stays on the same level
    return n.type in JS_NESTING


JS_RULES = Rules(_js_skip, _js_decision, _js_nesting)

# ---- Python -------------------------------------------------------------------------------
PY_DECISIONS = {"if_statement", "elif_clause", "for_statement", "while_statement", "except_clause",
                "except_group_clause", "conditional_expression", "boolean_operator",
                "for_in_clause", "if_clause"}
PY_NESTING = {"if_statement", "for_statement", "while_statement", "try_statement",
              "with_statement", "match_statement"}


def _py_skip(n: ts.Node) -> bool:
    if n.type in ("function_definition", "class_definition"):
        return True
    if n.type == "decorated_definition":
        d = n.child_by_field_name("definition")
        return d is not None and d.type in ("function_definition", "class_definition")
    if n.type == "assignment":  # named lambda: its own symbol
        l, r = n.child_by_field_name("left"), n.child_by_field_name("right")
        return l is not None and r is not None and l.type == "identifier" and r.type == "lambda"
    return False


def _py_decision(n: ts.Node) -> int:
    if n.type in PY_DECISIONS:
        return 1
    if n.type == "case_clause":  # `case _:` is the default branch: no extra path (like JS `default`)
        pats = [c for c in n.named_children if c.type == "case_pattern"]
        return 0 if len(pats) == 1 and text(pats[0]).strip() == "_" else 1
    return 0


PY_RULES = Rules(_py_skip, _py_decision, lambda n: n.type in PY_NESTING)

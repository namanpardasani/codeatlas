from .base import text
from .types import RawImport


def collect_imports(root, result):
    """Find every `import x` / `from x import y` in a Python syntax tree (stored unresolved)."""
    stack = [root]
    while stack:
        node = stack.pop()
        line = node.start_point.row + 1

        if node.type == "import_statement":
            # import os, os.path as p  ->  one RawImport per module
            for child in node.named_children:
                if child.type == "dotted_name":
                    result.imports.append(RawImport(text(child), "import", line))
                elif child.type == "aliased_import":
                    result.imports.append(RawImport(text(child.child_by_field_name("name")), "import", line))
            continue

        if node.type == "import_from_statement":
            module = node.child_by_field_name("module_name")
            level, specifier = 0, ""
            if module is not None and module.type == "relative_import":
                for part in module.named_children:
                    if part.type == "import_prefix":
                        level = len(text(part))          # number of leading dots
                    elif part.type == "dotted_name":
                        specifier = text(part)
            elif module is not None:
                specifier = text(module)

            names = []
            for child in node.named_children:
                if module is not None and child.id == module.id:
                    continue
                if child.type == "dotted_name":
                    names.append(text(child))
                elif child.type == "aliased_import":
                    names.append(text(child.child_by_field_name("name")))
                elif child.type == "wildcard_import":
                    names.append("*")
            result.imports.append(RawImport(specifier, "from", line, names, level))
            continue

        stack.extend(node.children)  # imports can also hide inside functions / try blocks

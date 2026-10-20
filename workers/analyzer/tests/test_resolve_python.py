from analyzer.resolve.python import PyResolver
from analyzer.resolve.types import ImportItem


def item(frm, spec, kind="import", names=None, level=0):
    return ImportItem(frm, 0, spec, kind, names or [], level)


def make(*paths):
    return PyResolver(set(paths))


def test_absolute_module_and_package_imports():
    r = make("app/__init__.py", "app/models.py", "app/util/__init__.py", "main.py")
    assert r.resolve(item("main.py", "app.models")).targets == ["app/models.py"]
    assert r.resolve(item("main.py", "app.util")).targets == ["app/util/__init__.py"]
    assert r.resolve(item("main.py", "app")).targets == ["app/__init__.py"]


def test_from_import_links_submodules_too():
    r = make("pkg/__init__.py", "pkg/a.py", "pkg/b/__init__.py", "main.py")
    res = r.resolve(item("main.py", "pkg", "from", ["a", "b", "some_function"]))
    assert res.status == "internal"
    assert res.targets == ["pkg/__init__.py", "pkg/a.py", "pkg/b/__init__.py"]


def test_relative_levels():
    r = make("a/__init__.py", "a/x.py", "a/sub/__init__.py", "a/sub/y.py", "a/sub/z.py")
    assert r.resolve(item("a/sub/y.py", "z", "from", ["f"], level=1)).targets == ["a/sub/z.py"]
    assert r.resolve(item("a/sub/y.py", "x", "from", ["f"], level=2)).targets == ["a/x.py"]
    # `from . import z` where z is a submodule -> only a/sub/z.py (day 9: the package __init__ is an implicit side
    # effect, not a dependency; counting it made children "import" the parent that re-exports them)
    assert r.resolve(item("a/sub/y.py", "", "from", ["z"], level=1)).targets == ["a/sub/z.py"]
    assert r.resolve(item("a/sub/y.py", "", "from", ["x"], level=2)).targets == ["a/x.py"]


def test_relative_failures_are_unresolved():
    r = make("a/__init__.py", "a/y.py")
    assert r.resolve(item("a/y.py", "nope", "from", ["q"], level=1)).status == "unresolved"
    beyond = r.resolve(item("a/y.py", "x", "from", ["q"], level=5))
    assert beyond.status == "unresolved" and "beyond" in beyond.reason


def test_src_layout():
    r = make("src/mypkg/__init__.py", "src/mypkg/core.py", "tests/test_core.py")
    assert r.resolve(item("tests/test_core.py", "mypkg.core")).targets == ["src/mypkg/core.py"]


def test_stdlib_and_third_party_are_external():
    r = make("main.py")
    os_ = r.resolve(item("main.py", "os.path"))
    assert (os_.status, os_.package, os_.reason) == ("external", "os", "stdlib")
    assert r.resolve(item("main.py", "numpy")).package == "numpy"
    assert r.resolve(item("main.py", "requests.adapters", "from", ["X"])).package == "requests"


def test_missing_submodule_of_internal_package_is_unresolved_not_external():
    r = make("app/__init__.py", "main.py")
    res = r.resolve(item("main.py", "app.missing"))
    assert res.status == "unresolved" and "app" in res.reason


def test_namespace_package_and_sibling_script_imports():
    r = make("ns/mod.py", "scripts/run.py", "scripts/helper.py", "main.py")
    assert r.resolve(item("main.py", "ns.mod")).targets == ["ns/mod.py"]
    assert r.resolve(item("main.py", "ns", "from", ["mod"])).targets == ["ns/mod.py"]
    assert r.resolve(item("scripts/run.py", "helper")).targets == ["scripts/helper.py"]  # sys.path[0]


def test_package_beats_module_of_same_name_and_star_import():
    r = make("m/__init__.py", "m.py", "main.py")
    assert r.resolve(item("main.py", "m")).targets == ["m/__init__.py"]
    assert r.resolve(item("main.py", "m", "from", ["*"])).targets == ["m/__init__.py"]


def test_from_package_import_submodules_does_not_depend_on_the_package_init():
    r = make("pkg/__init__.py", "pkg/a.py", "pkg/b.py", "pkg/sub/__init__.py", "pkg/sub/c.py", "pkg/sub/d.py")
    # every name is a submodule -> only those files
    assert r.resolve(item("pkg/b.py", "", "from", ["a"], level=1)).targets == ["pkg/a.py"]
    assert r.resolve(item("pkg/sub/c.py", "", "from", ["c", "d"], level=1)).targets == ["pkg/sub/c.py", "pkg/sub/d.py"]
    assert r.resolve(item("x.py", "pkg", "from", ["a", "b"], level=0)).targets == ["pkg/a.py", "pkg/b.py"]
    # a name defined in __init__ itself (not a submodule) keeps the edge to __init__
    assert r.resolve(item("pkg/b.py", "", "from", ["a", "VERSION"], level=1)).targets == ["pkg/__init__.py", "pkg/a.py"]
    assert r.resolve(item("pkg/b.py", "", "from", ["VERSION"], level=1)).targets == ["pkg/__init__.py"]
    assert r.resolve(item("pkg/b.py", "", "from", ["*"], level=1)).targets == ["pkg/__init__.py"]
    # a plain `from .a import f` is unaffected: it depends on a.py, and `import pkg` on __init__
    assert r.resolve(item("pkg/b.py", "a", "from", ["f"], level=1)).targets == ["pkg/a.py"]
    assert r.resolve(item("x.py", "pkg", "import", [], level=0)).targets == ["pkg/__init__.py"]

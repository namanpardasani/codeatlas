import json

from analyzer.resolve.js import JsResolver, package_name


def make(files: dict[str, str]):
    return JsResolver(set(files), lambda p: files.get(p))


def test_relative_extensions_index_and_ts_twin():
    r = make({k: "" for k in [
        "src/app.ts", "src/util.ts", "src/lib/index.ts", "src/data.json", "src/comp.tsx",
        "src/esm.ts", "src/types.d.ts",
    ]})
    assert r.resolve("src/app.ts", "./util").targets == ["src/util.ts"]
    assert r.resolve("src/app.ts", "./lib").targets == ["src/lib/index.ts"]
    assert r.resolve("src/app.ts", "./lib/").targets == ["src/lib/index.ts"]
    assert r.resolve("src/app.ts", "./data.json").targets == ["src/data.json"]
    assert r.resolve("src/app.ts", "./comp").targets == ["src/comp.tsx"]
    assert r.resolve("src/app.ts", "./esm.js").targets == ["src/esm.ts"]  # TS ESM convention
    assert r.resolve("src/lib/index.ts", "../util").targets == ["src/util.ts"]
    assert r.resolve("src/app.ts", "./types").targets == ["src/types.d.ts"]


def test_unresolved_is_recorded_not_guessed():
    r = make({"src/app.ts": ""})
    res = r.resolve("src/app.ts", "./missing")
    assert res.status == "unresolved" and "no file matches" in res.reason
    assert r.resolve("src/app.ts", "../../outside").status == "unresolved"
    assert r.resolve("src/app.ts", "/abs/path").status == "unresolved"
    assert r.resolve("src/app.ts", "#internal").status == "unresolved"
    assert r.resolve("src/app.ts", "").status == "unresolved"


def test_external_packages_and_builtins():
    r = make({"a.ts": ""})
    assert (r.resolve("a.ts", "react").status, r.resolve("a.ts", "react").package) == ("external", "react")
    assert r.resolve("a.ts", "lodash/fp").package == "lodash"
    assert r.resolve("a.ts", "@scope/pkg/deep/file").package == "@scope/pkg"
    assert r.resolve("a.ts", "node:fs").package == "node:fs"
    fs = r.resolve("a.ts", "fs")
    assert fs.status == "external" and fs.reason == "node builtin"
    assert r.resolve("a.ts", "https://cdn.example.com/x.js").status == "external"
    assert package_name("@a/b/c") == ("@a/b", "c") and package_name("x") == ("x", "")


def test_tsconfig_paths_with_comments_and_wildcards():
    files = {
        "tsconfig.json": '{ // comment\n "compilerOptions": { "baseUrl": ".", "paths": {"@/*": ["src/*"], "@utils": ["src/utils/index.ts"],}, }, }',
        "src/a.ts": "", "src/utils/index.ts": "", "src/components/Button.tsx": "",
    }
    r = make(files)
    assert r.resolve("src/a.ts", "@/components/Button").targets == ["src/components/Button.tsx"]
    assert r.resolve("src/a.ts", "@utils").targets == ["src/utils/index.ts"]
    assert r.resolve("src/a.ts", "src/utils").targets == ["src/utils/index.ts"]  # via baseUrl
    miss = r.resolve("src/a.ts", "@/nope")
    assert miss.status == "unresolved" and "alias" in miss.reason


def test_nearest_tsconfig_in_monorepo_and_extends():
    files = {
        "tsconfig.base.json": json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"~/*": ["src/*"]}}}),
        "packages/web/tsconfig.json": json.dumps({"extends": "../../tsconfig.base.json"}),
        "packages/web/src/x.ts": "", "packages/api/src/y.ts": "", "src/shared.ts": "",
        "packages/api/tsconfig.json": json.dumps({"compilerOptions": {"baseUrl": "src", "paths": {"~/*": ["*"]}}}),
    }
    r = make(files)
    # web inherits base paths (relative to the base config's baseUrl = repo root)
    assert r.resolve("packages/web/src/x.ts", "~/shared").targets == ["src/shared.ts"]
    # api overrides: "~/*" -> packages/api/src/*
    assert r.resolve("packages/api/src/y.ts", "~/y").targets == ["packages/api/src/y.ts"]


def test_vite_style_references_config():
    files = {
        "tsconfig.json": json.dumps({"files": [], "references": [{"path": "./tsconfig.app.json"}]}),
        "tsconfig.app.json": json.dumps({"compilerOptions": {"baseUrl": ".", "paths": {"@/*": ["./src/*"]}}}),
        "src/main.tsx": "", "src/App.tsx": "",
    }
    assert make(files).resolve("src/main.tsx", "@/App").targets == ["src/App.tsx"]


def test_workspace_packages():
    files = {
        "package.json": json.dumps({"name": "root", "workspaces": ["packages/*"]}),
        "packages/shared/package.json": json.dumps({"name": "@org/shared", "main": "dist/index.js"}),
        "packages/shared/src/index.ts": "", "packages/shared/src/format.ts": "",
        "packages/app/src/main.ts": "",
    }
    r = make(files)
    assert r.resolve("packages/app/src/main.ts", "@org/shared").targets == ["packages/shared/src/index.ts"]
    assert r.resolve("packages/app/src/main.ts", "@org/shared/format").targets == ["packages/shared/src/format.ts"]
    assert r.resolve("packages/app/src/main.ts", "@org/shared/missing").status == "unresolved"
    assert r.resolve("packages/app/src/main.ts", "@org/other").status == "external"

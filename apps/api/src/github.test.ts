import { describe, it, expect } from "vitest";
import { parseGithubUrl } from "./github.js";

describe("parseGithubUrl", () => {
  it("accepts canonical and .git/trailing-slash forms", () => {
    expect(parseGithubUrl("https://github.com/Expressjs/Express")?.fullName).toBe("expressjs/express");
    expect(parseGithubUrl("https://github.com/a/b.git")?.url).toBe("https://github.com/a/b");
    expect(parseGithubUrl("https://github.com/a/b/")?.name).toBe("b");
  });

  it.each([
    "http://github.com/a/b",
    "https://gitlab.com/a/b",
    "https://github.com.evil.com/a/b",
    "https://evil.com/github.com/a/b",
    "https://user:pw@github.com/a/b",
    "https://github.com:8443/a/b",
    "https://github.com/a/b?x=1",
    "https://github.com/a/b#frag",
    "https://github.com/a",
    "https://github.com/a/b/c",
    "https://github.com/a/..",
    "https://github.com/-bad/repo",
    "https://github.com/a/-upload-pack=x",
    "file:///etc/passwd",
    "git@github.com:a/b.git",
    "https://127.0.0.1/a/b",
    "https://localhost/a/b",
    "",
    "not a url",
  ])("rejects %s", (input) => {
    expect(parseGithubUrl(input)).toBeNull();
  });

  it("rejects non-strings and overlong input", () => {
    expect(parseGithubUrl(undefined as unknown as string)).toBeNull();
    expect(parseGithubUrl("https://github.com/a/" + "b".repeat(300))).toBeNull();
  });
});

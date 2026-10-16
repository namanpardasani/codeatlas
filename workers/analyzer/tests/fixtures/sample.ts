/** Adds numbers. */
export function add(a: number, b?: number, ...rest: number[]): number {
  function helper() {}
  return a + (b ?? 0);
}

export default class Service extends Base {
  static counter = () => 1;
  /** documented */
  async run(job: Job, retries = 3) {}
  private stop() {}
}

export const handler = async (req, { body }) => body;
const local = x => x;
export { local as renamed };
interface Options { a: number }
type Id = string;
enum Color { Red }

import fs, * as path from "node:path";
import { a, b as c } from "./lib";
import type { T } from "../types";
export { x as y } from "./re";
export * from "./all";
const m = require("./cjs");
const lazy = () => import("./lazy");
const dynamicNonLiteral = (n) => import(n);

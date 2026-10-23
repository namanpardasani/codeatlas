import sum, { double } from './lib/math'
import { plus, Store, total } from './lib'
import * as M from './lib/math'
import Widget from './Widget'
import React from 'react'
const { helper } = require('./cjs')

export function run(s: Store, obj: any, key: string) {
  plus(1, 2)
  double(2)
  sum([1])
  total([2])
  M.add(1, 1)
  s.get(0)
  const c = new CachedStore()
  c.put('x')
  helper()
  obj[key]()
  React.useState(0)
  setTimeout(run, 1)
  return <div><Widget /></div>
}

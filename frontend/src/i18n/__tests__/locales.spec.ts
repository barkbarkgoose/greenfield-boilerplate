// Translation regression tests. They fail when:
// - a key exists in one language but not the other, or is empty
// - the two languages use different {placeholders} or plural branches (" | ")
// - a key isn't BEM-shaped: block__element or block__element--modifier
// - the code uses a key that doesn't exist, or a key is no longer used anywhere
import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { describe, expect, it } from 'vitest'
import en from '../locales/en.json'
import es from '../locales/es.json'

const BEM_KEY = /^[a-z0-9]+(?:-[a-z0-9]+)*__[a-z0-9]+(?:-[a-z0-9]+)*(?:--[a-z0-9_]+(?:-[a-z0-9_]+)*)?$/
const SRC = fileURLToPath(new URL('../..', import.meta.url))

const english = en as Record<string, string>
const spanish = es as Record<string, string>

function placeholders(text: string): string[] {
  return [...text.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
}

function sourceFiles(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name)
    if (statSync(path).isDirectory()) return name === '__tests__' || name === 'locales' ? [] : sourceFiles(path)
    return /\.(vue|ts)$/.test(name) ? [path] : []
  })
}

const source = sourceFiles(SRC)
  .map((file) => readFileSync(file, 'utf8'))
  .join('\n')
// Keys written out in full, and dynamic keys like `request-status__label--${status}`.
const literalKeys = new Set(
  [...source.matchAll(/['"`]([a-z0-9-]+__[a-z0-9-]+(?:--[a-z0-9_-]+)?)['"`]/g)].map((m) => m[1])
)
const dynamicPrefixes = [...source.matchAll(/`([a-z0-9-]+__[a-z0-9-]*(?:--)?)\$\{/g)].map((m) => m[1])

describe('translations', () => {
  it('have the same keys in English and Spanish', () => {
    expect(Object.keys(spanish).filter((k) => !(k in english))).toEqual([])
    expect(Object.keys(english).filter((k) => !(k in spanish))).toEqual([])
  })

  it('have no empty text', () => {
    const empty = [...Object.entries(english), ...Object.entries(spanish)].filter(([, v]) => !v.trim())
    expect(empty).toEqual([])
  })

  it('use the same placeholders and plural branches in both languages', () => {
    const mismatched = Object.keys(english).filter(
      (key) =>
        placeholders(english[key]).join() !== placeholders(spanish[key] ?? '').join() ||
        english[key].split(' | ').length !== (spanish[key] ?? '').split(' | ').length
    )
    expect(mismatched).toEqual([])
  })

  it('use BEM-style keys', () => {
    expect(Object.keys(english).filter((key) => !BEM_KEY.test(key))).toEqual([])
  })

  it('define every key the code uses', () => {
    const missing = [...literalKeys].filter((key) => BEM_KEY.test(key) && !(key in english))
    const missingPrefixes = dynamicPrefixes.filter((prefix) => !Object.keys(english).some((k) => k.startsWith(prefix)))
    expect(missing).toEqual([])
    expect(missingPrefixes).toEqual([])
  })

  it('have no unused keys', () => {
    const unused = Object.keys(english).filter(
      (key) => !literalKeys.has(key) && !dynamicPrefixes.some((prefix) => key.startsWith(prefix))
    )
    expect(unused).toEqual([])
  })
})

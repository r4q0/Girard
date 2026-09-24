// Girard never shows em dashes. Every AI answer goes through this before it reaches the screen or a file.
// The dash characters are written as \u escapes below, so this file itself contains none.

const DASH = '[\\u2014\\u2013\\u2015]'

/** "A <em dash> B" becomes "A, B"; a number range "10<en dash>15" becomes "10-15". */
export function noDashes(text: string): string {
  return text
    .replace(new RegExp(`(\\d)\\s*${DASH}\\s*(\\d)`, 'g'), '$1-$2')
    .replace(new RegExp(`^\\s*${DASH}\\s*`), '')
    .replace(new RegExp(`\\s*${DASH}\\s*$`), '')
    .replace(new RegExp(`\\s*${DASH}\\s*`, 'g'), ', ')
    .replace(/,\s*([,.;:!?])/g, '$1') // ", ." left behind becomes "."
    .replace(/\s{2,}/g, ' ')
}

/** noDashes on every string inside a JSON-like value. */
export function cleanDeep<T>(value: T): T {
  if (typeof value === 'string') return noDashes(value) as T
  if (Array.isArray(value)) return value.map(cleanDeep) as T
  if (value && typeof value === 'object') {
    return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, cleanDeep(v)])) as T
  }
  return value
}

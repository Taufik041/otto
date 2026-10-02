import { parseInline, parseMarkdown } from './markdown'

it('inline code, bold, italics and links', () => {
  expect(parseInline('Found it. `qualifies_for_bulk` used `>` **not** *quite* [PR](https://github.com/x/y/pull/3)')).toEqual([
    { t: 'text', v: 'Found it. ' },
    { t: 'code', v: 'qualifies_for_bulk' },
    { t: 'text', v: ' used ' },
    { t: 'code', v: '>' },
    { t: 'text', v: ' ' },
    { t: 'strong', c: [{ t: 'text', v: 'not' }] },
    { t: 'text', v: ' ' },
    { t: 'em', c: [{ t: 'text', v: 'quite' }] },
    { t: 'text', v: ' ' },
    { t: 'link', href: 'https://github.com/x/y/pull/3', c: [{ t: 'text', v: 'PR' }] },
  ])
})

it('only http(s) links; snake_case stays text', () => {
  expect(parseInline('[x](javascript:alert(1)) my_var_name')).toEqual([{ t: 'text', v: '[x](javascript:alert(1)) my_var_name' }])
})

it('paragraphs, lists, headings and fenced code', () => {
  const md = '## Fix\n\nYes. A rule:\n\n```python\nif x > 1:\n    pass\n```\n\n- one\n- two `x`\n\n1. first\n2. second\n\nDone.'
  expect(parseMarkdown(md)).toEqual([
    { t: 'h', c: [{ t: 'text', v: 'Fix' }] },
    { t: 'p', c: [{ t: 'text', v: 'Yes. A rule:' }] },
    { t: 'pre', lang: 'python', code: 'if x > 1:\n    pass' },
    { t: 'ul', items: [[{ t: 'text', v: 'one' }], [{ t: 'text', v: 'two ' }, { t: 'code', v: 'x' }]] },
    { t: 'ol', items: [[{ t: 'text', v: 'first' }], [{ t: 'text', v: 'second' }]] },
    { t: 'p', c: [{ t: 'text', v: 'Done.' }] },
  ])
})

it('an unclosed fence takes the rest', () => {
  expect(parseMarkdown('```\ncode')).toEqual([{ t: 'pre', lang: null, code: 'code' }])
})

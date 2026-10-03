import { activeMention, extractRepo, filterRepos, findRepo, removeMention } from './mention'
import { repos } from '@/test/fixtures'

describe('activeMention', () => {
  it('finds an @ at the start or after a space, up to the caret', () => {
    expect(activeMention('@')).toEqual({ start: 0, end: 1, query: '' })
    expect(activeMention('@ott')).toEqual({ start: 0, end: 4, query: 'ott' })
    expect(activeMention('fix @otto_te')).toEqual({ start: 4, end: 12, query: 'otto_te' })
    expect(activeMention('in @Taufik041/otto')).toMatchObject({ query: 'Taufik041/otto' })
    expect(activeMention('a\n@p')).toMatchObject({ start: 2, query: 'p' })
  })

  it('ignores an @ inside a word, or one the caret has left', () => {
    expect(activeMention('me@example')).toBeNull()
    expect(activeMention('@otto_test fix')).toBeNull()
    expect(activeMention('@otto ')).toBeNull()
    expect(activeMention('')).toBeNull()
  })

  it('reads only up to the caret', () => {
    expect(activeMention('fix @ott tests', 8)).toEqual({ start: 4, end: 8, query: 'ott' })
  })
})

describe('filterRepos', () => {
  it('matches any part of the full name, any case, name prefixes first', () => {
    expect(filterRepos(repos, '').map((r) => r.full_name)).toHaveLength(3)
    expect(filterRepos(repos, 'PET').map((r) => r.full_name)).toEqual(['Taufik041/petal'])
    expect(filterRepos(repos, 'o').map((r) => r.full_name)).toEqual([
      'Taufik041/otto_test', // starts with o
      'Taufik041/portfolio',
    ])
    expect(filterRepos(repos, 'taufik041/p').map((r) => r.full_name)).toEqual(['Taufik041/portfolio', 'Taufik041/petal'])
    expect(filterRepos(repos, 'zzz')).toEqual([])
  })
})

describe('removeMention', () => {
  it('drops the @query and puts the caret where it was', () => {
    expect(removeMention('@ott', { start: 0, end: 4, query: 'ott' })).toEqual({ text: '', caret: 0 })
    expect(removeMention('fix @ott', { start: 4, end: 8, query: 'ott' })).toEqual({ text: 'fix ', caret: 4 })
    expect(removeMention('fix @ott now', { start: 4, end: 8, query: 'ott' })).toEqual({ text: 'fix now', caret: 4 })
  })
})

describe('findRepo and extractRepo', () => {
  it('find by full name or by a unique short name', () => {
    expect(findRepo(repos, 'taufik041/OTTO_TEST')?.full_name).toBe('Taufik041/otto_test')
    expect(findRepo(repos, 'petal')?.full_name).toBe('Taufik041/petal')
    expect(findRepo(repos, 'nope')).toBeNull()
    const twins = [...repos, { ...repos[2]!, full_name: 'someone/petal' }]
    expect(findRepo(twins, 'petal')).toBeNull()
  })

  it('a typed @repo becomes the chat repo and leaves the text', () => {
    expect(extractRepo('@otto_test fix the failing tests', repos)).toEqual({
      text: 'fix the failing tests',
      repo: repos[0],
    })
    expect(extractRepo('Explain how the pricing works in @otto_test', repos)).toEqual({
      text: 'Explain how the pricing works in',
      repo: repos[0],
    })
    expect(extractRepo('ask @Taufik041/petal about it', repos).repo?.full_name).toBe('Taufik041/petal')
  })

  it('leaves unknown mentions and emails alone', () => {
    expect(extractRepo('mail me@example.com about @nobody', repos)).toEqual({
      text: 'mail me@example.com about @nobody',
      repo: null,
    })
  })
})

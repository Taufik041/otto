import { initialModel } from './models'
import { models } from '@/test/fixtures'

it("preselects the user's default while available, else the server's default_model", () => {
  const catalog = { default_model: 'openrouter:openrouter/free', models }
  expect(initialModel(catalog, null)).toBe('openrouter:openrouter/free')
  expect(initialModel(catalog, 'openai:gpt-4.1-mini')).toBe('openai:gpt-4.1-mini')
  expect(initialModel(catalog, 'openai:gpt-4.1')).toBe('openrouter:openrouter/free') // unavailable
  expect(initialModel({ default_model: null, models }, null)).toBe('openrouter:openrouter/free')
})

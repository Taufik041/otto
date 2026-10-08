import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ModelMenu } from './ModelMenu'
import { models } from '@/test/fixtures'

function setup(selected = 'openrouter:openrouter/free') {
  const onPick = vi.fn()
  render(<ModelMenu models={models} selected={selected} defaultId="openrouter:openrouter/free" onPick={onPick} />)
  return { onPick }
}

it('the default model comes first, then "Other models"; descriptions and the Default tag', () => {
  setup()
  const groups = screen.getAllByRole('group')
  expect(groups.map((g) => g.getAttribute('aria-label'))).toEqual(['Default model', 'Other models'])
  expect(screen.getByText('Other models')).toBeInTheDocument()
  expect(screen.queryByText('OpenRouter')).not.toBeInTheDocument() // no provider headings
  expect(within(groups[0]!).getAllByRole('option')).toHaveLength(1)
  const free = screen.getByRole('option', { name: /OpenRouter Free/ })
  expect(within(free).getByText('Default')).toBeInTheDocument()
  expect(within(free).getByText('Free, good for small tasks')).toBeInTheDocument()
  expect(free).toHaveAttribute('aria-selected', 'true')
})

it('an unavailable model is disabled, shows its hint, and cannot be picked', async () => {
  const { onPick } = setup()
  const gpt = screen.getByRole('option', { name: /^GPT-4\.1\s*Best/ })
  expect(gpt).toHaveAttribute('aria-disabled', 'true')
  expect(within(gpt).getByText('Unavailable right now. Try again later.')).toBeInTheDocument()

  await userEvent.click(gpt)
  expect(onPick).not.toHaveBeenCalled()

  const mini = screen.getByRole('option', { name: /GPT-4\.1 mini/ })
  expect(mini).not.toHaveAttribute('aria-disabled')
  await userEvent.click(mini)
  expect(onPick).toHaveBeenCalledWith('openai:gpt-4.1-mini')
})

it('the default leads even when the catalog lists it later', () => {
  render(<ModelMenu models={[models[1]!, models[0]!]} selected={null} defaultId="openrouter:openrouter/free" onPick={() => {}} />)
  expect(screen.getAllByRole('option').map((o) => o.id)).toEqual(['model-openrouter_openrouter_free', 'model-openai_gpt-4_1-mini'])
})

it('the keyboard skips unavailable models', async () => {
  const { onPick } = setup()
  expect(screen.getByRole('listbox')).toHaveFocus()
  await userEvent.keyboard('{ArrowDown}{ArrowDown}{Enter}') // free -> mini -> (gpt-4.1 skipped) free
  expect(onPick).toHaveBeenLastCalledWith('openrouter:openrouter/free')
  await userEvent.keyboard('{ArrowDown}{Enter}')
  expect(onPick).toHaveBeenLastCalledWith('openai:gpt-4.1-mini')
  expect(onPick).not.toHaveBeenCalledWith('openai:gpt-4.1')
})

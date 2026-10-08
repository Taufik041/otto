import { screen } from '@testing-library/react'
import { WorkersOffline } from './WorkersOffline'
import { renderSignedIn } from '@/test/render'

it('"Book a live demo" opens the booking page in a new tab', () => {
  renderSignedIn(<WorkersOffline bookingUrl="https://cal.example/otto" />)
  const link = screen.getByRole('link', { name: 'Book a live demo' })
  expect(link).toHaveAttribute('href', 'https://cal.example/otto')
  expect(link).toHaveAttribute('target', '_blank')
  expect(link).toHaveAttribute('rel', 'noopener noreferrer')
})

it('without VITE_DEMO_BOOKING_URL there is no booking link', () => {
  renderSignedIn(<WorkersOffline bookingUrl={null} />)
  expect(screen.queryByRole('link', { name: 'Book a live demo' })).not.toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Ask Taufik to bring it up' })).toBeInTheDocument()
})

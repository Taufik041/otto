import { Fragment, type ReactNode } from 'react'
import { Link, useParams } from 'react-router'
import { useIsMobile } from '@/hooks/useMediaQuery'
import { BUILD_DATE, CONTACT_EMAIL } from '@/utils/links'
import { NotFoundPage } from '../NotFoundPage'
import { PublicLayout } from '../public/PublicLayout'
import { LEGAL, LEGAL_DOCS, longDate, OPERATOR, type LegalDoc } from './content'

/** The contact email inside a paragraph, as a link. */
function withMail(text: string): ReactNode {
  const parts = text.split(CONTACT_EMAIL)
  return parts.map((p, i) => (
    <Fragment key={i}>
      {p}
      {i < parts.length - 1 && <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>}
    </Fragment>
  ))
}

/** /legal/terms, /legal/privacy, /legal/acceptable-use: a readable article (720px) with, on
 *  desktop, a table of contents on the left. */
export function LegalPage() {
  const { doc } = useParams()
  const mobile = useIsMobile()
  const legal = LEGAL[doc as LegalDoc]
  if (!legal) return <NotFoundPage />

  return (
    <PublicLayout>
      <div className="mx-auto flex max-w-[1100px] items-start gap-16 px-5 pb-[72px] pt-10 sm:px-12 sm:pb-[120px] sm:pt-[72px]">
        {!mobile && (
          <nav aria-label="On this page" className="sticky top-24 flex w-[200px] shrink-0 flex-col gap-0.5">
            <div className="px-2.5 pb-2.5 text-xs font-medium text-muted">On this page</div>
            {legal.sections.map((s) => (
              <a key={s.id} href={`#${s.id}`} className="rounded-lg px-2.5 py-1.5 text-sm text-muted hover:bg-hover hover:text-text">
                {s.heading}
              </a>
            ))}
          </nav>
        )}
        <article className="min-w-0 max-w-[720px] flex-1">
          <nav aria-label="Legal documents" className="mb-8 flex flex-wrap gap-1.5">
            {LEGAL_DOCS.map((d) => {
              const on = d.slug === legal.slug
              return (
                <Link
                  key={d.slug}
                  to={`/legal/${d.slug}`}
                  aria-current={on ? 'page' : undefined}
                  className="inline-flex h-8 items-center rounded-full border border-solid px-3.5 text-sm"
                  style={{
                    borderColor: on ? 'var(--inv)' : 'var(--line)',
                    background: on ? 'var(--inv)' : 'transparent',
                    color: on ? 'var(--inv-text)' : 'var(--text)',
                  }}
                >
                  {d.short}
                </Link>
              )
            })}
          </nav>
          <h1 className="m-0 text-[36px] font-normal leading-[1.06] tracking-[-0.03em] sm:text-[48px]">{legal.title}</h1>
          <p className="m-0 mt-3 text-sm text-muted">
            Last updated {longDate(BUILD_DATE)} · Operated by {OPERATOR}
          </p>
          <p className="m-0 mt-7 text-[17px] leading-[1.6] text-pretty">{withMail(legal.intro)}</p>
          {legal.sections.map((s) => (
            <section key={s.id} id={s.id} className="scroll-mt-20 pt-9">
              <h2 className="m-0 text-[22px] font-normal tracking-[-0.02em]">{s.heading}</h2>
              {s.body.map((p, i) => (
                <p key={i} className="m-0 mt-2.5 text-base leading-[1.65] text-muted text-pretty">
                  {withMail(p)}
                </p>
              ))}
            </section>
          ))}
          <p className="m-0 mt-12 border-0 border-t border-solid border-hair pt-6 text-[15px] text-muted">
            Questions? Email <a href={`mailto:${CONTACT_EMAIL}`}>{CONTACT_EMAIL}</a>.
          </p>
        </article>
      </div>
    </PublicLayout>
  )
}

/**
 * The legal pages' text, in plain language. Otto is a non-commercial demo run by one person; the
 * text says so, names both sites, and gives one contact. "Last updated" is the build date.
 */
import { CONTACT_EMAIL } from '@/utils/links'

export type LegalDoc = 'terms' | 'privacy' | 'acceptable-use'
export type LegalSection = { id: string; heading: string; body: string[] }
export type Legal = { slug: LegalDoc; title: string; short: string; intro: string; sections: LegalSection[] }

export const OPERATOR = 'Taufik Khan'
const SITES = 'otto.taufi.dev (the website) and ottoci.taufi.dev (the app)'

const s = (id: string, heading: string, ...body: string[]): LegalSection => ({ id, heading, body })

const TERMS: Legal = {
  slug: 'terms',
  title: 'Terms of Service',
  short: 'Terms',
  intro: `These terms cover your use of Otto at ${SITES}. Otto is a personal, non-commercial project run by ${OPERATOR}. By creating an account or using Otto, you agree to these terms and to the Acceptable Use Policy.`,
  sections: [
    s('service', 'The service',
      'Otto is an AI coding agent. When you mention a repository you connected, it works on it in an isolated cloud sandbox: it reads the code, runs commands and tests, makes changes, and pushes them to a branch of its own. It then proposes a pull request for you to review.',
      'Otto is a demo in beta. It is free during the beta, it is not a commercial product, and it comes with no promise of support. It runs on hardware the operator owns, so it may be offline at times, and features may change or go away.'),
    s('accounts', 'Eligibility and accounts',
      'You must be at least 18, or the age of majority where you live, and able to agree to these terms. Sign-ups may be invite-only.',
      `One person per account. You are responsible for what happens under your account and for keeping your password safe. Tell us at ${CONTACT_EMAIL} if you think someone else used it.`),
    s('code', 'Your code and pull requests',
      'Your code stays yours, and so do the changes Otto makes for you. You let Otto read, run and change the repositories you connect, only to do the tasks you ask for.',
      'Nothing reaches your repository\'s main branch through Otto: it pushes to its own branch, and a pull request is opened only when you approve it. Review every pull request before you merge it. Once merged, the change is yours to keep or revert.',
      'Only connect repositories you own or are allowed to work on.'),
    s('ai', 'AI output may be wrong',
      'Otto uses AI models and can make mistakes. Its code, explanations and test results can be wrong, incomplete or insecure. Check them yourself. You are responsible for what you merge and run.'),
    s('availability', 'Availability',
      'Otto runs on personal hardware and can be offline, slow or rate-limited at any time. Features, models and limits may change without notice. There is no uptime guarantee, and the service may be discontinued.'),
    s('limits', 'Daily usage limits',
      'Each account has a daily limit on the model tokens it can use, and a cap on how many tasks can run at once. When you reach the limit, Otto stops until the limit resets at midnight UTC. Don\'t try to get around the limits, for example with several accounts.'),
    s('termination', 'Termination',
      'You can delete your account at any time in Settings. We may suspend or close an account that breaks these terms or the Acceptable Use Policy, or to protect the service or other people, with or without notice.'),
    s('disclaimer', 'Disclaimer',
      'Otto is provided "as is" and "as available", without warranties of any kind, express or implied, including fitness for a particular purpose, accuracy and non-infringement.'),
    s('liability', 'Limitation of liability',
      `As far as the law allows, ${OPERATOR} is not liable for any indirect, incidental or consequential losses, or for lost data, code, profits or time, arising from your use of Otto. Since Otto is free, total liability for any claim is limited to zero, or the lowest amount the law allows.`),
    s('law', 'Governing law',
      'These terms are governed by the laws of India. Courts in India have jurisdiction over any dispute about them or about Otto.'),
    s('changes', 'Changes to these terms',
      'These terms may change. The date at the top shows the latest version. If a change matters, we will say so in the app. Using Otto after a change means you accept it.'),
    s('contact', 'Contact', `Questions about these terms go to ${CONTACT_EMAIL}.`),
  ],
}

const PRIVACY: Legal = {
  slug: 'privacy',
  title: 'Privacy Policy',
  short: 'Privacy',
  intro: `This policy explains what Otto collects at ${SITES}, why, who else sees it, and what you can do about it. Otto is run by ${OPERATOR}, who is responsible for your data.`,
  sections: [
    s('collect', 'What we collect',
      'Your account: your email, your name, and a hash of your password (never the password itself).',
      'GitHub: your GitHub login and avatar, the GitHub App installations you connect, and the names of the repositories they give Otto.',
      'Your work: your chats, and each session\'s event log: the commands Otto ran, the diffs it made, their output, and its messages.',
      'Usage: token counts per day and per model, used for daily limits.',
      'Security logs: sign-ins, the device (browser) a sign-in came from, IP addresses for rate limits, and errors.'),
    s('use', 'How it\'s used',
      'To run your tasks and show you their history, to apply daily limits, to keep your account secure, and to keep the service working and fix it. We don\'t use your data for ads, and we don\'t sell it.'),
    s('ai', 'AI providers',
      'Your messages and the code context Otto reads are sent to the AI model you pick, through OpenRouter or OpenAI, to generate responses. They process it under their own terms and privacy policies. Don\'t put secrets you can\'t share with them in a chat or a repository you connect.'),
    s('github', 'GitHub access',
      'Otto uses a GitHub App that you install. It only sees the repositories you select for it. It pushes to its own branch, and opens a pull request only when you approve it. You can change which repositories it sees, or uninstall it, on GitHub at any time.'),
    s('hosting', 'Hosting providers',
      'Otto runs on infrastructure from Vercel (the web app), AWS and Cloudflare (servers and networking), and on personal hardware (the sandboxes). They process data only to provide those services.'),
    s('retention', 'Retention and deletion',
      'Chats are kept until you delete them or your account. A sandbox and its files are removed when its task ends or goes idle.',
      'Deleting your account deactivates it immediately. Its data is permanently deleted, or anonymized, within 30 days. Security logs may be kept a little longer when needed to stop abuse.'),
    s('selling', 'No selling of data', 'We never sell or rent your personal data, and we don\'t share it except as this policy describes or when the law requires it.'),
    s('cookies', 'Cookies',
      'Otto uses only essential cookies: one that keeps you signed in, and short-lived ones that protect GitHub sign-in. No analytics or advertising cookies. Your theme choice is kept in your browser\'s local storage.'),
    s('choices', 'Your choices',
      `In Settings you can rename or delete chats, disconnect GitHub, change models, and delete your account. Email ${CONTACT_EMAIL} to get a copy of your data or to correct it.`),
    s('contact', 'Contact', `Write to ${CONTACT_EMAIL} about anything in this policy.`),
  ],
}

const AUP: Legal = {
  slug: 'acceptable-use',
  title: 'Acceptable Use Policy',
  short: 'Acceptable use',
  intro: `Otto gives you a real machine to run code on, at ${SITES}. Use it for real software work on your own repositories. This policy is part of the Terms of Service.`,
  sections: [
    s('malware', 'No malware', 'Don\'t use Otto to write, run, test or spread malware, ransomware, or any code meant to harm systems, data or people.'),
    s('attacks', 'No attacks or scanning',
      'Don\'t use sandboxes to scan, probe, attack or overload other systems, to break into accounts, or to get around anyone\'s security. That includes the sandbox itself and the systems Otto runs on.'),
    s('sandboxes', 'No abusing the sandboxes',
      'No cryptocurrency mining, no proxies or VPNs, no spam or bulk email, no long-running servers, and no compute unrelated to the repository you\'re working on.'),
    s('illegal', 'Nothing illegal', 'Don\'t use Otto for anything illegal, or to create or store content that is illegal or infringes someone else\'s rights.'),
    s('limits', 'No circumventing limits', 'Don\'t get around daily limits, rate limits or invite-only sign-ups, for example with several accounts or by automating the app.'),
    s('repos', 'Only repositories you may work on', 'Only connect repositories you own, or have permission to change. Don\'t use Otto on other people\'s repositories without their permission.'),
    s('enforcement', 'Enforcement', 'We may stop a task, delete a sandbox, suspend or close an account, or report activity to the authorities when this policy is broken.'),
    s('contact', 'Contact', `Report abuse, or ask about this policy, at ${CONTACT_EMAIL}.`),
  ],
}

export const LEGAL: Record<LegalDoc, Legal> = { terms: TERMS, privacy: PRIVACY, 'acceptable-use': AUP }
export const LEGAL_DOCS: Legal[] = [TERMS, PRIVACY, AUP]

/** "October 7, 2026" from "2026-10-07" (the build date), in UTC. */
export function longDate(iso: string): string {
  return new Date(`${iso}T00:00:00Z`).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric', timeZone: 'UTC' })
}

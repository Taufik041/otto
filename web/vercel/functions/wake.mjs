// The landing project's Vercel function, POST /api/wake (scripts/vercel-output.mjs packages it
// with wake.mjs and node.mjs). Its env, set on the landing project: RESEND_API_KEY (the
// "otto-landing" sending key), OTTO_NOTIFY_TO, EMAIL_FROM.
import { clientIp, toRequest, writeResponse } from './node.mjs'
import { handleWake, resendSend } from './wake.mjs'

export default async function handler(req, res) {
  const env = process.env
  const response = await handleWake(await toRequest(req), {
    env,
    send: (payload) => resendSend(payload, env.RESEND_API_KEY),
    ip: clientIp(req),
  })
  await writeResponse(res, response)
}

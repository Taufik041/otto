import type { IncomingMessage, ServerResponse } from 'node:http'
export function toRequest(req: IncomingMessage): Promise<Request>
export function clientIp(req: IncomingMessage): string
export function writeResponse(res: ServerResponse, response: Response): Promise<void>

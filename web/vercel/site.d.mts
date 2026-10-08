import type { Plugin } from 'vite'

export type Site = 'app' | 'landing'
export const APP_ROUTES: string[]
export function isAppRoute(path: string): boolean
export const ASSETS: string
export const IMMUTABLE: string
export const REVALIDATE: string
export function inlineScriptHashes(html: string): string[]
export function apiOrigins(apiUrl: string): [string, string]
export function securityHeaders(o: { apiUrl: string; scriptHashes: string[] }): Record<string, string>
export function fallback(site: Site, path: string): { file: string | null; status: number }
export function vercelConfig(site: Site, o: { apiUrl: string; scriptHashes: string[] }): { version: 3; routes: Record<string, unknown>[] }
export function previewPlugin(site: Site, apiUrl: string): Plugin

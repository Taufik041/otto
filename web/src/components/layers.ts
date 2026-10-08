/**
 * The app's stacking order, in one place. Menus and dialogs are portalled to <body>, so they must
 * sit above every layer they can open over: the sidebar (and, on phones, its drawer and scrim).
 * A menu at z-50 under the sidebar's z-80 was painted behind it: the profile menu "did nothing".
 */
export const LAYER = {
  scrim: 79, // the drawer's backdrop
  sidebar: 80, // the sidebar, or the drawer on phones
  menu: 90, // dropdown menus (profile, chat rows, the chat's "⋯")
  dialog: 100, // dialogs and their backdrop
} as const

/** The chat's top bar and the workspace panel's header: one height, so their hairlines line up. */
export const HEADER_HEIGHT = 56

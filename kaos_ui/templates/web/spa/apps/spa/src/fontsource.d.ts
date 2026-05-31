// The UI package exports `./fonts` as source (`packages/ui/src/fonts.ts`),
// so this app's tsc compiles those side-effect font imports directly and
// needs the same ambient module shim the UI package declares. @fontsource
// ships CSS only; a bare declaration satisfies TypeScript 6's TS2882.
declare module "@fontsource-variable/inter";
declare module "@fontsource-variable/source-serif-4";

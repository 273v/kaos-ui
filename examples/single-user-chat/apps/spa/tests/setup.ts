import "@testing-library/jest-dom/vitest";

// happy-dom doesn't ship matchMedia / ResizeObserver — most component
// libraries assume they exist.

if (!globalThis.matchMedia) {
  globalThis.matchMedia = () =>
    ({
      matches: false,
      media: "",
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }) as unknown as MediaQueryList;
}

if (!globalThis.ResizeObserver) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

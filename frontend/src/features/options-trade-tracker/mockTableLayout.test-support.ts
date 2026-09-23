import { afterAll, vi } from 'vitest'

// jsdom has no layout engine. Give the real virtualizer a viewport and row sizes;
// browser verification covers resizing, scrolling geometry, and native focus.
export function mockTableLayout() {
  const originalScrollTo = HTMLElement.prototype.scrollTo
  const originalWindowScrollTo = window.scrollTo
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  )
  vi.spyOn(HTMLElement.prototype, 'offsetHeight', 'get').mockImplementation(
    function (this: HTMLElement) {
      return this.getAttribute('aria-label') === 'Trades table' ? 650 : 0
    },
  )
  vi.spyOn(HTMLElement.prototype, 'offsetWidth', 'get').mockReturnValue(1200)
  vi.spyOn(HTMLElement.prototype, 'clientHeight', 'get').mockReturnValue(650)
  vi.spyOn(HTMLElement.prototype, 'scrollHeight', 'get').mockImplementation(
    function (this: HTMLElement) {
      return Math.max(
        650,
        (Number(
          this.querySelector('table')?.getAttribute('aria-rowcount') ?? 2,
        ) -
          2) *
          55 +
          85,
      )
    },
  )
  vi.spyOn(Element.prototype, 'getBoundingClientRect').mockImplementation(
    function (this: HTMLElement) {
      const height = this.hasAttribute('data-trade-row-id')
        ? 55
        : this.tagName === 'THEAD'
          ? 45
          : 0
      const top = -window.scrollY
      return {
        x: 0,
        y: top,
        width: 1200,
        height,
        top,
        right: 1200,
        bottom: top + height,
        left: 0,
        toJSON() {},
      }
    },
  )
  HTMLElement.prototype.scrollTo = function (
    options: ScrollToOptions | number = {},
    y?: number,
  ) {
    const next =
      typeof options === 'number' ? (y ?? 0) : (options.top ?? this.scrollTop)
    if (this.scrollTop === next) return
    this.scrollTop = next
    queueMicrotask(() => {
      if (this.isConnected) this.dispatchEvent(new Event('scroll'))
    })
  }
  window.scrollTo = ((options: ScrollToOptions | number = {}, y?: number) => {
    scrollPage(typeof options === 'number' ? (y ?? 0) : (options.top ?? window.scrollY))
  }) as typeof window.scrollTo
  afterAll(() => {
    window.scrollTo = originalWindowScrollTo
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    HTMLElement.prototype.scrollTo = originalScrollTo
  })
}

// The trades table virtualizes against the page scroll.
export function scrollPage(top: number) {
  if (window.scrollY === top) return
  Object.defineProperty(window, 'scrollY', { configurable: true, value: top })
  window.dispatchEvent(new Event('scroll'))
}

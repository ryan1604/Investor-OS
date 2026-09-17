import { afterAll, vi } from 'vitest'

// jsdom has no layout engine. Give the real virtualizer a viewport and row sizes;
// browser verification covers resizing, scrolling geometry, and native focus.
export function mockTableLayout() {
  const originalScrollTo = HTMLElement.prototype.scrollTo
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
      return {
        x: 0,
        y: 0,
        width: 1200,
        height,
        top: 0,
        right: 1200,
        bottom: height,
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
  afterAll(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
    HTMLElement.prototype.scrollTo = originalScrollTo
  })
}

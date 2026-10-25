// happy-dom 不做真实布局，getBoundingClientRect/getClientRects 恒为零尺寸，
// 会被分析器的可见性判断全部过滤掉。这里统一补一个非零矩形。
const rect: DOMRect = {
  x: 0,
  y: 0,
  top: 0,
  left: 0,
  right: 200,
  bottom: 40,
  width: 200,
  height: 40,
  toJSON: () => ({}),
} as DOMRect;

const rectList: DOMRectList = {
  length: 1,
  item: () => rect,
  [Symbol.iterator]: function* iterate() {
    yield rect;
  },
} as unknown as DOMRectList;

for (const prototype of [Element.prototype, HTMLElement.prototype]) {
  Object.defineProperty(prototype, "getBoundingClientRect", { configurable: true, value: () => rect });
  Object.defineProperty(prototype, "getClientRects", { configurable: true, value: () => rectList });
}

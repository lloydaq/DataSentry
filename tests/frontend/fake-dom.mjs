// A deliberately small DOM stand-in for unit-testing frontend/app.js under Node without a
// browser or a dependency. It mirrors the browser behaviours the tests rely on, including the
// one that caused the "null" text bug: Element.append() turns any non-Node value into a text
// node via String(value).

export class Node {
  constructor() {
    this.childNodes = [];
    this.parentNode = null;
  }

  append(...items) {
    for (const item of items) {
      const node = item instanceof Node ? item : new Text(String(item));
      node.parentNode = this;
      this.childNodes.push(node);
    }
  }

  replaceChildren(...items) {
    this.childNodes = [];
    this.append(...items);
  }

  get textContent() {
    return this.childNodes.map((n) => n.textContent).join("");
  }

  set textContent(value) {
    this.childNodes = [];
    if (value !== null && value !== undefined && value !== "") this.append(String(value));
  }

  // Every node in the subtree (depth first), excluding this one.
  *descendants() {
    for (const child of this.childNodes) {
      yield child;
      yield* child.descendants();
    }
  }
}

export class Text extends Node {
  constructor(data) {
    super();
    this.data = data;
  }

  get textContent() {
    return this.data;
  }

  set textContent(value) {
    this.data = String(value);
  }
}

export class Element extends Node {
  constructor(tagName, namespaceURI = null) {
    super();
    this.tagName = tagName.toUpperCase();
    this.namespaceURI = namespaceURI;
    this.attributes = new Map();
    this.listeners = new Map();
    this.style = {};
    this.dataset = {};
    this.className = "";
    this.hidden = false;
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.has(name) ? this.attributes.get(name) : null;
  }

  addEventListener(type, handler) {
    if (!this.listeners.has(type)) this.listeners.set(type, []);
    this.listeners.get(type).push(handler);
  }

  dispatch(type, event = {}) {
    for (const handler of this.listeners.get(type) || []) handler(event);
  }

  get children() {
    return this.childNodes.filter((n) => n instanceof Element);
  }
}

export function createDocument() {
  const byId = new Map();
  return {
    documentElement: new Element("html"),
    createElement: (tag) => new Element(tag),
    createElementNS: (ns, tag) => new Element(tag, ns),
    createTextNode: (data) => new Text(String(data)),
    getElementById: (id) => byId.get(id) || null,
    querySelector: () => null,
    querySelectorAll: () => [],
    addEventListener: () => {},
    // Test hook: register an element so $(id) finds it.
    register(id, element = new Element("div")) {
      byId.set(id, element);
      return element;
    },
  };
}

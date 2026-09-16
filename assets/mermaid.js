/* Render the mermaid fences, and let a diagram be opened full screen.
 *
 * The theme ships mermaid's *colour variables* and not mermaid itself, and it
 * claims the `mermaid` class and empties what carries it, so every `graph TD`
 * on the flavours page reached the browser as an empty div. The fences use
 * `awl-mermaid` for that reason; see the custom_fences note in zensical.toml.
 *
 * Pinned to the major the diagrams are generated against, so a breaking release
 * cannot silently stop rendering a page that is built from a macro.
 *
 * Full screen is not decoration. A flavour of the `ast` profile draws 54 nodes,
 * and at the width a documentation page gives it that is a grey mat.
 */
/* Imported dynamically, because the theme emits a plain `<script src>` and a
 * top-level `import` in a classic script is a syntax error: the file would be
 * fetched, rejected before its first line ran, and the page would look exactly
 * as it does with no script at all. */
const loading = import("https://cdn.jsdelivr.net/npm/mermaid@11/dist/mermaid.esm.min.mjs").then(
  (module) => {
    const mermaid = module.default
    /* Mermaid picks its palette once, at init, so the scheme has to be read
     * before rendering rather than corrected after. */
    mermaid.initialize({
      startOnLoad: false,
      theme: document.body.dataset.mdColorScheme === "slate" ? "dark" : "default",
      securityLevel: "strict",
      flowchart: { useMaxWidth: true, htmlLabels: true },
    })
    return mermaid
  },
)

/* The button is added to a wrapper and not to the diagram, because mermaid
 * replaces the fence's contents with the SVG it renders and would take any
 * child of it with them. */
function wrap(node) {
  if (node.parentElement && node.parentElement.classList.contains("awl-diagram")) {
    return node.parentElement
  }
  /* Kept before anything renders. The fence is a `<pre><code>`, and the
   * diagram's own text is the only thing that reliably says what to draw:
   * letting mermaid read the element gave it the wrapper, and on a second pass
   * it read back the stylesheet mermaid itself had just injected. */
  node.dataset.awlSource = node.textContent

  const holder = document.createElement("div")
  holder.className = "awl-diagram"
  node.parentNode.insertBefore(holder, node)
  holder.appendChild(node)

  const button = document.createElement("button")
  button.type = "button"
  button.className = "awl-diagram__full"
  button.title = "Show this diagram full screen"
  button.setAttribute("aria-label", "Show this diagram full screen")
  button.textContent = "Full screen"
  button.addEventListener("click", () => {
    if (document.fullscreenElement === holder) {
      document.exitFullscreen()
    } else {
      holder.requestFullscreen().catch(() => {
        /* Refused (an iframe without the permission, or a browser that does not
         * offer it). The class alone still fills the viewport, so the button
         * does something rather than nothing. */
        holder.classList.add("awl-diagram--filling")
      })
    }
  })
  holder.appendChild(button)
  return holder
}

document.addEventListener("fullscreenchange", () => {
  for (const holder of document.querySelectorAll(".awl-diagram")) {
    const open = document.fullscreenElement === holder
    holder.classList.toggle("awl-diagram--open", open)
    const button = holder.querySelector(".awl-diagram__full")
    if (button) button.textContent = open ? "Close" : "Full screen"
  }
})

/* Escape leaves a fallback fill, which no browser reports as a fullscreenchange. */
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    for (const holder of document.querySelectorAll(".awl-diagram--filling")) {
      holder.classList.remove("awl-diagram--filling")
    }
  }
})

/* Only what is on screen. Mermaid measures the container, so a fence in an
 * unselected tab renders to an SVG with no size and keeps that size once the
 * tab is shown: rendering all ten at once produced ten diagrams and not one
 * visible pixel. */
const shown = (node) => node.getBoundingClientRect().width > 0

async function render() {
  const pending = [...document.querySelectorAll(".awl-mermaid")].filter(
    (node) => !node.dataset.awlRendered && shown(node),
  )
  if (!pending.length) return
  for (const node of pending) {
    node.dataset.awlRendered = "1"
    wrap(node)
  }
  /* Rendered from the captured text rather than from the element, so this is
   * idempotent: running it twice over the same fence draws the same diagram
   * instead of trying to parse the last one's output. */
  const mermaid = await loading
  for (const node of pending) {
    try {
      const { svg, bindFunctions } = await mermaid.render(`awl-diagram-${count++}`, node.dataset.awlSource)
      node.innerHTML = svg
      if (bindFunctions) bindFunctions(node)
    } catch (failure) {
      /* Left as the text it was, which is readable, rather than replaced by
       * mermaid's error card, which is not. */
      node.dataset.awlRendered = ""
      console.warn("awl: a diagram did not render", failure)
    }
  }
}

let count = 0

/* A fence inside an unselected tab has no size, and mermaid measures the
 * container: rendering it then produces an SVG a pixel wide that stays that way
 * once the tab is shown. Every diagram here lives in a tab, so this waits for
 * the tab rather than rendering into a hidden box.
 */
function whenShown() {
  const seen = new IntersectionObserver((entries) => {
    if (entries.some((entry) => entry.isIntersecting)) render()
  })
  for (const node of document.querySelectorAll(".awl-mermaid")) seen.observe(node)
  for (const input of document.querySelectorAll(".tabbed-set input")) {
    input.addEventListener("change", () => requestAnimationFrame(render))
  }
  render()
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", whenShown)
} else {
  whenShown()
}

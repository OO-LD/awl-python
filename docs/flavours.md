# Flavours

One procedure, shown under every setting the document generator takes, from the
smallest useful representation to the one a query is run against. Each section
ends with a question, the SPARQL that asks it, and the answer that flavour
gives. The answers are computed when this page is built, so a query that stops
working stops appearing here as though it still did.

A **profile** is a name for a set of those settings: which wrappers are
transparent, which types go opaque, whether keywords fold, and which lookups
run. The `ast` profile asks for everything below. RDF is not a second
derivation of the source; it is the same document in another notation, so the
two tabs on the right of each section always say the same thing.

The `@context` is identical in every flavour and is left out of the JSON tabs,
where it would bury the part that differs.

{{ shared_context() }}

## One lookup at a time

{{ single_flavours() }}

## Combined

Each of these adds to the one before it, ending with what the `ast` profile
produces. Spans are on throughout: a span is what joins a step to the statement
it came from, so without one the layers sit in the same graph and touch
nowhere.

{{ combined_flavours() }}

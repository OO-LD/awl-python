"""AWL-LD: a semantic graph derived from Python syntax trees.

The entry point is :mod:`awl.pipeline`, which composes the stages. Everything
it composes is a total function over plain data, so any stage can be used on
its own::

    from awl import pipeline

    doc = pipeline.to_compact(source, module="battery.procedure")
    graph = pipeline.to_graph(source, module="battery.procedure")
"""

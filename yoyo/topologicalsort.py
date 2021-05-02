from collections import defaultdict
from typing import Any
from typing import Callable
from typing import Iterable


class CycleError(ValueError):
    """
    Raised when cycles exist in the input graph.

    The second element in the args attribute of instances will contain the
    sequence of nodes in which the cycle lies.
    """


def gapotchenko_topological_sort(
    iterable: Iterable[Any],
    is_arrow: Callable[[Any, Any], bool],
    *,
    raise_on_cycle: bool = False
):
    """
    Implement the Gapotchenko stable topological sort algorithm
    (http://blog.gapotchenko.com/stable-topological-sort).
    The algorithm has been optimised and can optionally raise on cycles

    :param iterable: an ordered iterable of vertices
    :param is_arrow: a callable(v1, v2) that returns True if there is an arrow
                     from v1 to v2
    :param raise_on_cycle: If true, raise a CycleError if a circular dependency
                           if found.
    """
    vertices = list(iterable)
    tc = transitive_closure(vertices, is_arrow)

    while True:
        for i, vi in enumerate(vertices):
            for j, vj in enumerate(vertices[:i]):
                if is_arrow(vj, vi):
                    if vj not in tc[vi]:
                        # vj is not in the transitive closure of vi --> no cycle
                        del vertices[i]
                        vertices.insert(j, vi)
                        break  # restart
                    # it is a cycle
                    if raise_on_cycle:
                        raise CycleError(
                            "Input graph contains a cycle",
                            [v for v in vertices if v in tc[vi]],
                        )
            else:
                if raise_on_cycle and is_arrow(vi, vi):
                    raise CycleError("Input graph contains a cycle", [vi])
                continue
            break
        else:
            return vertices


def child_vertices(vs, is_arrow, v):
    return (v_ for v_ in vs if is_arrow(v, v_))


def transitive_closure(vs, is_arrow):
    """
    Compute the transitive closure of a graph

    :param vs: set of graph vertices
    :param is_arrow: callable(v1, v2) that returns True if there is an edge
                     linking v1 to v2
    """
    reachable = defaultdict(set)
    for start_vertex in vs:
        stack = [start_vertex]
        while stack:
            v = stack.pop()
            reachable[start_vertex].add(v)
            for v_ in child_vertices(vs, is_arrow, v):
                if v_ not in reachable[start_vertex]:
                    stack.append(v_)
    return reachable

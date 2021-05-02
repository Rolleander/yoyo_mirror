from collections import defaultdict
from typing import Any
from typing import Callable
from typing import Iterable

from yoyo import exceptions


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
    """
    vertices = list(iterable)

    # compute the transitive closure (= reach-ability)
    # using a recursive depth first search (DFS)
    tc = defaultdict(set)

    def dfs(s, v):
        # Mark reachability from start to v as true.
        s.add(id(v))
        # Find all the vertices reachable through v
        for vv in vertices:
            if id(vv) not in s and is_arrow(v, vv):
                dfs(s, vv)

    for v in vertices:
        dfs(tc[id(v)], v)

    # And now the algorithm given by Oleksiy Gapotchenko
    while True:
        for i, vi in enumerate(vertices):
            for j in range(i):
                vj = vertices[j]
                if is_arrow(vj, vi):
                    if id(vj) not in tc[id(vi)]:
                        # vj is not in the transitive closure of vi --> no cycle
                        del vertices[i]
                        vertices.insert(j, vi)
                        break  # restart
                    # it is a cycle
                    if raise_on_cycle:
                        # raise ValueError("graph contains a cycle", vi)
                        raise exceptions.BadMigration(
                            "Circular dependencies among these migrations {}".format(
                                ", ".join(m.id for m in vertices if id(m) in tc[id(vi)])
                            )
                        )
            else:
                if raise_on_cycle and is_arrow(vi, vi):
                    # a degenerate cycle
                    raise exceptions.BadMigration(
                        "Circular dependencies among these migrations {}".format(vi.id)
                    )
                continue
            break
        else:
            return vertices

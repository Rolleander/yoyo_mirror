from typing import Set
from typing import Dict
from typing import Mapping
from typing import TypeVar
from typing import Iterable
from typing import Collection
from collections import defaultdict
from heapq import heappop
from heapq import heappush


class CycleError(ValueError):
    """
    Raised when cycles exist in the input graph.

    The second element in the args attribute of instances will contain the
    sequence of nodes in which the cycle lies.
    """


T = TypeVar("T")


def topological_sort(
    items: Iterable[T], dependency_graph: Mapping[T, Collection[T]]
) -> Iterable[T]:

    # Tag each item with its input order
    pqueue = list(enumerate(items))
    ordering = {item: ix for ix, item in pqueue}
    seen_since_last_change = 0
    output: Set[T] = set()

    # Map blockers to the list of items they block
    blocked_on: Dict[T, Set[T]] = defaultdict(set)
    while pqueue:
        if seen_since_last_change == len(pqueue):
            raise_cycle_error(ordering, pqueue, blocked_on)

        _, n = heappop(pqueue)

        if all(d in output for d in dependency_graph.get(n, [])):
            changed = True
            output.add(n)
            yield n
            for blocked in blocked_on.pop(n, []):
                heappush(pqueue, (ordering[blocked], blocked))
        else:
            changed = False
            for d in dependency_graph.get(n, []):
                if n not in blocked_on[d]:
                    blocked_on[d].add(n)
                    changed = True
        if changed:
            seen_since_last_change = 0
        else:
            seen_since_last_change += 1

    if blocked_on:
        raise_cycle_error(ordering, pqueue, blocked_on)


def raise_cycle_error(ordering, pqueue, blocked_on):
    bad = next((item for item in blocked_on if item not in ordering), None)
    if bad:
        raise ValueError(f"Dependency graph contains a non-existent node {bad!r}")
    unresolved = {n for _, n in pqueue}
    unresolved.update(*blocked_on.values())
    if unresolved:
        raise CycleError(
            f"Dependency graph loop detected among {unresolved!r}",
            list(sorted(unresolved, key=ordering.get)),
        )

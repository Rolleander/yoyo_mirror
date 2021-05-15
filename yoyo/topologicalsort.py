from typing import Set
from typing import Dict
from typing import Mapping
from typing import TypeVar
from typing import Iterable
from typing import Collection
from collections import defaultdict


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

    seen_since_last_change = 0
    stack = list(reversed(list(items)))
    output: Set[T] = set()
    blocked_on: Dict[T, Set[T]] = defaultdict(set)
    while stack:
        if seen_since_last_change == len(stack):
            for item in blocked_on:
                if item not in stack:
                    raise ValueError(
                        f"Dependency graph contains a non-existent node {item!r}"
                    )
            raise CycleError("Dependency graph loop detected", stack)
        n = stack.pop()
        if all(d in output for d in dependency_graph.get(n, [])):
            changed = True
            output.add(n)
            yield n
            for blocked in blocked_on[n]:
                stack.append(blocked)
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

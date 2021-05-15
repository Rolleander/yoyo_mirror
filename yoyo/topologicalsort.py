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

    seen_since_last_output = 0
    stack = list(reversed(list(items)))
    output: Set[T] = set()
    blocked_on: Dict[T, Set[T]] = defaultdict(set)
    while stack:
        if seen_since_last_output == len(stack):
            raise CycleError("Dependency graph loop detected", stack)
        n = stack.pop()
        if all(d in output for d in dependency_graph.get(n, [])):
            seen_since_last_output = 0
            output.add(n)
            yield n
            for blocked in blocked_on[n]:
                stack.append(blocked)
        else:
            seen_since_last_output += 1
            for d in dependency_graph.get(n, []):
                blocked_on[d].add(n)

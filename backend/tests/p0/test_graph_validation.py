import pytest

from services.graph_validation import GraphValidationError, prepare_graph, validate_graph


@pytest.fixture()
def valid_graph():
    return [
        {"key": "root", "label": "Root", "parent_keys": [], "estimated_minutes": 20},
        {"key": "b", "label": "B", "parent_keys": ["root"], "estimated_minutes": 30},
        {"key": "a", "label": "A", "parent_keys": ["root"], "estimated_minutes": 30},
        {"key": "c", "label": "C", "parent_keys": ["a"], "estimated_minutes": 40},
        {"key": "d", "label": "D", "parent_keys": ["a"], "estimated_minutes": 50},
        {"key": "e", "label": "E", "parent_keys": ["b"], "estimated_minutes": 60},
    ]


def test_valid_graph_uses_stable_topological_order_and_existing_layout(valid_graph):
    ordered = validate_graph(valid_graph)
    assert [node["key"] for node in ordered] == ["root", "b", "a", "c", "d", "e"]

    positioned = prepare_graph(valid_graph)
    assert all(node["x"] > 0 and node["y"] > 0 for node in positioned)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda graph: graph[:5], "GRAPH_NODE_COUNT"),
        (lambda graph: [*graph, {**graph[-1], "label": "Duplicate"}], "GRAPH_DUPLICATE_KEY"),
        (
            lambda graph: [
                *graph,
                {"key": "other-root", "label": "Other", "parent_keys": [], "estimated_minutes": 20},
            ],
            "GRAPH_ROOT_COUNT",
        ),
        (
            lambda graph: [{**graph[1], "parent_keys": ["missing"]}, *graph[2:], graph[0]],
            "GRAPH_PARENT_MISSING",
        ),
        (lambda graph: [{**graph[0], "parent_keys": ["root"]}, *graph[1:]], "GRAPH_SELF_REFERENCE"),
        (lambda graph: [graph[0], {**graph[1], "parent_keys": ["e"]}, *graph[2:]], "GRAPH_CYCLE"),
        (lambda graph: [{**graph[0], "estimated_minutes": 9}, *graph[1:]], "GRAPH_DURATION"),
    ],
)
def test_invalid_graphs_are_rejected(valid_graph, mutate, code):
    with pytest.raises(GraphValidationError) as error:
        validate_graph(mutate(valid_graph))
    assert error.value.code == code


def test_graph_rejects_multiple_parents(valid_graph):
    graph = [
        {**node, "parent_keys": ["a", "b"]} if node["key"] == "c" else node for node in valid_graph
    ]

    with pytest.raises(GraphValidationError) as error:
        validate_graph(graph)

    assert error.value.code == "GRAPH_TREE_PARENT_COUNT"


def test_graph_rejects_a_linear_tree(valid_graph):
    graph = [
        {"key": "root", "label": "Root", "parent_keys": [], "estimated_minutes": 20},
        *[
            {"key": key, "label": key.upper(), "parent_keys": [parent], "estimated_minutes": 20}
            for key, parent in zip(("a", "b", "c", "d", "e"), ("root", "a", "b", "c", "d"))
        ],
    ]

    with pytest.raises(GraphValidationError) as error:
        validate_graph(graph)

    assert error.value.code == "GRAPH_TREE_ROOT_BRANCHING"

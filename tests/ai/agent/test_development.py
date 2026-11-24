from tchekam.ai.agent.development import make_graph


def test_studio_graph_runs_without_database_or_network():
    result = make_graph().invoke({"run_id": 1})
    assert result["completed"]
    assert result["action"].kind == "results"
    assert len(result["replies"]) == 1


def test_outer_graph_exports_every_policy_and_terminal_path():
    graph = make_graph().get_graph()
    expected = {
        "__start__",
        "__end__",
        "claim_turn",
        "authorize_turn",
        "load_memory",
        "prepare_input",
        "transcribe_audio",
        "build_context",
        "before_agent",
        "agent",
        "validate_response_action",
        "render_response",
        "guard_out",
        "safe_fallback",
        "revalidate_turn",
        "persist_memory",
        "publish_delivery",
        "discard_turn",
    }
    assert set(graph.nodes) == expected
    edges = {(edge.source, edge.target) for edge in graph.edges}
    assert ("transcribe_audio", "safe_fallback") in edges
    assert ("revalidate_turn", "discard_turn") in edges
    assert ("persist_memory", "publish_delivery") in edges
    assert ("discard_turn", "__end__") in edges

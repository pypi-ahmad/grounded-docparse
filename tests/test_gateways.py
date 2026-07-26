from grounded_docparse.gateways import GlmOcrGateway
from grounded_docparse.models import NodeType


def test_glm_routes_region_prompts_by_type() -> None:
    assert GlmOcrGateway.prompt_for(NodeType.TABLE) == "Table Recognition:"
    assert GlmOcrGateway.prompt_for(NodeType.FORMULA) == "Formula Recognition:"
    assert GlmOcrGateway.prompt_for(NodeType.FIGURE) == "Figure Recognition:"
    assert GlmOcrGateway.prompt_for(NodeType.PARAGRAPH) == "Text Recognition:"

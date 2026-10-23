from core.ai_client import get_ai_client, resolve_llm_profile
from .prompts import GENERATE_NODES_PROMPT, build_generate_prompt
from .util import extract_json_from_markdown
import json


def generate_graph(topic: str, model_id: str | None = None) -> dict:
    """同步阻塞调用 LLM，为指定主题生成知识图谱节点结构，通常需要 5~15 秒。

    返回格式：{"nodes": [...]}，每个节点包含 key、label、sub、parent_keys 等字段。
    """
    profile = resolve_llm_profile(model_id)
    client = get_ai_client(model_id) if model_id else get_ai_client()
    response = client.chat.completions.create(
        model=profile.model,
        messages=[
            {"role": "system", "content": GENERATE_NODES_PROMPT},
            {"role": "user", "content": build_generate_prompt(topic)},
        ],
        max_tokens=2000,
        temperature=0.3,
    )
    return json.loads(extract_json_from_markdown(response.choices[0].message.content))


def assign_positions(nodes: list) -> list:
    """BFS 分层布局：根据父子关系将节点分配到不同层级，计算 SVG 画布的 x/y 坐标。

    布局规则：
    - 无父节点的节点作为根节点（第 0 层）
    - 子节点放在父节点的下一层，同层节点水平均分
    - 与其他节点完全无连接的孤立节点单独放在最后一层
    - 层间距和水平间距会根据总层数和最宽层自适应调整
    """
    children_map: dict = {}
    root_keys = []

    for n in nodes:
        parents = n.get("parent_keys", [])
        if not parents:
            root_keys.append(n["key"])
        for p in parents:
            children_map.setdefault(p, []).append(n["key"])

    # 没有根节点时兜底取第一个，避免 BFS 无法启动
    if not root_keys and nodes:
        root_keys = [nodes[0]["key"]]

    # BFS 分层，visited 集合去重，防止同一节点出现在多层
    layers: list = []
    visited = set(root_keys)
    current_layer = root_keys[:]

    while current_layer:
        layers.append(current_layer)
        next_layer = []
        for key in current_layer:
            for child in children_map.get(key, []):
                if child not in visited:
                    visited.add(child)
                    next_layer.append(child)
        current_layer = next_layer

    # 将未被 BFS 访问到的孤立节点追加到最后一层
    all_keys = {n["key"] for n in nodes}
    orphans = [k for k in all_keys if k not in visited]
    if orphans:
        layers.append(orphans)

    max_per_layer = max(len(layer) for layer in layers) if layers else 1
    total_layers = len(layers)

    # 根据节点数量自适应间距，防止节点过多时超出可视区
    node_w = 140
    h_gap = max(180, node_w * 1.4)
    v_gap = max(140, min(180, 800 // max(total_layers, 1)))

    margin = 100
    canvas_w = max(600, margin * 2 + (max_per_layer - 1) * h_gap)
    y_start = 120

    # 计算每个节点的坐标，同层节点水平居中分布
    positions = {}
    for i, layer in enumerate(layers):
        y = y_start + i * v_gap
        count = len(layer)

        if count == 1:
            x_list = [canvas_w / 2]
        else:
            total_width = (count - 1) * h_gap
            x_start = (canvas_w - total_width) / 2
            x_list = [x_start + j * h_gap for j in range(count)]

        for j, key in enumerate(layer):
            positions[key] = {"x": round(x_list[j]), "y": round(y)}

    # 将计算好的坐标写回节点对象
    key_map = {n["key"]: n for n in nodes}
    for key, pos in positions.items():
        if key in key_map:
            key_map[key]["x"] = pos["x"]
            key_map[key]["y"] = pos["y"]

    # 兜底：为极少数未分配坐标的节点补充位置，放在画布底部
    canvas_h = y_start + total_layers * v_gap + 100
    unpositioned = [n for n in nodes if "x" not in n or n.get("x") == 0]
    for i, n in enumerate(unpositioned):
        n["x"] = margin + i * h_gap
        n["y"] = canvas_h

    return nodes

def extract_json_from_markdown(text: str) -> str:
    """去掉 LLM 回复中常见的 ```json ... ``` 代码块外壳，返回纯 JSON 字符串。

    即使 system prompt 要求"只返回 JSON"，部分模型仍会偶发包裹代码块，
    直接 json.loads 会报错，统一在解析前先剥壳可避免每个调用点重复处理。
    """
    s = text.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    return s.strip()

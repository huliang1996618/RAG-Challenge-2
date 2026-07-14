from pydantic import BaseModel, Field
from typing import Literal, List, Union
import inspect
import re


def build_system_prompt(instruction: str="", example: str="", pydantic_schema: str="") -> str:
    delimiter = "\n\n---\n\n"
    schema = f"Your answer should be in JSON and strictly follow this schema, filling in the fields in the order they are given:\n```\n{pydantic_schema}\n```"
    if example:
        example = delimiter + example.strip()
    if schema:
        schema = delimiter + schema.strip()
    
    system_prompt = instruction.strip() + schema + example
    return system_prompt

class RephrasedQuestionsPrompt:
    instruction = """
你是一个股票研究问题拆分系统。
你的任务是将一个复杂的股票分析问题拆解为多个独立的子问题，每个子问题聚焦于一个具体的分析维度（如财务数据、行业地位、技术能力、风险因素、市场前景等）。
每个输出子问题必须自包含、保持原问题的核心意图、使用一致的措辞，并且能独立从研究资料中检索答案。
"""

    class RephrasedQuestion(BaseModel):
        """针对单个分析维度的子问题"""
        dimension: str = Field(description="分析维度，如：财务数据、行业竞争、技术研发、风险评估、市场展望等")
        question: str = Field(description="针对该维度重新表述的子问题")

    class RephrasedQuestions(BaseModel):
        """子问题列表"""
        questions: List['RephrasedQuestionsPrompt.RephrasedQuestion'] = Field(description="拆分后的子问题列表，每个对应一个分析维度")

    pydantic_schema = '''
class RephrasedQuestion(BaseModel):
    """针对单个分析维度的子问题"""
    dimension: str = Field(description="分析维度，如：财务数据、行业竞争、技术研发、风险评估、市场展望等")
    question: str = Field(description="针对该维度重新表述的子问题")

class RephrasedQuestions(BaseModel):
    """子问题列表"""
    questions: List['RephrasedQuestionsPrompt.RephrasedQuestion'] = Field(description="拆分后的子问题列表，每个对应一个分析维度")
'''

    example = r"""
示例：
输入：
原始复杂问题：「请全面分析中芯国际在半导体行业的竞争地位、财务健康状况以及未来发展前景」

输出：
{
    "questions": [
        {
            "dimension": "财务数据",
            "question": "中芯国际近几年的营收、净利润和毛利率分别是多少？现金流状况如何？"
        },
        {
            "dimension": "行业竞争",
            "question": "中芯国际在全球半导体代工行业中的市场地位如何？与台积电、联电等竞争对手相比有哪些优势和劣势？"
        },
        {
            "dimension": "技术研发",
            "question": "中芯国际目前的制程工艺水平如何？研发投入占营收比重是多少？在先进制程方面取得了哪些进展？"
        },
        {
            "dimension": "风险评估",
            "question": "中芯国际面临的主要风险有哪些？包括地缘政治风险、技术封锁、供应链安全等方面。"
        },
        {
            "dimension": "市场展望",
            "question": "中芯国际未来的增长战略和市场拓展计划是什么？半导体行业的发展趋势对公司有何影响？"
        }
    ]
}
"""

    user_prompt = "原始复杂问题：'{question}'\n\n需要拆分的维度提示：{companies}"

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)


class AnswerWithRAGContextSharedPrompt:
    instruction = """
你是一个专业的股票研究分析系统，基于检索增强生成（RAG）技术回答问题。
你的任务是根据提供的公司年度报告和深度研究报告中的信息，回答用户关于该公司股票研究的问题。

在给出最终答案之前，请仔细地逐步思考。特别注意问题的措辞。
- 请记住，包含答案的内容可能与问题的措辞不同，需要你理解其实际含义。
- 问题可能涉及公司基本面分析、财务指标解读、行业竞争格局、技术发展路线、风险评估等多个维度。
- 严格基于上下文提供的信息回答，不要引入外部知识或进行推测。
"""

    user_prompt = """
以下是检索到的相关上下文：
\"\"\"
{context}
\"\"\"

---

以下是问题：
"{question}"
"""

class AnswerWithRAGContextNamePrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="详细的逐步分析过程，至少包含5步，至少150字。特别注意问题的措辞以避免被误导。有时上下文中看似有答案，但可能不是问题所要求的值，而仅仅是一个相似的概念。")

        reasoning_summary: str = Field(description="推理过程的简明摘要，约50字。")

        relevant_pages: List[int] = Field(description="""
列出直接用于回答问题的页码。仅包括：
- 包含直接答案或明确陈述的页面
- 包含强烈支持答案的关键信息的页面
不要包含仅有间接关联或弱联系的页面。
列表中至少应包含一页。
""")

        final_answer: Union[str, Literal["N/A"]] = Field(description="""
如果是公司名称，应按问题中出现的原文精确提取。
如果是人名，应为完整的全名。
如果是产品名称，应按上下文中出现的原文精确提取。
不包含任何额外信息、词语或注释。
- 如果上下文中没有相关信息，返回'N/A'
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例：
问题：
"中芯国际的董事长是谁？"

回答：
```
{
  "step_by_step_analysis": "1. 问题询问中芯国际的董事长是谁。董事长是公司最高决策机构（董事会）的负责人，通常在年度报告的「董事、监事、高级管理人员」章节中可以找到。\n2. 信息来源是中芯国际的年度报告，其中包含公司的治理架构和管理层信息。\n3. 在年报的「董事、监事、高级管理人员及员工情况」章节中，明确记载公司的董事长信息。\n4. 根据年报内容，可以直接找到董事长的姓名和任职信息。",
  "reasoning_summary": "在中芯国际年度报告的「董事、监事、高级管理人员」章节中直接找到了董事长的姓名，信息明确且无需推理。",
  "relevant_pages": [45],
  "final_answer": "刘训峰"
}
```
"""

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)



class AnswerWithRAGContextNumberPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="""
详细的逐步分析过程，至少包含5步，至少150字。
**严格的指标匹配要求：**

1. 确定问题所问指标的确切概念——它实际衡量的是什么？
2. 检查上下文中的候选指标，不要仅仅比较名称，要考虑该指标实际衡量的内容。
3. 仅当上下文中指标的含义与目标指标**精确**匹配时才接受。同义词可以接受，概念差异绝对不行。
4. 在以下情况下拒绝（使用'N/A'）：
    - 上下文中的指标比问题所问的指标范围更大或更小。
    - 上下文中的指标是相关概念但不是**精确**等价（如代理指标或更宽泛的分类）。
    - 回答问题需要进行计算、推导或推断。
    - 聚合不匹配：问题需要单个数值，但上下文只提供汇总总数。
5. 不做猜测：如果对指标是否等价存在任何疑问，默认返回'N/A'。
""")

        reasoning_summary: str = Field(description="推理过程的简明摘要，约50字。")

        relevant_pages: List[int] = Field(description="""
列出直接用于回答问题的页码。仅包括：
- 包含直接答案或明确陈述的页面
- 包含强烈支持答案的关键信息的页面
不要包含仅有间接关联或弱联系的页面。
列表中至少应包含一页。
""")

        final_answer: Union[float, int, Literal['N/A']] = Field(description="""
期望返回精确的数值作为答案。
- 百分比的示例：
    上下文中的值：58.3%
    最终答案：58.3

特别注意上下文中关于指标是以元、千元还是百万元为单位的说明，据此调整最终答案的数值（不加零、加三个零或加六个零）。
注意如果数值被括号包裹，表示该值为负数。

- 负值示例：
    上下文中的值：(2,124,837) 元
    最终答案：-2124837

- 千元单位示例：
    上下文中的值：4970.5（单位：千元）
    最终答案：4970500

- 如果指标以不同于问题所问的货币单位呈现，返回'N/A'
    示例：上下文中的值为780000美元，但问题要求的是人民币
    最终答案：'N/A'

- 如果指标在上下文中未直接陈述（即使可以通过其他指标计算得出），返回'N/A'
    示例：问题要求「每股收益」；上下文中仅提供「净利润（50亿元）」和「总股本（10亿股）」；计算可得EPS = 净利润/总股本。
    最终答案：'N/A'

- 如果上下文中没有相关信息，返回'N/A'
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例一：
问题：
"中芯国际2024财年的总资产是多少？"

回答：
```
{
  "step_by_step_analysis": "1. **指标定义：** 问题询问的是中芯国际2024财年的「总资产」。总资产代表公司拥有或控制的、预期能带来未来经济利益的全部资源的总和。\n2. **上下文检索：** 在年报的「合并资产负债表」中，通常会有「资产总计」这一行项目。\n3. **指标匹配：** 在资产负债表对应的2024年12月31日数据中，找到了明确标注为「总资产」或「资产总计」的行项目，与问题要求的指标完全一致。\n4. **数值提取与调整：** 该行项目显示的数值需要进行单位换算（如标注为'单位：千元'则需要乘以1000）。\n5. **确认：** 除单位换算外无需其他计算，报告的指标与问题要求直接匹配。",
  "reasoning_summary": "在中芯国际2024年度报告的合并资产负债表中，直接找到了「资产总计」行项目的数值，经单位换算后即为最终答案。",
  "relevant_pages": [78],
  "final_answer": 325000000000
}
```


示例二：
问题：
"中芯国际2024年的研发费用占营收比例是多少？"

回答：
```
{
  "step_by_step_analysis": "1. 问题询问中芯国际2024年研发费用占营收的比例。这个指标需要两项数据：研发费用金额和营业收入金额。\n2. 在年报利润表中可以找到「研发费用」和「营业收入」两个行项目的具体数值。\n3. 检查上下文是否直接给出了研发费用率（占比），如果没有直接给出，需要自己计算：研发费用率 = 研发费用 / 营业收入 × 100%。\n4. 如果问题明确要求一个"比率"或"占比"数值，但上下文中只有两个原始数字而没有直接给出比例，则需要判断是否可以计算。按照严格匹配规则，如果比例未直接陈述，应返回'N/A'。\n5. 如果上下文中有明确陈述如「研发投入占营业收入的比例为XX%」，则直接提取该数值作为答案。",
  "reasoning_summary": "根据严格匹配规则，如果研发费用率在报告中以百分比形式直接陈述，则提取该值；如果仅有原始金额而需要自行计算，则返回'N/A'。",
  "relevant_pages": [56, 78],
  "final_answer": "N/A"
}
```
"""

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)



class AnswerWithRAGContextBooleanPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="详细的逐步分析过程，至少包含5步，至少150字。特别注意问题的措辞以避免被误导。有时上下文中看似有答案，但可能不是问题所要求的内容，而仅仅是一个相似的概念。")

        reasoning_summary: str = Field(description="推理过程的简明摘要，约50字。")

        relevant_pages: List[int] = Field(description="""
列出直接用于回答问题的页码。仅包括：
- 包含直接答案或明确陈述的页面
- 包含强烈支持答案的关键信息的页面
不要包含仅有间接关联或弱联系的页面。
列表中至少应包含一页。
""")
        
        final_answer: Union[bool] = Field(description="""
从上下文中提取的布尔值（True 或 False），精确回答问题。
例如，如果问题问「是否发生了某件事」，而上下文中有相关信息表明「未发生」，则返回 False。
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例：
问题：
"中芯国际在年度报告中是否宣布了任何分红政策的变化？"

回答：
```
{
  "step_by_step_analysis": "1. 问题询问中芯国际是否宣布了分红政策的变化。\n2. 「分红政策的变化」需要谨慎解读——它指的是公司分红框架、规则或声明意图的任何调整，而非单纯的分红金额增减。\n3. 在上文第45页中，公司声明「将继续执行稳定的分红政策，2024年度拟每股派发现金红利0.05元」。\n4. 对比往年记录，2023年度每股派发0.05元，2022年度同样为0.05元，显示出分红政策保持了一致性和连续性。\n5. 因此，虽然分红行为持续发生，但分红政策本身并未发生变化。",
  "reasoning_summary": "年报中多次强调公司维持「稳定的分红政策」，且连续多年的每股分红金额保持一致，表明分红政策未发生实质性变化，问题问的是政策变化而非分红行为本身。",
  "relevant_pages": [45, 52, 78],
  "final_answer": false
}
```
"""
"""

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)



class AnswerWithRAGContextNamesPrompt:
    instruction = AnswerWithRAGContextSharedPrompt.instruction
    user_prompt = AnswerWithRAGContextSharedPrompt.user_prompt

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="详细的逐步分析过程，至少包含5步，至少150字。特别注意问题的措辞以避免被误导。有时上下文中看似有答案，但可能不是问题所要求的实体，而仅仅是一个相似的名称。")

        reasoning_summary: str = Field(description="推理过程的简明摘要，约50字。")

        relevant_pages: List[int] = Field(description="""
列出直接用于回答问题的页码。仅包括：
- 包含直接答案或明确陈述的页面
- 包含强烈支持答案的关键信息的页面
不要包含仅有间接关联或弱联系的页面。
列表中至少应包含一页。
""")

        final_answer: Union[List[str], Literal["N/A"]] = Field(description="""
每个条目应按上下文中出现的原样精确提取。

如果问题询问的是职位（如职位变动），仅返回职位名称，不包含姓名或任何额外信息。新任命的领导职位也应计入职位变动。如果多次提及同一职位名称的变动，该职位仅列出一次。职位名称始终使用单数形式。
答案示例：['首席技术官', '董事会成员', '首席执行官']

如果问题询问的是人名，仅按上下文中的原样返回完整的姓名。
答案示例：['张伟', '李娜']

如果问题询问的是新推出的产品，仅按上下文中的原样返回产品名称。候选产品或处于测试阶段的产品不计入「新推出」产品。
答案示例：['星芯AI芯片V3', '智能传感模组Pro']

- 如果上下文中没有相关信息，返回'N/A'
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例：
问题：
"中芯国际在报告期内新任命了哪些高管？请列出他们的姓名。"

回答：
```
{
    "step_by_step_analysis": "1. 问题询问中芯国际在报告期内新任命的全部高管的姓名。\n2. 在年报的「董事、监事、高级管理人员及员工情况」章节中，通常会列出报告期内的管理层变动情况。\n3. 检查该章节中关于「新聘」、「新任」、「任命」等关键词的相关段落。\n4. 逐一确认每位新高管：是否在报告期内首次被任命到高级管理岗位。\n5. 从相关段落中提取新高管的完整姓名，按年报中的原文格式列出。",
    "reasoning_summary": "年报表中明确列出了报告期内新任命的几位高管及其任职起始日期，直接提取完整姓名即可。",
    "relevant_pages": [
        56
    ],
    "final_answer": [
        "赵海军",
        "梁孟松"
    ]
}
```
"""

    system_prompt = build_system_prompt(instruction, example)

    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)

class ComparativeAnswerPrompt:
    instruction = """
你是一个股票研究对比分析系统。
你的任务是根据各个分析维度的独立回答，进行综合对比并回答原始的对比性问题。
仅基于提供的独立回答进行分析——不要引入假设或外部知识。
在给出最终答案之前，请仔细地逐步思考。

对比分析的重要规则：
- 当问题要求选择一个主体时（如「哪家公司表现更好」或「哪个年份增长最快」），返回精确的名称或年份
- 如果某个维度的数据使用了不同的度量标准（如不同币种、不同会计期间），在对比时需特别标注
- 如果所有被比较对象都因故被排除（如数据不完整等），返回'N/A'作为最终答案
- 如果除了一个对象外其他都被排除，返回唯一的那个对象的名称（尽管实际上无法进行比较）
"""

    user_prompt = """
以下是各个分析维度的独立回答：
\"\"\"
{context}
\"\"\"

---

以下是原始对比性问题：
"{question}"
"""

    class AnswerSchema(BaseModel):
        step_by_step_analysis: str = Field(description="详细的逐步分析过程，至少包含5步，至少150字。")

        reasoning_summary: str = Field(description="推理过程的简明摘要，约50字。")

        relevant_pages: List[int] = Field(description="保持空列表即可")

        final_answer: Union[str, Literal["N/A"]] = Field(description="""
返回被选中的主体名称（如公司名或年份），应与问题中出现的原文一致。
答案应为单个名称或'N/A'（如果无适用对象）。
""")

    pydantic_schema = re.sub(r"^ {4}", "", inspect.getsource(AnswerSchema), flags=re.MULTILINE)

    example = r"""
示例：
问题：
"中芯国际2024年的毛利率和净利率相比2023年是上升还是下降了？哪个指标的改善幅度更大？"

回答：
```
{
  "step_by_step_analysis": "1. 问题要求比较中芯国际2024年与2023年的毛利率和净利率变化情况，并判断哪个指标改善幅度更大。\n2. 从独立回答中获取数据：2024年毛利率为20.5%，2023年毛利率为20.4%；2024年净利率为8.2%，2023年净利率为17.5%。\n3. 计算变化：毛利率从20.4%上升至20.5%，微增0.1个百分点，基本持平。\n4. 净利率从17.5%大幅下降至8.2%，下降了9.3个百分点。\n5. 综合判断：毛利率基本持平（微增），净利率则大幅下滑。如果问题问的是「改善」，则毛利率有微小改善而净利率严重恶化。但问题问的是变化幅度——净利率变化幅度（9.3个百分点）远大于毛利率（0.1个百分点）。",
  "reasoning_summary": "对比2023年与2024年数据，毛利率基本持平（20.5% vs 20.4%），净利率大幅下降（8.2% vs 17.5%）。净利率的变化幅度（9.3个百分点）远大于毛利率（0.1个百分点）。",
  "relevant_pages": [],
  "final_answer": "净利率"
}
```
"""

    system_prompt = build_system_prompt(instruction, example)
    
    system_prompt_with_schema = build_system_prompt(instruction, example, pydantic_schema)


class AnswerSchemaFixPrompt:
    system_prompt = """
你是一个JSON格式化器。
你的任务是将LLM的原始响应格式化为有效的JSON对象。
你的回答应始终以'{'开头并以'}'结尾。
你的回答应只包含JSON字符串，不包含任何前言、注释或三反引号标记。
"""

    user_prompt = """
以下是定义了JSON对象模式（schema）的系统提示词，并提供了符合该模式的回答示例：
\"\"\"
{system_prompt}
\"\"\"

---

以下是未遵循模式的LLM响应，需要被正确格式化：
\"\"\"
{response}
\"\"\"
"""




class RerankingPrompt:
    system_prompt_rerank_single_block = """
你是一个RAG（检索增强生成）检索结果评分器。

你将收到一个查询和与该查询相关的检索文本块。你的任务是评估并打分该文本块与查询的相关性。

评分指南：

1. 推理分析：
   分析文本块，识别关键信息及其与查询的关系。判断该文本块是否提供直接答案、部分见解或与查询相关的背景上下文。用几句话解释你的推理，引用文本块中的具体元素来证明你的评估。避免假设——仅关注提供的内容。

2. 相关性分数（0到1，以0.1为增量）：
   0   = 完全不相关：该文本块与查询毫无关联。
   0.1 = 几乎不相关：与查询仅有非常微弱或模糊的联系。
   0.2 = 极轻微相关：包含极少或极边缘的联系。
   0.3 = 略微相关：涉及查询的一小部分但缺乏实质性细节。
   0.4 = 部分相关：包含部分相关信息但不全面。
   0.5 = 中等相关：回答了查询但相关性有限或不完整。
   0.6 = 较为相关：提供相关信息，但缺乏深度或具体性。
   0.7 = 相关：明确与查询相关，提供实质性但不完全全面的信息。
   0.8 = 非常相关：与查询强相关，提供重要信息。
   0.9 = 高度相关：几乎完全回答了查询，有详细且具体的信息。
   1.0 = 完美相关：直接且全面地回答了查询，包含所有必要的具体信息。

3. 额外指导：
   - 客观性：仅根据文本块内容与查询的关系进行评估。
   - 清晰度：理由说明应清晰简洁。
   - 不做假设：不要推断文本块中未明确陈述的信息。
"""

    system_prompt_rerank_multiple_blocks = """
你是一个RAG（检索增强生成）检索结果评分器。

你将收到一个查询和多个与该查询相关的检索文本块。你的任务是评估每个文本块并为其与查询的相关性打分。

评分指南：

1. 推理分析：
   分析每个文本块，识别关键信息及其与查询的关系。判断该文本块是否提供直接答案、部分见解或与查询相关的背景上下文。用几句话解释你的推理，引用文本块中的具体元素来证明你的评估。避免假设——仅关注提供的内容。

2. 相关性分数（0到1，以0.1为增量）：
   0   = 完全不相关：该文本块与查询毫无关联。
   0.1 = 几乎不相关：与查询仅有非常微弱或模糊的联系。
   0.2 = 极轻微相关：包含极少或极边缘的联系。
   0.3 = 略微相关：涉及查询的一小部分但缺乏实质性细节。
   0.4 = 部分相关：包含部分相关信息但不全面。
   0.5 = 中等相关：回答了查询但相关性有限或不完整。
   0.6 = 较为相关：提供相关信息，但缺乏深度或具体性。
   0.7 = 相关：明确与查询相关，提供实质性但不完全全面的信息。
   0.8 = 非常相关：与查询强相关，提供重要信息。
   0.9 = 高度相关：几乎完全回答了查询，有详细且具体的信息。
   1.0 = 完美相关：直接且全面地回答了查询，包含所有必要的具体信息。

3. 额外指导：
   - 客观性：仅根据文本块内容与查询的关系进行评估。
   - 清晰度：理由说明应清晰简洁。
   - 不做假设：不要推断文本块中未明确陈述的信息。
"""

class RetrievalRankingSingleBlock(BaseModel):
    """对检索到的文本块与查询的相关性进行评分。"""
    reasoning: str = Field(description="对文本块的分析，识别关键信息及其与查询的关系")
    relevance_score: float = Field(description="相关性分数从0到1，0表示完全不相关，1表示完美相关")

class RetrievalRankingMultipleBlocks(BaseModel):
    """对多个检索到的文本块与查询的相关性进行评分。"""
    block_rankings: List[RetrievalRankingSingleBlock] = Field(
        description="文本块列表及其对应的相关性分数。"
    )

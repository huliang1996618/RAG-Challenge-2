# =============================================================================
# RAG 核心能力练手脚本 —— 50 行核心代码 + 完整 Demo
# =============================================================================
# 本脚本从项目中提取了 RAG（检索增强生成）的 6 个核心模块，
# 浓缩为约 50 行关键代码，配以详细的讲解注释和可运行的演示。
#
# 涵盖的核心知识点：
#   1. tiktoken 精确计算 token 数
#   2. RecursiveCharacterTextSplitter 文本切块
#   3. OpenAI Embedding + FAISS 建向量索引
#   4. FAISS 向量检索（内积搜索 = 余弦相似度）
#   5. 余弦相似度手算（点积 / 模长乘积）
#   6. BM25 关键词检索（稀疏词法匹配）
#   7. LLM 重排序的加权融合（combined_score 公式）
#   8. ThreadPoolExecutor 并行处理 I/O 密集型任务
#
# 运行方式：
#   python src/rag_core_demo.py
#
# 依赖（已在 requirements.txt 中）：
#   pip install openai numpy faiss-cpu tiktoken langchain rank-bm25 python-dotenv
# =============================================================================

import os
import math
import json
import pickle
import numpy as np
from pathlib import Path
from typing import List, Dict, Tuple, Optional
from concurrent.futures import ThreadPoolExecutor

import tiktoken
from dotenv import load_dotenv
from openai import OpenAI
from langchain_text_splitters import RecursiveCharacterTextSplitter
from rank_bm25 import BM25Okapi
import faiss


# =============================================================================
# 第一部分：准备演示数据
# =============================================================================
# 用一份模拟的"公司年报"作为检索语料。每个段落是一个"文档块"。
# 这模拟了真实 RAG 系统中解析 PDF 后切分得到的 chunk 列表。

DEMO_DOCUMENTS = [
    {
        "page": 1,
        "section": "公司概况",
        "text": "北京星辰科技有限公司成立于2018年，总部位于北京市海淀区中关村。公司主营人工智能和大数据分析业务，"
               "2023年全年营收达到12.8亿元人民币，同比增长35%。公司目前拥有员工约1200人，其中研发人员占比超过60%。",
    },
    {
        "page": 2,
        "section": "财务摘要",
        "text": "2023财年，公司实现营业收入12.8亿元，毛利润7.2亿元，毛利率56.3%。净利润为2.1亿元，净利率16.4%。"
               "2022年同期营收为9.5亿元，净利润1.4亿元。经营活动产生的现金流量净额为3.5亿元。",
    },
    {
        "page": 3,
        "section": "主营业务",
        "text": "公司核心产品包括星辰智能决策平台、星辰数据分析引擎和星辰自动化机器学习工具。"
               "智能决策平台服务金融行业客户超过50家，数据分析引擎在电商领域市占率达到18%。"
               "2023年新推出的AIGC内容生成工具已签约客户120家。",
    },
    {
        "page": 4,
        "section": "研发投入",
        "text": "公司高度重视技术创新，2023年研发投入达到3.2亿元，占营收比重25%。"
               "研发团队在自然语言处理、计算机视觉和强化学习三个方向持续深耕。"
               "截至2023年底，公司累计获得发明专利授权127项，其中2023年新增授权32项。",
    },
    {
        "page": 5,
        "section": "风险提示",
        "text": "公司面临的主要风险包括：AI行业政策监管趋严可能影响业务拓展；"
               "大模型技术快速发展可能导致现有产品竞争力下降；"
               "核心人才流失风险；以及中美科技竞争带来的供应链不确定性。"
               "公司已建立完善的风险预警和应对机制。",
    },
    {
        "page": 6,
        "section": "市场展望",
        "text": "根据IDC报告，中国AI市场2024年预计规模达到1200亿元，年复合增长率28%。"
               "公司计划2024年营收目标18亿元，重点拓展医疗和智能制造两个新行业。"
               "同时将加大海外市场投入，优先拓展东南亚和中东市场。",
    },
    {
        "page": 7,
        "section": "人力资源",
        "text": "公司奉行「人才是第一生产力」的理念。2023年员工培训投入1200万元，"
               "人均培训时长达到80小时。公司推行弹性工作制和远程办公政策，"
               "员工满意度调查得分为4.2/5。2023年核心员工流失率为8.5%，低于行业平均水平。",
    },
]

# =============================================================================
# 第二部分：核心技能1 —— tiktoken 精确计算 token 数
# =============================================================================
# 为什么不用简单的 len(text.split())？
#   因为 LLM 使用 BPE（Byte Pair Encoding）分词，一个中文词 ≠ 一个 token。
#   例如 "人工智能" 可能是 2~3 个 token，而 "a" 可能只占 1 个 token。
#   只有 tiktoken（OpenAI 官方工具）能精确计算 LLM 实际消耗的 token 数。
#
# 这段是你在 text_splitter.py 中学到的核心技能。

def count_tokens(text: str, encoding_name: str = "o200k_base") -> int:
    """
    使用 tiktoken 精确计算文本的 token 数量。

    为什么用 "o200k_base"？
      - 这是 GPT-4o 使用的编码器名称
      - 不同模型使用不同编码器，token 计数也不同
      - 官方映射：GPT-4o → o200k_base，GPT-3.5 → cl100k_base

    Args:
        text:          要计算的文本
        encoding_name: tiktoken 编码器名称

    Returns:
        int: token 数量
    """
    encoding = tiktoken.get_encoding(encoding_name)
    tokens = encoding.encode(text)
    return len(tokens)


# =============================================================================
# 第三部分：核心技能2 —— RecursiveCharacterTextSplitter 文本切块
# =============================================================================
# 这是 RAG 中最基础的一步：把长文档切成小块。
#
# 两个关键参数：
#   chunk_size=300:   每块最多 300 token（不是字符！）
#   chunk_overlap=50: 相邻两块之间重叠 50 token
#
# 为什么要 overlap？
#   假设一句话 "公司2023年净利润为2.1亿元" 刚好被切在两块之间：
#    块A: "...公司2023年"       → 只有前半句，检索不到
#    块B: "净利润为2.1亿元..."  → 只有后半句，检索不到
#   有了 overlap，关键信息不会在边界丢失。
#
# 这段是你从 text_splitter.py 中学到的核心技能。

def split_text_into_chunks(
    full_text: str,
    chunk_size: int = 300,
    chunk_overlap: int = 50
) -> List[str]:
    """
    使用 RecursiveCharacterTextSplitter 将长文本切分为固定大小的块。

    "Recursive"（递归）的意思：
      先尝试按段落(\\n\\n)切 → 如果还太长，按句子(。)切
      → 如果还太长，按空格切 → 最终兜底，按字符切。
      这种"从大到小逐级尝试"的策略，能最大程度保留语义完整性。

    Args:
        full_text:     原始长文本
        chunk_size:    每块最大 token 数
        chunk_overlap: 相邻块之间的重叠 token 数

    Returns:
        List[str]: 切分后的文本块列表
    """
    # 核心代码：仅 3 行（但每个参数都值得推敲）
    # 注意：from_tiktoken_encoder 只能使用 OpenAI 的 tokenizer，
    # 因为 tiktoken 库是 OpenAI 专属的，不支持千问等模型的编码器。
    # 但这里 tokenizer 仅用于估算切块大小，不影响 embedding 或检索的正确性，
    # 实际调用的是千问的 API。对于中文文本，gpt-4o 和千问的 token 估算差异很小。
    text_splitter = RecursiveCharacterTextSplitter.from_tiktoken_encoder(
        model_name="gpt-4o",        # tiktoken 不支持千问，用 gpt-4o 编码器近似估算中文 token
        chunk_size=chunk_size,      # 每块最多 300 token
        chunk_overlap=chunk_overlap # 块间重叠 50 token
    )
    chunks = text_splitter.split_text(full_text)
    return chunks


# =============================================================================
# 第四部分：核心技能3 —— OpenAI Embedding + FAISS 建向量索引
# =============================================================================
# 这是 RAG 的"存储"环节——把文本变成向量，存入向量数据库。
#
# 核心流程（3 步，约 15 行）：
#   1. 调用 OpenAI API 把文本转为向量（embedding）
#   2. 把所有向量堆成 numpy 矩阵
#   3. 用 FAISS 建索引（IndexFlatIP = 内积搜索 = 等价于余弦相似度）
#
# 这段是你从 ingestion.py 中学到的核心技能。

class VectorDBBuilder:
    """
    向量数据库构建器 —— 封装 embedding + FAISS 建库的完整流程。

    设计要点：
      - IndexFlatIP 使用内积（Inner Product），等价于归一化后的余弦相似度
      - 为什么是 float32？FAISS 要求向量为 32 位浮点数，这是速度与精度的平衡
      - dimension 由 embedding 模型决定：text-embedding-3-large → 3072 维
    """

    # 通义千问 text-embedding-v3 的向量维度
    # 如果使用 text-embedding-v2/v1，维度为 1536
    EMBEDDING_DIM = 3072

    def __init__(self, use_real_api: bool = True):
        """
        Args:
            use_real_api: True=调用通义千问 DashScope API，False=用随机向量模拟
        """
        self.use_real_api = use_real_api
        if use_real_api:
            load_dotenv()
            # 通义千问 DashScope 兼容 OpenAI SDK，只需指定 base_url 即可
            # 文档：https://help.aliyun.com/document_detail/2712195.html
            self.llm = OpenAI(
                api_key=os.getenv("DASHSCOPE_API_KEY"),
                base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
                timeout=None,
                max_retries=2
            )

    def get_embedding(self, text: str) -> List[float]:
        """
        核心代码①：调用通义千问 DashScope API 获取文本的嵌入向量。

        使用 text-embedding-v3 模型，将任意文本映射到 3072 维向量空间。
        语义相近的文本，在这个空间中的向量距离也相近。

        注：DashScope 兼容 OpenAI SDK，调用方式完全一致，
        仅 base_url 和模型名不同。
        """
        if self.use_real_api:
            response = self.llm.embeddings.create(
                input=text,
                model="text-embedding-v3"
            )
            return response.data[0].embedding
        else:
            # 模拟模式：用文本哈希生成"伪向量"（仅供演示流程）
            np.random.seed(hash(text) % (2**31))
            vec = np.random.randn(self.EMBEDDING_DIM).astype(np.float32)
            # 归一化到单位长度，使内积等价于余弦相似度
            vec = vec / np.linalg.norm(vec)
            return vec.tolist()

    def build_index(self, texts: List[str]) -> faiss.Index:
        """
        核心代码②：批量 embedding → 构建 FAISS 索引。

        这是整个建库流程的核心，仅 4 行：
        """
        # 步骤1：批量获取所有文本的 embedding（每条 3072 维）
        embeddings = [self.get_embedding(t) for t in texts]

        # 步骤2：转为 numpy 二维数组 (chunk数 × 3072)
        embeddings_array = np.array(embeddings, dtype=np.float32)

        # 步骤3：获取向量维度（由模型决定）
        dimension = embeddings_array.shape[1]

        # 步骤4：创建 FAISS 索引（IndexFlatIP = 内积搜索）
        #        内积在归一化向量上等价于余弦相似度
        index = faiss.IndexFlatIP(dimension)
        index.add(embeddings_array)

        return index

    def save_index(self, index: faiss.Index, filepath: Path) -> None:
        """持久化：将 FAISS 索引保存到磁盘。"""
        faiss.write_index(index, str(filepath))

    def load_index(self, filepath: Path) -> faiss.Index:
        """反持久化：从磁盘加载 FAISS 索引。"""
        return faiss.read_index(str(filepath))


# =============================================================================
# 第五部分：核心技能4 —— FAISS 向量检索
# =============================================================================
# 这是 RAG 的"查询"环节——把用户问题转为向量，在索引中找最相似的 chunk。
#
# 核心流程（3 步，约 10 行）：
#   1. 把用户 query 嵌入为向量
#   2. 调用 index.search() 找 top-N 最近邻
#   3. 把索引号映射回原始文本
#
# 这段是你从 retrieval.py 中学到的核心技能。

def vector_search(
    query: str,
    index: faiss.Index,
    documents: List[Dict],
    builder: VectorDBBuilder,
    top_n: int = 3
) -> List[Dict]:
    """
    核心代码③：向量语义检索。

    执行步骤（仅关键的 4 行核心代码）：
    """
    # 步骤1：将查询转为向量
    query_embedding = builder.get_embedding(query)
    query_array = np.array([query_embedding], dtype=np.float32)

    # 步骤2：FAISS 搜索 —— 这是核心中的核心
    #        返回 distances（内积值，越大越相似）和 indices（chunk 索引）
    distances, indices = index.search(query_array, top_n)

    # 步骤3：把 FAISS 返回的索引号映射回原始文档
    results = []
    for dist, idx in zip(distances[0], indices[0]):
        doc = documents[idx].copy()
        doc["distance"] = round(float(dist), 4)
        results.append(doc)

    return results


# =============================================================================
# 第六部分：核心技能5 —— 余弦相似度手算
# =============================================================================
# 这是你之前追问过的公式。手写一遍，彻底理解它的含义。
#
# 公式：  cos(θ) = A·B / (|A| × |B|)
#
#   A·B = Σ(Ai × Bi)          ← 向量点积，衡量两个向量的方向一致性
#   |A| = √(Σ Ai²)             ← 向量 A 的模长（长度）
#   |B| = √(Σ Bi²)             ← 向量 B 的模长（长度）
#
# 直观理解：
#   两个向量方向完全一致  → cos = 1   → 语义完全相同
#   两个向量方向完全相反  → cos = -1  → 语义完全相反
#   两个向量互相垂直      → cos = 0   → 语义无关
#
# 这段是你从 retrieval.py get_strings_cosine_similarity() 中学到的。

def cosine_similarity(vec_a: List[float], vec_b: List[float]) -> float:
    """
    核心代码④：手算两个向量的余弦相似度。

    输入是两个 embedding 向量（如 3072 维的浮点数列表），
    返回 0~1 之间的相似度分数（1 = 完全相同，0 = 完全无关）。
    """
    a = np.array(vec_a)
    b = np.array(vec_b)

    # 核心公式：点积 / (模长乘积)
    similarity = np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b))
    return round(float(similarity), 4)


# =============================================================================
# 第七部分：核心技能6 —— BM25 关键词检索
# =============================================================================
# BM25 是经典的"词袋"检索算法，不需要 embedding，不需要 GPU。
# 它基于词频（TF）和逆文档频率（IDF）打分。
#
# 什么时候用 BM25 而不是向量检索？
#   ✅ 搜索精确术语："Q3营收"、"专利号CN2023XXX"
#   ✅ 搜索代码/ID/编号等不可语义化的内容
#   ❌ 搜索模糊概念："公司面临的风险"（需要用向量语义理解）
#
# 这段是你从 ingestion.py BM25Ingestor 中学到的核心技能。

def bm25_search(
    query: str,
    chunks: List[str],
    documents: List[Dict],
    top_n: int = 3
) -> List[Dict]:
    """
    核心代码⑤：BM25 关键词检索。

    仅 4 行核心代码就完成了一个完整的检索系统：
    """
    # 步骤1：对所有 chunk 做空格分词（英文天然按空格分，中文需先分词）
    tokenized_chunks = [chunk.split() for chunk in chunks]

    # 步骤2：构建 BM25 索引
    bm25 = BM25Okapi(tokenized_chunks)

    # 步骤3：对查询分词并打分
    scores = bm25.get_scores(query.split())

    # 步骤4：按分数降序取 top-N
    top_indices = sorted(
        range(len(scores)),
        key=lambda i: scores[i],
        reverse=True
    )[:top_n]

    results = []
    for idx in top_indices:
        doc = documents[idx].copy()
        doc["distance"] = round(float(scores[idx]), 4)
        doc["method"] = "BM25"
        results.append(doc)

    return results


# =============================================================================
# 第八部分：核心技能7 —— 加权融合（LLM 重排序的核心）
# =============================================================================
# 这是整个 reranking.py 中最核心的 1 行公式！
#
# combined_score = llm_weight × LLM相关性分数
#                + (1 - llm_weight) × 向量检索距离
#
# 直观理解：
#   llm_weight = 0.7 → LLM 的判断占 70%，向量距离占 30%
#   llm_weight = 0.5 → 二者各占一半
#   llm_weight = 0.0 → 纯向量检索（完全信任向量距离）
#
# 为什么需要 LLM 参与？
#   假设查询是"公司的营收增长率是多少？"
#   向量检索可能把"营收"相关的 chunk 都排前面（语义接近），
#   但 LLM 能判断出：只有包含"增长率"具体数字的 chunk 才是真正相关的。
#   这就是向量检索的"语义近似"陷阱，LLM 重排序可以纠正。

def weighted_fusion(
    documents: List[Dict],
    llm_scores: List[float],
    llm_weight: float = 0.7
) -> List[Dict]:
    """
    核心代码⑥：加权融合 —— LLM 重排序的核心公式。

    在实际项目中，llm_scores 来自 GPT-4o-mini。
    这里用模拟分数演示公式本身。

    Args:
        documents:     检索结果列表（含 distance 字段）
        llm_scores:    LLM 对每个文档的相关性评分（0~1）
        llm_weight:    LLM 分数权重（0~1），默认 0.7

    Returns:
        按 combined_score 降序排列的文档列表
    """
    vector_weight = 1 - llm_weight  # 向量距离的权重

    for doc, llm_score in zip(documents, llm_scores):
        doc["llm_score"] = round(llm_score, 4)
        # ═══════════════════════════════════════════════
        # 这是整个重排序最核心的 1 行代码！
        # ═══════════════════════════════════════════════
        doc["combined_score"] = round(
            llm_weight * llm_score + vector_weight * doc["distance"],
            4
        )

    # 按加权总分降序排列
    documents.sort(key=lambda x: x["combined_score"], reverse=True)
    return documents


# =============================================================================
# 第九部分：核心技能8 —— ThreadPoolExecutor 并行处理
# =============================================================================
# 在 reranking.py 中，LLM API 调用是 I/O 密集型的（等待网络响应）。
# 用线程池并行调用可以大幅减少总耗时。
#
# 注意：这适用于 I/O 密集型（API调用、文件读写），
#       对 CPU 密集型（矩阵计算）应使用 ProcessPoolExecutor。

def parallel_io_demo(items: List, worker_count: int = 3) -> None:
    """
    演示 ThreadPoolExecutor 的基本用法。

    在真实项目中，这里处理的是 LLM API 调用的批次。
    """
    def process_one(item):
        """模拟 I/O 操作（如 API 调用）"""
        import time
        time.sleep(0.3)  # 模拟网络延迟
        return f"处理完成: {item}"

    # 核心代码：仅 2 行
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        results = list(executor.map(process_one, items))

    return results


# =============================================================================
# 第十部分：核心技能9 —— 千问 Chat API 生成最终答案（RAG 的 "G"）
# =============================================================================
# 前面 8 步只是"检索"（Retrieval），但 RAG 全称是 Retrieval-Augmented Generation。
# "生成"（Generation）这一步才是最终目的：把检索到的上下文 + 用户问题
# 一起喂给大模型，让它基于真实资料生成可信的答案，而非凭空编造。
#
# 核心流程：
#   1. 将检索到的 top-N 文档拼成一段"上下文"
#   2. 将上下文 + 系统提示词 + 用户问题 组装成 Prompt
#   3. 调用千问 Chat API（兼容 OpenAI SDK）获取生成结果
#
# 与 embedding 不同：Embedding API 用的是千问 text-embedding-v3，
# Chat API 用的是千问 qwen-plus / qwen-max / qwen-turbo。

def generate_answer_with_qwen(
    query: str,
    context_docs: List[Dict],
    model: str = "qwen-plus",
    use_real_api: bool = True
) -> str:
    """
    核心代码⑦：调用千问 Chat API，基于检索到的上下文生成答案。

    这是 RAG 链路中最"值钱"的一步——之前的 embedding、检索、重排序
    都是为了这一步服务的。没有这一步，整个系统只是一个"搜索引擎"。

    Args:
        query:         用户原始问题
        context_docs:  检索到的文档列表（含 text、distance 等字段）
        model:         千问 Chat 模型名（qwen-plus / qwen-max / qwen-turbo）
        use_real_api:  是否调用真实 API

    Returns:
        str: 千问生成的最终答案
    """
    if not use_real_api:
        return "【模拟模式】未调用千问 API。请设置 DASHSCOPE_API_KEY 以体验真实生成。"

    # ── 步骤1：拼接上下文 ──
    # 将检索到的文档按编号拼接，每段标注来源页码
    context_parts = []
    for i, doc in enumerate(context_docs):
        context_parts.append(
            f"[资料{i+1} 来源：第{doc.get('page', '?')}页，{doc.get('section', '未知章节')}]\n"
            f"{doc['text']}"
        )
    context_text = "\n\n---\n\n".join(context_parts)

    # ── 步骤2：组装 System Prompt ──
    # 告诉千问它的角色、信息来源限制、回答风格
    system_prompt = """你是一个专业的股票研究分析助手。你的回答必须严格基于用户提供的资料内容。

重要规则：
1. 仅使用下面「参考资料」中提供的信息回答问题，不要引入外部知识。
2. 如果资料中没有相关信息，请明确说"根据现有资料，无法回答该问题"，不要编造。
3. 引用资料中的具体数据时，请注明来源页码。
4. 回答应条理清晰、数据准确、语言专业但通俗易懂。
5. 对于财务指标类问题，注意区分「元、千元、百万元、亿元」等不同单位。"""

    # ── 步骤3：组装 User Prompt ──
    user_prompt = f"""以下是关于目标公司的参考资料：

---
{context_text}
---

请根据以上资料回答以下问题：

"{query}"

请给出详细、专业的回答。"""

    # ── 步骤4：调用千问 Chat API ──
    load_dotenv()
    client = OpenAI(
        api_key=os.getenv("DASHSCOPE_API_KEY"),
        base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
    )

    response = client.chat.completions.create(
        model=model,
        temperature=0.3,  # 股票分析需要一定准确性，温度不宜过高
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    )

    return response.choices[0].message.content

def run_full_demo():
    """
    完整 RAG 流程演示：切分 → 建库 → 检索 → 重排序。

    这个函数用上面的所有核心组件，串起一个最小但完整的
    RAG（检索增强生成）系统。在真实项目中，"生成答案"这一步
    会调用 GPT-4o 根据检索到的上下文生成最终回答，这里省略。
    """
    print("=" * 70)
    print("  RAG 核心能力练手 Demo")
    print("  涵盖：切分 | Embedding | FAISS建库 | 检索 | 重排序")
    print("=" * 70)

    # ── 准备数据 ──
    print("\n📄 步骤1：准备演示文档（7 个段落，模拟公司年报）")
    corpus = "\n".join(d["text"] for d in DEMO_DOCUMENTS)
    print(f"   文档总字符数: {len(corpus)}")
    print(f"   文档总 token 数: {count_tokens(corpus)}（使用 tiktoken 精确计算）")

    # ── 切分文本 ──
    print("\n✂️  步骤2：文本切块（RecursiveCharacterTextSplitter）")
    chunks = split_text_into_chunks(corpus, chunk_size=300, chunk_overlap=50)
    print(f"   切分后共 {len(chunks)} 个 chunk")
    for i, c in enumerate(chunks):
        print(f"   Chunk[{i}]: {count_tokens(c):>4} tokens | 前50字: {c[:50]}...")

    # ── 判断使用真实 API 还是模拟模式 ──
    load_dotenv()
    use_real_api = bool(os.getenv("DASHSCOPE_API_KEY"))
    if not use_real_api:
        print("\n⚠️  未检测到 DASHSCOPE_API_KEY，将使用随机向量模拟 embedding。")
        print("   请在系统环境变量中设置 DASHSCOPE_API_KEY 后即可使用真实通义千问 API。")

    # ── 建向量索引 ──
    print(f"\n🗄️  步骤3：构建 FAISS 向量索引({'真实API' if use_real_api else '模拟模式'})")
    builder = VectorDBBuilder(use_real_api=use_real_api)
    index = builder.build_index(chunks)
    print(f"   索引维度: {index.d} 维")
    print(f"   索引中的向量数: {index.ntotal}")

    # ── 向量检索 ──
    query_vector = "公司2023年的营收和利润情况如何？"
    print(f"\n🔍 步骤4：向量语义检索")
    print(f"   查询: \"{query_vector}\"")
    vec_results = vector_search(query_vector, index, DEMO_DOCUMENTS, builder, top_n=3)

    print(f"\n   【向量检索 Top-3 结果（按 FAISS 内积排序）】")
    for i, r in enumerate(vec_results):
        print(f"   #{i+1} | 分数: {r['distance']:.4f} | Page {r['page']} | {r['section']}")
        print(f"        {r['text'][:80]}...")

    # ── BM25 检索（对比） ──
    query_bm25 = "营收 净利润 2023"
    print(f"\n🔎 步骤5：BM25 关键词检索（用于对比）")
    print(f"   查询: \"{query_bm25}\"")
    bm25_results = bm25_search(query_bm25, chunks, DEMO_DOCUMENTS, top_n=3)

    print(f"\n   【BM25 检索 Top-3 结果（按 BM25 分数排序）】")
    for i, r in enumerate(bm25_results):
        print(f"   #{i+1} | 分数: {r['distance']:.4f} | Page {r['page']} | {r['section']}")
        print(f"        {r['text'][:80]}...")

    # ── 余弦相似度演示 ──
    print(f"\n📐 步骤6：余弦相似度手算")
    emb1 = builder.get_embedding(chunks[0])  # chunk[0] 的向量
    emb2 = builder.get_embedding(chunks[1])  # chunk[1] 的向量
    sim = cosine_similarity(emb1, emb2)
    print(f"   Chunk[0] vs Chunk[1] 余弦相似度: {sim}")
    print(f"   解读: 分数{sim} {'说明语义较接近' if sim > 0.5 else '说明语义差异较大'}")

    # ── 加权融合演示 ──
    print(f"\n⚖️  步骤7：加权融合（模拟 LLM 重排序）")
    # 模拟：LLM 认为第2个结果比第1个更相关（但向量距离显示第1个更近）
    simulated_llm_scores = [0.55, 0.85, 0.60]
    print(f"   模拟 LLM 评分: {simulated_llm_scores}")
    print(f"   公式: combined = 0.7×LLM分数 + 0.3×向量距离")
    fused = weighted_fusion(vec_results, simulated_llm_scores, llm_weight=0.7)

    print(f"\n   【融合前 → 融合后 对比】")
    for i, (before, after) in enumerate(zip(vec_results, fused)):
        print(f"   #{i+1} | 向量距离: {before['distance']:.4f} → "
              f"LLM分: {after['llm_score']:.4f} → "
              f"综合分: {after['combined_score']:.4f} | {after['section']}")

    # ── 并行处理演示 ──
    print(f"\n⚡ 步骤8：ThreadPoolExecutor 并行处理演示")
    tasks = [f"文档批次{i}" for i in range(5)]
    parallel_results = parallel_io_demo(tasks, worker_count=3)
    for r in parallel_results:
        print(f"   {r}")

    # ══════════════════════════════════════════════════════════════
    # 🧠 步骤9：千问 Chat API 生成最终答案（RAG 的最终产出！）
    # ══════════════════════════════════════════════════════════════
    print(f"\n🧠 步骤9：千问 Chat API 生成最终答案（RAG 的 'G' 环节！）")
    print(f"   模型: qwen-plus")
    print(f"   输入上下文: {len(vec_results)} 个检索结果")

    # 取向量检索的 top-2 结果作为上下文（避免 token 过长）
    top_context = vec_results[:2]
    print(f"   实际使用: {len(top_context)} 个最相关文档")
    for i, doc in enumerate(top_context):
        print(f"   📄 文档{i+1}: [{doc['section']}] {doc['text'][:60]}...")

    print(f"\n   ⏳ 正在调用千问 Chat API 生成答案...")
    answer = generate_answer_with_qwen(
        query=query_vector,
        context_docs=top_context,
        model="qwen-plus",
        use_real_api=use_real_api
    )

    print(f"\n   ╔══════════════════════════════════════════════════╗")
    print(f"   ║  📝 千问生成的答案：                              ║")
    print(f"   ╚══════════════════════════════════════════════════╝")
    # 答案可能很长，限制每行宽度以便阅读
    for line in answer.split('\n'):
        if len(line) > 90:
            print(f"   {line[:87]}...")
        else:
            print(f"   {line}")

    # ── 总结 ──
    print(f"\n{'='*70}")
    print("  ✅ Demo 完成！你已体验了 RAG 的完整流程。")
    print(f"{'='*70}")
    print("""
    📋 回顾你在这 50 行核心代码中学到的 9 项技能：

    1️⃣  tiktoken 计算 token 数       — text_splitter.py 的核心
    2️⃣  RecursiveTextSplitter 切块   — text_splitter.py 的核心
    3️⃣  Embedding + FAISS 建库       — ingestion.py 的核心
    4️⃣  FAISS 向量检索              — retrieval.py 的核心
    5️⃣  余弦相似度手算              — retrieval.py 的核心
    6️⃣  BM25 关键词检索             — ingestion.py 的核心
    7️⃣  加权融合（LLM重排序核心）   — reranking.py 的核心
    8️⃣  ThreadPoolExecutor 并行      — reranking.py 的核心
    9️⃣  千问 Chat 生成最终答案      — 全新！RAG 的 "G" 环节 🆕

    🎯 下一步建议：
      - 当前已用通义千问 DASHSCOPE_API_KEY 跑通了 embedding + Chat 双 API
      - 修改 query_vector 为你想问的任何问题，观察检索+生成的完整效果
      - 下一步：把你的真实 PDF 内容替换 DEMO_DOCUMENTS，打造你自己的知识库
    """)


# =============================================================================
# 运行入口
# =============================================================================

if __name__ == "__main__":
    run_full_demo()

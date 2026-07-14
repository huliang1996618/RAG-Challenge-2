import os
from dotenv import load_dotenv
from openai import OpenAI
import requests
import src.prompts as prompts
from concurrent.futures import ThreadPoolExecutor


# ======================================================================
# 模块：reranking.py
# ======================================================================
# 提供两种重排序（Reranking）策略，用于对检索阶段返回的候选文档
# 进行精细化的二次排序，提升最终返回给用户的文档相关性：
#   1. JinaReranker  — 调用 Jina AI 远程重排序 API（外部服务）
#   2. LLMReranker   — 使用 GPT-4o-mini 对文档打分（本地LLM判断）
#
# 重排序是整个 RAG 流水线的"精排"环节：检索（粗筛）→ 重排序（精排）→ 返回。
# 两种策略可以互相替代，当前项目默认使用 LLMReranker。
# ======================================================================


# ======================================================================
# JinaReranker
# ======================================================================
# 基于 Jina AI 的远程重排序服务。将查询和候选文档发送到 Jina API，
# 由专门训练的 Cross-Encoder 模型计算相关性分数并返回排序结果。
#
# 优点：无需本地 GPU，模型专门为排序任务训练，效果好。
# 缺点：依赖外部网络，有延迟和费用，不适合离线场景。
# 当前项目中作为备选方案，默认未启用（使用 LLMReranker 替代）。
# ======================================================================

class JinaReranker:
    def __init__(self):
        """
        初始化 Jina 重排序器，设置 API 端点和认证头。

        Jina Reranker API 地址固定为 v1/rerank，
        认证使用环境变量 JINA_API_KEY 中的 Bearer Token。
        """
        self.url = 'https://api.jina.ai/v1/rerank'
        self.headers = self.get_headers()
        
    def get_headers(self):
        """
        构建 HTTP 请求头，包含 Jina API 认证信息。

        从 .env 文件加载 JINA_API_KEY 环境变量，
        组装标准的 JSON 内容类型 + Bearer Token 认证头。
        注意这里重新调用了 load_dotenv()，允许独立调用此方法。
        """
        load_dotenv()
        jina_api_key = os.getenv("JINA_API_KEY")    
        headers = {'Content-Type': 'application/json',
                   'Authorization': f'Bearer {jina_api_key}'}
        return headers
    
    def rerank(self, query, documents, top_n = 10):
        """
        调用 Jina AI 远程 API 进行文档重排序。

        将查询字符串和候选文档列表 POST 到 Jina Reranker API，
        使用 jina-reranker-v2-base-multilingual 模型（支持多语言）。
        API 返回按相关性降序排列的结果。

        参数：
            query:     用户查询字符串
            documents: 候选文档文本列表（字符串数组）
            top_n:     返回前 N 个最相关结果，默认 10

        返回：
            API 响应的 JSON 字典，包含排序后的结果和分数
        """
        data = {
            "model": "jina-reranker-v2-base-multilingual",
            "query": query,
            "top_n": top_n,
            "documents": documents
        }

        response = requests.post(url=self.url, headers=self.headers, json=data)

        return response.json()

# ======================================================================
# LLMReranker
# ======================================================================
# 基于通义千问 qwen-plus 的文档重排序器。核心思路：
#   1. 将查询 + 候选文档构造为结构化 Prompt
#   2. 让 LLM 判断每个文档与查询的相关性并打分（0~1）
#   3. 将 LLM 分数与向量检索的距离分数按权重加权融合
#   4. 按加权总分降序排列返回
#
# 与 JinaReranker 的区别：
#   - LLMReranker 不需要额外 API（复用 OpenAI Key）
#   - LLM 能够理解"细微语义差异"（如：问"增长率"但文档只有"收入"，
#     纯向量可能误判为相关，LLM 能识别出信息缺失）
#   - 支持单文档和批量文档两种评分模式
#   - 批量模式下使用线程池并行处理，提升吞吐量
# ======================================================================

class LLMReranker:
    def __init__(self):
        """
        初始化 LLM 重排序器。

        预加载以下资源：
        - OpenAI 客户端（用于调用 GPT-4o-mini）
        - 两套 System Prompt（单文档评分 / 批量文档评分）
        - 两套 Structured Output Schema（确保 LLM 返回结构化 JSON）
        """
        self.llm = self.set_up_llm()
        # 单文档评分的系统提示词：详细分析单个文档块与查询的相关性
        self.system_prompt_rerank_single_block = prompts.RerankingPrompt.system_prompt_rerank_single_block
        # 批量文档评分的系统提示词：一次性比较多个文档块
        self.system_prompt_rerank_multiple_blocks = prompts.RerankingPrompt.system_prompt_rerank_multiple_blocks
        # 单文档评分的结构化输出格式定义（Pydantic Schema）
        self.schema_for_single_block = prompts.RetrievalRankingSingleBlock
        # 批量文档评分的结构化输出格式定义（Pydantic Schema）
        self.schema_for_multiple_blocks = prompts.RetrievalRankingMultipleBlocks
      
    def set_up_llm(self):
        """
        创建通义千问 DashScope 客户端实例。

        从 .env 文件加载 DASHSCOPE_API_KEY 环境变量，
        用于后续调用千问模型进行文档重排序评分。
        DashScope 兼容 OpenAI SDK，仅需指定 base_url 即可。
        """
        load_dotenv()
        api_key = os.getenv("DASHSCOPE_API_KEY")
        if not api_key:
            raise ValueError(
                "未找到 DASHSCOPE_API_KEY 环境变量！\n"
                "请在 .env 文件或系统环境变量中设置：DASHSCOPE_API_KEY=你的密钥"
            )
        llm = OpenAI(
            api_key=api_key,
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1"
        )
        return llm
    
    def get_rank_for_single_block(self, query, retrieved_document):
        """
        对单个文档块进行 LLM 相关性评分。

        构造 User Prompt → 调用 GPT-4o-mini（Structured Output 模式）
        → 返回结构化的评分结果（含 relevance_score 和推理过程）。

        使用场景：
        - 当 documents_batch_size = 1 时，每个文档单独调用此方法
        - 单文档模式下 LLM 可以给出更细致的分析

        参数：
            query:              用户查询字符串
            retrieved_document: 单个检索到的文档文本块

        返回：
            dict，包含：
            - relevance_score: 相关性分数（0~1，1=最相关）
            - reasoning:       LLM 给出的评分理由
        """
        # ── 构造 User Prompt：将查询和文档块嵌入模板 ──
        user_prompt = f'/nHere is the query:/n"{query}"/n/nHere is the retrieved text block:/n"""/n{retrieved_document}/n"""/n'
        
        # ── 调用通义千问 qwen-plus，使用 Structured Output 模式 ──
        # response_format 参数确保返回的 JSON 严格遵循 schema_for_single_block 定义
        completion = self.llm.beta.chat.completions.parse(
            model="qwen-plus",
            temperature=0,  # 温度=0 确保评分稳定、可复现
            messages=[
                {"role": "system", "content": self.system_prompt_rerank_single_block},
                {"role": "user", "content": user_prompt},
            ],
            response_format=self.schema_for_single_block
        )

        # ── 解析结构化响应 ──
        response = completion.choices[0].message.parsed
        response_dict = response.model_dump()
        
        return response_dict

    def get_rank_for_multiple_blocks(self, query, retrieved_documents):
        """
        对多个文档块进行批量 LLM 相关性评分。

        一次 LLM 调用同时评估多个文档块与查询的相关性，
        比逐个调用单文档方法效率更高（减少 API 调用次数）。

        构造方式：
        - 将所有文档块用 "---" 分隔符拼接为一个 Prompt
        - LLM 一次性返回所有文档块的结构化评分列表

        参数：
            query:               用户查询字符串
            retrieved_documents: 文档文本块列表（字符串数组）

        返回：
            dict，包含：
            - block_rankings: 评分列表，每个元素包含 relevance_score 和 reasoning
        """
        # ── 构造批量文档的格式化字符串 ──
        # 每个文档块标记为 "Block 1:", "Block 2:", ... 用 "---" 分隔
        formatted_blocks = "\n\n---\n\n".join([
            f'Block {i+1}:\n\n"""\n{text}\n"""'
            for i, text in enumerate(retrieved_documents)
        ])
        
        # ── 构造 User Prompt ──
        user_prompt = (
            f"Here is the query: \"{query}\"\n\n"
            "Here are the retrieved text blocks:\n"
            f"{formatted_blocks}\n\n"
            f"You should provide exactly {len(retrieved_documents)} rankings, in order."
        )

        # ── 调用通义千问 qwen-plus（Structured Output 模式） ──
        completion = self.llm.beta.chat.completions.parse(
            model="qwen-plus",
            temperature=0,
            messages=[
                {"role": "system", "content": self.system_prompt_rerank_multiple_blocks},
                {"role": "user", "content": user_prompt},
            ],
            response_format=self.schema_for_multiple_blocks
        )

        response = completion.choices[0].message.parsed
        response_dict = response.model_dump()
      
        return response_dict

    def rerank_documents(
        self,
        query: str,
        documents: list,
        documents_batch_size: int = 4,
        llm_weight: float = 0.7
    ):
        """
        对文档列表进行重排序——整个模块的核心编排方法。

        流程概览：
          1. 将文档列表按 documents_batch_size 切分为多个批次
          2. 对每个批次调用 LLM 获取相关性评分（并行）
          3. 将 LLM 分数与原始向量距离加权融合
          4. 按加权总分降序排列，返回排序后的文档列表

        加权公式：
          combined_score = llm_weight × LLM相关性分数
                         + (1 - llm_weight) × 向量距离分数

        并行策略：
          使用 ThreadPoolExecutor 线程池并行处理多个批次。
          LLM API 调用是 I/O 密集型操作，线程并行能显著减少总耗时。

        两种模式：
          - 单文档模式（batch_size=1）：每个文档单独调用 LLM，
            评分更细致但 API 调用次数多
          - 批量模式（batch_size>1）：多个文档打包为一次 LLM 调用，
            API 调用次数少，省费用

        参数：
            query:                 用户查询字符串
            documents:             候选文档列表，每个元素为 {"distance": ..., "text": ..., "page": ...}
            documents_batch_size:  每批包含几个文档（1 用单文档模式，>1 用批量模式）
            llm_weight:            LLM 评分的权重（0~1），剩余权重给向量距离

        返回：
            按 combined_score 降序排列的文档列表，每个文档新增：
            - relevance_score: LLM 给出的相关性分数
            - combined_score:  加权融合后的最终分数
        """
        # ── 第1步：将文档列表切分为固定大小的批次 ──
        doc_batches = [
            documents[i:i + documents_batch_size]
            for i in range(0, len(documents), documents_batch_size)
        ]
        # 向量距离的权重 = 1 - LLM权重
        vector_weight = 1 - llm_weight
        
        # ══════════════════════════════════════════════════════════════
        # 分支 A：单文档模式（documents_batch_size == 1）
        # 每个文档单独调用一次 LLM，评分更精确但速度较慢
        # ══════════════════════════════════════════════════════════════
        if documents_batch_size == 1:
            def process_single_doc(doc):
                """
                处理单个文档：调用 LLM 评分 → 加权融合。

                闭包函数，捕获外层的 query、llm_weight、vector_weight。
                每个文档独立调用 get_rank_for_single_block，
                适合对评分精度要求高的场景。
                """
                # ── 调用 LLM 对单个文档打分 ──
                ranking = self.get_rank_for_single_block(query, doc['text'])
                
                doc_with_score = doc.copy()
                doc_with_score["relevance_score"] = ranking["relevance_score"]
                # ── 加权融合：LLM分数 + 向量距离 ──
                # 注意：distance 在 FAISS 中是 L2 距离（越小越好），
                # 但这里直接用于加权求和，实际使用效果取决于上游
                doc_with_score["combined_score"] = round(
                    llm_weight * ranking["relevance_score"] +
                    vector_weight * doc['distance'],
                    4
                )
                return doc_with_score

            # ── 线程池并行处理所有文档 ──
            with ThreadPoolExecutor() as executor:
                all_results = list(executor.map(process_single_doc, documents))
                
        # ══════════════════════════════════════════════════════════════
        # 分支 B：批量模式（documents_batch_size > 1）
        # 多个文档打包为一次 LLM 调用，节省 API 费用
        # ══════════════════════════════════════════════════════════════
        else:
            def process_batch(batch):
                """
                处理一个批次：提取文本 → 批量调用 LLM → 逐一融合分数。

                闭包函数，捕获外层的 query、llm_weight、vector_weight。
                每个批次内的多个文档在单次 LLM 调用中同时评分。
                """
                # ── 提取批次中所有文档的文本 ──
                texts = [doc['text'] for doc in batch]
                # ── 批量调用 LLM ──
                rankings = self.get_rank_for_multiple_blocks(query, texts)
                results = []
                block_rankings = rankings.get('block_rankings', [])
                
                # ── 容错处理：LLM 返回的评分数量少于预期 ──
                # 可能是 API 截断或模型输出不完整，用默认0分补齐
                if len(block_rankings) < len(batch):
                    print(f"\nWarning: Expected {len(batch)} rankings but got {len(block_rankings)}")
                    for i in range(len(block_rankings), len(batch)):
                        doc = batch[i]
                        print(f"Missing ranking for document on page {doc.get('page', 'unknown')}:")
                        print(f"Text preview: {doc['text'][:100]}...\n")
                    
                    # 用默认评分补齐缺失的条目
                    for _ in range(len(batch) - len(block_rankings)):
                        block_rankings.append({
                            "relevance_score": 0.0,  # 默认给0分，表示"不相关"
                            "reasoning": "Default ranking due to missing LLM response"
                        })
                
                # ── 逐文档加权融合 ──
                for doc, rank in zip(batch, block_rankings):
                    doc_with_score = doc.copy()
                    doc_with_score["relevance_score"] = rank["relevance_score"]
                    doc_with_score["combined_score"] = round(
                        llm_weight * rank["relevance_score"] +
                        vector_weight * doc['distance'],
                        4
                    )
                    results.append(doc_with_score)
                return results

            # ── 线程池并行处理所有批次 ──
            with ThreadPoolExecutor() as executor:
                batch_results = list(executor.map(process_batch, doc_batches))
            
            # ── 展平嵌套列表：[[batch1结果], [batch2结果], ...] → [全部结果] ──
            all_results = []
            for batch in batch_results:
                all_results.extend(batch)
        
        # ── 最后一步：按加权总分降序排列 ──
        # 分数最高的排在前面，确保最相关的文档优先返回
        all_results.sort(key=lambda x: x["combined_score"], reverse=True)
        return all_results

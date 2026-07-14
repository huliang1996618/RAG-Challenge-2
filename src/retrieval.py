import json
import logging
from typing import List, Tuple, Dict, Union
from rank_bm25 import BM25Okapi
import pickle
from pathlib import Path
import faiss
from openai import OpenAI
from dotenv import load_dotenv
import os
import numpy as np
from src.reranking import LLMReranker

_log = logging.getLogger(__name__)


# ======================================================================
# 模块：retrieval.py
# ======================================================================
# 为解析后的 PDF 报告提供三种 RAG 检索策略：
#   1. BM25Retriever     — 稀疏词法检索（基于关键词匹配）
#   2. VectorRetriever   — 稠密语义检索（基于 FAISS 向量搜索）
#   3. HybridRetriever   — 向量检索 + LLM 重排序，追求最高精度
#
# 所有检索器均以公司为单位工作：给定 company_name，先定位对应的
# JSON 报告 + 索引/数据库，然后仅在该文档内进行搜索。
# ======================================================================


# ======================================================================
# BM25Retriever — BM25 关键词检索器
# ======================================================================
# 使用 BM25 算法的稀疏词法检索。BM25 擅长精确术语匹配（公司名称、
# 产品代码、财务指标等），无需嵌入模型——快速且确定性高。
# BM25 索引在预处理阶段构建，每个文档一个 .pkl 文件，查询时通过
# pickle 加载。
# ======================================================================

class BM25Retriever:
    def __init__(self, bm25_db_dir: Path, documents_dir: Path):
        """
        初始化 BM25 检索器，指定预构建 BM25 索引和解析后 JSON 文档的路径。

        Args:
            bm25_db_dir:  存放 *.pkl BM25 索引文件的目录
            documents_dir: 存放解析后 JSON 报告文件的目录
        """
        self.bm25_db_dir = bm25_db_dir
        self.documents_dir = documents_dir
        
    def retrieve_by_company_name(
        self,
        company_name: str,
        query: str,
        top_n: int = 3,
        return_parent_pages: bool = False
    ) -> List[Dict]:
        """
        在指定公司的报告中执行 BM25 关键词搜索。

        执行步骤：
          1. 通过 company_name 匹配 metainfo 定位 JSON 文档
          2. 加载该文档对应的预构建 BM25 索引（.pkl 文件）
          3. 对查询进行分词（空格切分）后对所有 chunk 打分
          4. 返回得分最高的 top-N 个 chunk（或去重后的完整页面）

        Args:
            company_name: 要搜索的公司名称（精确匹配）
            query:        原始查询字符串（BM25 使用空格分词）
            top_n:        返回结果的最大数量
            return_parent_pages: 若为 True，将结果聚合为页面级（按页码去重）

        Returns:
            dict 列表，每个结果包含：
              - distance: BM25 得分（越高越相关）
              - page:     结果所在页码
              - text:     chunk 文本或完整页面文本
        """
        # ── 第 1 步：通过公司名称定位 JSON 文档 ──
        document_path = None
        for path in self.documents_dir.glob("*.json"):
            with open(path, 'r', encoding='utf-8') as f:
                doc = json.load(f)
                if doc["metainfo"]["company_name"] == company_name:
                    document_path = path
                    document = doc
                    break
                    
        if document_path is None:
            raise ValueError(f"No report found with '{company_name}' company name.")
            
        # ── 第 2 步：加载该文档的 BM25 索引 ──
        # 索引文件以 sha1_name 命名（原始 PDF 文件名的哈希值）
        bm25_path = self.bm25_db_dir / f"{document['metainfo']['sha1_name']}.pkl"
        with open(bm25_path, 'rb') as f:
            bm25_index = pickle.load(f)
            
        # ── 第 3 步：从文档中提取 chunk 和页面数据 ──
        chunks = document["content"]["chunks"]
        pages = document["content"]["pages"]
        
        # ── 第 4 步：用 BM25 对所有 chunk 打分 ──
        # 使用空格分词；BM25 算法天然处理停用词
        tokenized_query = query.split()
        scores = bm25_index.get_scores(tokenized_query)
        
        # ── 第 5 步：按分数选取 top-N chunk ──
        actual_top_n = min(top_n, len(scores))
        top_indices = sorted(
            range(len(scores)),
            key=lambda i: scores[i],
            reverse=True
        )[:actual_top_n]
        
        # ── 第 6 步：构建结果列表 ──
        retrieval_results = []
        seen_pages = set()  # return_parent_pages=True 时用于去重
        
        for index in top_indices:
            score = round(float(scores[index]), 4)
            chunk = chunks[index]
            parent_page = next(
                page for page in pages if page["page"] == chunk["page"]
            )
            
            if return_parent_pages:
                # 去重：同一页只返回一次（取第一个命中的 chunk 得分）
                if parent_page["page"] not in seen_pages:
                    seen_pages.add(parent_page["page"])
                    result = {
                        "distance": score,
                        "page": parent_page["page"],
                        "text": parent_page["text"]
                    }
                    retrieval_results.append(result)
            else:
                # 返回每个 chunk（同一页可能有多个 chunk）
                result = {
                    "distance": score,
                    "page": chunk["page"],
                    "text": chunk["text"]
                }
                retrieval_results.append(result)
        
        return retrieval_results



# ======================================================================
# VectorRetriever — 向量语义检索器
# ======================================================================
# 使用通义千问 text-embedding-v3 + FAISS 实现稠密语义检索。
# 查询和 chunk 被嵌入为高维向量，FAISS 执行近似最近邻（ANN）搜索
# 以找到语义最相关的 chunk。
#
# 核心设计决策：
#   - FAISS 索引在预处理阶段构建，每个文档一个 .faiss 文件
#   - 初始化时将所有 DB 加载到内存（self.all_dbs），以空间换时间
#   - 支持整页模式（return_parent_pages）和"返回全部"模式
# ======================================================================

class VectorRetriever:
    def __init__(self, vector_db_dir: Path, documents_dir: Path):
        """
        初始化向量检索器。

        实例化时会将所有可用的 FAISS 索引和对应的 JSON 文档加载到内存。
        这是"以空间换时间"的策略——查询时无需任何磁盘 I/O。

        Args:
            vector_db_dir:  存放 *.faiss 向量索引文件的目录
            documents_dir:  存放解析后 JSON 报告文件的目录
        """
        self.vector_db_dir = vector_db_dir
        self.documents_dir = documents_dir
        self.all_dbs = self._load_dbs()       # 预加载所有 FAISS 索引和文档
        self.llm = self._set_up_llm()          # OpenAI 客户端（实例级）

    def _set_up_llm(self):
        """
        创建通义千问 DashScope 客户端实例，用于生成嵌入向量。

        通过 python-dotenv 从环境变量 DASHSCOPE_API_KEY 读取密钥。
        DashScope 兼容 OpenAI SDK，仅需指定 base_url 即可。
        timeout=None 表示不限制嵌入 API 调用的超时时间。
        max_retries=2 提供对瞬时网络错误的容错能力。
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
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=None,
            max_retries=2
            )
        return llm
    
    @staticmethod
    def set_up_llm():
        """
        _set_up_llm 的静态版本，用于静态方法中无法访问 self 的场景
        （如 get_strings_cosine_similarity）。

        此方法复制了 _set_up_llm 的逻辑，因为 Python 静态方法无法访问
        实例属性，而仅为一次相似度计算创建完整实例过于浪费。
        
        使用通义千问 DashScope 兼容模式，与 text-embedding-v3 模型配合。
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
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
            timeout=None,
            max_retries=2
            )
        return llm

    def _load_dbs(self):
        """
        预加载所有 FAISS 向量索引及其对应的 JSON 文档。

        匹配逻辑：
          - 遍历 documents_dir 中的每个 *.json 文件，在 vector_db_dir 中
            查找同名 stem（不含扩展名的文件名）的 *.faiss 文件。
          - 通过 stem 匹配确保每个文档与正确的索引配对。

        校验规则：
          - 跳过没有匹配 FAISS 索引的文档
          - 跳过格式错误的 JSON 文件（记录 error 日志）
          - 跳过缺少必要 schema 字段（metainfo + content）的文档

        Returns:
            字典列表，每个元素包含：
              - name:      文档标识符（stem）
              - vector_db: FAISS Index 对象（已加载，可直接搜索）
              - document:  解析后的 JSON 文档字典
        """
        all_dbs = []
        # ── 构建映射表：文件名 stem → FAISS 文件路径 ──
        all_documents_paths = list(self.documents_dir.glob('*.json'))
        vector_db_files = {
            db_path.stem: db_path
            for db_path in self.vector_db_dir.glob('*.faiss')
        }
        
        for document_path in all_documents_paths:
            stem = document_path.stem
            
            # ── 跳过无匹配 FAISS 索引的文档 ──
            if stem not in vector_db_files:
                _log.warning(f"No matching vector DB found for document {document_path.name}")
                continue
            
            # ── 加载并校验 JSON 文档 ──
            try:
                with open(document_path, 'r', encoding='utf-8') as f:
                    document = json.load(f)
            except Exception as e:
                _log.error(f"Error loading JSON from {document_path.name}: {e}")
                continue
            
            if not (isinstance(document, dict) and "metainfo" in document and "content" in document):
                _log.warning(f"Skipping {document_path.name}: does not match the expected schema.")
                continue
            
            # ── 加载 FAISS 向量索引 ──
            try:
                vector_db = faiss.read_index(str(vector_db_files[stem]))
            except Exception as e:
                _log.error(f"Error reading vector DB for {document_path.name}: {e}")
                continue
                
            report = {
                "name": stem,
                "vector_db": vector_db,
                "document": document
            }
            all_dbs.append(report)
        
        return all_dbs

    @staticmethod
    def get_strings_cosine_similarity(str1, str2):
        """
        计算两个任意字符串之间的余弦相似度。

        使用 OpenAI text-embedding-3-large 分别嵌入两个字符串，然后
        计算余弦相似度 = dot(A,B) / (|A| * |B|)。
        这是一个定性比较的辅助工具，不用于主检索流程（主流程使用
        FAISS L2 距离）。

        Args:
            str1, str2: 要比较的两个字符串

        Returns:
            float: 余弦相似度分数，四舍五入到 4 位小数
                   范围：-1 到 1（1 表示语义完全相同，0 表示无关）
        """
        # 使用静态方法避免创建完整的 VectorRetriever 实例
        # 使用通义千问 text-embedding-v3（与建库时模型一致，确保向量空间对齐）
        llm = VectorRetriever.set_up_llm()
        embeddings = llm.embeddings.create(
            input=[str1, str2],
            model="text-embedding-v3"
        )
        embedding1 = embeddings.data[0].embedding
        embedding2 = embeddings.data[1].embedding
        
        # 余弦相似度公式：向量点积 / 模长乘积
        similarity_score = np.dot(embedding1, embedding2) / (
            np.linalg.norm(embedding1) * np.linalg.norm(embedding2)
        )
        similarity_score = round(similarity_score, 4)
        return similarity_score

    def retrieve_by_company_name(
        self,
        company_name: str,
        query: str,
        llm_reranking_sample_size: int = None,
        top_n: int = 3,
        return_parent_pages: bool = False
    ) -> List[Tuple[str, float]]:
        """
        在指定公司的报告中执行向量语义搜索。

        执行流程：
          1. 在 self.all_dbs 中定位公司的预加载报告 + FAISS 索引
          2. 使用 text-embedding-3-large 将查询嵌入为 3072 维向量
          3. 在 FAISS 索引中搜索 top-N 最近邻（L2 距离）
          4. 将 FAISS 结果映射回 chunk/页面文本

        注意：llm_reranking_sample_size 参数仅为了与 HybridRetriever
        保持接口兼容，VectorRetriever 会忽略它（所有向量搜索结果直接
        返回，不做重排序）。

        Args:
            company_name:              要搜索的公司名称（精确匹配）
            query:                     自然语言搜索查询
            llm_reranking_sample_size: （未使用，仅为接口兼容保留）
            top_n:                     返回结果的最大数量
            return_parent_pages:       若为 True，按页面级去重

        Returns:
            字典列表，每个结果包含：
              - distance: FAISS L2 距离（越小越相似）
              - page:     页码
              - text:     chunk 或完整页面文本
        """
        # ── 第 1 步：在预加载的数据库中定位公司报告 ──
        target_report = None
        for report in self.all_dbs:
            document = report.get("document", {})
            metainfo = document.get("metainfo")
            if not metainfo:
                _log.error(f"Report '{report.get('name')}' is missing 'metainfo'!")
                raise ValueError(f"Report '{report.get('name')}' is missing 'metainfo'!")
            if metainfo.get("company_name") == company_name:
                target_report = report
                break
        
        if target_report is None:
            _log.error(f"No report found with '{company_name}' company name.")
            raise ValueError(f"No report found with '{company_name}' company name.")
        
        document = target_report["document"]
        vector_db = target_report["vector_db"]
        chunks = document["content"]["chunks"]
        pages = document["content"]["pages"]
        
        actual_top_n = min(top_n, len(chunks))
        
        # ── 第 2 步：使用通义千问嵌入查询 ──
        # text-embedding-v3 生成 3072 维嵌入向量（与建库时模型一致，确保向量空间对齐）
        embedding = self.llm.embeddings.create(
            input=query,
            model="text-embedding-v3"
        )
        embedding = embedding.data[0].embedding
        
        # 重塑为 FAISS 搜索所需的 2D 数组 (1, 3072)
        embedding_array = np.array(embedding, dtype=np.float32).reshape(1, -1)
        
        # ── 第 3 步：FAISS 近似最近邻搜索 ──
        # 返回：top-k 最近 chunk 的 distances（L2 距离）和 indices（索引）
        distances, indices = vector_db.search(x=embedding_array, k=actual_top_n)
    
        # ── 第 4 步：将结果映射回文本 ──
        retrieval_results = []
        seen_pages = set()
        
        for distance, index in zip(distances[0], indices[0]):
            distance = round(float(distance), 4)
            chunk = chunks[index]
            parent_page = next(
                page for page in pages if page["page"] == chunk["page"]
            )
            if return_parent_pages:
                if parent_page["page"] not in seen_pages:
                    seen_pages.add(parent_page["page"])
                    result = {
                        "distance": distance,
                        "page": parent_page["page"],
                        "text": parent_page["text"]
                    }
                    retrieval_results.append(result)
            else:
                result = {
                    "distance": distance,
                    "page": chunk["page"],
                    "text": chunk["text"]
                }
                retrieval_results.append(result)
            
        return retrieval_results

    def retrieve_all(self, company_name: str) -> List[Dict]:
        """
        返回某公司报告的"全部"页面（不做任何筛选）。

        这是一个"全量导出"模式，适用于调用方需要完整文档上下文的场景
        ——例如，将整份报告送入大上下文窗口的 LLM 中。
        每个页面被赋予固定的 distance=0.5（中性分，因为此模式下排序无意义）。

        Args:
            company_name: 要检索的公司名称（精确匹配）

        Returns:
            按页码排序的字典列表，每个结果包含：
              - distance: 固定值 0.5（中性分）
              - page:     页码
              - text:     完整页面文本
        """
        # ── 定位公司报告 ──
        target_report = None
        for report in self.all_dbs:
            document = report.get("document", {})
            metainfo = document.get("metainfo")
            if not metainfo:
                continue
            if metainfo.get("company_name") == company_name:
                target_report = report
                break
        
        if target_report is None:
            _log.error(f"No report found with '{company_name}' company name.")
            raise ValueError(f"No report found with '{company_name}' company name.")
        
        document = target_report["document"]
        pages = document["content"]["pages"]
        
        # ── 按自然阅读顺序返回所有页面 ──
        all_pages = []
        for page in sorted(pages, key=lambda p: p["page"]):
            result = {
                "distance": 0.5,  # 中性分——此处无意义的排序
                "page": page["page"],
                "text": page["text"]
            }
            all_pages.append(result)
            
        return all_pages


# ======================================================================
# HybridRetriever — 混合检索器（向量 + LLM 重排序）
# ======================================================================
# 两阶段检索流水线，追求最高精度：
#   阶段一 — VectorRetriever： 获取大量候选集（sample_size 个）
#   阶段二 — LLMReranker：     LLM 对每个文档与查询的相关性打分，
#                             然后将 LLM 分数与向量距离加权合并
#
# LLM 重排序器是本类的核心差异优势：它能理解纯嵌入相似度捕捉不到的
# 语义细微差别（例如"营收增长率" vs "营收"——嵌入向量可能很接近，
# 但 LLM 知道哪个 chunk 真正回答了问题）。
# ======================================================================

class HybridRetriever:
    def __init__(self, vector_db_dir: Path, documents_dir: Path):
        """
        初始化混合检索器，组合 VectorRetriever + LLMReranker。

        VectorRetriever 在实例化时预加载所有 FAISS 索引。
        LLMReranker 采用延迟初始化（首次查询前不发起 API 调用）。
        """
        self.vector_retriever = VectorRetriever(vector_db_dir, documents_dir)
        self.reranker = LLMReranker()
        
    def retrieve_by_company_name(
        self, 
        company_name: str, 
        query: str, 
        llm_reranking_sample_size: int = 28,
        documents_batch_size: int = 2,
        top_n: int = 6,
        llm_weight: float = 0.7,
        return_parent_pages: bool = False
    ) -> List[Dict]:
        """
        两阶段检索 + 重排序流水线。

        阶段一 — 向量候选池（粗筛）：
          使用 VectorRetriever 获取较大的候选集（默认 sample_size=28）。
          这相当于"粗过滤器"——FAISS 快速将数千个 chunk 缩小到几十个
          合理候选。

        阶段二 — LLM 重排序（精排）：
          将候选文档分批（batch_size=2）喂给 LLM，同时传入原始查询。
          LLM 对每个文档的相关性打分。最终分数 =
          llm_weight * LLM分数 + (1 - llm_weight) * 向量距离。
          默认 llm_weight=0.7 意味着 LLM 判断占主导地位。

        为何未集成 BM25？
          当前实现仅依赖向量检索作为第一阶段。可以将 BM25 作为并行检索
          源加入，通过倒数排名融合（RRF）合并，以获得更高的召回率。

        Args:
            company_name:              要搜索的公司名称
            query:                     自然语言查询
            llm_reranking_sample_size:  阶段一检索的候选数量
            documents_batch_size:      每次 LLM 调用处理的文档数
            top_n:                     最终返回的结果数量
            llm_weight:                LLM 分数权重（0-1），剩余为向量权重
            return_parent_pages:       若为 True，页面级去重

        Returns:
            重排序后的字典列表（长度 ≤ top_n），每个结果包含：
              - distance: 综合得分（越高越相关）
              - page:     页码
              - text:     chunk 或完整页面文本
        """
        # ── 阶段一：向量候选池 ──
        # 检索较大的初始集合——多于实际需要的数量，为重排序器
        # 提供充足的筛选素材
        vector_results = self.vector_retriever.retrieve_by_company_name(
            company_name=company_name,
            query=query,
            top_n=llm_reranking_sample_size,
            return_parent_pages=return_parent_pages
        )
        
        # ── 阶段二：LLM 重排序 ──
        # 重排序器对每个候选文档与查询进行评分，并通过加权组合
        # 将 LLM 分数与原始向量距离合并
        reranked_results = self.reranker.rerank_documents(
            query=query,
            documents=vector_results,
            documents_batch_size=documents_batch_size,
            llm_weight=llm_weight
        )
        
        # ── 返回重排序后的 top-N 结果 ──
        return reranked_results[:top_n]

import os
import json
import pickle
from typing import List, Union
from pathlib import Path
from tqdm import tqdm

from dotenv import load_dotenv
from openai import OpenAI
from rank_bm25 import BM25Okapi
import faiss
import numpy as np
from tenacity import retry, wait_fixed, stop_after_attempt


class BM25Ingestor:
    def __init__(self):
        pass

    def create_bm25_index(self, chunks: List[str]) -> BM25Okapi:
        """Create a BM25 index from a list of text chunks."""
        tokenized_chunks = [chunk.split() for chunk in chunks]
        return BM25Okapi(tokenized_chunks)
    
    def process_reports(self, all_reports_dir: Path, output_dir: Path):
        """Process all reports and save individual BM25 indices.
        
        Args:
            all_reports_dir (Path): Directory containing the JSON report files
            output_dir (Path): Directory where to save the BM25 indices
        """
        output_dir.mkdir(parents=True, exist_ok=True)
        all_report_paths = list(all_reports_dir.glob("*.json"))

        for report_path in tqdm(all_report_paths, desc="Processing reports for BM25"):
            # Load the report
            with open(report_path, 'r', encoding='utf-8') as f:
                report_data = json.load(f)
                
            # Extract text chunks and create BM25 index
            text_chunks = [chunk['text'] for chunk in report_data['content']['chunks']]
            bm25_index = self.create_bm25_index(text_chunks)
            
            # Save BM25 index
            sha1_name = report_data["metainfo"]["sha1_name"]
            output_file = output_dir / f"{sha1_name}.pkl"
            with open(output_file, 'wb') as f:
                pickle.dump(bm25_index, f)
                
        print(f"Processed {len(all_report_paths)} reports")

class VectorDBIngestor:
    def __init__(self):
        self.llm = self._set_up_llm()

    def _set_up_llm(self):
        """初始化千问 DashScope 客户端（兼容 OpenAI SDK，仅需修改 base_url）"""
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

    @retry(wait=wait_fixed(20), stop=stop_after_attempt(2))
    def _get_embeddings(self, text: Union[str, List[str]], model: str = "text-embedding-v3") -> List[float]:
        """
        调用千问 text-embedding-v3 获取文本嵌入向量。
        
        注意：千问 v3 为 3072 维，v1/v2 为 1536 维。
        DashScope embedding API 兼容 OpenAI SDK 调用方式。
        """
        if isinstance(text, str) and not text.strip():
            raise ValueError("输入文本不能为空字符串。")
        
        if isinstance(text, list):
            # 千问 embedding API 单次最多 2048 条
            text_chunks = [text[i:i + 2048] for i in range(0, len(text), 2048)]
        else:
            text_chunks = [text]

        embeddings = []
        for chunk in text_chunks:
            response = self.llm.embeddings.create(input=chunk, model=model)
            embeddings.extend([embedding.embedding for embedding in response.data])
        
        return embeddings

    def _create_vector_db(self, embeddings: List[float]):
        embeddings_array = np.array(embeddings, dtype=np.float32)
        dimension = len(embeddings[0])
        index = faiss.IndexFlatIP(dimension)  # Cosine distance
        index.add(embeddings_array)
        return index
    
    def _process_report(self, report: dict):
        text_chunks = [chunk['text'] for chunk in report['content']['chunks']]
        embeddings = self._get_embeddings(text_chunks)
        index = self._create_vector_db(embeddings)
        return index

    def process_reports(self, all_reports_dir: Path, output_dir: Path):
        all_report_paths = list(all_reports_dir.glob("*.json"))
        output_dir.mkdir(parents=True, exist_ok=True)

        for report_path in tqdm(all_report_paths, desc="Processing reports"):
            with open(report_path, 'r', encoding='utf-8') as file:
                report_data = json.load(file)
            index = self._process_report(report_data)
            sha1_name = report_data["metainfo"]["sha1_name"]
            faiss_file_path = output_dir / f"{sha1_name}.faiss"
            faiss.write_index(index, str(faiss_file_path))

        print(f"Processed {len(all_report_paths)} reports")
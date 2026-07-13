import os                      # 操作系统接口，用于设置环境变量 OMP_NUM_THREADS
import time                    # 计时工具，统计解析耗时
import logging                 # 日志记录，跟踪解析进度和错误
import re                      # 正则表达式（预留，用于文本模式匹配）
import json                    # JSON 序列化，将解析结果保存为 JSON 文件
from tabulate import tabulate  # 表格渲染库，将表格数据转为 Markdown 格式
from pathlib import Path       # 面向对象的文件路径处理
from typing import Iterable, List  # 类型注解（Iterable 表示可迭代对象，List 表示列表）

# from docling.backend.docling_parse_backend import DoclingParseDocumentBackend  # 旧版 V1 后端（已弃用）
from docling.backend.docling_parse_v2_backend import DoclingParseV2DocumentBackend  # 新版 V2 后端（默认使用）
# from docling.backend.pypdfium2_backend import PyPdfiumDocumentBackend  # 备选 pypdfium2 后端（已弃用）
from docling.datamodel.base_models import ConversionStatus  # 转换状态枚举（SUCCESS / FAILURE）
from docling.datamodel.document import ConversionResult     # 转换结果对象（包含解析后的文档数据）

_log = logging.getLogger(__name__)  # 获取当前模块的日志记录器，用于统一日志输出

def _process_chunk(pdf_paths, pdf_backend, output_dir, num_threads, metadata_lookup, debug_data_path):
    """辅助函数：在独立的子进程中处理一批 PDF 文件（供 ProcessPoolExecutor 调用）"""
    # 为当前子进程创建一个全新的 PDFParser 实例（避免跨进程共享状态导致冲突）
    parser = PDFParser(
        pdf_backend=pdf_backend,
        output_dir=output_dir,
        num_threads=num_threads,
        csv_metadata_path=None  # 不通过 CSV 文件加载元数据，而是直接传入已解析好的字典
    )
    parser.metadata_lookup = metadata_lookup  # 直接将主进程的元数据字典注入到子进程的 parser 中
    parser.debug_data_path = debug_data_path  # 直接将主进程的调试路径注入到子进程的 parser 中
    parser.parse_and_export(pdf_paths)        # 调用串行解析方法处理当前 chunk 中的所有 PDF
    return f"Processed {len(pdf_paths)} PDFs."  # 返回处理完成信息（主进程通过解析此字符串追踪进度）


class PDFParser:
    """PDF 解析器：负责配置 Docling 引擎并将 PDF 文件转换为结构化 JSON"""
    def __init__(
        self,
        pdf_backend=DoclingParseV2DocumentBackend,  # 默认使用 Docling V2 后端（更好的解析效果）
        output_dir: Path = Path("./parsed_pdfs"),   # 解析结果 JSON 的输出目录
        num_threads: int = None,                     # 底层 OCR/CPU 线程数（None 表示使用默认值）
        csv_metadata_path: Path = None,              # CSV 元数据文件路径（包含公司名等信息）
    ):
        self.pdf_backend = pdf_backend               # 保存 PDF 后端类引用
        self.output_dir = output_dir                 # 保存输出目录路径
        self.doc_converter = self._create_document_converter()  # 核心：创建 Docling 文档转换器
        self.num_threads = num_threads               # 保存线程数配置
        self.metadata_lookup = {}                    # 初始化元数据查找字典（sha1 → {company_name}）
        self.debug_data_path = None                  # 调试数据输出路径（None 表示不输出调试信息）

        if csv_metadata_path is not None:
            self.metadata_lookup = self._parse_csv_metadata(csv_metadata_path)  # 解析 CSV 元数据文件
            
        if self.num_threads is not None:
            os.environ["OMP_NUM_THREADS"] = str(self.num_threads)  # 设置 OpenMP 线程数（影响 OCR 性能）

    @staticmethod
    def _parse_csv_metadata(csv_path: Path) -> dict:
        """解析 CSV 元数据文件，创建以 sha1 为键的查找字典"""
        import csv                          # 延迟导入 CSV 模块（仅在需要时加载）
        metadata_lookup = {}                # 初始化空字典
        
        with open(csv_path, 'r', encoding='utf-8') as csvfile:
            reader = csv.DictReader(csvfile)  # 使用 DictReader，每行自动转为字典
            for row in reader:
                # 兼容新旧 CSV 格式：优先取 company_name 字段，其次取 name 字段
                company_name = row.get('company_name', row.get('name', '')).strip('"')
                metadata_lookup[row['sha1']] = {   # 以 PDF 文件的 sha1 哈希值作为键
                    'company_name': company_name   # 存储公司名称
                }
        return metadata_lookup                   # 返回构建好的查找字典

    def _create_document_converter(self) -> "DocumentConverter": # type: ignore
        """创建并配置 Docling 的 DocumentConverter（文档转换器），这是解析质量的"控制面板" """
        from docling.document_converter import DocumentConverter, FormatOption  # 文档转换器及格式选项
        from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode, EasyOcrOptions  # Pipeline 配置
        from docling.datamodel.base_models import InputFormat  # 输入格式枚举（PDF/图片等）
        from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline  # 标准 PDF 处理管线
        
        pipeline_options = PdfPipelineOptions()                 # 创建 PDF 管线配置对象
        pipeline_options.do_ocr = True                          # 开启 OCR（光学字符识别），处理扫描件中的文字
        ocr_options = EasyOcrOptions(lang=['en'], force_full_page_ocr=False)  # 使用 EasyOCR，仅识别英文，不全页 OCR
        pipeline_options.ocr_options = ocr_options              # 将 OCR 配置注入管线
        pipeline_options.do_table_structure = True              # 开启表格结构识别（检测 PDF 中的表格）
        pipeline_options.table_structure_options.do_cell_matching = True  # 开启单元格匹配（关联单元格和表头）
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE  # 表格识别模式：精度优先（而非速度优先）
        
        format_options = {                                      # 构建格式选项字典
            InputFormat.PDF: FormatOption(                      # 为 PDF 格式指定处理方案
                pipeline_cls=StandardPdfPipeline,               # 使用标准 PDF 管线
                pipeline_options=pipeline_options,              # 传入上面配置好的管线选项
                backend=self.pdf_backend                        # 传入 PDF 解析后端（默认 V2）
            )
        }
        
        return DocumentConverter(format_options=format_options)  # 返回配置好的文档转换器实例

    def convert_documents(self, input_doc_paths: List[Path]) -> Iterable[ConversionResult]:
        """将 PDF 文件列表批量转换为 Docling 文档对象（返回可迭代的转换结果）"""
        conv_results = self.doc_converter.convert_all(source='input_doc_paths')  # 调用 Docling 批量转换所有 PDF
        return conv_results  # 返回转换结果的可迭代对象（惰性求值，逐个处理）
    
    def process_documents(self, conv_results: Iterable[ConversionResult]):
        """遍历转换结果，将成功的文档用 JsonReportProcessor 组装为统一 JSON 格式并保存"""
        if self.output_dir is not None:
            self.output_dir.mkdir(parents=True, exist_ok=True)  # 确保输出目录存在（递归创建父目录）
        success_count = 0   # 成功计数
        failure_count = 0   # 失败计数

        for conv_res in conv_results:                           # 遍历每个文档的转换结果
            if conv_res.status == ConversionStatus.SUCCESS:     # 判断转换是否成功
                success_count += 1                              # 成功计数 +1
                processor = JsonReportProcessor(                 # 为每个文档创建独立的报告处理器
                    metadata_lookup=self.metadata_lookup,        # 传入元数据（公司名等）
                    debug_data_path=self.debug_data_path         # 传入调试数据输出路径
                )
                
                # 将 Docling 文档对象导出为字典格式，并规整页码序列（填补缺失页）
                data = conv_res.document.export_to_dict()       # 导出 Docling 原始字典（包含所有解析信息）
                normalized_data = self._normalize_page_sequence(data)  # 规整页码：确保从第1页到最后一页连续
                
                processed_report = processor.assemble_report(conv_res, normalized_data)  # 组装为自定义 JSON 报告
                doc_filename = conv_res.input.file.stem          # 获取文件名（不含 .pdf 后缀），作为 JSON 文件名
                if self.output_dir is not None:
                    with (self.output_dir / f"{doc_filename}.json").open("w", encoding="utf-8") as fp:
                        json.dump(processed_report, fp, indent=2, ensure_ascii=False)  # 保存 JSON（2空格缩进，支持中文）
            else:
                failure_count += 1                               # 失败计数 +1
                _log.info(f"Document {conv_res.input.file} failed to convert.")  # 记录失败文档的日志

        _log.info(f"Processed {success_count + failure_count} docs, of which {failure_count} failed")  # 输出汇总日志
        return success_count, failure_count                     # 返回成功和失败的数量

    def _normalize_page_sequence(self, data: dict) -> dict:
        """规整页码序列：确保 content 中的页码从1开始连续，缺失页用空模板填充（防御性设计）"""
        if 'content' not in data:           # 如果数据中没有 content 字段（异常情况）
            return data                     # 直接返回原数据，不做处理
        
        normalized_data = data.copy()       # 浅拷贝原数据，避免修改原始字典
        
        existing_pages = {page['page'] for page in data['content']}  # 提取所有已存在的页码（集合去重）
        max_page = max(existing_pages)      # 获取最大页码
        
        empty_page_template = {             # 定义空页面模板
            "content": [],                  # 空内容列表
            "page_dimensions": {}           # 空页面尺寸
        }
        
        new_content = []                    # 新的内容列表（将按页码顺序排列）
        for page_num in range(1, max_page + 1):  # 从第1页遍历到最大页码
            # 查找当前页码对应的内容，若不存在则用空模板填充
            page_content = next(
                (page for page in data['content'] if page['page'] == page_num),  # 查找匹配页码的页面
                {"page": page_num, **empty_page_template}  # 默认值：页码 + 空内容模板
            )
            new_content.append(page_content)  # 将当前页面加入新内容列表
        
        normalized_data['content'] = new_content  # 用规整后的内容替换原 content
        return normalized_data               # 返回规整后的数据

    def parse_and_export(self, input_doc_paths: List[Path] = None, doc_dir: Path = None):
        """串行模式：解析 PDF 文件并导出为 JSON（逐个处理，不支持并行）"""
        start_time = time.time()             # 记录开始时间
        if input_doc_paths is None and doc_dir is not None:
            input_doc_paths = list(doc_dir.glob("*.pdf"))  # 如果未指定文件列表，从目录中收集所有 PDF
        
        total_docs = len(input_doc_paths)    # 统计 PDF 总数
        _log.info(f"Starting to process {total_docs} documents")  # 日志：开始处理
        
        conv_results = self.convert_documents(input_doc_paths)  # 步骤1：调用 Docling 转换所有 PDF
        success_count, failure_count = self.process_documents(conv_results=conv_results)  # 步骤2：处理转换结果
        elapsed_time = time.time() - start_time  # 计算总耗时

        if failure_count > 0:                # 如果存在转换失败的文档
            error_message = f"Failed converting {failure_count} out of {total_docs} documents."
            failed_docs = "Paths of failed docs:\n" + '\n'.join(str(path) for path in input_doc_paths)
            _log.error(error_message)        # 记录错误日志
            _log.error(failed_docs)          # 记录失败文档的路径
            raise RuntimeError(error_message)  # 零容忍策略：任何失败都抛出异常（下游依赖全部文档）

        _log.info(f"{'#'*50}\nCompleted in {elapsed_time:.2f} seconds. Successfully converted {success_count}/{total_docs} documents.\n{'#'*50}")

    def parse_and_export_parallel(
        self,
        input_doc_paths: List[Path] = None,   # PDF 文件路径列表
        doc_dir: Path = None,                 # PDF 所在目录（与 input_doc_paths 二选一）
        optimal_workers: int = 10,             # 并行工作进程数（默认10个）
        chunk_size: int = None                 # 每个进程处理的 PDF 数量（None = 自动计算）
    ):
        """并行模式：使用多进程（ProcessPoolExecutor）同时解析多个 PDF，大幅提升处理速度
        
        参数:
            input_doc_paths: PDF 文件路径列表
            doc_dir: 包含 PDF 文件的目录（当 input_doc_paths 为 None 时使用）
            optimal_workers: 并行工作进程数，None 则自动使用 CPU 核心数
            chunk_size: 每个 chunk 包含的 PDF 数量，None 则自动计算
        """
        import multiprocessing                                   # 多进程模块（获取 CPU 核心数）
        from concurrent.futures import ProcessPoolExecutor, as_completed  # 进程池执行器和完成通知

        # 如果未提供文件列表，从目录中收集所有 PDF 文件
        if input_doc_paths is None and doc_dir is not None:
            input_doc_paths = list(doc_dir.glob("*.pdf"))

        total_pdfs = len(input_doc_paths)                        # 统计 PDF 总数
        _log.info(f"Starting parallel processing of {total_pdfs} documents")  # 日志：开始并行处理
        
        cpu_count = multiprocessing.cpu_count()                  # 获取当前机器的 CPU 核心数
        
        # 自动计算最优工作进程数：不超过 CPU 核心数，也不超过 PDF 总数
        if optimal_workers is None:
            optimal_workers = min(cpu_count, total_pdfs)
        
        if chunk_size is None:
            # 自动计算每个 chunk 的大小：PDF 总数 ÷ 进程数（至少处理1个）
            chunk_size = max(1, total_pdfs // optimal_workers)
        
        # 将 PDF 列表按 chunk_size 切分为多个子列表
        chunks = [
            input_doc_paths[i : i + chunk_size]
            for i in range(0, total_pdfs, chunk_size)
        ]

        start_time = time.time()            # 记录开始时间
        processed_count = 0                 # 已处理的 PDF 计数
        
        # 使用进程池执行器并行处理（每个进程有独立的 Python 解释器，绕过 GIL）
        with ProcessPoolExecutor(max_workers=optimal_workers) as executor:
            # 将所有 chunk 提交到进程池，每个 chunk 调用 _process_chunk 函数
            futures = [
                executor.submit(
                    _process_chunk,         # 提交模块级函数（类方法无法被 pickle 序列化）
                    chunk,                  # 当前 chunk 的 PDF 路径列表
                    self.pdf_backend,       # 传入 PDF 后端类
                    self.output_dir,        # 传入输出目录
                    self.num_threads,       # 传入线程数配置
                    self.metadata_lookup,   # 传入元数据查找字典
                    self.debug_data_path    # 传入调试数据路径
                )
                for chunk in chunks
            ]
            
            # 使用 as_completed 实时获取完成的任务（哪个先完成就先处理哪个）
            for future in as_completed(futures):
                try:
                    result = future.result()                                      # 获取子进程的返回结果
                    processed_count += int(result.split()[1])                     # 从 "Processed X PDFs." 中提取数字
                    _log.info(f"{'#'*50}\n{result} ({processed_count}/{total_pdfs} total)\n{'#'*50}")
                except Exception as e:
                    _log.error(f"Error processing chunk: {str(e)}")              # 记录错误日志
                    raise                                                        # 重新抛出异常（零容忍策略）

        elapsed_time = time.time() - start_time  # 计算总耗时
        _log.info(f"Parallel processing completed in {elapsed_time:.2f} seconds.")  # 日志：完成



class JsonReportProcessor:
    """JSON 报告组装器：将 Docling 的原始字典结构重组为层次清晰的四模块 JSON 报告"""
    def __init__(self, metadata_lookup: dict = None, debug_data_path: Path = None):
        self.metadata_lookup = metadata_lookup or {}  # 元数据查找字典（空字典兜底）
        self.debug_data_path = debug_data_path        # 调试数据输出路径

    def assemble_report(self, conv_result, normalized_data=None):
        """组装完整报告：调用四个子模块分别处理 metainfo / content / tables / pictures"""
        # 优先使用规整后的数据，否则从转换结果中重新导出字典
        data = normalized_data if normalized_data is not None else conv_result.document.export_to_dict()
        assembled_report = {}                                         # 初始化报告字典
        assembled_report['metainfo'] = self.assemble_metainfo(data)   # ① 组装元数据（页数、统计、公司名）
        assembled_report['content'] = self.assemble_content(data)      # ② 组装逐页内容（文本/表格/图片引用）
        assembled_report['tables'] = self.assemble_tables(             # ③ 组装表格（Markdown + HTML + JSON）
            conv_result.document.tables, data
        )
        assembled_report['pictures'] = self.assemble_pictures(data)    # ④ 组装图片信息（位置 + 关联文本）
        self.debug_data(data)                                          # ⑤ 输出调试快照（如果配置了 debug_data_path）
        return assembled_report                                        # 返回组装好的报告
    
    def assemble_metainfo(self, data):
        """从 Docling 原始数据中提取元信息：文件标识、统计数据和公司名称"""
        metainfo = {}
        sha1_name = data['origin']['filename'].rsplit('.', 1)[0]  # 从文件名中去掉 .pdf 后缀，得到 sha1 标识
        metainfo['sha1_name'] = sha1_name                         # 文档唯一标识（PDF 文件的 sha1 哈希）
        metainfo['pages_amount'] = len(data.get('pages', []))     # 文档总页数
        metainfo['text_blocks_amount'] = len(data.get('texts', []))    # 文本块数量
        metainfo['tables_amount'] = len(data.get('tables', []))        # 表格数量
        metainfo['pictures_amount'] = len(data.get('pictures', []))    # 图片数量
        metainfo['equations_amount'] = len(data.get('equations', []))  # 公式数量
        metainfo['footnotes_amount'] = len([t for t in data.get('texts', []) if t.get('label') == 'footnote'])  # 脚注数量
        
        # 如果有 CSV 元数据且 sha1 匹配，补充公司名称
        if self.metadata_lookup and sha1_name in self.metadata_lookup:
            csv_meta = self.metadata_lookup[sha1_name]
            metainfo['company_name'] = csv_meta['company_name']  # 注入公司名称（用于后续"按公司名检索"）
            
        return metainfo

    def process_table(self, table_data):
        # 表格处理占位方法（预留接口，当前返回占位字符串）
        return 'processed_table_content'

    def debug_data(self, data):
        """调试数据输出：将 Docling 的完整原始字典保存为 JSON 文件（用于排查解析质量问题）"""
        if self.debug_data_path is None:              # 如果未配置调试路径，直接跳过
            return
        doc_name = data['name']                       # 获取文档名称
        path = self.debug_data_path / f"{doc_name}.json"  # 构造输出路径
        path.parent.mkdir(parents=True, exist_ok=True)    # 确保父目录存在
        with path.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)  # 保存原始数据（2空格缩进）

    def expand_groups(self, body_children, groups):
        """展开 Docling 的 groups（分组/列表项），将嵌套的 group 子元素"拍平"到顶层"""
        expanded_children = []                        # 初始化展开后的子元素列表

        for item in body_children:                    # 遍历 body 的每个子元素
            if isinstance(item, dict) and '$ref' in item:  # 检查是否为引用类型（如 "#/texts/5"）
                ref = item['$ref']                    # 获取引用字符串
                ref_type, ref_num = ref.split('/')[-2:]   # 解析引用类型和编号（如 "texts", "5"）
                ref_num = int(ref_num)                # 将编号转为整数

                if ref_type == 'groups':              # 如果是分组引用
                    group = groups[ref_num]           # 获取对应的 group 对象
                    group_id = ref_num                # 记录 group ID
                    group_name = group.get('name', '')    # 获取 group 名称
                    group_label = group.get('label', '')  # 获取 group 标签

                    for child in group['children']:   # 遍历 group 中的每个子元素
                        child_copy = child.copy()     # 浅拷贝子元素（避免污染原数据）
                        child_copy['group_id'] = group_id       # 附加 group_id 信息
                        child_copy['group_name'] = group_name   # 附加 group_name 信息
                        child_copy['group_label'] = group_label # 附加 group_label 信息
                        expanded_children.append(child_copy)     # 加入展开列表
                else:
                    expanded_children.append(item)    # 非 group 引用直接保留
            else:
                expanded_children.append(item)        # 非引用元素直接保留

        return expanded_children                      # 返回展开后的子元素列表
    
    def _process_text_reference(self, ref_num, data):
        """处理文本引用：根据引用编号从 texts 数组中提取文本块，构造标准化的内容项
        
        参数:
            ref_num (int): 文本在 data['texts'] 中的索引编号
            data (dict): Docling 原始文档数据字典
            
        返回:
            dict: 标准化的内容项，包含 text、type、text_id 及可选的 orig/enumerated/marker 字段
        """
        text_item = data['texts'][ref_num]     # 根据索引获取文本项对象
        item_type = text_item['label']         # 获取文本标签（如 'paragraph'、'heading'、'footnote'）
        content_item = {                       # 构建标准化内容项
            'text': text_item.get('text', ''), # 文本内容（使用 get 兜底，避免缺失字段报错）
            'type': item_type,                 # 文本类型标签
            'text_id': ref_num                 # 文本在 texts 数组中的编号（用于溯源）
        }
        
        # 如果原始文本（orig）与最终文本（text）不同，附加 orig 字段（OCR 纠正前的内容）
        orig_content = text_item.get('orig', '')
        if orig_content != text_item.get('text', ''):
            content_item['orig'] = orig_content

        # 如果有附加字段则追加（列表项编号、列表标记等）
        if 'enumerated' in text_item:
            content_item['enumerated'] = text_item['enumerated']  # 是否属于有序列表
        if 'marker' in text_item:
            content_item['marker'] = text_item['marker']          # 列表标记符号（如 '•'、'1.'）
            
        return content_item                     # 返回构建好的内容项
    
    def assemble_content(self, data):
        """核心方法：将 Docling 的 body.children 引用链按页码重新组织为 page → content[] 结构"""
        pages = {}                              # 页码到页面对象的映射字典
        # 步骤1：展开 groups，将嵌套的分组结构"拍平"
        body_children = data['body']['children']  # 获取文档主体内容引用列表
        groups = data.get('groups', [])           # 获取分组列表（空列表兜底）
        expanded_body_children = self.expand_groups(body_children, groups)  # 展开 groups

        # 步骤2：遍历展开后的 children，按引用类型分发到对应页码
        for item in expanded_body_children:
            if isinstance(item, dict) and '$ref' in item:  # 检查是否为 $ref 引用
                ref = item['$ref']                         # 获取引用字符串
                ref_type, ref_num = ref.split('/')[-2:]     # 解析类型和编号
                ref_num = int(ref_num)                      # 编号转整数

                if ref_type == 'texts':                    # ─── 处理文本引用 ───
                    text_item = data['texts'][ref_num]      # 获取文本项
                    content_item = self._process_text_reference(ref_num, data)  # 加工为标准化内容项

                    # 如果该 item 是从 group 展开来的，附加 group 信息
                    if 'group_id' in item:
                        content_item['group_id'] = item['group_id']         # 所属分组 ID
                        content_item['group_name'] = item['group_name']      # 所属分组名称
                        content_item['group_label'] = item['group_label']    # 所属分组标签

                    # 从 prov（溯源信息）中提取页码
                    if 'prov' in text_item and text_item['prov']:
                        page_num = text_item['prov'][0]['page_no']  # 取第一个溯源记录的页码

                        if page_num not in pages:             # 如果该页码尚未初始化
                            pages[page_num] = {
                                'page': page_num,              # 页码
                                'content': [],                 # 内容列表（初始为空）
                                'page_dimensions': text_item['prov'][0].get('bbox', {})  # 页面尺寸
                            }

                        pages[page_num]['content'].append(content_item)  # 将内容项归入对应页码

                elif ref_type == 'tables':                   # ─── 处理表格引用 ───
                    table_item = data['tables'][ref_num]      # 获取表格项
                    content_item = {
                        'type': 'table',                      # 标记类型为表格
                        'table_id': ref_num                   # 表格在 tables 数组中的编号
                    }

                    if 'prov' in table_item and table_item['prov']:
                        page_num = table_item['prov'][0]['page_no']  # 提取页码

                        if page_num not in pages:             # 初始化页面
                            pages[page_num] = {
                                'page': page_num,
                                'content': [],
                                'page_dimensions': table_item['prov'][0].get('bbox', {})
                            }

                        pages[page_num]['content'].append(content_item)  # 归入对应页码
                
                elif ref_type == 'pictures':                 # ─── 处理图片引用 ───
                    picture_item = data['pictures'][ref_num]  # 获取图片项
                    content_item = {
                        'type': 'picture',                    # 标记类型为图片
                        'picture_id': ref_num                 # 图片在 pictures 数组中的编号
                    }
                    
                    if 'prov' in picture_item and picture_item['prov']:
                        page_num = picture_item['prov'][0]['page_no']  # 提取页码

                        if page_num not in pages:             # 初始化页面
                            pages[page_num] = {
                                'page': page_num,
                                'content': [],
                                'page_dimensions': picture_item['prov'][0].get('bbox', {})
                            }
                        
                        pages[page_num]['content'].append(content_item)  # 归入对应页码

        # 步骤3：按页码升序排列，返回有序页面列表
        sorted_pages = [pages[page_num] for page_num in sorted(pages.keys())]
        return sorted_pages                                   # 返回按页组织的内容列表

    def assemble_tables(self, tables, data):
        """组装表格数据：将每个表格输出为 Markdown + HTML + 原始 JSON 三种格式"""
        assembled_tables = []                   # 初始化表格列表
        
        for i, table in enumerate(tables):      # 遍历每个表格（同时获取索引 i）
            table_json_obj = table.model_dump() # ① 原始 JSON：完整表格数据（包含所有元数据）
            table_md = self._table_to_md(table_json_obj)  # ② Markdown：转为 GitHub 风格表格（适合 LLM 消费）
            table_html = table.export_to_html()           # ③ HTML：导出 HTML 格式（保留视觉结构、合并单元格等）
            
            table_data = data['tables'][i]      # 从原始数据中获取第 i 个表格的元数据
            table_page_num = table_data['prov'][0]['page_no']  # 表格所在页码
            table_bbox = table_data['prov'][0]['bbox']          # 表格在 PDF 中的边界框坐标
            table_bbox = [                     # 将 bbox 字典转为四元列表 [左, 上, 右, 下]
                table_bbox['l'],               # left（左边界）
                table_bbox['t'],               # top（上边界）
                table_bbox['r'],               # right（右边界）
                table_bbox['b']                # bottom（下边界）
            ]
            
            # 从表格数据中提取行列信息
            nrows = table_data['data']['num_rows']  # 行数
            ncols = table_data['data']['num_cols']  # 列数

            ref_num = table_data['self_ref'].split('/')[-1]  # 从自引用路径中提取编号
            ref_num = int(ref_num)                            # 转为整数

            table_obj = {                       # 构建表格对象
                'table_id': ref_num,            # 表格唯一 ID
                'page': table_page_num,         # 所在页码
                'bbox': table_bbox,             # 边界框坐标 [左, 上, 右, 下]
                '#-rows': nrows,               # 行数
                '#-cols': ncols,               # 列数
                'markdown': table_md,           # Markdown 格式表格
                'html': table_html,             # HTML 格式表格
                'json': table_json_obj          # 原始 JSON 格式表格
            }
            assembled_tables.append(table_obj)  # 加入表格列表
        return assembled_tables                 # 返回所有组装的表格

    def _table_to_md(self, table):
        """将 Docling 的 grid 格式表格转换为 GitHub 风格的 Markdown 表格"""
        # 从 grid（二维网格）中逐格提取 cell['text']，构建二维文本数组
        table_data = []
        for row in table['data']['grid']:       # 遍历每一行
            table_row = [cell['text'] for cell in row]  # 提取该行每个单元格的文本
            table_data.append(table_row)         # 加入表格数据
        
        # 如果表格有至少2行且首行非空，将首行作为表头
        if len(table_data) > 1 and len(table_data[0]) > 0:
            try:
                md_table = tabulate(             # 使用 tabulate 库渲染
                    table_data[1:],              # 数据行（第2行开始）
                    headers=table_data[0],       # 表头（第1行）
                    tablefmt="github"            # GitHub 风格表格格式
                )
            except ValueError:                   # 如果类型推断失败（如混合类型）
                md_table = tabulate(
                    table_data[1:],
                    headers=table_data[0],
                    tablefmt="github",
                    disable_numparse=True,       # 关闭数字解析，全部视为字符串
                )
        else:                                    # 单行或无表头的情况
            md_table = tabulate(table_data, tablefmt="github")  # 不使用表头直接渲染
        
        return md_table                          # 返回 Markdown 表格字符串

    def assemble_pictures(self, data):
        """组装图片信息：提取每个图片的位置坐标和关联文本"""
        assembled_pictures = []                  # 初始化图片列表
        
        for i, picture in enumerate(data['pictures']):  # 遍历每张图片
            children_list = self._process_picture_block(picture, data)  # 提取图片关联的子文本
            
            ref_num = picture['self_ref'].split('/')[-1]  # 从自引用路径提取图片编号
            ref_num = int(ref_num)                        # 转为整数
            
            picture_page_num = picture['prov'][0]['page_no']  # 图片所在页码
            picture_bbox = picture['prov'][0]['bbox']          # 图片边界框坐标
            picture_bbox = [                     # 转为四元列表 [左, 上, 右, 下]
                picture_bbox['l'],               # 左
                picture_bbox['t'],               # 上
                picture_bbox['r'],               # 右
                picture_bbox['b']                # 下
            ]
            
            picture_obj = {                      # 构建图片对象
                'picture_id': ref_num,           # 图片唯一 ID
                'page': picture_page_num,        # 所在页码
                'bbox': picture_bbox,            # 边界框坐标
                'children': children_list,       # 关联的文本内容（如图注、说明）
            }
            assembled_pictures.append(picture_obj)  # 加入图片列表
        return assembled_pictures                # 返回所有组装的图片信息
    
    def _process_picture_block(self, picture, data):
        """处理图片块：提取图片内部的文本引用（如图注 caption）"""
        children_list = []                       # 初始化子文本列表
        
        for item in picture['children']:         # 遍历图片的子元素
            if isinstance(item, dict) and '$ref' in item:  # 检查是否为 $ref 引用
                ref = item['$ref']               # 获取引用字符串
                ref_type, ref_num = ref.split('/')[-2:]  # 解析类型和编号
                ref_num = int(ref_num)            # 编号转整数
                
                if ref_type == 'texts':           # 仅处理文本引用
                    content_item = self._process_text_reference(ref_num, data)  # 复用通用文本处理方法
                    children_list.append(content_item)  # 加入子文本列表

        return children_list                      # 返回图片的子文本内容列表

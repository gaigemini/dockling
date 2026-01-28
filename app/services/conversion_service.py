import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, List, Union

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.page_chunker import PageChunker
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
from docling_core.types.doc.base import ImageRefMode
from docling_core.types.doc.document import DoclingDocument
import tiktoken

from config import settings
from .base_service import BaseService
from ..models import ApiResponse, ChunkType, OutputType

def create_document_converter(enable_ocr: bool = False, ocr_langs: list[str] = None, num_threads: int = 6) -> DocumentConverter:
    """Create and configure DocumentConverter with multiple format support"""
    if ocr_langs is None:
        ocr_langs = [lang.strip() for lang in settings.DEFAULT_OCR_LANGS.split(',')]
    
    # Create and configure pipeline options
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = enable_ocr
    pipeline_options.do_table_structure = True
    pipeline_options.table_structure_options.do_cell_matching = True
    pipeline_options.ocr_options.lang = ocr_langs
    pipeline_options.accelerator_options = AcceleratorOptions(
        num_threads=num_threads, device=AcceleratorDevice.AUTO
    )

    # Create document converter with multiple format support
    converter = DocumentConverter(
        allowed_formats=[
            InputFormat.PDF,
            InputFormat.IMAGE,
            InputFormat.DOCX,
            InputFormat.HTML,
            InputFormat.PPTX,
            InputFormat.XLSX,
            InputFormat.ASCIIDOC,
            InputFormat.CSV,
            InputFormat.MD,
        ],
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
        }
    )

    return converter

class ConversionService(BaseService):
    def __init__(self, logger):
        super().__init__(logger)
        self.converter = None
        self._executor = ThreadPoolExecutor(max_workers=4)

    async def initialize_converter(self, enable_ocr: bool = False, ocr_langs: list[str] = None):
        """Initialize DocumentConverter with multiple format support"""
        self.logger.info(f"Initializing converter with OCR: {enable_ocr}")
        
        try:
            def _init():
                self.converter = create_document_converter(enable_ocr, ocr_langs)
                return True

            success = await asyncio.get_event_loop().run_in_executor(
                self._executor, _init
            )
            self.logger.info("Docling converter initialized successfully")
            return success
        except Exception as e:
            self.logger.error(f"Failed to initialize Docling converter: {str(e)}", exc_info=True)
            try:
                def _fallback_init():
                    self.converter = DocumentConverter()
                    return True

                success = await asyncio.get_event_loop().run_in_executor(
                    self._executor, _fallback_init
                )
                self.logger.info("Docling converter initialized with default settings")
                return success
            except Exception as fallback_error:
                self.logger.error(f"Fallback initialization failed: {str(fallback_error)}", exc_info=True)
                return False

    async def convert(self, file_path: str, output_type: OutputType = OutputType.MARKDOWN) -> ApiResponse:
        """Async method to convert document"""
        self.logger.info(f"Starting document conversion: {file_path}", extra={
            "output_type": output_type,
            "file_path": file_path
        })
        
        try:
            result = await asyncio.get_event_loop().run_in_executor(
                self._executor,
                self._convert_document_sync,
                file_path,
                output_type
            )
            
            if result["success"]:
                self.logger.info("Document converted successfully", extra={
                    "processing_time": result["processing_time"],
                    "page_count": result["metadata"].get("page_count")
                })
                return ApiResponse(
                    status=0,
                    message="Document converted successfully",
                    data={
                        "content": result["content"],
                        "processing_time": result["processing_time"],
                        "metadata": result.get("metadata", {})
                    }
                )
            else:
                self.logger.error(f"Conversion failed: {result['error']}")
                return ApiResponse(
                    status=4,
                    message=result["error"],
                    data=None
                )
        except Exception as e:
            self.logger.error(f"Conversion error: {str(e)}", exc_info=True)
            return ApiResponse(
                status=4,
                message=f"Document conversion failed: {str(e)}",
                data=None
            )

    def _convert_document_sync(self, source: Union[Path, str, DocumentStream], output_type: OutputType = OutputType.MARKDOWN) -> Dict[str, Any]:
        """Synchronous implementation of document conversion"""
        start_time = time.time()

        try:
            if not self.converter:
                self.converter = create_document_converter()

            result = self.converter.convert(source)
            processing_time = time.time() - start_time

            # Extract content based on output type
            if output_type == OutputType.PLAINTEXT:
                content = result.document.export_to_text()
            elif output_type == OutputType.HTML:
                content = result.document.export_to_html()
            else:  # default to markdown
                content = result.document.export_to_markdown(
                    image_mode=ImageRefMode.EMBEDDED
                )

            # Basic metadata
            metadata = {
                "page_count": len(result.document.pages) if hasattr(result.document, 'pages') else None,
                "file_type": getattr(source, 'name', str(source)).split('.')[-1] if hasattr(source, 'name') else str(source).split('.')[-1]
            }

            return {
                "success": True,
                "content": content,
                "processing_time": round(processing_time, 2),
                "metadata": metadata,
                "document": result.document
            }

        except Exception as e:
            self.logger.error(f"Sync conversion error: {str(e)}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "processing_time": time.time() - start_time
            }

    async def chunk(self, document: DoclingDocument, max_tokens: int = None, chunk_type: ChunkType = ChunkType.HYBRID) -> ApiResponse:
        """Async method to chunk document into token-limited chunks"""
        if max_tokens is None:
            max_tokens = settings.MAX_TOKENS
            
        self.logger.info("Starting document chunking", extra={
            "max_tokens": max_tokens,
            "chunk_type": chunk_type
        })
        
        start_time = time.time()

        def _chunk_sync():
            try:
                # Initialize tokenizer
                tokenizer = OpenAITokenizer(
                    tokenizer=tiktoken.encoding_for_model("gpt-4o"),
                    max_tokens=max_tokens
                )

                # Initialize chunker based on type
                if chunk_type == ChunkType.PAGE:
                    chunker = PageChunker()
                elif chunk_type == ChunkType.HIERARCHICAL:
                    chunker = HierarchicalChunker()
                else:  # HYBRID
                    chunker = HybridChunker(tokenizer=tokenizer)

                # Generate chunks
                chunk_iter = chunker.chunk(dl_doc=document)

                # Process chunks
                chunks = []
                for i, chunk in enumerate(chunk_iter):
                    enriched_text = chunker.contextualize(chunk=chunk)
                    token_count = tokenizer.count_tokens(enriched_text) if enriched_text else 0
                    
                    chunks.append({
                        "chunk_id": i,
                        "enriched_text": enriched_text,
                        "token_count": token_count,
                        "content": enriched_text
                    })

                return chunks
            except Exception as e:
                self.logger.error(f"Chunking error: {str(e)}", exc_info=True)
                raise e

        try:
            chunks = await asyncio.get_event_loop().run_in_executor(
                self._executor, _chunk_sync
            )

            self.logger.info(f"Document chunked successfully", extra={
                "total_chunks": len(chunks),
                "processing_time": time.time() - start_time
            })
            
            return ApiResponse(
                status=0,
                message="Document chunked successfully",
                data={
                    "chunks": chunks,
                    "total_chunks": len(chunks),
                    "processing_time": time.time() - start_time
                }
            )
        except Exception as e:
            self.logger.error(f"Failed to chunk document: {str(e)}", exc_info=True)
            return ApiResponse(
                status=4,
                message=f"Failed to chunk document: {str(e)}",
                data=None
            )

    async def convert_and_chunk(self, file_path: str, max_tokens: int = None, output_type: OutputType = OutputType.MARKDOWN, chunk_type: ChunkType = ChunkType.HYBRID) -> ApiResponse:
        """Combined method to convert document and chunk it in one operation"""
        if max_tokens is None:
            max_tokens = settings.MAX_TOKENS
            
        self.logger.info("Starting combined conversion and chunking", extra={
            "file_path": file_path,
            "max_tokens": max_tokens,
            "output_type": output_type,
            "chunk_type": chunk_type
        })
        
        start_time = time.time()
        
        # Convert document
        conversion_result = await self.convert(file_path, output_type)

        if conversion_result.status != 0:
            return conversion_result

        # Chunk document
        chunk_result = await self.chunk(
            conversion_result.data["document"], 
            max_tokens, 
            chunk_type
        )

        if chunk_result.status != 0:
            # Return conversion result even if chunking fails
            self.logger.warning("Chunking failed, returning conversion result only")
            return ApiResponse(
                status=chunk_result.status,
                message=chunk_result.message,
                data={
                    "conversion": {
                        "content": conversion_result.data["content"],
                        "metadata": conversion_result.data["metadata"]
                    },
                    "chunks": [],
                    "total_chunks": 0,
                    "processing_time": time.time() - start_time
                }
            )

        return ApiResponse(
            status=0,
            message="Document converted and chunked successfully",
            data={
                "conversion": {
                    "content": conversion_result.data["content"],
                    "metadata": conversion_result.data["metadata"]
                },
                "chunks": chunk_result.data["chunks"],
                "total_chunks": chunk_result.data["total_chunks"],
                "processing_time": time.time() - start_time
            }
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._executor:
            self._executor.shutdown(wait=True)
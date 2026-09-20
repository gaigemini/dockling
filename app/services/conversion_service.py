"""Document conversion service using Docling."""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from docling.datamodel.accelerator_options import AcceleratorDevice, AcceleratorOptions
from docling.datamodel.base_models import DocumentStream, InputFormat
from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling_core.transforms.chunker.hierarchical_chunker import HierarchicalChunker
from docling_core.transforms.chunker.hybrid_chunker import HybridChunker
from docling_core.transforms.chunker.page_chunker import PageChunker
from docling_core.transforms.chunker.tokenizer.openai import OpenAITokenizer
from docling_core.types.doc.base import ImageRefMode
from docling_core.types.doc.document import DoclingDocument
import tiktoken

from config import settings
from app.models.api_response import ApiResponse
from app.models.document_model import ChunkType, OutputType
from .base_service import BaseService


def create_document_converter(
    enable_ocr: bool = False,
    ocr_langs: Optional[list[str]] = None,
    num_threads: Optional[int] = None,
    generate_picture_images: bool = False,
    table_mode: Optional[str] = None,
    generate_table_images: bool = False
) -> DocumentConverter:
    """Create and configure DocumentConverter with multiple format support.

    Args:
        enable_ocr: Enable OCR for scanned documents.
        ocr_langs: List of OCR language codes.
        num_threads: Number of threads for model inference.
        generate_picture_images: Extract and embed picture images from PDF.
        table_mode: TableFormer mode - "accurate" (default) or "fast".
        generate_table_images: Generate table images alongside structure (uses generate_page_images).
    """
    if ocr_langs is None:
        ocr_langs = [lang.strip() for lang in settings.DEFAULT_OCR_LANGS.split(',')]
    if num_threads is None:
        num_threads = settings.CONVERTER_NUM_THREADS
    if table_mode is None:
        table_mode = settings.TABLE_STRUCTURE_MODE

    # Create and configure pipeline options
    pipeline_options = PdfPipelineOptions()
    pipeline_options.do_ocr = enable_ocr
    pipeline_options.do_table_structure = settings.ENABLE_TABLE_STRUCTURE
    pipeline_options.table_structure_options.do_cell_matching = settings.ENABLE_CELL_MATCHING
    pipeline_options.ocr_options.lang = ocr_langs
    pipeline_options.generate_picture_images = generate_picture_images

    # Table extraction mode: ACCURATE (better quality) or FAST (faster processing)
    if table_mode.lower() == "fast":
        pipeline_options.table_structure_options.mode = TableFormerMode.FAST
    else:
        pipeline_options.table_structure_options.mode = TableFormerMode.ACCURATE

    # Generate page images so tables/figures can be extracted as images post-conversion
    if generate_table_images:
        pipeline_options.generate_page_images = True

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


_shared_executor: Optional[ThreadPoolExecutor] = None


def get_shared_executor() -> ThreadPoolExecutor:
    """Get or create the shared thread pool executor."""
    global _shared_executor
    if _shared_executor is None:
        _shared_executor = ThreadPoolExecutor(max_workers=settings.THREAD_POOL_SIZE)
    return _shared_executor


def shutdown_shared_executor():
    """Shutdown the shared thread pool executor."""
    global _shared_executor
    if _shared_executor is not None:
        _shared_executor.shutdown(wait=True)
        _shared_executor = None


class ConversionService(BaseService):
    """Service for document conversion and chunking."""

    def __init__(self, logger=None) -> None:
        super().__init__(logger)
        self.converter: Optional[DocumentConverter] = None
        self._executor = get_shared_executor()
        # Converter instances cached by configuration key, so the startup
        # pre-warm is reused instead of rebuilding heavy models per request.
        self._converters: Dict[tuple, DocumentConverter] = {}
        self._init_lock = asyncio.Lock()

    async def initialize_converter(
        self,
        enable_ocr: bool = False,
        ocr_langs: Optional[list[str]] = None,
        logger=None,
        generate_picture_images: bool = False,
        table_mode: Optional[str] = None,
        generate_table_images: bool = False
    ) -> Optional[DocumentConverter]:
        """Return the (cached) DocumentConverter for the given configuration.

        Builds the converter on first use per configuration key and reuses it
        afterwards, so concurrent requests with the same options no longer
        rebuild the model pipeline. Returns the converter instance so callers
        can pin it for the duration of their conversion.

        Args:
            enable_ocr: Enable OCR for scanned documents.
            ocr_langs: OCR language codes.
            logger: Logger instance.
            generate_picture_images: Extract and embed picture images.
            table_mode: TableFormer mode - "accurate" (default) or "fast".
            generate_table_images: Generate table images alongside structure.

        Returns:
            The converter to use for this request, or ``None`` when both the
            primary and the fallback initialization failed.
        """
        log = logger or self.logger
        cache_key = (
            bool(enable_ocr),
            tuple(ocr_langs) if ocr_langs else None,
            bool(generate_picture_images),
            table_mode,
            bool(generate_table_images),
        )

        cached = self._converters.get(cache_key)
        if cached is not None:
            self.converter = cached
            return cached

        async with self._init_lock:
            # Re-check after acquiring the lock (another caller may have built it)
            cached = self._converters.get(cache_key)
            if cached is not None:
                self.converter = cached
                return cached

            log.info(
                f"Initializing converter with OCR: {enable_ocr}, "
                f"generate_picture_images: {generate_picture_images}, "
                f"table_mode: {table_mode}, generate_table_images: {generate_table_images}"
            )

            def _init() -> DocumentConverter:
                return create_document_converter(
                    enable_ocr,
                    ocr_langs,
                    generate_picture_images=generate_picture_images,
                    table_mode=table_mode,
                    generate_table_images=generate_table_images,
                )

            try:
                converter = await asyncio.get_running_loop().run_in_executor(
                    self._executor, _init
                )
            except Exception as e:
                log.error(f"Failed to initialize Docling converter: {str(e)}", exc_info=True)
                try:
                    converter = await asyncio.get_running_loop().run_in_executor(
                        self._executor, DocumentConverter
                    )
                    log.info("Docling converter initialized with default settings")
                except Exception as fallback_error:
                    log.error(
                        f"Fallback initialization failed: {str(fallback_error)}",
                        exc_info=True,
                    )
                    return None

            self._converters[cache_key] = converter
            self.converter = converter
            log.info("Docling converter initialized successfully")
            return converter

    async def convert(
        self,
        file_path: str,
        output_type: OutputType = OutputType.MARKDOWN,
        page_range: Optional[Tuple[int, int]] = None,
        image_mode: Optional[ImageRefMode] = None,
        logger=None,
        converter: Optional[DocumentConverter] = None,
    ) -> ApiResponse:
        """Async method to convert document from file path.

        Args:
            file_path: Path to the document file.
            output_type: Desired output format.
            page_range: Optional (start, end) 1-based page range (inclusive).
            image_mode: Image reference mode for markdown export.
            logger: Logger instance.
        """
        log = logger or self.logger
        log.info(f"Starting document conversion: {file_path}", extra={
            "output_type": output_type,
            "file_path": file_path
        })

        try:
            result = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                self._convert_document_sync,
                file_path,
                output_type,
                page_range,
                image_mode,
                converter,
            )

            if result["success"]:
                log.info("Document converted successfully", extra={
                    "processing_time": result["processing_time"],
                    "page_count": result["metadata"].get("page_count"),
                    "page_range": page_range
                })
                return ApiResponse.success(
                    data={
                        "content": result["content"],
                        "processing_time": result["processing_time"],
                        "metadata": result.get("metadata", {})
                    }
                )
            else:
                log.error(f"Conversion failed: {result['error']}")
                return ApiResponse.error(error_message=result["error"])
        except Exception as e:
            log.error(f"Conversion error: {str(e)}", exc_info=True)
            return ApiResponse.error(
                error_message=f"Document conversion failed: {str(e)}"
            )

    async def convert_stream(
        self,
        file_content: BytesIO,
        filename: str,
        output_type: OutputType = OutputType.MARKDOWN,
        page_range: Optional[Tuple[int, int]] = None,
        image_mode: Optional[ImageRefMode] = None,
        logger=None,
        converter: Optional[DocumentConverter] = None,
    ) -> ApiResponse:
        """Convert document from in-memory bytes stream using DocumentStream (no disk write).

        Args:
            file_content: In-memory bytes stream of the document.
            filename: Original filename for format detection.
            output_type: Desired output format.
            page_range: Optional (start, end) 1-based page range (inclusive).
            image_mode: Image reference mode for markdown export.
            logger: Logger instance.
        """
        log = logger or self.logger
        log.info(f"Starting document conversion from stream: {filename}", extra={
            "output_type": output_type,
            "filename": filename
        })

        try:
            source = DocumentStream(name=filename, stream=file_content)
            result = await asyncio.get_running_loop().run_in_executor(
                self._executor,
                self._convert_document_sync,
                source,
                output_type,
                page_range,
                image_mode,
                converter,
            )

            if result["success"]:
                log.info("Document converted successfully from stream", extra={
                    "processing_time": result["processing_time"],
                    "page_count": result["metadata"].get("page_count")
                })
                return ApiResponse.success(
                    data={
                        "content": result["content"],
                        "processing_time": result["processing_time"],
                        "metadata": result.get("metadata", {})
                    }
                )
            else:
                log.error(f"Stream conversion failed: {result['error']}")
                return ApiResponse.error(error_message=result["error"])
        except Exception as e:
            log.error(f"Stream conversion error: {str(e)}", exc_info=True)
            return ApiResponse.error(
                error_message=f"Document conversion failed: {str(e)}"
            )

    def _convert_document_sync(
        self,
        source: Union[Path, str, DocumentStream],
        output_type: OutputType = OutputType.MARKDOWN,
        page_range: Optional[Tuple[int, int]] = None,
        image_mode: Optional[ImageRefMode] = None,
        converter: Optional[DocumentConverter] = None
    ) -> Dict[str, Any]:
        """Synchronous implementation of document conversion.

        Args:
            source: File path, URL, or DocumentStream.
            output_type: Desired output format.
            page_range: Optional (start, end) 1-based page range (inclusive).
            image_mode: Image reference mode for markdown export (default: EMBEDDED).
        """
        start_time = time.time()

        try:
            active_converter = converter or self.converter
            if not active_converter:
                active_converter = create_document_converter()
                self.converter = active_converter

            convert_kwargs: Dict[str, Any] = {}
            if page_range is not None:
                convert_kwargs["page_range"] = page_range

            result = active_converter.convert(source, **convert_kwargs)
            processing_time = time.time() - start_time

            # Extract content based on output type
            if output_type == OutputType.PLAINTEXT:
                content = result.document.export_to_text()
            elif output_type == OutputType.HTML:
                content = result.document.export_to_html()
            else:  # default to markdown
                resolved_image_mode = image_mode if image_mode is not None else ImageRefMode.EMBEDDED
                content = result.document.export_to_markdown(
                    image_mode=resolved_image_mode
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

    async def chunk(
        self,
        document: DoclingDocument,
        max_tokens: Optional[int] = None,
        chunk_type: ChunkType = ChunkType.HYBRID,
        logger=None
    ) -> ApiResponse:
        """Async method to chunk document into token-limited chunks."""
        log = logger or self.logger
        if max_tokens is None:
            max_tokens = settings.MAX_TOKENS

        log.info("Starting document chunking", extra={
            "max_tokens": max_tokens,
            "chunk_type": chunk_type
        })

        start_time = time.time()

        def _chunk_sync() -> List[Dict[str, Any]]:
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
                log.error(f"Chunking error: {str(e)}", exc_info=True)
                raise e

        try:
            chunks = await asyncio.get_running_loop().run_in_executor(
                self._executor, _chunk_sync
            )

            log.info("Document chunked successfully", extra={
                "total_chunks": len(chunks),
                "processing_time": time.time() - start_time
            })

            return ApiResponse.success(
                data={
                    "chunks": chunks,
                    "total_chunks": len(chunks),
                    "processing_time": time.time() - start_time
                }
            )
        except Exception as e:
            log.error(f"Failed to chunk document: {str(e)}", exc_info=True)
            return ApiResponse.error(
                error_message=f"Failed to chunk document: {str(e)}"
            )

    async def convert_and_chunk(
        self,
        file_path: str,
        max_tokens: Optional[int] = None,
        output_type: OutputType = OutputType.MARKDOWN,
        chunk_type: ChunkType = ChunkType.HYBRID,
        page_range: Optional[Tuple[int, int]] = None,
        image_mode: Optional[ImageRefMode] = None,
        logger=None,
        converter: Optional[DocumentConverter] = None,
    ) -> ApiResponse:
        """Combined method to convert document from path and chunk it in one operation.

        Args:
            file_path: Path to the document file.
            max_tokens: Maximum tokens per chunk.
            output_type: Desired output format.
            chunk_type: Chunking strategy.
            page_range: Optional (start, end) 1-based page range (inclusive).
            image_mode: Image reference mode for markdown export.
            logger: Logger instance.
        """
        log = logger or self.logger
        if max_tokens is None:
            max_tokens = settings.MAX_TOKENS

        log.info("Starting combined conversion and chunking", extra={
            "file_path": file_path,
            "max_tokens": max_tokens,
            "output_type": output_type,
            "chunk_type": chunk_type
        })

        start_time = time.time()

        conversion_result = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            self._convert_document_sync,
            file_path,
            output_type,
            page_range,
            image_mode,
            converter,
        )

        if not conversion_result["success"]:
            return ApiResponse.error(error_message=conversion_result["error"])

        # Chunk document
        chunk_result = await self.chunk(
            conversion_result["document"],
            max_tokens,
            chunk_type
        )

        if chunk_result.is_error():
            # Return conversion result even if chunking fails
            log.warning("Chunking failed, returning conversion result only")
            return ApiResponse.error(
                error_message=chunk_result.error_message,
                data={
                    "conversion": {
                        "content": conversion_result["content"],
                        "metadata": conversion_result["metadata"]
                    },
                    "chunks": [],
                    "total_chunks": 0,
                    "processing_time": time.time() - start_time
                }
            )

        return ApiResponse.success(
            data={
                "conversion": {
                    "content": conversion_result["content"],
                    "metadata": conversion_result["metadata"]
                },
                "chunks": chunk_result.data["chunks"],
                "total_chunks": chunk_result.data["total_chunks"],
                "processing_time": time.time() - start_time
            }
        )

    async def convert_and_chunk_stream(
        self,
        file_content: BytesIO,
        filename: str,
        max_tokens: Optional[int] = None,
        output_type: OutputType = OutputType.MARKDOWN,
        chunk_type: ChunkType = ChunkType.HYBRID,
        page_range: Optional[Tuple[int, int]] = None,
        image_mode: Optional[ImageRefMode] = None,
        logger=None,
        converter: Optional[DocumentConverter] = None,
    ) -> ApiResponse:
        """Combined method to convert document from stream and chunk it (no disk write).

        Args:
            file_content: In-memory bytes stream of the document.
            filename: Original filename for format detection.
            max_tokens: Maximum tokens per chunk.
            output_type: Desired output format.
            chunk_type: Chunking strategy.
            page_range: Optional (start, end) 1-based page range (inclusive).
            image_mode: Image reference mode for markdown export.
            logger: Logger instance.
        """
        log = logger or self.logger
        if max_tokens is None:
            max_tokens = settings.MAX_TOKENS

        log.info("Starting combined stream conversion and chunking", extra={
            "filename": filename,
            "max_tokens": max_tokens,
            "output_type": output_type,
            "chunk_type": chunk_type
        })

        start_time = time.time()

        source = DocumentStream(name=filename, stream=file_content)
        conversion_result = await asyncio.get_running_loop().run_in_executor(
            self._executor,
            self._convert_document_sync,
            source,
            output_type,
            page_range,
            image_mode,
            converter,
        )

        if not conversion_result["success"]:
            return ApiResponse.error(error_message=conversion_result["error"])

        # Chunk document
        chunk_result = await self.chunk(
            conversion_result["document"],
            max_tokens,
            chunk_type
        )

        if chunk_result.is_error():
            log.warning("Chunking failed, returning conversion result only")
            return ApiResponse.error(
                error_message=chunk_result.error_message,
                data={
                    "conversion": {
                        "content": conversion_result["content"],
                        "metadata": conversion_result["metadata"]
                    },
                    "chunks": [],
                    "total_chunks": 0,
                    "processing_time": time.time() - start_time
                }
            )

        return ApiResponse.success(
            data={
                "conversion": {
                    "content": conversion_result["content"],
                    "metadata": conversion_result["metadata"]
                },
                "chunks": chunk_result.data["chunks"],
                "total_chunks": chunk_result.data["total_chunks"],
                "processing_time": time.time() - start_time
            }
        )
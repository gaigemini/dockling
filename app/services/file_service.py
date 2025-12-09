import os
import aiofiles
import re
from datetime import datetime
from fastapi import UploadFile, HTTPException
import magic
from typing import Set
from config import settings
from .base_service import BaseService

class FileService(BaseService):
    def __init__(self, logger):
        super().__init__(logger)
        self.upload_dir = settings.UPLOAD_DIR
        self.supported_formats = set(settings.SUPPORTED_FORMATS.split(','))
        os.makedirs(self.upload_dir, exist_ok=True)

    async def save_upload_file(self, file: UploadFile) -> str:
        """Save uploaded file and return file path"""
        self.logger.info(f"Processing file upload: {file.filename}")
        
        try:
            # Validate file type
            content = await file.read(1024)
            await file.seek(0)  # Reset file pointer

            file_type = magic.from_buffer(content, mime=True)
            
            # Check if file type is supported
            is_supported = any(
                supported_format.endswith('/*') and file_type.startswith(supported_format[:-2])
                or file_type == supported_format
                for supported_format in self.supported_formats
            )
            
            if not is_supported:
                self.logger.warning(f"Unsupported file type: {file_type}")
                raise HTTPException(
                    status_code=400,
                    detail=f"Unsupported file type: {file_type}. Supported: {self.supported_formats}"
                )

            # Generate safe filename
            safe_filename = self._get_safe_filename(file.filename)
            file_path = os.path.join(self.upload_dir, safe_filename)

            # Save file
            async with aiofiles.open(file_path, 'wb') as f:
                while chunk := await file.read(8192):  # 8KB chunks
                    await f.write(chunk)

            self.logger.info(f"File saved successfully: {safe_filename}", extra={
                "file_size": os.path.getsize(file_path),
                "file_type": file_type
            })
            return file_path

        except HTTPException:
            raise
        except Exception as e:
            self.logger.error(f"Error saving file: {str(e)}", exc_info=True)
            raise HTTPException(
                status_code=500, detail=f"Error saving file: {str(e)}")

    def _get_safe_filename(self, filename: str) -> str:
        """Generate safe filename"""
        # Remove path separators and keep only filename
        name = os.path.basename(filename)
        # Replace unsafe characters
        name = re.sub(r'[^\w\.-]', '_', name)
        # Add timestamp to avoid collisions
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        name, ext = os.path.splitext(name)
        return f"{name}_{timestamp}{ext}"

    def cleanup_file(self, file_path: str):
        """Remove temporary file"""
        try:
            if os.path.exists(file_path):
                os.remove(file_path)
                self.logger.info(f"Cleaned up file: {file_path}")
        except Exception as e:
            self.logger.warning(f"Could not cleanup file {file_path}: {str(e)}")
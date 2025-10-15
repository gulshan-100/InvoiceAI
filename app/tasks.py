from celery import shared_task
from .utils.invoice_processor import process_invoice
from .utils.store_database import store_invoice_data
import tempfile
import os

@shared_task
def process_invoice_async(file_content, filename):
    """
    Background task to process an invoice file and store its data.
    
    Args:
        file_content (bytes): Binary content of the invoice file
        filename (str): Original filename for reference
    
    Returns:
        dict: Processed invoice data
    """
    temp_file = None
    try:
        # Create a temporary file
        temp_file = tempfile.NamedTemporaryFile(delete=False, suffix=".jpg")
        temp_file.write(file_content)
        temp_file.flush()
        temp_file.close()  # Close the file so it can be opened by other processes
        
        # Create a simple file-like object
        class SimpleUploadedFile:
            def __init__(self, name, path):
                self.name = name
                self._path = path
            
            def read(self):
                with open(self._path, 'rb') as f:
                    content = f.read()
                    if not content:
                        raise ValueError(f"Empty file at {self._path}")
                    return content
                    
            def chunks(self):
                with open(self._path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)
                        if not chunk:
                            break
                        yield chunk
                        
            def seek(self, position):
                # Adding seek method for compatibility
                pass
        
        # Create a file object for processing
        file_obj = SimpleUploadedFile(filename, temp_file.name)
        
        # Verify the file is readable and not empty
        test_content = file_obj.read()
        if not test_content:
            raise ValueError(f"Empty file content for {filename}")
        
        # Process the invoice
        processed_data, raw_text = process_invoice(file_obj)
        return processed_data
        
    except Exception as e:
        return {"error": str(e), "filename": filename}
        
    finally:
        # Clean up temporary file
        if temp_file and os.path.exists(temp_file.name):
            try:
                os.remove(temp_file.name)
            except Exception:
                pass
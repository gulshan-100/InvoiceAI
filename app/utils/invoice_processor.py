

"""Invoice processing using langchain/langgraph for OCR and parsing.

This module provides a simple API:
- process_invoice(uploaded_file) -> (parsed_json, raw_text)
  Takes a Django UploadedFile, processes it through OCR and parsing,
  and returns the structured data + raw text.

Environment variables:
- OPENAI_API_KEY: Required for GPT-4o OCR and parsing
- MAX_RETRIES: Optional, default 3
- BACKOFF_BASE: Optional, default 1.0
"""

import os
import re
import json
import time
import tempfile
import logging
from typing import Tuple, Optional, Dict, Any, List
import base64

from dotenv import load_dotenv
load_dotenv()

from langchain_openai import ChatOpenAI
from langchain.agents import Tool
from langgraph.graph import StateGraph
from typing import TypedDict

from . import store_database

logger = logging.getLogger(__name__)


# LLM initialization
llm = ChatOpenAI(
    model="gpt-4o", 
    temperature=0,
    api_key=os.getenv("OPENAI_API_KEY")
)


def _retry_invoke(payload_callable, max_retries: int = 3, base_backoff: float = 1.0):
    """Call a function that invokes the LLM, with retries/backoff on 429s/temporary errors.

    payload_callable should be a zero-arg callable that performs the llm.invoke call.
    """
    for attempt in range(1, max_retries + 1):
        try:
            return payload_callable()
        except Exception as e:
            msg = str(e)
            # Treat rate-limit-like errors as retryable
            if "429" in msg or "Too Many Requests" in msg or attempt < max_retries:
                backoff = base_backoff * (2 ** (attempt - 1))
                logger.warning("LLM invoke failed (attempt %s/%s): %s — backing off %.1fs", attempt, max_retries, msg, backoff)
                time.sleep(backoff)
                continue
            raise


def encode_image_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        file_content = f.read()
        # Ensure we're not trying to encode an empty file
        if not file_content:
            raise ValueError(f"Empty file at {path}")
        return base64.b64encode(file_content).decode("utf-8")


def ocr_extract_text(image_path: str) -> str:
    # Build payload callable for retry wrapper
    def _call():
        image_base64 = encode_image_to_base64(image_path)
        messages = [
            {"role": "system", "content": "You are an OCR assistant that extracts text accurately from invoices."},
            {"role": "user", "content": [
                {"type": "text", "text": "Extract all visible text from this invoice image."},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
            ]}
        ]
        response = llm.invoke(messages)
        # support response.content or str(response)
        return getattr(response, "content", str(response)).strip()

    return _retry_invoke(_call)


def parse_invoice_data(raw_text: str) -> dict:
    prompt = f"""
You are an expert invoice parser.
From the following invoice text, extract the following structured information as valid JSON only:

{{
  "Vendor Details": {{
    "Name": "",
    "Address": "",
    "Tax Number": "",
    "Phone Number": ""
  }},
  "Invoice Details": {{
    "Invoice Number": "",
    "Invoice Date": "",
    "Type of Invoice": ""
  }},
  "Invoice Items": [
    {{
      "Name": "",
      "Quantity": "",
      "HSN_SAC_code": "",
      "Rate": ""
    }}
  ],
  "Overall": {{
    "Total Invoice Value": "",
    "GST Value": ""
  }}
}}

Only return valid JSON. No markdown formatting or explanations.
Here is the extracted text:
{raw_text}
"""

    def _call():
        response = llm.invoke(prompt)
        return getattr(response, "content", str(response)).strip()

    content = _retry_invoke(_call)
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content).strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "Could not parse JSON", "raw": content}


# Tools (kept for compatibility with graph usage)
ocr_tool = Tool(name="OCRExtractor", func=ocr_extract_text, description="Extracts text content from an invoice image.")
parse_tool = Tool(name="InvoiceParser", func=parse_invoice_data, description="Parses OCR text into structured invoice fields.")


class InvoiceState(TypedDict):
    image_path: str
    raw_text: str
    invoice_data: dict
    error: Optional[str]  # To store validation errors


def step_ocr(state: InvoiceState):
    # Call the OCR tool directly (Tool.run may differ between langchain versions)
    text = ocr_extract_text(state["image_path"])
    return {"raw_text": text}


def step_parse(state: InvoiceState):
    data = parse_invoice_data(state["raw_text"])
    return {"invoice_data": data}


def validate_invoice(invoice_data: dict, raw_text: str) -> str:
    """Use LLM to validate invoice data and check for errors."""
    prompt = f"""
You are an expert invoice validator. Your task is to thoroughly validate this invoice and automatically reject it if you find any errors.
Focus specifically on these critical validations:

1. Calculations Validation:
   - Calculate sum of (Quantity × Rate) for all items
   - Compare calculated sum with the Total Invoice Value
   - Verify GST calculations (check if GST Value matches applicable rate)
   - Flag any mathematical discrepancies

2. Vendor Information Validation:
   - Check if vendor name is complete and legitimate (no generic terms)
   - Verify address format and completeness (should have street, city, postal code)
   - Validate tax number format (GST/VAT number)
   - Flag missing or suspicious vendor details

3. Invoice Items Validation:
   - Check if item names are specific and clear (not generic)
   - Verify HSN/SAC codes format
   - Validate if quantities and rates are reasonable
   - Flag any suspicious or invalid items

Return your findings in this exact format:
- If valid: just return "VALID"
- If invalid, return the error in this format: "ERROR: [Category] - [Specific Issue]"
Examples of error messages:
- "ERROR: Calculations - Total amount (₹5000) does not match sum of items (₹4800)"
- "ERROR: GST - Incorrect GST calculation. Expected 18% of ₹5000 (₹900), found ₹800"
- "ERROR: Vendor - Address missing city and postal code"
- "ERROR: Items - Quantity × Rate mismatch for item 'Office Supplies'"

Invoice Data to Validate:
{json.dumps(invoice_data, indent=2)}

Original Text for Cross-Reference:
{raw_text}

Return ONLY 'VALID' or an error message in the specified format. No other text or explanations.
"""
    def _call():
        response = llm.invoke(prompt)
        return getattr(response, "content", str(response)).strip()

    result = _retry_invoke(_call)
    return "" if result == "VALID" else result


def step_validate(state: InvoiceState):
    """Validate the invoice data for errors."""
    invoice_data = state.get("invoice_data", {})
    raw_text = state.get("raw_text", "")
    
    # Skip validation if we already have an error
    if "error" in invoice_data:
        return {"error": invoice_data["error"]}
        
    error = validate_invoice(invoice_data, raw_text)
    if error:
        invoice_data["error"] = error
        return {"invoice_data": invoice_data, "error": error}
    
    return {"invoice_data": invoice_data, "error": ""}


def step_finalize(state: InvoiceState):
    """Final step that ensures error field is included."""
    data = state.get("invoice_data", {})
    error = state.get("error", "")
    if error:
        data["error"] = error
    return {"invoice_data": data}


# Build the state graph workflow
graph = StateGraph(InvoiceState)

# Add all nodes
graph.add_node("OCR", step_ocr)
graph.add_node("PARSE", step_parse)
graph.add_node("VALIDATE", step_validate)
graph.add_node("FINAL", step_finalize)

# Define workflow
graph.add_edge("OCR", "PARSE")
graph.add_edge("PARSE", "VALIDATE")
graph.add_edge("VALIDATE", "FINAL")

graph.set_entry_point("OCR")
app = graph.compile()


				# Build the state graph workflow
# Build the state graph workflow
graph = StateGraph(InvoiceState)
graph.add_node("OCR", step_ocr)
graph.add_node("PARSE", step_parse)
graph.add_node("FINAL", step_finalize)
graph.add_edge("OCR", "PARSE")
graph.add_edge("PARSE", "FINAL")
graph.set_entry_point("OCR")
app = graph.compile()


def process_invoice(uploaded_file) -> Tuple[dict, str]:
    """Process a single invoice file and return (parsed_json, raw_text)."""
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as f:
            tmp = f.name
            # uploaded_file might be Django UploadedFile with chunks()
            if hasattr(uploaded_file, "chunks"):
                for chunk in uploaded_file.chunks():
                    f.write(chunk)
            else:
                # Make sure we're at the beginning of the file
                if hasattr(uploaded_file, "seek"):
                    uploaded_file.seek(0)
                content = uploaded_file.read()
                if not content:
                    raise ValueError(f"Empty file content for {getattr(uploaded_file, 'name', 'unknown file')}")
                f.write(content)
            
            # Flush and close before continuing
            f.flush()

        # invoke the graph using the temp file path
        result = app.invoke({"image_path": tmp})
        parsed = result.get("invoice_data", {})
        raw_text = result.get("raw_text", "")

        # Store result in MongoDB if no errors
        if "error" not in parsed:
            try:
                inserted_id = store_database.store_invoice_data(
                    parsed,
                    source_filename=getattr(uploaded_file, "name", None)
                )
                parsed["_id"] = str(inserted_id)
            except Exception as e:
                logger.exception("Failed to store invoice in MongoDB: %s", e)
                parsed["db_error"] = str(e)

        return parsed, raw_text
    finally:
        # best-effort cleanup
        try:
            if tmp and os.path.exists(tmp):
                os.remove(tmp)
        except Exception:
            logger.exception("Failed to remove temp file %s", tmp)


				
def process_multiple_invoices(files) -> List[Dict[str, Any]]:
    """Process multiple invoice files sequentially.
    
    Args:
        files: List of file-like objects (e.g., Django UploadedFile instances)
        
    Returns:
        List of dicts containing processing results for each file:
        [
            {
                "file_name": str,
                "success": bool,
                "data": dict,  # The parsed and validated invoice data
                "error": str   # Error message if any, empty string if successful
            },
            ...
        ]
    """
    results = []
    
    for file_obj in files:
        file_name = getattr(file_obj, 'name', 'unknown')
        try:
            parsed, raw_text = process_invoice(file_obj)
            
            results.append({
                "file_name": file_name,
                "success": "error" not in parsed,
                "data": parsed,
                "error": parsed.get("error", "")
            })
            
        except Exception as e:
            logger.exception(f"Failed to process file {file_name}")
            results.append({
                "file_name": file_name,
                "success": False,
                "data": {},
                "error": f"Processing failed: {str(e)}"
            })
            
        # Small delay between files to avoid rate limiting
        time.sleep(0.5)
    
    return results


if __name__ == "__main__":
    # Quick CLI test runner
    import sys
    if len(sys.argv) > 1:
        files = []
        for path in sys.argv[1:]:
            if os.path.exists(path):
                files.append(open(path, 'rb'))
            else:
                print(f"Error: Image not found at {path}")
                continue
        
        try:
            results = process_multiple_invoices(files)
            for result in results:
                print(f"\nFile: {result['file_name']}")
                print(f"Success: {result['success']}")
                if result['error']:
                    print(f"Error: {result['error']}")
                else:
                    print("Parsed data:")
                    print(json.dumps(result['data'], indent=2))
        finally:
            for f in files:
                f.close()
    else:
        print("Please provide one or more image paths")
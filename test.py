# --- STEP 1: Imports ---
from langchain_openai import ChatOpenAI
from langchain.agents import Tool
from langgraph.graph import StateGraph
from typing import TypedDict
import base64, json, re, os
from pymongo import MongoClient
from pprint import pprint
from datetime import datetime, timezone

# --- STEP 2: Initialize the LLM ---
from dotenv import load_dotenv
load_dotenv()

llm = ChatOpenAI(
    model="gpt-4o",
    temperature=0,
    api_key=os.getenv('OPENAI_API_KEY')
)

# --- STEP 3: Helper Functions / Tools ---
def encode_image_to_base64(path: str) -> str:
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("utf-8")

def ocr_extract_text(image_path: str) -> str:
    image_base64 = encode_image_to_base64(image_path)
    response = llm.invoke([
        {"role": "system", "content": "You are an OCR assistant that extracts text accurately from invoices."},
        {"role": "user", "content": [
            {"type": "text", "text": "Extract all visible text from this invoice image."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
        ]}
    ])
    return response.content.strip()

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
    response = llm.invoke(prompt)
    content = response.content.strip()
    content = re.sub(r"^```(json)?", "", content)
    content = re.sub(r"```$", "", content)
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        return {"error": "Could not parse JSON", "raw": content}

# --- STEP 4: Register Tools ---
ocr_tool = Tool(name="OCRExtractor", func=ocr_extract_text, description="Extracts text content from an invoice image.")
parse_tool = Tool(name="InvoiceParser", func=parse_invoice_data, description="Parses OCR text into structured invoice fields.")

# --- STEP 5: Define State Schema ---
class InvoiceState(TypedDict):
    image_path: str
    raw_text: str
    invoice_data: dict

# --- STEP 6: Define Workflow Steps ---
def step_ocr(state: InvoiceState):
    text = ocr_tool.run(state["image_path"])
    return {"raw_text": text}

def step_parse(state: InvoiceState):
    data = parse_tool.run(state["raw_text"])
    return {"invoice_data": data}

def step_finalize(state: InvoiceState):
    data = state.get("invoice_data", {})
    return {"invoice_data": data}

# --- STEP 7: Create LangGraph Workflow ---
graph = StateGraph(InvoiceState)
graph.add_node("OCR", step_ocr)
graph.add_node("PARSE", step_parse)
graph.add_node("FINAL", step_finalize)
graph.add_edge("OCR", "PARSE")
graph.add_edge("PARSE", "FINAL")
graph.set_entry_point("OCR")
app = graph.compile()

# --- STEP 8: MongoDB Connection (Updated) ---
from pymongo import MongoClient
from pprint import pprint

# Connect to MongoDB Atlas
client = MongoClient(os.getenv('MONGO_URI'))

# Select your database
db = client.get_database('invoice_ai')

# Select the 'invoices' collection
invoices = db.invoices

# --- STEP 9: Run the Graph and Save Result ---
if __name__ == "__main__":
    # Use absolute path to the image
    image_path = os.path.join(os.path.dirname(__file__), "invoice-sample-1.jpg")
    if not os.path.exists(image_path):
        raise FileNotFoundError(f"Image not found at: {image_path}. Please ensure the image exists in the same directory as this script.")

    # Run the invoice extraction pipeline
    result = app.invoke({"image_path": image_path})
    invoice_data = result["invoice_data"]

    # Insert result into MongoDB
    def sanitize_for_mongo(obj):
        """Recursively sanitize dict keys for MongoDB: replace '.' with '_' and
        avoid keys that start with '$'."""
        if isinstance(obj, dict):
            new = {}
            for k, v in obj.items():
                new_key = k.replace('.', '_')
                if new_key.startswith('$'):
                    new_key = '_' + new_key[1:]
                new[new_key] = sanitize_for_mongo(v)
            return new
        if isinstance(obj, list):
            return [sanitize_for_mongo(i) for i in obj]
        return obj

    sanitized_invoice = sanitize_for_mongo(invoice_data)

    record = {
        "invoice_data": sanitized_invoice,
        "source_image": os.path.basename(image_path),
        "processed_at": datetime.now(timezone.utc)
    }
    insert_result = invoices.insert_one(record)
    print(f"✅ Invoice data saved to MongoDB with _id: {insert_result.inserted_id}")

    # Print the extracted invoice JSON
    print("\n🧾 Extracted Invoice Data:\n")
    print(json.dumps(invoice_data, indent=2))

    # Fetch and display all invoices from the DB
    print("\n📜 Invoices in the 'invoices' collection:\n")
    for invoice in invoices.find():
        pprint(invoice)

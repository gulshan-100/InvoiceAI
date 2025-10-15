# AI Invoice Manager

A Django application that uses AI-powered OCR and GPT models to extract structured data from invoice images, store it in MongoDB, and allow easy viewing and download of processed invoice data.

## Features

- **AI-powered Invoice Processing**: Leverages OpenAI's GPT-4o model for OCR and text extraction
- **Parallel Processing**: Uses Celery for asynchronous processing of multiple invoices simultaneously
- **Structured Data Extraction**: Extracts vendor details, invoice details, line items, and totals
- **Data Validation**: AI-based validation to detect calculation errors and suspicious invoice data
- **MongoDB Storage**: Stores all extracted invoice data in MongoDB for easy querying
- **Modern Web Interface**: Clean, responsive UI for uploading and managing invoices
- **Export to CSV**: Download all invoice data in CSV format for analysis

## Web Interface
<img width="1442" height="857" alt="Screenshot 2025-10-16 035850" src="https://github.com/user-attachments/assets/afd9c624-34f3-4607-ad0e-09bac1a36bd6" />

## Database Storage Sample 
<img width="889" height="512" alt="Screenshot 2025-10-15 145646" src="https://github.com/user-attachments/assets/d3c3fc18-5a94-4424-84eb-2f66c49935cf" />


## Technology Stack

- **Backend**: Django, Celery
- **AI Processing**: OpenAI GPT-4o, LangChain, LangGraph
- **Database**: MongoDB
- **Queue/Task Management**: Redis
- **Frontend**: HTML, CSS, JavaScript

## System Architecture

The application follows a modern architecture:

1. **Web Interface**: Allows uploading one or more invoice images
2. **Asynchronous Processing**: Delegates heavy processing to Celery workers
3. **AI Pipeline**:
   - OCR text extraction from invoice images
   - Structured data parsing from raw text
   - Invoice data validation
4. **Storage**: MongoDB for document storage
5. **API Endpoints**: RESTful endpoints for uploading, listing, and downloading invoice data

## Prerequisites

- Python 3.8+
- Redis server
- MongoDB server
- OpenAI API key

## Environment Variables

Create a `.env` file in the project root with:

```
OPENAI_API_KEY=your_openai_api_key
MONGO_URI=your_mongodb_connection_string
REDIS_URL=your_redis_url
MONGO_DB=invoice_ai  # optional, default: invoice_ai
MONGO_COLLECTION=invoices  # optional, default: invoices
```

## Installation

1. Clone the repository:
```bash
git clone https://github.com/gulshan-100/InvoiceAI.git
cd InvoiceAI
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
# On Windows
venv\Scripts\activate
# On macOS/Linux
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run migrations:
```bash
python manage.py migrate
```

## Running the Application

1. Start the Redis server (if not already running)

2. Start the Celery worker:
```bash
# On Windows
celery -A aiinvoice worker --pool=solo -l info
# On macOS/Linux
celery -A aiinvoice worker -l info
```

3. Run the Django development server:
```bash
python manage.py runserver
```

4. Open your browser and navigate to `http://127.0.0.1:8000/`


## Example Usage

1. Visit the main page at `http://127.0.0.1:8000/`
2. Upload one or more invoice images
3. Wait for processing to complete (progress is shown in real-time)
4. View the structured data extracted from invoices
5. Download all processed data as CSV for further analysis
